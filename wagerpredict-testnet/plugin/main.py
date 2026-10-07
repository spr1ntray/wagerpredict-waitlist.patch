from __future__ import annotations

import threading
from typing import Any

from soft_hub.sdk import CancelledError, HubAccount, HubContext

from plugin.wager_bot.allowlist import (
    AllowlistStatus,
    checksum_from_address,
    checksum_from_key,
    classify_before_submit,
    fetch_status,
    normalize_handle,
    parse_status,
    submit_request,
)
from plugin.wager_bot.errors import BlockedError, SoftError
from plugin.wager_bot.http import ProjectHttp
from plugin.wager_bot.options import RunConfig, run_config
from plugin.wager_bot.utils import pause_ms


def run(context: HubContext) -> dict[str, Any]:
    if context.action_id not in {"register", "inspect"}:
        raise ValueError("unsupported_action")
    cfg = run_config(context.options) if context.action_id == "register" else RunConfig()
    return _run(context, cfg)


def _run(context: HubContext, cfg: RunConfig) -> dict[str, Any]:
    counters = {
        "total": len(context.accounts),
        "succeeded": 0,
        "failed": 0,
        "blocked": 0,
        "cancelled": 0,
        "submitted": 0,
        "already": 0,
        "allowed": 0,
    }
    lock = threading.Lock()

    def tally(status: str, meta: dict[str, int]) -> str:
        with lock:
            counters[status] = counters.get(status, 0) + 1
            counters["submitted"] += int(meta.get("submitted") or 0)
            counters["already"] += int(meta.get("already") or 0)
            counters["allowed"] += int(meta.get("allowed") or 0)
        return status

    def worker(account: HubAccount) -> str:
        try:
            if context.action_id == "register":
                status, meta = _register_account(context, account, cfg)
            else:
                status, meta = _inspect_account(context, account)
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

    _map_accounts(context, worker, context.accounts)
    return {
        "total": counters["total"],
        "succeeded": counters["succeeded"],
        "failed": counters["failed"],
        "blocked": counters["blocked"],
        "cancelled": counters["cancelled"],
        "submitted": counters["submitted"],
        "already": counters["already"],
        "allowed": counters["allowed"],
        "mode": context.action_id,
    }


def _wave_size(context: HubContext, accounts: tuple[HubAccount, ...] | list[HubAccount]) -> int:
    if not accounts:
        return 0
    declared = int(getattr(context, "account_concurrency", 1) or 1)
    return max(1, min(declared, len(accounts)))


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


def _register_account(
    context: HubContext, account: HubAccount, cfg: RunConfig
) -> tuple[str, dict[str, int]]:
    wrote = False
    meta = {"submitted": 0, "already": 0, "allowed": 0}
    context.account_state(
        account.id,
        status="running",
        stage="preflight",
        progress=0.08,
        message="Проверяем ключ, прокси и почту",
    )
    context.check_cancelled()
    try:
        private_key = account.secret("evm_private_key")
        proxy = account.secret("proxy")
        email = account.secret("email")
    except KeyError:
        return _blocked(context, account, "Не заполнен ключ, прокси или почта")

    try:
        address = checksum_from_key(private_key)
        handle = normalize_handle(email)
    except BlockedError as exc:
        return _blocked(context, account, exc.message, exc.code)
    except SoftError as exc:
        return _fail_soft(context, account, exc, wrote)

    context.protect_secret(handle)
    try:
        http = ProjectHttp(proxy, timeout=cfg.request_timeout)
        context.account_state(
            account.id,
            status="running",
            stage="request_ready",
            progress=0.28,
            message="Смотрим очередь по кошельку",
        )
        status = fetch_status(http, address)
        decision = classify_before_submit(status)
        if decision == "already_allowed":
            meta["allowed"] = 1
            meta["already"] = 1
            return _finish(
                context,
                account,
                status,
                "Кошелёк уже в списке",
                submitted=False,
                meta=meta,
            )
        if decision == "already_queued":
            meta["already"] = 1
            return _finish(
                context,
                account,
                status,
                "Заявка уже в очереди",
                submitted=False,
                meta=meta,
            )
        if decision == "closed":
            return _blocked(context, account, "Набор в очередь сейчас закрыт", "allowlist_closed")

        pause_ms(cfg.pause_from_ms, cfg.pause_to_ms, context.check_cancelled)
        context.check_cancelled()
        context.account_state(
            account.id,
            status="running",
            stage="submit",
            progress=0.62,
            message="Отправляем заявку",
        )
        wrote = True
        try:
            posted = submit_request(http, address, handle)
        except SoftError as exc:
            if exc.code not in {"http_timeout", "http_network", "proxy_error"}:
                raise
            status = fetch_status(http, address)
            if status.allowed or status.requested:
                meta["already"] = 1
                if status.allowed:
                    meta["allowed"] = 1
                return _finish(
                    context,
                    account,
                    status,
                    "Заявка уже в очереди" if status.requested and not status.allowed else "Кошелёк уже в списке",
                    submitted=False,
                    meta=meta,
                )
            raise
        posted_status = parse_status(posted, already_requested=bool(posted.get("alreadyRequested")))
        context.account_state(
            account.id,
            status="running",
            stage="response_received",
            progress=0.82,
            message="Проверяем очередь после заявки",
        )
        confirmed = fetch_status(http, address)
        merged = AllowlistStatus(
            enabled=confirmed.enabled,
            allowed=confirmed.allowed,
            requested=confirmed.allowed or confirmed.requested or True,
            status=confirmed.status or posted_status.status or "pending",
            requested_at=confirmed.requested_at,
            already_requested=posted_status.already_requested,
        )
        if merged.allowed:
            meta["allowed"] = 1
            meta["already"] = 1
            message = "Кошелёк уже в списке"
        elif posted_status.already_requested or decision == "already_queued":
            meta["already"] = 1
            message = "Заявка уже в очереди"
        else:
            meta["submitted"] = 1
            message = "Заявка в очереди"
        return _finish(context, account, merged, message, submitted=True, meta=meta)
    except CancelledError:
        context.account_state(
            account.id,
            status="cancelled",
            stage="external_outcome_unknown" if wrote else "cancelled",
            message=(
                "Запуск остановлен. Проверьте очередь на сайте перед повтором"
                if wrote
                else "Работа остановлена до отправки заявки"
            ),
        )
        raise
    except BlockedError as exc:
        return _blocked(context, account, exc.message, exc.code)
    except SoftError as exc:
        return _fail_soft(context, account, exc, wrote)


