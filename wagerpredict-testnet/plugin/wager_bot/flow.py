from __future__ import annotations

from typing import Any


def already_linked(stats: dict[str, Any] | None) -> bool:
    data = stats or {}
    if data.get("attributed") is True:
        return True
    for key in (
        "referrer",
        "referred_by",
        "referrer_address",
        "parent",
        "parent_address",
        "ref",
    ):
        value = data.get(key)
        if isinstance(value, str):
            text = value.strip().lower()
            if text and text not in {"none", "null", "0x0000000000000000000000000000000000000000"}:
                return True
        if isinstance(value, dict) and (value.get("address") or value.get("slug")):
            return True
    return False


def linked_result(result: str) -> bool:
    return result in {"attributed", "already"}


def tradable_quote(shares: int) -> bool:
    return int(shares) > 0


def farm_status(*, bets: int, vault: int, error_code: str | None) -> tuple[str, str]:
    if error_code is None:
        if bets > 0:
            return "succeeded", "Цикл завершён"
        return "partial", "Регистрация прошла, но ставку поставить не удалось"
    if bets > 0 or vault:
        return "partial", "Часть цикла прошла, дальше сеть не приняла транзакцию"
    return "failed", ""
