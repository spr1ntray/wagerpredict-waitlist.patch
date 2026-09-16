from __future__ import annotations

import random
from typing import Any

from .config import BETS_MAX, MIN_BET_USDC, MIN_VAULT_USDC, VAULT_TIERS, VAULT_USDC_MAX, RunConfig
from .utils import usdc_to_raw


def integer_option(options: dict[str, Any], name: str, default: int, low: int, high: int) -> int:
    value = options.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name}_invalid")
    if not low <= value <= high:
        raise ValueError(f"{name}_range")
    return value


def string_option(options: dict[str, Any], name: str, default: str, allowed: set[str]) -> str:
    value = options.get(name, default)
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{name}_invalid")
    return value


def farm_config(options: dict[str, Any]) -> RunConfig:
    bets_from = integer_option(options, "bets_from", 10, 1, BETS_MAX)
    bets_to = integer_option(options, "bets_to", 14, 1, BETS_MAX)
    if bets_from > bets_to:
        raise ValueError("bets_range")
    bet_from = integer_option(options, "bet_usdc_from", 100, 10, 10_000)
    bet_to = integer_option(options, "bet_usdc_to", 1000, 10, 10_000)
    if bet_from > bet_to:
        raise ValueError("bet_usdc_range")
    vault_from = integer_option(options, "vault_usdc_from", 50, 0, VAULT_USDC_MAX)
    vault_to = integer_option(options, "vault_usdc_to", 10000, 0, VAULT_USDC_MAX)
    if vault_from > vault_to:
        raise ValueError("vault_usdc_range")
    tier_name = string_option(options, "vault_tier", "flexible", set(VAULT_TIERS))
    pause_from = integer_option(options, "pause_from_ms", 800, 200, 8000)
    pause_to = integer_option(options, "pause_to_ms", 2400, 200, 8000)
    if pause_from > pause_to:
        raise ValueError("pause_range")
    return RunConfig(
        bets_from=bets_from,
        bets_to=bets_to,
        bet_usdc_from=bet_from,
        bet_usdc_to=bet_to,
        vault_usdc_from=vault_from,
        vault_usdc_to=vault_to,
        vault_tier=VAULT_TIERS[tier_name],
        pause_from_ms=pause_from,
        pause_to_ms=pause_to,
    )


def pick_bet_raw(cfg: RunConfig, balance: int, reserve_usdc: int, remaining_bets: int) -> int:
    reserve = usdc_to_raw(reserve_usdc) if reserve_usdc >= MIN_VAULT_USDC else 0
    available = max(0, int(balance) - reserve)
    if available < usdc_to_raw(MIN_BET_USDC):
        return 0
    left = max(1, int(remaining_bets))
    slice_ = available // left
    low = usdc_to_raw(cfg.bet_usdc_from)
    high = usdc_to_raw(cfg.bet_usdc_to)
    high = min(available, max(high, slice_))
    low = min(low, high)
    if low <= 0:
        return 0
    return random.randint(low, high)


def pick_vault_amount(cfg: RunConfig) -> int:
    low = max(0, cfg.vault_usdc_from)
    high = max(low, cfg.vault_usdc_to)
    if high < MIN_VAULT_USDC:
        return 0
    chosen = random.randint(low, high)
    if chosen <= 0:
        return 0
    if chosen < MIN_VAULT_USDC:
        return MIN_VAULT_USDC
    return chosen
