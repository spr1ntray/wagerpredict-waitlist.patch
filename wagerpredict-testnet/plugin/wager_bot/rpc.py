from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from typing import TypeVar

READ_ONLY_RPC_MARKERS = ("workers.dev", "blastapi.io")
LEGACY_GAS_FLOOR_WEI = 100_000_000  # 0.1 gwei — chapel testnet
GAS_LIMIT_CAP = 600_000
_SEND_BLOCK_TTL = 180.0
_RATE_BLOCK_TTL = 20.0

T = TypeVar("T")

_block_lock = threading.Lock()
_blocked_until: dict[str, float] = {}


def is_write_rpc(url: str) -> bool:
    text = (url or "").lower()
    return bool(text) and not any(marker in text for marker in READ_ONLY_RPC_MARKERS)


def write_rpc_urls(urls: Sequence[str]) -> tuple[str, ...]:
    return tuple(url for url in urls if is_write_rpc(url))


def preferred_write_urls(urls: Sequence[str], sticky: str = "") -> tuple[str, ...]:
    writes = list(write_rpc_urls(urls))
    if sticky and sticky in writes:
        writes.remove(sticky)
        writes.insert(0, sticky)
    return tuple(writes)


def send_modes(proxy: str | None) -> tuple[bool, ...]:
    """HTTPProvider `direct` flags. With an account proxy, never egress from the Hub host."""
    if proxy:
        return (False,)
    return (True,)


def is_rpc_hard_reject(exc: BaseException) -> bool:
    text = str(exc).lower()
    if is_native_gas_error(exc) or is_nonce_error(exc) or is_already_known(exc):
        return False
    return (
        "403" in text
        or "forbidden" in text
        or "method not allowed" in text
        or "unauthorized" in text
        or "no longer available" in text
        or "401 unauthorized" in text
    )


def block_ttl_for(exc: BaseException) -> float:
    text = str(exc).lower()
    if "429" in text or "too many requests" in text or "rate limit" in text:
        return _RATE_BLOCK_TTL
    if is_rpc_hard_reject(exc):
        return _SEND_BLOCK_TTL
    return 0.0


def mark_send_blocked(url: str, ttl: float = _SEND_BLOCK_TTL) -> None:
    with _block_lock:
        _blocked_until[url] = time.monotonic() + max(1.0, float(ttl))


def is_send_blocked(url: str) -> bool:
    with _block_lock:
        return _blocked_until.get(url, 0) > time.monotonic()


def clear_send_blocks() -> None:
    with _block_lock:
        _blocked_until.clear()


def live_write_urls(urls: Sequence[str], sticky: str = "") -> tuple[str, ...]:
    ordered = preferred_write_urls(urls, sticky=sticky)
    live = tuple(url for url in ordered if not is_send_blocked(url))
    return live or ordered


def ordered_rpc_urls(urls: Sequence[str]) -> tuple[str, ...]:
    writes = [url for url in urls if is_write_rpc(url)]
    reads = [url for url in urls if not is_write_rpc(url)]
    return tuple(writes + reads)


def apply_legacy_fees(
    tx: dict,
    *,
    gas_price: int,
    multiplier: float = 1.25,
    floor: int = LEGACY_GAS_FLOOR_WEI,
) -> dict:
    out = dict(tx)
    out.pop("maxFeePerGas", None)
    out.pop("maxPriorityFeePerGas", None)
    out.pop("type", None)
    out["gasPrice"] = max(int(int(gas_price) * float(multiplier)), int(floor))
    if "gas" in out:
        out["gas"] = max(21_000, min(int(out["gas"]), GAS_LIMIT_CAP))
    return out


def provider_kwargs(timeout: int, proxy: str | None, *, direct: bool) -> dict:
    kwargs: dict = {"timeout": int(timeout)}
    if proxy and not direct:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    return kwargs


def is_already_known(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "already known" in text or "known transaction" in text or "alreadyimported" in text


def is_nonce_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "nonce too low" in text or "replacement transaction" in text or "already in the tx pool" in text


def is_underpriced(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "underpriced" in text or "fee too low" in text or "max fee per gas less than" in text


_HAVE_WANT_RE = re.compile(r"have\s+(\d+)\s+want\s+(\d+)", re.I)


def parse_have_want(exc: BaseException) -> tuple[int, int] | None:
    match = _HAVE_WANT_RE.search(str(exc))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def fitted_gas_price(have: int, gas: int, floor: int = 10_000_000) -> int:
    units = max(1, int(gas))
    price = int(have) // units
    if price < int(floor):
        return 0
    return price


def affordable_fees(have: int, gas: int, network_price: int, min_price: int = 10_000_000) -> tuple[int, int]:
    """(gas, gasPrice) at network price if `have` can pay, else (0, 0).

    Below-network fees sit in mempool and time out — do not send them.
    """
    units = max(21_000, min(int(gas), GAS_LIMIT_CAP))
    network = max(LEGACY_GAS_FLOOR_WEI, max(1, int(network_price)))
    wallet = max(0, int(have))
    if wallet >= units * network:
        return units, network
    return 0, 0


def is_native_gas_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "allowance" in text or "exceeds balance" in text or "erc20" in text:
        return False
    return (
        "insufficient funds for gas" in text
        or "insufficient funds for intrinsic" in text
        or "insufficient funds for transfer" in text
        or "insufficient funds" in text
        or ("мало" in text and "tbnb" in text)
    )


def rpc_send_hint(exc: BaseException) -> str:
    text = str(exc).lower()
    if is_already_known(exc):
        return "транзакция уже в сети"
    if "403" in text or "forbidden" in text or "method not allowed" in text:
        return "RPC запретил отправку"
    if "429" in text or "rate limit" in text or "too many" in text:
        return "RPC ограничил частоту"
    if "timeout" in text or "timed out" in text:
        return "RPC не ответил вовремя"
    if is_native_gas_error(exc):
        return "мало tBNB на комиссию"
    if is_nonce_error(exc):
        return "не тот nonce"
    return "транзакция не ушла в сеть"


def broadcast_raw(raw: bytes, senders: Iterable[Callable[[bytes], T]]) -> T:
    last: Exception | None = None
    tried = False
    for sender in senders:
        tried = True
        try:
            return sender(raw)
        except Exception as exc:
            last = exc
            continue
    if not tried:
        raise RuntimeError("no_write_rpc")
    assert last is not None
    raise last
