from __future__ import annotations

import random
import threading
from typing import Any

from soft_hub.sdk import CancelledError, HubAccount, HubContext

from plugin.wager_bot.client import ChainClient, read_balances
from plugin.wager_bot.config import (
    FAUCET_GAS_WEI,
    MIN_BET_USDC,
    MIN_GAS_WEI,
    MIN_VAULT_USDC,
    SIDE_NO,
    SIDE_YES,
    SPOT,
    VAULT,
    RunConfig,
)
from plugin.wager_bot.capsolver import is_unsupported_service
from plugin.wager_bot.errors import BlockedError, SoftError
from plugin.wager_bot.adspower_quicknode import claim_quicknode_tbnb
from plugin.wager_bot.chapel_faucet import CHAPEL_FAUCET_DROP_WEI, claim_chapel_tbnb
from plugin.wager_bot.faucet import claim_gas, claim_usdc
from plugin.wager_bot.flow import already_linked, farm_status, linked_result, tradable_quote
from plugin.wager_bot.http import ProjectHttp
from plugin.wager_bot.markets import earned_achievements, list_open_markets, pick_markets, user_bet_count
from plugin.wager_bot.options import farm_config, pick_bet_raw, pick_vault_amount
from plugin.wager_bot.pace import AccountPace, make_pace
from plugin.wager_bot.referral import attribute_parent, claim_own_slug, fetch_stats, public_slug, referred_count
from plugin.wager_bot.utils import raw_to_usdc, usdc_to_raw, wei_to_tbnb


def run(context: HubContext) -> dict[str, Any]:
    if context.action_id not in {"farm", "inspect"}:
        raise ValueError("unsupported_action")
    if context.action_id == "farm":
        cfg = farm_config(context.options)
        return _run_levels(context, cfg, mode="farm")
    return _run_levels(context, RunConfig(), mode="inspect")


def _run_levels(context: HubContext, cfg: RunConfig, *, mode: str) -> dict[str, Any]:
    counters = {
        "total": len(context.accounts),
        "succeeded": 0,
        "partial": 0,
        "failed": 0,
        "skipped": 0,
        "blocked": 0,
        "cancelled": 0,
        "bets": 0,
        "vaults": 0,
        "attributed": 0,
        "achievements": 0,
    }
    lock = threading.Lock()
    parent_slugs: dict[str, str] = {}
    parent_lock = threading.Lock()
    skip_farm: set[str] = set()
    levels = _referral_levels(context) if mode == "farm" else (tuple(context.accounts),)

    def tally(status: str, meta: dict[str, int]) -> str:
        with lock:
            counters[status] = counters.get(status, 0) + 1
            counters["bets"] += int(meta.get("bets") or 0)
            counters["vaults"] += int(meta.get("vault") or 0)
            counters["attributed"] += int(meta.get("attributed") or 0)
            counters["achievements"] += int(meta.get("achievements") or 0)
        return status

    def inspect_worker(account: HubAccount) -> str:
        try:
            status, meta = _inspect_account(context, account, cfg)
        except CancelledError:
            with lock:
                counters["cancelled"] += 1
            raise
        except Exception:
            _fail_unknown(context, account)
            with lock:
                counters["failed"] += 1
            return "failed"
        return tally(status, meta)

    def bootstrap_worker(account: HubAccount) -> str:
        try:
            pace = make_pace()
            pace.start(context.check_cancelled)
            status, meta = _bootstrap_account(
                context, account, cfg, parent_slugs, parent_lock, pace
            )
        except CancelledError:
            with lock:
                counters["cancelled"] += 1
            raise
        except Exception:
            _fail_unknown(context, account)
            with lock:
                skip_farm.add(account.id)
                counters["failed"] += 1
            return "failed"
        if status == "blocked":
            with lock:
                skip_farm.add(account.id)
            return tally(status, meta)
        with lock:
            counters["attributed"] += int(meta.get("attributed") or 0)
        return status

    def farm_worker(account: HubAccount) -> str:
        if account.id in skip_farm:
            return "blocked"
        try:
            pace = make_pace()
            pace.start(context.check_cancelled)
            status, meta = _farm_onchain(context, account, cfg, pace)
        except CancelledError:
            with lock:
                counters["cancelled"] += 1
            raise
        except Exception:
            _fail_unknown(context, account)
            with lock:
                counters["failed"] += 1
            return "failed"
        return tally(status, meta)

    try:
        if mode == "inspect":
            _map_accounts(context, inspect_worker, context.accounts)
        else:
            for index, level in enumerate(levels):
                context.check_cancelled()
                workers = _wave_size(context, level)
                context.log(
                    f"Реферальная цепь, уровень {index}: {len(level)} аккаунтов, параллельно {workers}",
                    data={"accounts": len(level), "level": index, "parallel": workers},
                )
                _map_accounts(context, bootstrap_worker, level)
            context.check_cancelled()
            targets = tuple(account for account in context.accounts if account.id not in skip_farm)
            workers = _wave_size(context, targets)
            context.log(
                f"Фарм после цепи: {len(targets)} аккаунтов, параллельно {workers}",
                data={"accounts": len(targets), "parallel": workers},
            )
            if targets:
                _map_accounts(context, farm_worker, targets)
    finally:
        with parent_lock:
            parent_slugs.clear()

    return {
        "total": counters["total"],
        "succeeded": counters["succeeded"],
        "partial": counters["partial"],
        "failed": counters["failed"],
        "skipped": counters["skipped"],
        "blocked": counters["blocked"],
        "cancelled": counters["cancelled"],
        "bets": counters["bets"],
        "vaults": counters["vaults"],
        "attributed": counters["attributed"],
        "achievements": counters["achievements"],
        "levels": len(levels),
        "mode": mode,
    }


