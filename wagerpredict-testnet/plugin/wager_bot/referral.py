from __future__ import annotations

from typing import Any, Callable

from .errors import BlockedError, SoftError
from .flow import already_linked
from .http import ProjectHttp
from .slug import SLUG_RE, alternate_slug, slug_from_email

Protect = Callable[[str], str]


def fetch_stats(http: ProjectHttp, address: str) -> dict[str, Any]:
    data = http.get(f"/api/referrals/stats/{address.lower()}")
    return data if isinstance(data, dict) else {}


def public_slug(stats: dict[str, Any]) -> str:
    value = str(stats.get("slug") or "").strip().lower()
    return value if SLUG_RE.fullmatch(value) else ""


def referred_count(stats: dict[str, Any]) -> int:
    try:
        return int(stats.get("total_referred") or 0)
    except (TypeError, ValueError):
        return 0


def attribute_parent(http: ProjectHttp, *, address: str, parent_slug: str) -> str:
    stats = fetch_stats(http, address)
    if already_linked(stats):
        return "already"
    if not SLUG_RE.fullmatch(parent_slug or ""):
        raise BlockedError("parent_slug_missing", "У родителя ещё нет реферальной ссылки")
    try:
        payload = http.post(
            "/api/referrals/attribute",
            {"address": address.lower(), "ref": parent_slug},
        )
    except SoftError as exc:
        if exc.code in {"already", "already_attributed", "exists"}:
            return "already"
        raise SoftError(exc.code, "Не удалось привязать аккаунт к родителю") from exc
    if isinstance(payload, dict) and payload.get("attributed") is False:
        reason = str(payload.get("reason") or "attribute_failed")
        if reason in {"already", "already_attributed", "exists"}:
            return "already"
        raise SoftError("attribute_failed", "Не удалось привязать аккаунт к родителю")
    return "attributed"


def claim_own_slug(
    http: ProjectHttp,
    *,
    address: str,
    email: str,
    protect: Protect,
) -> str:
    stats = fetch_stats(http, address)
    existing = public_slug(stats)
    if existing:
        protect(existing)
        return "exists"

    base = slug_from_email(email, address)
    candidates = [base, alternate_slug(base, address)]
    last = "claim_failed"
    for raw in candidates:
        code = protect(raw) or raw
        try:
            payload = http.post(
                "/api/referrals/claim",
                {"address": address.lower(), "slug": code},
            )
        except SoftError as exc:
            last = exc.code
            if exc.code in {"taken", "slug_taken", "conflict"}:
                continue
            raise
        claimed = ""
        if isinstance(payload, dict):
            claimed = str(payload.get("slug") or "").strip().lower()
            if payload.get("ok") is False:
                last = str(payload.get("error") or "claim_failed")
                continue
        if claimed:
            protect(claimed)
        confirm = public_slug(fetch_stats(http, address))
        if confirm:
            protect(confirm)
            return "claimed"
    raise SoftError(last, "Не удалось закрепить собственную реферальную ссылку")
