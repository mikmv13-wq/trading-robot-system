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
from trading_system.adapters.tinvest import (
    TInvestInstrumentsRestClient,
    TInvestMarketDataRestClient,
)
from trading_system.application import (
    BackfillHistoricalCandlesUseCase,
    BootstrapDatabasesUseCase,
    DataApplicationService,
    GetSystemStatusUseCase,
    HistoricalBackfillService,
    JobApplicationService,
    JobManager,
    SyncInstrumentsUseCase,
    TInvestTokenService,
    ValidateMarketDataUseCase,
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
    historical_backfill: HistoricalBackfillService
    validate_market_data: ValidateMarketDataUseCase
    data: DataApplicationService
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
    backfill_use_case = BackfillHistoricalCandlesUseCase(
        market_data_client,
        market_repository,
    )
    jobs_service = JobApplicationService(job_manager)
    universe_config = FileUniverseConfig(settings.universe_config_path)
    sync_use_case = SyncInstrumentsUseCase(
        universe_config,
        instruments_client,
        market_repository,
    )
    validation_use_case = ValidateMarketDataUseCase(market_repository)
    backfill_service = HistoricalBackfillService(
        job_manager,
        backfill_use_case,
    )
    data_service = DataApplicationService(
        sync_use_case,
        backfill_service,
        validation_use_case,
        jobs_service,
        market_repository,
        universe_config,
    )

    return ApplicationServices(
        bootstrap_databases=BootstrapDatabasesUseCase(
            DuckDBBootstrapper(settings, connection_factory)
        ),
        get_system_status=GetSystemStatusUseCase(repositories),
        jobs=jobs_service,
        tinvest_token=token_service,
        tinvest_market_data=market_data_client,
        validate_market_data=validation_use_case,
        historical_backfill=backfill_service,
        sync_instruments=sync_use_case,
        data=data_service,
        _job_manager=job_manager,
    )