def _wave_size(context: HubContext, accounts: tuple[HubAccount, ...] | list[HubAccount]) -> int:
    if not accounts:
        return 0
    return max(1, min(int(getattr(context, "account_concurrency", 1) or 1), 5, len(accounts)))


def _map_accounts(context: HubContext, worker: Any, accounts: tuple[HubAccount, ...] | list[HubAccount]) -> None:
    selected = tuple(accounts)
    if not selected:
        return
    if hasattr(context, "map_accounts"):
        context.map_accounts(worker, accounts=selected)
        return
    from concurrent.futures import ThreadPoolExecutor, as_completed

    workers = _wave_size(context, selected)
    if workers == 1:
        for account in selected:
            context.check_cancelled()
            worker(account)
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker, account) for account in selected]
        for future in as_completed(futures):
            future.result()


def _referral_levels(context: HubContext) -> tuple[tuple[HubAccount, ...], ...]:
    levels = getattr(context, "referral_levels", None)
    if levels is None:
        return (tuple(context.accounts),)
    try:
        materialised = tuple(tuple(level) for level in levels)
    except Exception:
        return (tuple(context.accounts),)
    return materialised or (tuple(context.accounts),)


def _parent_for(context: HubContext, child: HubAccount) -> HubAccount | None:
    referrals = getattr(context, "referrals", None)
    if referrals is None:
        return None
    getter = getattr(referrals, "parent_for", None)
    if not callable(getter):
        return None
    try:
        return getter(child.id)
    except KeyError:
        return None


def _inspect_account(
    context: HubContext, account: HubAccount, cfg: RunConfig
) -> tuple[str, dict[str, int]]:
    context.account_state(
        account.id,
        status="running",
        stage="preflight",
        progress=0.06,
        message="Проверяем доступ к API",
    )
    context.check_cancelled()
    try:
        proxy = account.secret("proxy")
    except KeyError:
        context.result(
            f"{account.label}: нет прокси",
            kind="account_snapshot",
            status="blocked",
            account_id=account.id,
            data=_empty_snapshot(),
        )
        context.account_state(
            account.id,
            status="blocked",
            stage="resource_missing",
            message="Не заполнен прокси",
        )
        return "blocked", {}

    http = ProjectHttp(proxy, timeout=cfg.request_timeout)
    address = (account.evm_address or "").lower()
    context.account_state(
        account.id,
        status="running",
        stage="request_ready",
        progress=0.25,
        message="Запрашиваем статистику аккаунта",
    )
    stats = fetch_stats(http, address)
    slug = public_slug(stats)
    if slug:
        context.protect_secret(slug)
    context.account_state(
        account.id,
        status="running",
        stage="response_received",
        progress=0.55,
        message="Ответ статистики получен",
    )
    bets = user_bet_count(http, address)
    badges = earned_achievements(http, address)
    usdc = "0"
    tbnb = "0"
    try:
        raw_bnb, raw_usdc = read_balances(address, proxy, cfg)
        usdc = raw_to_usdc(raw_usdc)
        tbnb = wei_to_tbnb(raw_bnb)
    except SoftError:
        pass
    context.account_state(
        account.id,
        status="running",
        stage="response_validated",
        progress=0.88,
        message="Статистика проверена",
    )
    data = {
        "has_slug": bool(slug),
        "referred": referred_count(stats),
        "bets": bets,
        "usdc": usdc,
        "tbnb": tbnb,
        "achievements": badges,
    }
    context.result(
        f"{account.label}: статистика собрана",
        kind="account_snapshot",
        status="succeeded",
        account_id=account.id,
        data=data,
    )
    context.account_state(
        account.id,
        status="succeeded",
        stage="completed",
        progress=1.0,
        message="Статистика аккаунта собрана",
    )
    return "succeeded", {"bets": bets}


