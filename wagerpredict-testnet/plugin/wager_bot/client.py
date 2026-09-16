from __future__ import annotations

import threading
from typing import Any

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from .abis import ERC20_ABI, SPOT_ABI, VAULT_ABI
from .config import CHAIN_ID, FAUCET_WAIT_ATTEMPTS, MAX_UINT, SEND_SLOTS, SPOT, USDC, VAULT, RunConfig
from .errors import SoftError
from .rpc import (
    affordable_fees,
    apply_legacy_fees,
    block_ttl_for,
    broadcast_raw,
    is_already_known,
    is_native_gas_error,
    is_nonce_error,
    is_underpriced,
    live_write_urls,
    mark_send_blocked,
    ordered_rpc_urls,
    parse_have_want,
    provider_kwargs,
    rpc_send_hint,
    send_modes,
)
from .utils import normalize_private_key, normalize_proxy

_SEND_SLOTS = threading.Semaphore(SEND_SLOTS)


def _inject_poa(w3: Web3) -> None:
    try:
        from web3.middleware import ExtraDataToPOAMiddleware

        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        return
    except Exception:
        pass
    try:
        from web3.middleware import geth_poa_middleware

        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        pass


def read_balances(address: str, proxy: str | None, cfg: RunConfig) -> tuple[int, int]:
    checksum = Web3.to_checksum_address(address)
    last: Exception | None = None
    try:
        proxy_url = normalize_proxy(proxy)
    except ValueError:
        proxy_url = None
    for direct in (True, False):
        if not direct and not proxy_url:
            continue
        for url in ordered_rpc_urls(cfg.rpc_urls):
            try:
                w3 = Web3(
                    Web3.HTTPProvider(
                        url,
                        request_kwargs=provider_kwargs(cfg.request_timeout, proxy_url, direct=direct),
                    )
                )
                _inject_poa(w3)
                if int(w3.eth.chain_id) != CHAIN_ID:
                    continue
                usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_ABI)
                return int(w3.eth.get_balance(checksum)), int(usdc.functions.balanceOf(checksum).call())
            except Exception as exc:
                last = exc
                continue
    raise SoftError("rpc_unavailable", "Нет рабочего RPC тестнета") from last


