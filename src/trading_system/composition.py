from __future__ import annotations

from dataclasses import dataclass

from trading_system.adapters.duckdb import (
    DuckDBBootstrapper,
    DuckDBConnectionFactory,
    DuckDBLiveRepository,
    DuckDBMarketRepository,
    DuckDBResearchRepository,
)
from trading_system.application import BootstrapDatabasesUseCase, GetSystemStatusUseCase
from trading_system.config import Settings


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    """Composition root result shared by CLI and the future desktop GUI."""

    bootstrap_databases: BootstrapDatabasesUseCase
    get_system_status: GetSystemStatusUseCase


def build_application_services(settings: Settings) -> ApplicationServices:
    """Wire application use cases to concrete local adapters."""

    connection_factory = DuckDBConnectionFactory()
    repositories = {
        "market": DuckDBMarketRepository(settings.market_db_path, connection_factory),
        "research": DuckDBResearchRepository(settings.research_db_path, connection_factory),
        "live": DuckDBLiveRepository(settings.live_db_path, connection_factory),
    }

    return ApplicationServices(
        bootstrap_databases=BootstrapDatabasesUseCase(
            DuckDBBootstrapper(settings, connection_factory)
        ),
        get_system_status=GetSystemStatusUseCase(repositories),
    )
