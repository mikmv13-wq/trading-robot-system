from __future__ import annotations

from typing import Mapping, Protocol, Sequence


class DatabaseBootstrapper(Protocol):
    def bootstrap(self) -> Mapping[str, Sequence[int]]: ...
