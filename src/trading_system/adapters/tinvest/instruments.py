from __future__ import annotations

from trading_system.adapters.tinvest.errors import TInvestResponseError
from trading_system.adapters.tinvest.sdk import InstrumentStatus
from trading_system.adapters.tinvest.session import TInvestGrpcSession
from trading_system.domain import Instrument


class TInvestInstrumentsGrpcClient:
    """T-Invest instruments adapter backed by the official Python gRPC SDK."""

    def __init__(self, session: TInvestGrpcSession) -> None:
        self._session = session

    def list_shares(self) -> tuple[Instrument, ...]:
        response = self._session.execute(
            lambda client: client.instruments.shares(
                instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE,
            )
        )
        raw_instruments = getattr(response, "instruments", None)
        if raw_instruments is None or isinstance(raw_instruments, (str, bytes)):
            raise TInvestResponseError(
                "T-Invest Shares response does not contain instruments"
            )

        try:
            items = tuple(raw_instruments)
        except TypeError as exc:
            raise TInvestResponseError(
                "T-Invest Shares response contains invalid instruments"
            ) from exc

        instruments: list[Instrument] = []
        for item in items:
            instruments.append(
                Instrument(
                    instrument_uid=self._required_str(item, "uid"),
                    ticker=self._required_str(item, "ticker").upper(),
                    lot_size=self._required_int(item, "lot"),
                    name=self._optional_str(item, "name"),
                    currency=self._optional_str(item, "currency"),
                    figi=self._optional_str(item, "figi"),
                    exchange=self._optional_str(item, "exchange"),
                    instrument_type="share",
                    active=self._optional_bool(
                        item,
                        "api_trade_available_flag",
                        default=False,
                    ),
                )
            )
        return tuple(instruments)

    @staticmethod
    def _required_str(item: object, name: str) -> str:
        value = getattr(item, name, None)
        if not isinstance(value, str) or not value.strip():
            raise TInvestResponseError(f"T-Invest instrument has invalid {name}")
        return value.strip()

    @staticmethod
    def _optional_str(item: object, name: str) -> str | None:
        value = getattr(item, name, None)
        if value is None:
            return None
        if not isinstance(value, str):
            raise TInvestResponseError(f"T-Invest instrument has invalid {name}")
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _required_int(item: object, name: str) -> int:
        value = getattr(item, name, None)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise TInvestResponseError(f"T-Invest instrument has invalid {name}")
        return value

    @staticmethod
    def _optional_bool(item: object, name: str, *, default: bool) -> bool:
        value = getattr(item, name, None)
        if value is None:
            return default
        if not isinstance(value, bool):
            raise TInvestResponseError(f"T-Invest instrument has invalid {name}")
        return value