def _bootstrap_account(
    context: HubContext,
    account: HubAccount,
    cfg: RunConfig,
    parent_slugs: dict[str, str],
    parent_lock: threading.Lock,
    pace: AccountPace,
) -> tuple[str, dict[str, int]]:
    context.account_state(
        account.id,
        status="running",
        stage="preflight",
        progress=0.05,
        message="Проверяем ключ, прокси и почту",
    )
    context.check_cancelled()
    try:
        proxy = account.secret("proxy")
        email = account.secret("email")
        account.secret("evm_private_key")
        context.settings.secret("capsolver")
    except KeyError:
        context.result(
            f"{account.label}: не хватает данных",
            kind="farm_summary",
            status="blocked",
            account_id=account.id,
            data={"error_code": "resource_missing"},
        )
        context.account_state(
            account.id,
            status="blocked",
            stage="resource_missing",
            message="Не заполнен ключ, прокси, почта или ключ проверки",
        )
        return "blocked", {}

    meta = {"bets": 0, "vault": 0, "attributed": 0}
    http = ProjectHttp(proxy, timeout=cfg.request_timeout)
    address = (account.evm_address or "").lower()
    stats = fetch_stats(http, address) if address else {}
    if already_linked(stats):
        meta["attributed"] = 1

    parent = _parent_for(context, account)
    if parent is not None and not already_linked(stats):
        pace.step(context.check_cancelled)
        context.account_state(
            account.id,
            status="running",
            stage="referral_parent",
            progress=0.16,
            message="Привязываем аккаунт к родителю из цепи",
        )
        try:
            parent_slug = _parent_slug(context, parent, http, parent_slugs, parent_lock)
            result = attribute_parent(http, address=address, parent_slug=parent_slug)
            if linked_result(result):
                meta["attributed"] = 1
        except BlockedError as exc:
            if exc.code != "parent_slug_missing":
                raise
            context.log(
                f"{account.label}: родитель ещё без ссылки, фарм продолжим",
                data={"error_code": exc.code},
            )

    context.check_cancelled()
    pace.step(context.check_cancelled)
    existing = public_slug(stats)
    context.account_state(
        account.id,
        status="running",
        stage="referral_claim",
        progress=0.24,
        message=(
            "Аккаунт уже с реферальной ссылкой"
            if existing
            else "Закрепляем собственную реферальную ссылку"
        ),
    )
    claim_own_slug(
        http,
        address=address,
        email=email,
        protect=context.protect_secret,
    )
    with parent_lock:
        fresh = fetch_stats(http, address)
        slug = public_slug(fresh)
        if slug:
            context.protect_secret(slug)
            parent_slugs[account.id] = slug
    return "ok", meta


