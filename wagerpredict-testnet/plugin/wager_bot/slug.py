from __future__ import annotations

import re

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,28}[a-z0-9]$")


def slug_from_email(email: str, address: str = "") -> str:
    local = (email or "").split("@", 1)[0].lower()
    local = local.split("+", 1)[0]
    cleaned = re.sub(r"[^a-z0-9-]+", "", local)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    if not SLUG_RE.fullmatch(cleaned):
        tail = re.sub(r"[^a-z0-9]", "", (address or "").lower().removeprefix("0x"))[-6:]
        body = re.sub(r"[^a-z0-9]", "", cleaned) + tail
        body = (body or "wpuser")[:30]
        if len(body) < 3:
            body = (body + "wp")[:30]
        cleaned = body
    if not SLUG_RE.fullmatch(cleaned):
        cleaned = (cleaned.replace("-", "") + "wp")[:30]
        if len(cleaned) < 3:
            cleaned = (cleaned + "wp0")[:30]
        if not cleaned[0].isalnum():
            cleaned = "w" + cleaned[1:]
        if not cleaned[-1].isalnum():
            cleaned = cleaned[:-1] + "0"
    return cleaned[:30]


def alternate_slug(base: str, address: str) -> str:
    tail = re.sub(r"[^a-z0-9]", "", (address or "").lower().removeprefix("0x"))[-4:]
    stem = re.sub(r"[^a-z0-9]", "", base)[:24] or "wp"
    candidate = f"{stem}-{tail}" if tail else f"{stem}x"
    if SLUG_RE.fullmatch(candidate):
        return candidate
    return slug_from_email(candidate, address)
