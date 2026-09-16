from __future__ import annotations

import threading
from typing import Any

from .capsolver import solve_turnstile
from .config import FAUCET_SLOTS, TURNSTILE_PAGE, TURNSTILE_SITEKEY
from .errors import SoftError, faucet_reason_message, faucet_retryable, is_soft_faucet
from .http import ProjectHttp

_FAUCET_SLOTS = threading.Semaphore(FAUCET_SLOTS)


def _post_faucet(http: ProjectHttp, path: str, address: str, token: str) -> dict[str, Any]:
    data = http.post(path, {"address": address, "turnstileToken": token})
    return data if isinstance(data, dict) else {}


def claim_gas(
    http: ProjectHttp,
    *,
    address: str,
    capsolver_key: str,
    proxy: str | None,
    protect=None,
) -> str:
    status = http.get("/api/faucet/gas")
    if isinstance(status, dict) and status.get("enabled") is False:
        return "disabled"
    last = "error"
    for attempt in range(3):
        token = ""
        if not isinstance(status, dict) or status.get("turnstile", True):
            token = solve_turnstile(
                capsolver_key,
                site_key=TURNSTILE_SITEKEY,
                page_url=TURNSTILE_PAGE,
                proxy=proxy,
            )
            if protect is not None:
                token = protect(token) or token
        try:
            with _FAUCET_SLOTS:
                payload = _post_faucet(http, "/api/faucet/gas", address, token)
        except SoftError as exc:
            if faucet_retryable(exc.code) and attempt < 2:
                import time

                time.sleep(8.0 + attempt * 4.0)
                last = exc.code
                continue
            if is_soft_faucet(exc.code):
                return exc.code
            raise SoftError(exc.code, faucet_reason_message("gas", exc.code)) from exc
        if payload.get("ok") is False:
            reason = str(payload.get("reason") or "error")
            if faucet_retryable(reason) and attempt < 2:
                import time

                time.sleep(8.0 + attempt * 4.0)
                last = reason
                continue
            if is_soft_faucet(reason):
                return reason
            raise SoftError(reason, faucet_reason_message("gas", reason))
        return "claimed"
    return last


def claim_usdc(
    http: ProjectHttp,
    *,
    address: str,
    capsolver_key: str,
    proxy: str | None,
    protect=None,
) -> str:
    status = http.get("/api/faucet/usdc")
    if isinstance(status, dict) and status.get("enabled") is False:
        return "disabled"
    token = ""
    if not isinstance(status, dict) or status.get("turnstile", True):
        token = solve_turnstile(
            capsolver_key,
            site_key=TURNSTILE_SITEKEY,
            page_url=TURNSTILE_PAGE,
            proxy=proxy,
        )
        if protect is not None:
            token = protect(token) or token
    try:
        with _FAUCET_SLOTS:
            payload = _post_faucet(http, "/api/faucet/usdc", address, token)
    except SoftError as exc:
        if is_soft_faucet(exc.code):
            return exc.code
        raise SoftError(exc.code, faucet_reason_message("usdc", exc.code)) from exc
    if payload.get("ok") is False:
        reason = str(payload.get("reason") or "error")
        if is_soft_faucet(reason):
            return reason
        raise SoftError(reason, faucet_reason_message("usdc", reason))
    return "claimed"
