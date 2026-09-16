from __future__ import annotations

import random
from dataclasses import dataclass

from .utils import pause_ms


@dataclass(frozen=True)
class AccountPace:
    start_ms: int
    step_from_ms: int
    step_to_ms: int
    tx_from_ms: int
    tx_to_ms: int
    think_from_ms: int
    think_to_ms: int

    def start(self, check_cancelled=None) -> None:
        pause_ms(self.start_ms, self.start_ms, check_cancelled)

    def step(self, check_cancelled=None) -> None:
        pause_ms(self.step_from_ms, self.step_to_ms, check_cancelled)

    def before_tx(self, check_cancelled=None) -> None:
        pause_ms(self.tx_from_ms, self.tx_to_ms, check_cancelled)

    def think(self, check_cancelled=None) -> None:
        pause_ms(self.think_from_ms, self.think_to_ms, check_cancelled)


def make_pace() -> AccountPace:
    step_lo = random.randint(40, 140)
    tx_lo = random.randint(180, 450)
    think_lo = random.randint(60, 180)
    return AccountPace(
        start_ms=random.randint(80, 700),
        step_from_ms=step_lo,
        step_to_ms=step_lo + random.randint(80, 280),
        tx_from_ms=tx_lo,
        tx_to_ms=tx_lo + random.randint(150, 700),
        think_from_ms=think_lo,
        think_to_ms=think_lo + random.randint(80, 350),
    )
