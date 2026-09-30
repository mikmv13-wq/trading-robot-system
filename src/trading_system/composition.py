from __future__ import annotations

from dataclasses import dataclass

from trading_system.adapters.duckdb import (
    DuckDBBootstrapper,
    DuckDBConnectionFactory,
    DuckDBLiveRepository,
    DuckDBMarketRepository,
    DuckDBResearchRepository,
)
from trading_system.adapters.keychain import KeyringSecretStorage
from trading_system.application import (
    BootstrapDatabasesUseCase,
    GetSystemStatusUseCase,
    JobApplicationService,
    JobManager,
    TInvestTokenService,
)
from trading_system.config import Settings
from trading_system.infrastructure import ThreadJobManager
from trading_system.ports import SecretStorage


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    """Composition root result shared by CLI and desktop GUI."""

    bootstrap_databases: BootstrapDatabasesUseCase
    get_system_status: GetSystemStatusUseCase
    jobs: JobApplicationService
    tinvest_token: TInvestTokenService
    _job_manager: JobManager

    def close(self) -> None:
        self._job_manager.shutdown(wait=False, cancel_running=True)


def build_application_services(
    settings: Settings,
    *,
    secret_storage: SecretStorage | None = None,
) -> ApplicationServices:
    """Wire application use cases to concrete local adapters."""

    connection_factory = DuckDBConnectionFactory()
    repositories = {
        "market": DuckDBMarketRepository(settings.market_db_path, connection_factory),
        "research": DuckDBResearchRepository(settings.research_db_path, connection_factory),
        "live": DuckDBLiveRepository(settings.live_db_path, connection_factory),
    }
    job_manager = ThreadJobManager(max_workers=2)
    resolved_secret_storage = secret_storage or KeyringSecretStorage()

    return ApplicationServices(
        bootstrap_databases=BootstrapDatabasesUseCase(
            DuckDBBootstrapper(settings, connection_factory)
        ),
        get_system_status=GetSystemStatusUseCase(repositories),
        jobs=JobApplicationService(job_manager),
        tinvest_token=TInvestTokenService(resolved_secret_storage),
        _job_manager=job_manager,
    )
