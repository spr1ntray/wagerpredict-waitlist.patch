from __future__ import annotations

import random
import time
from typing import Any

from .errors import SoftError
from .http import ProjectHttp


def list_open_markets(http: ProjectHttp, limit: int = 200) -> list[dict[str, Any]]:
    data = http.get("/api/markets", params={"limit": max(20, min(limit, 1000))})
    items: list[Any]
    if isinstance(data, dict):
        items = list(data.get("markets") or [])
    elif isinstance(data, list):
        items = data
    else:
        items = []
    now = int(time.time())
    open_markets: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "") != "open":
            continue
        if item.get("hidden") is True:
            continue
        if str(item.get("result") or "none") not in {"", "none", "null"}:
            continue
        try:
            expires = int(item.get("expires_at") or 0)
        except (TypeError, ValueError):
            expires = 0
        if expires and expires <= now:
            continue
        try:
            market_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        open_markets.append({"id": market_id, "category": str(item.get("category") or "")})
    if not open_markets:
        raise SoftError("no_open_markets", "Сейчас нет открытых рынков для ставки")
    return open_markets


def pick_markets(markets: list[dict[str, Any]], count: int) -> list[int]:
    ids = [int(item["id"]) for item in markets]
    random.shuffle(ids)
    if not ids:
        return []
    if count >= len(ids):
        return ids
    return ids[:count]


def user_bet_count(http: ProjectHttp, address: str) -> int:
    data = http.get(f"/api/bets/user/{address.lower()}", params={"limit": 100})
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        bets = data.get("bets")
        if isinstance(bets, list):
            return len(bets)
        try:
            return int(data.get("count") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def earned_achievements(http: ProjectHttp, address: str) -> int:
    data = http.get(f"/api/achievements/{address.lower()}")
    items = data.get("achievements") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return 0
    return sum(1 for item in items if isinstance(item, dict) and item.get("earned") is True)
