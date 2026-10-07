from __future__ import annotations

import random
import time
from typing import Callable
from urllib.parse import quote, urlparse

_CHECK_CANCEL = Callable[[], None]


def normalize_private_key(raw: str) -> str:
    value = (raw or "").strip()
    if value.startswith("0x") or value.startswith("0X"):
        value = value[2:]
    if len(value) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        raise ValueError("bad_key")
    return "0x" + value.lower()


def normalize_proxy(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None

    if "://" in value:
        parsed = urlparse(value)
        if not parsed.hostname or not parsed.port:
            raise ValueError("invalid_proxy")
        scheme = parsed.scheme or "http"
        if parsed.username is None:
            return f"{scheme}://{parsed.hostname}:{parsed.port}"
        user = quote(parsed.username, safe="")
        password = quote(parsed.password or "", safe="")
        return f"{scheme}://{user}:{password}@{parsed.hostname}:{parsed.port}"

    parts = value.split(":")
    if len(parts) == 2:
        host, port = parts
        if not host or not port.isdigit():
            raise ValueError("invalid_proxy")
        return f"http://{host}:{port}"
    if len(parts) >= 4:
        host, port, user = parts[0], parts[1], parts[2]
        password = ":".join(parts[3:])
        if not host or not port.isdigit() or not user:
            raise ValueError("invalid_proxy")
        return f"http://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    raise ValueError("invalid_proxy")


def pause_ms(low: int, high: int, check_cancelled: _CHECK_CANCEL | None = None) -> None:
    lo = max(0, min(int(low), int(high)))
    hi = max(lo, int(high))
    delay = random.randint(lo, hi) / 1000.0
    deadline = time.monotonic() + delay
    while True:
        if check_cancelled is not None:
            check_cancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.25, remaining))
