from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class Repository(Protocol):
    """Common diagnostic contract exposed by all storage repositories."""

    def healthcheck(self) -> None: ...

    def schema_version(self) -> int: ...

    def metadata(self) -> Mapping[str, str]: ...


class MarketRepository(Repository, Protocol):
    pass


class ResearchRepository(Repository, Protocol):
    pass


class LiveRepository(Repository, Protocol):
    pass
