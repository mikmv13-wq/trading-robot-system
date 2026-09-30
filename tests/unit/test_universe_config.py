from pathlib import Path

import pytest

from trading_system.config import FileUniverseConfig, UniverseConfigError


def test_file_universe_config_loads_and_normalizes_tickers(tmp_path: Path) -> None:
    path = tmp_path / "universe.toml"
    path.write_text(
        """
[universes.default]
name = "Test"
tickers = ["sber", " GAZP "]
""".strip(),
        encoding="utf-8",
    )

    universe = FileUniverseConfig(path).get_universe("default")

    assert universe.universe_id == "default"
    assert universe.name == "Test"
    assert universe.tickers == ("SBER", "GAZP")


def test_file_universe_config_rejects_duplicate_tickers(tmp_path: Path) -> None:
    path = tmp_path / "universe.toml"
    path.write_text(
        """
[universes.default]
name = "Test"
tickers = ["SBER", "sber"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(UniverseConfigError, match="duplicates"):
        FileUniverseConfig(path).get_universe("default")