class ChainClient:
    def __init__(self, cfg: RunConfig, *, private_key: str, proxy: str | None) -> None:
        self.cfg = cfg
        try:
            self.proxy = normalize_proxy(proxy)
        except ValueError as exc:
            raise SoftError("invalid_proxy", "Неверный формат прокси") from exc
        self.account: LocalAccount = Account.from_key(normalize_private_key(private_key))
        self.address = Web3.to_checksum_address(self.account.address)
        self.rpc_url = ""
        self.w3 = self._connect_rpc()
        self._bind_contracts()

    def _make_w3(self, url: str, *, direct: bool) -> Web3:
        w3 = Web3(
            Web3.HTTPProvider(
                url,
                request_kwargs=provider_kwargs(self.cfg.request_timeout, self.proxy, direct=direct),
            )
        )
        _inject_poa(w3)
        return w3

    def _connect_rpc(self) -> Web3:
        last: Exception | None = None
        modes = (True, False) if self.proxy else (True,)
        for direct in modes:
            for url in ordered_rpc_urls(self.cfg.rpc_urls):
                try:
                    w3 = self._make_w3(url, direct=direct)
                    if int(w3.eth.chain_id) != CHAIN_ID:
                        continue
                    self.rpc_url = url
                    return w3
                except Exception as exc:
                    last = exc
                    continue
        raise SoftError("rpc_unavailable", "Нет рабочего RPC тестнета") from last

    def _bind_contracts(self) -> None:
        self.usdc = self.w3.eth.contract(address=Web3.to_checksum_address(USDC), abi=ERC20_ABI)
        self.spot = self.w3.eth.contract(address=Web3.to_checksum_address(SPOT), abi=SPOT_ABI)
        self.vault = self.w3.eth.contract(address=Web3.to_checksum_address(VAULT), abi=VAULT_ABI)

    def _adopt(self, w3: Web3, url: str) -> None:
        self.w3 = w3
        self.rpc_url = url
        self._bind_contracts()

    def _read(self, fn: Any) -> Any:
        try:
            return fn()
        except SoftError:
            raise
        except Exception as exc:
            raise SoftError("rpc_unavailable", "Нет рабочего RPC тестнета") from exc

    def native_wei(self) -> int:
        return int(self._read(lambda: self.w3.eth.get_balance(self.address)))

    def usdc_raw(self) -> int:
        return int(self._read(lambda: self.usdc.functions.balanceOf(self.address).call()))

    def allowance(self, spender: str) -> int:
        return int(
            self._read(
                lambda: self.usdc.functions.allowance(
                    self.address,
                    Web3.to_checksum_address(spender),
                ).call()
            )
        )

    def buy_quote(self, market_id: int, side: int, usdc_in: int) -> int:
        try:
            shares, _net = self.spot.functions.getBuyQuote(int(market_id), int(side), int(usdc_in)).call()
            return int(shares)
        except Exception:
            return 0

    def _write_urls(self) -> tuple[str, ...]:
        writes = live_write_urls(self.cfg.rpc_urls, sticky=self.rpc_url)
        if writes:
            return writes
        return tuple(url for url in self.cfg.rpc_urls if url)

    def _send_on(self, url: str, raw: bytes) -> tuple[Any, Web3, str]:
        last: Exception | None = None
        all_hard = True
        for direct in send_modes(self.proxy):
            try:
                w3 = self._make_w3(url, direct=direct)
                if int(w3.eth.chain_id) != CHAIN_ID:
                    all_hard = False
                    continue
                try:
                    tx_hash = w3.eth.send_raw_transaction(raw)
                except Exception as exc:
                    if not is_already_known(exc):
                        raise
                    tx_hash = w3.keccak(raw)
                return tx_hash, w3, url
            except Exception as exc:
                last = exc
                if block_ttl_for(exc) <= 0:
                    all_hard = False
                continue
        if last is not None and all_hard:
            ttl = block_ttl_for(last)
            if ttl > 0:
                mark_send_blocked(url, ttl)
        if last is not None:
            raise last
        raise SoftError("wrong_chain", "RPC вернул не ту сеть")

    def send(self, function_call: Any) -> str:
        import time

        try:
            latest = int(self.w3.eth.get_transaction_count(self.address, "latest"))
            try:
                pending = int(self.w3.eth.get_transaction_count(self.address, "pending"))
            except Exception:
                pending = latest
            bump = 1.25 if pending > latest else 1.0
            tx = function_call.build_transaction(
                {
                    "from": self.address,
                    "nonce": latest,
                    "chainId": CHAIN_ID,
                }
            )
            estimated = int(tx.get("gas") or 0)
            if estimated <= 0:
                estimated = int(self.w3.eth.estimate_gas(tx))
            padded = max(21_000, int(estimated * self.cfg.gas_multiplier))
            network_price = min(int(self.w3.eth.gas_price) or 100_000_000, 200_000_000)
            network_price = int(network_price * bump)
            have = int(self.w3.eth.get_balance(self.address))
            gas, price = affordable_fees(have, padded, network_price)
            if gas == 0:
                gas, price = affordable_fees(have, max(21_000, estimated), network_price)
            if gas == 0:
                raise SoftError("tx_rejected", "Мало tBNB на комиссию")
            tx = apply_legacy_fees(tx, gas_price=price, multiplier=1.0, floor=price)
            tx["gas"] = gas
            tx["nonce"] = latest
            signed = self.account.sign_transaction(tx)
            raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        except SoftError:
            raise
        except Exception as exc:
            raise SoftError("estimate_failed", "Транзакция не собралась до отправки") from exc

        last: Exception | None = None
        tx_hash = None
        sender = None
        used_url = self.rpc_url
        fitted = False

        def _refit(exc: BaseException) -> bool:
            nonlocal raw, signed, fitted
            if is_underpriced(exc) or is_nonce_error(exc):
                have = int(self.w3.eth.get_balance(self.address))
                gas = int(tx.get("gas") or 21_000)
                price = max(int(int(tx.get("gasPrice") or 100_000_000) * 1.25), 100_000_000)
                if have < gas * price:
                    return False
                tx["nonce"] = int(self.w3.eth.get_transaction_count(self.address, "latest"))
                tx["gasPrice"] = price
                signed = self.account.sign_transaction(tx)
                raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
                return True
            if fitted or not is_native_gas_error(exc):
                return False
            parsed = parse_have_want(exc)
            have = parsed[0] if parsed else int(self.w3.eth.get_balance(self.address))
            gas, price = affordable_fees(have, max(21_000, estimated), network_price)
            if gas <= 0 or price <= 0:
                return False
            tx["gas"] = gas
            tx["gasPrice"] = price
            signed = self.account.sign_transaction(tx)
            raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
            fitted = True
            return True

        try:
            for attempt in range(3):
                live = list(self._write_urls())
                if not live:
                    live = [url for url in self.cfg.rpc_urls if url]
                rotated = live[attempt:] + live[:attempt]
                senders = [
                    lambda payload, target=url: self._send_on(target, payload)
                    for url in rotated
                ]
                try:
                    with _SEND_SLOTS:
                        tx_hash, sender, used_url = broadcast_raw(raw, senders)
                    last = None
                    break
                except SoftError as exc:
                    last = exc
                    if _refit(exc):
                        continue
                except Exception as exc:
                    last = exc
                    if _refit(exc):
                        continue
                time.sleep(0.5 + attempt * 0.4)
            else:
                hint = rpc_send_hint(last) if last else "транзакция не ушла в сеть"
                raise SoftError("tx_rejected", hint[0].upper() + hint[1:]) from last
        finally:
            raw = None
            signed = None

        if sender is None or tx_hash is None:
            hint = rpc_send_hint(last) if last else "транзакция не ушла в сеть"
            raise SoftError("tx_rejected", hint[0].upper() + hint[1:]) from last
        self._adopt(sender, used_url)
        hx = tx_hash.hex() if hasattr(tx_hash, "hex") else sender.to_hex(tx_hash)
        if not str(hx).startswith("0x"):
            hx = "0x" + str(hx)
        try:
            receipt = self._wait_receipt(tx_hash, timeout=max(60, min(90, self.cfg.receipt_timeout)))
        except Exception as exc:
            raise SoftError("tx_unconfirmed", "Транзакция отправлена, но квитанция не подтверждена") from exc
        status = getattr(receipt, "status", None)
        if status is None:
            raise SoftError("tx_unconfirmed", "Транзакция отправлена, но квитанция не подтверждена")
        if int(status) != 1:
            raise SoftError("tx_reverted", "Сеть отклонила транзакцию")
        return str(hx)

    def _wait_receipt(self, tx_hash: Any, timeout: int) -> Any:
        import time

        deadline = time.monotonic() + max(8, int(timeout))
        last: Exception | None = None
        while time.monotonic() < deadline:
            for url in self._write_urls():
                try:
                    w3 = self._make_w3(url, direct=True)
                    receipt = w3.eth.get_transaction_receipt(tx_hash)
                    if receipt is not None and getattr(receipt, "blockHash", None):
                        return receipt
                except Exception as exc:
                    last = exc
                    continue
            time.sleep(1.2)
        raise TimeoutError(str(last or "receipt_timeout"))

    def approve_if_needed(self, spender: str, needed: int) -> str | None:
        if self.allowance(spender) >= needed:
            return None
        return self.send(self.usdc.functions.approve(Web3.to_checksum_address(spender), MAX_UINT))

    def buy_shares(self, market_id: int, side: int, usdc_in: int) -> str:
        return self.send(self.spot.functions.buyShares(int(market_id), int(side), int(usdc_in), 0))

    def vault_deposit(self, amount: int, tier: int) -> str:
        return self.send(self.vault.functions.deposit(int(amount), int(tier)))

    def refresh_rpc(self) -> None:
        self._rotate_rpc()

    def _rotate_rpc(self) -> None:
        urls = list(ordered_rpc_urls(self.cfg.rpc_urls))
        if not urls:
            return
        try:
            idx = urls.index(self.rpc_url)
        except ValueError:
            idx = -1
        for url in urls[idx + 1 :] + urls[: max(idx, 0)]:
            for direct in (True, False):
                if not direct and not self.proxy:
                    continue
                try:
                    w3 = self._make_w3(url, direct=direct)
                    if int(w3.eth.chain_id) != CHAIN_ID:
                        continue
                    self._adopt(w3, url)
                    return
                except Exception:
                    continue

    def wait_native(self, min_wei: int, attempts: int = FAUCET_WAIT_ATTEMPTS) -> bool:
        import time

        for i in range(max(1, attempts)):
            try:
                if self.native_wei() >= min_wei:
                    return True
            except SoftError:
                pass
            if i % 5 == 4:
                self._rotate_rpc()
            time.sleep(1.0 + min(i * 0.2, 1.5))
        try:
            return self.native_wei() >= min_wei
        except SoftError:
            return False

    def wait_usdc(self, min_raw: int, attempts: int = FAUCET_WAIT_ATTEMPTS) -> bool:
        import time

        for i in range(max(1, attempts)):
            try:
                if self.usdc_raw() >= min_raw:
                    return True
            except SoftError:
                pass
            if i % 5 == 4:
                self._rotate_rpc()
            time.sleep(1.0 + min(i * 0.2, 1.5))
        try:
            return self.usdc_raw() >= min_raw
        except SoftError:
            return False