def _inspect_account(context: HubContext, account: HubAccount) -> tuple[str, dict[str, int]]:
    context.account_state(
        account.id,
        status="running",
        stage="preflight",
        progress=0.08,
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

    try:
        address = checksum_from_address(account.evm_address or "")
    except SoftError:
        context.result(
            f"{account.label}: нет адреса",
            kind="account_snapshot",
            status="blocked",
            account_id=account.id,
            data=_empty_snapshot(),
        )
        context.account_state(
            account.id,
            status="blocked",
            stage="resource_missing",
            message="У аккаунта нет адреса кошелька",
        )
        return "blocked", {}

    context.account_state(
        account.id,
        status="running",
        stage="request_ready",
        progress=0.4,
        message="Запрашиваем статус очереди",
    )
    try:
        http = ProjectHttp(proxy)
        status = fetch_status(http, address)
    except SoftError as exc:
        context.result(
            f"{account.label}: {exc.message}",
            kind="account_snapshot",
            status="failed",
            account_id=account.id,
            data=_empty_snapshot(),
        )
        context.account_state(
            account.id,
            status="failed",
            stage="failed",
            message=exc.message,
        )
        return "failed", {}

    data = _snapshot(status)
    context.result(
        f"{account.label}: {status.queue_label}",
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
        message=f"Статус: {status.queue_label}",
    )
    meta = {"allowed": 1 if status.allowed else 0, "already": 1 if status.requested else 0}
    return "succeeded", meta


def _snapshot(status: AllowlistStatus) -> dict[str, Any]:
    return {
        "allowed": status.allowed,
        "requested": status.requested or status.already_requested,
        "queue_status": status.queue_label,
    }


def _empty_snapshot() -> dict[str, Any]:
    return {"allowed": False, "requested": False, "queue_status": "нет заявки"}


def _finish(
    context: HubContext,
    account: HubAccount,
    status: AllowlistStatus,
    message: str,
    *,
    submitted: bool,
    meta: dict[str, int],
) -> tuple[str, dict[str, int]]:
    context.result(
        f"{account.label}: {message.lower()}",
        kind="allowlist_summary",
        status="succeeded",
        account_id=account.id,
        data={
            "allowed": status.allowed,
            "requested": status.requested or status.already_requested,
            "queue_status": status.queue_label,
            "submitted": submitted and not status.already_requested,
        },
    )
    context.account_state(
        account.id,
        status="succeeded",
        stage="completed",
        progress=1.0,
        message=message,
    )
    return "succeeded", meta


def _blocked(
    context: HubContext,
    account: HubAccount,
    message: str,
    code: str = "resource_missing",
) -> tuple[str, dict[str, int]]:
    kind = "allowlist_summary" if context.action_id == "register" else "account_snapshot"
    data: dict[str, Any] = {"error_code": code} if kind == "allowlist_summary" else _empty_snapshot()
    context.result(
        f"{account.label}: {message}",
        kind=kind,
        status="blocked",
        account_id=account.id,
        data=data,
    )
    context.account_state(
        account.id,
        status="blocked",
        stage="resource_missing" if code == "resource_missing" else "blocked",
        message=message,
    )
    return "blocked", {}


def _fail_soft(
    context: HubContext, account: HubAccount, exc: SoftError, wrote: bool
) -> tuple[str, dict[str, int]]:
    message = exc.message
    if wrote:
        message = f"{exc.message}. Проверьте очередь на сайте перед повтором"
    context.result(
        f"{account.label}: {message}",
        kind="allowlist_summary",
        status="failed",
        account_id=account.id,
        data={"error_code": exc.code},
    )
    context.account_state(
        account.id,
        status="failed",
        stage="external_outcome_unknown" if wrote else "failed",
        message=message,
    )
    return "failed", {}


def _fail_unknown(context: HubContext, account: HubAccount) -> None:
    try:
        kind = "allowlist_summary" if context.action_id == "register" else "account_snapshot"
        context.result(
            f"{account.label}: внутренняя ошибка",
            kind=kind,
            status="failed",
            account_id=account.id,
            data={"error_code": "unexpected_error"} if kind == "allowlist_summary" else _empty_snapshot(),
        )
        context.account_state(
            account.id,
            status="failed",
            stage="failed",
            message="Сценарий завершился известной ошибкой",
        )
    except Exception:
        pass
