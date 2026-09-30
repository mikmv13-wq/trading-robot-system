from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol


class DatabaseBootstrapper(Protocol):
    def bootstrap(self) -> Mapping[str, Sequence[int]]: ...
