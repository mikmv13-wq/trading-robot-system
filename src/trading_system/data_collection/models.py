from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


NANO_FACTOR = 1_000_000_000


@dataclass(frozen=True, slots=True)
class Candle:
    instrument_id: str
    time: datetime
    open_nano: int
    high_nano: int
    low_nano: int
    close_nano: int
    volume: int
    is_complete: bool
    source: str | None = None