def _top_up_gas(
    context: HubContext,
    account: HubAccount,
    chain: ChainClient,
    http: ProjectHttp,
    *,
    capsolver_key: str,
    proxy: str | None,
    pace: AccountPace,
    twocaptcha_key: str = "",
) -> None:
    if chain.native_wei() >= MIN_GAS_WEI:
        return
    profile_id = ""
    ads_key = ""
    try:
        profile_id = str(account.secret("adspower_profile") or "").strip()
    except Exception:
        profile_id = ""
    try:
        ads_key = str(context.settings.secret("adspower_api") or "").strip()
    except Exception:
        ads_key = ""
    if len(profile_id) >= 4 and len(ads_key) >= 4:
        context.account_state(
            account.id,
            status="running",
            stage="faucet_quicknode",
            progress=0.34,
            message="Клеим tBNB через QuickNode в AdsPower",
        )
        pace.think(context.check_cancelled)
        ads_error: SoftError | None = None
        try:
            claim_quicknode_tbnb(
                address=chain.address,
                profile_id=profile_id,
                api_key=ads_key,
                get_native=chain.native_wei,
                min_wei=MIN_GAS_WEI,
            )
        except SoftError as exc:
            ads_error = exc
        if chain.native_wei() >= MIN_GAS_WEI:
            return
        if ads_error is not None and ads_error.code in {
            "quicknode_faucet",
            "adspower_unavailable",
            "playwright_missing",
        }:
            raise ads_error
    context.account_state(
        account.id,
        status="running",
        stage="faucet_chapel",
        progress=0.36,
        message="Запрашиваем tBNB с крана BNB Chain",
    )
    pace.think(context.check_cancelled)
    chapel_error: SoftError | None = None
    try:
        chapel_status = claim_chapel_tbnb(
            address=chain.address,
            capsolver_key=capsolver_key,
            proxy=proxy,
            protect=context.protect_secret,
            twocaptcha_key=twocaptcha_key,
        )
    except SoftError as exc:
        if exc.code == "chapel_mainnet_bnb":
            raise
        if is_unsupported_service(exc):
            chapel_error = SoftError(
                "chapel_captcha",
                "Capsolver не решает капчу крана BNB Chain. Склейми tBNB вручную на www.bnbchain.org/en/testnet-faucet (нужно ≥0.002 BNB в mainnet)",
            )
        else:
            chapel_error = exc
        chapel_status = ""
    if chapel_status == "claimed" and chain.wait_native(CHAPEL_FAUCET_DROP_WEI):
        return
    if chain.native_wei() >= MIN_GAS_WEI:
        return
    context.account_state(
        account.id,
        status="running",
        stage="faucet_gas",
        progress=0.40,
        message="Запрашиваем тестовый газ",
    )
    pace.think(context.check_cancelled)
    try:
        gas_status = claim_gas(
            http,
            address=chain.address,
            capsolver_key=capsolver_key,
            proxy=proxy,
            protect=context.protect_secret,
        )
        if gas_status == "claimed":
            chain.wait_native(FAUCET_GAS_WEI)
        elif chain.native_wei() < MIN_GAS_WEI:
            chain.wait_native(MIN_GAS_WEI, attempts=8)
    except SoftError:
        pass
    if chain.native_wei() >= MIN_GAS_WEI:
        return
    if chapel_error is not None:
        raise chapel_error
    raise SoftError("gas_not_received", "Мало tBNB, кран BNB Chain не пополнил кошелёк")


