from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunConfig:
    pause_from_ms: int = 400
    pause_to_ms: int = 1200
    request_timeout: int = 45


def integer_option(options: dict[str, Any], name: str, default: int, low: int, high: int) -> int:
    value = options.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name}_invalid")
    if not low <= value <= high:
        raise ValueError(f"{name}_range")
    return value


def run_config(options: dict[str, Any]) -> RunConfig:
    pause_from = integer_option(options, "pause_from_ms", 400, 0, 8000)
    pause_to = integer_option(options, "pause_to_ms", 1200, 0, 8000)
    if pause_from > pause_to:
        raise ValueError("pause_range")
    return RunConfig(pause_from_ms=pause_from, pause_to_ms=pause_to)
