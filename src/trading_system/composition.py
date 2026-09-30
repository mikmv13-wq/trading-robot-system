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
from trading_system.adapters.tinvest import TInvestInstrumentsRestClient, TInvestMarketDataRestClient
from trading_system.application import (
    BootstrapDatabasesUseCase,
    GetSystemStatusUseCase,
    JobApplicationService,
    JobManager,
    SyncInstrumentsUseCase,
    TInvestTokenService,
)
from trading_system.config import FileUniverseConfig, Settings
from trading_system.infrastructure import ThreadJobManager
from trading_system.ports import SecretStorage, TInvestMarketDataClient


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    """Composition root result shared by CLI and desktop GUI."""

    bootstrap_databases: BootstrapDatabasesUseCase
    get_system_status: GetSystemStatusUseCase
    jobs: JobApplicationService
    tinvest_token: TInvestTokenService
    sync_instruments: SyncInstrumentsUseCase
    tinvest_market_data: TInvestMarketDataClient
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
    token_service = TInvestTokenService(resolved_secret_storage)
    market_repository = repositories["market"]
    if not isinstance(market_repository, DuckDBMarketRepository):
        raise TypeError("market repository must be DuckDBMarketRepository")
    instruments_client = TInvestInstrumentsRestClient(token_service.get_token)
    market_data_client = TInvestMarketDataRestClient(token_service.get_token)

    return ApplicationServices(
        bootstrap_databases=BootstrapDatabasesUseCase(
            DuckDBBootstrapper(settings, connection_factory)
        ),
        get_system_status=GetSystemStatusUseCase(repositories),
        jobs=JobApplicationService(job_manager),
        tinvest_token=token_service,
        tinvest_market_data=market_data_client,
        sync_instruments=SyncInstrumentsUseCase(
            FileUniverseConfig(settings.universe_config_path),
            instruments_client,
            market_repository,
        ),
        _job_manager=job_manager,
    )