def _farm_onchain(
    context: HubContext,
    account: HubAccount,
    cfg: RunConfig,
    pace: AccountPace,
) -> tuple[str, dict[str, int]]:
    write_may_have = False
    meta = {"bets": 0, "vault": 0, "attributed": 0}
    hashes: list[str] = []
    try:
        private_key = account.secret("evm_private_key")
        proxy = account.secret("proxy")
        capsolver_key = context.settings.secret("capsolver")
        http = ProjectHttp(proxy, timeout=cfg.request_timeout)
        chain = ChainClient(cfg, private_key=private_key, proxy=proxy)

        context.check_cancelled()
        if chain.native_wei() >= MIN_GAS_WEI and chain.usdc_raw() > 0:
            context.account_state(
                account.id,
                status="running",
                stage="reuse",
                progress=0.30,
                message="Аккаунт уже в сети, работаем с текущим балансом",
            )
        if chain.native_wei() < MIN_GAS_WEI:
            _top_up_gas(
                context,
                account,
                chain,
                http,
                capsolver_key=capsolver_key,
                proxy=proxy,
                pace=pace,
                twocaptcha_key=cfg.twocaptcha_api_key,
            )

        needed_usdc = usdc_to_raw(max(cfg.bet_usdc_from * cfg.bets_from, MIN_VAULT_USDC, MIN_BET_USDC))
        if chain.usdc_raw() < min(needed_usdc, usdc_to_raw(100)):
            context.account_state(
                account.id,
                status="running",
                stage="faucet_usdc",
                progress=0.44,
                message="Запрашиваем тестовые USDC",
            )
            pace.think(context.check_cancelled)
            usdc_status = claim_usdc(
                http,
                address=chain.address,
                capsolver_key=capsolver_key,
                proxy=proxy,
                protect=context.protect_secret,
            )
            if usdc_status == "claimed":
                got_usdc = chain.wait_usdc(usdc_to_raw(1))
            else:
                got_usdc = chain.usdc_raw() > 0 or chain.wait_usdc(usdc_to_raw(1), attempts=8)
            if not got_usdc:
                try:
                    leftover_usdc = chain.usdc_raw()
                except SoftError:
                    leftover_usdc = 0
                if leftover_usdc <= 0:
                    prior = user_bet_count(http, chain.address.lower())
                    if prior >= 10:
                        context.result(
                            f"{account.label}: уже есть ставки, кран больше не выдаёт",
                            kind="farm_summary",
                            status="succeeded",
                            account_id=account.id,
                            data={"bets": 0, "vault": False, "own_slug": True, "already_farmed": True},
                        )
                        context.account_state(
                            account.id,
                            status="succeeded",
                            stage="completed",
                            progress=1.0,
                            message="Аккаунт уже отфармлен",
                        )
                        return "succeeded", meta
                    raise SoftError("usdc_not_received", "Нет USDC и кран не выдал")

        vault_amount = pick_vault_amount(cfg)
        usdc_now = chain.usdc_raw()
        min_bet_budget = usdc_to_raw(max(1, cfg.bets_from) * MIN_BET_USDC)
        vault_cap = max(0, usdc_now - min_bet_budget)
        if vault_amount >= MIN_VAULT_USDC and usdc_to_raw(vault_amount) > vault_cap:
            vault_amount = int(vault_cap // 1_000_000)
            if vault_amount < MIN_VAULT_USDC:
                vault_amount = 0

        context.check_cancelled()
        pace.think(context.check_cancelled)
        context.account_state(
            account.id,
            status="running",
            stage="approve",
            progress=0.54,
            message="Выдаём разрешение контрактам на USDC",
        )
        budget = chain.usdc_raw()
        if budget <= 0:
            raise BlockedError("no_usdc", "На кошельке нет тестовых USDC")
        pace.before_tx(context.check_cancelled)
        tx = chain.approve_if_needed(SPOT, budget)
        if tx:
            write_may_have = True
            hashes.append(tx)
        if vault_amount >= MIN_VAULT_USDC:
            pace.before_tx(context.check_cancelled)
            tx = chain.approve_if_needed(VAULT, usdc_to_raw(vault_amount))
            if tx:
                write_may_have = True
                hashes.append(tx)

        bets_target = random.randint(cfg.bets_from, cfg.bets_to)
        markets = list_open_markets(http, limit=max(200, cfg.bets_to * 3))
        market_ids = pick_markets(markets, max(bets_target * 3, bets_target))
        placed = 0
        rejects = 0
        for market_id in market_ids:
            if placed >= bets_target:
                break
            context.check_cancelled()
            amount = pick_bet_raw(
                cfg,
                chain.usdc_raw(),
                vault_amount,
                bets_target - placed,
            )
            if amount < usdc_to_raw(MIN_BET_USDC):
                break
            side, quote = _choose_side(chain, market_id, amount)
            if not tradable_quote(quote):
                continue
            progress = 0.58 + 0.22 * ((placed + 1) / max(1, bets_target))
            context.account_state(
                account.id,
                status="running",
                stage="betting",
                progress=min(progress, 0.84),
                message=f"Ставим {placed + 1} из {bets_target}",
            )
            pace.before_tx(context.check_cancelled)
            try:
                tx = chain.buy_shares(market_id, side, amount)
            except SoftError as exc:
                meta["bets"] = placed
                if exc.code == "tx_reverted":
                    continue
                if exc.code == "tx_rejected":
                    if "tBNB" in exc.message:
                        raise
                    rejects += 1
                    if rejects < 2:
                        continue
                raise
            write_may_have = True
            hashes.append(tx)
            placed += 1
            rejects = 0
        meta["bets"] = placed

        vault_done = 0
        if vault_amount >= MIN_VAULT_USDC:
            context.check_cancelled()
            context.account_state(
                account.id,
                status="running",
                stage="vault",
                progress=0.90,
                message="Кладём USDC в vault",
            )
            vault_raw = min(usdc_to_raw(vault_amount), chain.usdc_raw())
            if vault_raw >= usdc_to_raw(MIN_VAULT_USDC):
                pace.think(context.check_cancelled)
                pace.before_tx(context.check_cancelled)
                try:
                    tx = chain.vault_deposit(vault_raw, cfg.vault_tier)
                    write_may_have = True
                    hashes.append(tx)
                    vault_done = 1
                except SoftError as exc:
                    meta["vault"] = 0
                    if exc.code != "tx_reverted":
                        raise
        meta["vault"] = vault_done

        badges = earned_achievements(http, chain.address.lower())
        meta["achievements"] = badges
        status, message = farm_status(bets=placed, vault=vault_done, error_code=None)
        if placed == 0 and vault_done == 0:
            prior = user_bet_count(http, chain.address.lower())
            if prior >= 10 and chain.usdc_raw() <= 0:
                status, message = "succeeded", "Аккаунт уже отфармлен"
        if badges:
            message = f"{message}, бейджей {badges}"
        own_slug = bool(public_slug(fetch_stats(http, chain.address.lower())))
        context.result(
            f"{account.label}: {message.lower()}",
            kind="farm_summary",
            status=status,
            account_id=account.id,
            data={
                "bets": placed,
                "vault": bool(vault_done),
                "attributed": bool(meta["attributed"]),
                "own_slug": own_slug,
                "tx_count": len(hashes),
                "achievements": badges,
            },
        )
        context.account_state(
            account.id,
            status=status,
            stage="completed",
            progress=1.0 if status == "succeeded" else None,
            message=message,
        )
        return status, meta
    except CancelledError:
        context.account_state(
            account.id,
            status="cancelled",
            stage="external_outcome_unknown" if write_may_have else "cancelled",
            message=(
                "Запуск остановлен. Проверьте кошелёк и explorer перед повтором"
                if write_may_have
                else "Работа остановлена до внешнего действия"
            ),
        )
        raise
    except BlockedError as exc:
        context.result(
            f"{account.label}: {exc.message}",
            kind="farm_summary",
            status="blocked",
            account_id=account.id,
            data={"error_code": exc.code},
        )
        context.account_state(
            account.id,
            status="blocked",
            stage="blocked",
            message=exc.message,
        )
        return "blocked", meta
    except SoftError as exc:
        status, derived = farm_status(
            bets=int(meta.get("bets") or 0),
            vault=int(meta.get("vault") or 0),
            error_code=exc.code,
        )
        if status == "failed":
            message = exc.message
        else:
            message = derived
        unknown = write_may_have or exc.code in {"tx_unconfirmed", "tx_reverted"}
        if unknown and status == "failed":
            message = f"{exc.message}. Проверьте explorer перед повтором"
        context.result(
            f"{account.label}: {message}",
            kind="farm_summary",
            status=status,
            account_id=account.id,
            data={"error_code": exc.code, "bets": int(meta.get("bets") or 0)},
        )
        context.account_state(
            account.id,
            status=status,
            stage=(
                "external_outcome_unknown"
                if unknown and status == "failed"
                else "completed" if status == "partial" else "failed"
            ),
            message=message,
        )
        return status, meta


def _parent_slug(
    context: HubContext,
    parent: HubAccount,
    http: ProjectHttp,
    cache: dict[str, str],
    lock: threading.Lock,
) -> str:
    with lock:
        cached = cache.get(parent.id)
    if cached:
        return context.protect_secret(cached) or cached
    stats = fetch_stats(http, (parent.evm_address or "").lower())
    slug = public_slug(stats)
    if not slug:
        raise BlockedError("parent_slug_missing", "У родителя ещё нет реферальной ссылки")
    protected = context.protect_secret(slug) or slug
    with lock:
        cache[parent.id] = protected
    return protected


def _choose_side(chain: ChainClient, market_id: int, amount: int) -> tuple[int, int]:
    first = random.choice((SIDE_YES, SIDE_NO))
    second = SIDE_NO if first == SIDE_YES else SIDE_YES
    first_quote = chain.buy_quote(market_id, first, amount)
    if tradable_quote(first_quote):
        return first, first_quote
    second_quote = chain.buy_quote(market_id, second, amount)
    if tradable_quote(second_quote):
        return second, second_quote
    return first, 0


def _empty_snapshot() -> dict[str, Any]:
    return {
        "has_slug": False,
        "referred": 0,
        "bets": 0,
        "usdc": "0",
        "tbnb": "0",
        "achievements": 0,
    }


def _fail_unknown(context: HubContext, account: HubAccount) -> None:
    try:
        context.result(
            f"{account.label}: внутренняя ошибка",
            kind="farm_summary" if context.action_id == "farm" else "account_snapshot",
            status="failed",
            account_id=account.id,
            data={"error_code": "unexpected_error"} if context.action_id == "farm" else _empty_snapshot(),
        )
        context.account_state(
            account.id,
            status="failed",
            stage="failed",
            message="Сценарий завершился известной ошибкой",
        )
    except Exception:
        pass
