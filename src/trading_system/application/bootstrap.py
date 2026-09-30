from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from trading_system.ports import DatabaseBootstrapper


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    applied_migrations: Mapping[str, tuple[int, ...]]


class BootstrapDatabasesUseCase:
    def __init__(self, bootstrapper: DatabaseBootstrapper) -> None:
        self._bootstrapper = bootstrapper

    def execute(self) -> BootstrapResult:
        raw: Mapping[str, Sequence[int]] = self._bootstrapper.bootstrap()
        normalized = {name: tuple(versions) for name, versions in raw.items()}
        return BootstrapResult(applied_migrations=normalized)
