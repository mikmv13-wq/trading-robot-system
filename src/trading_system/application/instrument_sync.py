from __future__ import annotations

from dataclasses import dataclass

from trading_system.config import UniverseConfigProvider
from trading_system.domain import Instrument, Universe
from trading_system.ports import MarketRepository, TInvestInstrumentsClient


@dataclass(frozen=True, slots=True)
class InstrumentSyncIssue:
    ticker: str
    reason: str


class InstrumentSyncError(RuntimeError):
    def __init__(self, issues: tuple[InstrumentSyncIssue, ...]) -> None:
        self.issues = issues
        details = "; ".join(f"{issue.ticker}: {issue.reason}" for issue in issues)
        super().__init__(f"unable to resolve configured universe: {details}")


@dataclass(frozen=True, slots=True)
class InstrumentSyncResult:
    universe: Universe
    instruments: tuple[Instrument, ...]


class SyncInstrumentsUseCase:
    def __init__(
        self,
        universe_config: UniverseConfigProvider,
        tinvest: TInvestInstrumentsClient,
        market_repository: MarketRepository,
    ) -> None:
        self._universe_config = universe_config
        self._tinvest = tinvest
        self._market_repository = market_repository

    def execute(self, universe_id: str = "default") -> InstrumentSyncResult:
        definition = self._universe_config.get_universe(universe_id)
        broker_instruments = self._tinvest.list_shares()
        by_ticker: dict[str, list[Instrument]] = {}
        for instrument in broker_instruments:
            by_ticker.setdefault(instrument.ticker.upper(), []).append(instrument)

        resolved: list[Instrument] = []
        issues: list[InstrumentSyncIssue] = []
        for ticker in definition.tickers:
            candidates = by_ticker.get(ticker, [])
            active_candidates = [candidate for candidate in candidates if candidate.active]
            if not candidates:
                issues.append(InstrumentSyncIssue(ticker, "not found"))
                continue
            if not active_candidates:
                issues.append(
                    InstrumentSyncIssue(ticker, "not available for T-Invest API trading")
                )
                continue
            if len(active_candidates) > 1:
                issues.append(
                    InstrumentSyncIssue(
                        ticker,
                        f"ambiguous ({len(active_candidates)} active instruments)",
                    )
                )
                continue
            resolved.append(active_candidates[0])

        if issues:
            raise InstrumentSyncError(tuple(issues))

        universe = Universe(
            universe_id=definition.universe_id,
            name=definition.name,
            instrument_uids=tuple(instrument.instrument_uid for instrument in resolved),
        )
        self._market_repository.sync_universe(universe, tuple(resolved))
        return InstrumentSyncResult(universe=universe, instruments=tuple(resolved))
