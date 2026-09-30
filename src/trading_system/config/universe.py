from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast


class UniverseConfigError(RuntimeError):
    """Raised when the local universe configuration is invalid."""


@dataclass(frozen=True, slots=True)
class UniverseDefinition:
    universe_id: str
    name: str
    tickers: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized = tuple(ticker.strip().upper() for ticker in self.tickers)
        if not self.universe_id.strip():
            raise ValueError("universe_id must not be empty")
        if not self.name.strip():
            raise ValueError("universe name must not be empty")
        if any(not ticker for ticker in normalized):
            raise ValueError("universe tickers must not contain empty values")
        if len(set(normalized)) != len(normalized):
            raise ValueError("universe tickers must not contain duplicates")
        object.__setattr__(self, "tickers", normalized)


class UniverseConfigProvider(Protocol):
    def get_universe(self, universe_id: str) -> UniverseDefinition: ...

    def list_universes(self) -> tuple[UniverseDefinition, ...]: ...


class FileUniverseConfig:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def get_universe(self, universe_id: str) -> UniverseDefinition:
        universes = self._load_universes()
        try:
            return universes[universe_id]
        except KeyError as exc:
            raise UniverseConfigError(
                f"universe {universe_id!r} is not defined in {self._path}"
            ) from exc

    def list_universes(self) -> tuple[UniverseDefinition, ...]:
        universes = self._load_universes()
        return tuple(universes[key] for key in sorted(universes))

    def _load_universes(self) -> dict[str, UniverseDefinition]:
        try:
            with self._path.open("rb") as handle:
                document: object = tomllib.load(handle)
        except OSError as exc:
            raise UniverseConfigError(
                f"unable to read universe config: {self._path}"
            ) from exc
        except tomllib.TOMLDecodeError as exc:
            raise UniverseConfigError(
                f"invalid TOML in universe config: {self._path}"
            ) from exc

        if not isinstance(document, dict):
            raise UniverseConfigError("universe config root must be a table")
        root = cast(dict[str, object], document)
        raw_universes = root.get("universes")
        if not isinstance(raw_universes, dict):
            raise UniverseConfigError("universe config must contain [universes]")

        result: dict[str, UniverseDefinition] = {}
        for universe_id, raw_definition in cast(dict[str, object], raw_universes).items():
            if not isinstance(raw_definition, dict):
                raise UniverseConfigError(
                    f"universe {universe_id!r} must be a table"
                )
            definition = cast(dict[str, object], raw_definition)
            name = definition.get("name")
            tickers = definition.get("tickers")
            if not isinstance(name, str):
                raise UniverseConfigError(
                    f"universe {universe_id!r} must define string name"
                )
            if not isinstance(tickers, list) or not all(
                isinstance(ticker, str) for ticker in tickers
            ):
                raise UniverseConfigError(
                    f"universe {universe_id!r} must define string tickers"
                )
            try:
                result[universe_id] = UniverseDefinition(
                    universe_id=universe_id,
                    name=name,
                    tickers=tuple(cast(list[str], tickers)),
                )
            except ValueError as exc:
                raise UniverseConfigError(
                    f"invalid universe {universe_id!r}: {exc}"
                ) from exc

        return result
