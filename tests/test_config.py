from pathlib import Path

from trading_system.config import load_settings


def test_load_example_config(tmp_path: Path) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text(
        """
t_invest:
  token_env: T_INVEST_TOKEN
collector:
  interval: 1m
  history_from: "2021-01-01T00:00:00Z"
storage:
  root_path: data/market
  catalog_path: data/trading.duckdb
aggregations:
  intervals: [15m, 30m, 1h]
instruments:
  - instrument_id: TEST
    ticker: TST
""",
        encoding="utf-8",
    )

    settings = load_settings(config)
    assert settings.collector.interval == "1m"
    assert settings.instruments[0].instrument_id == "TEST"
    assert settings.t_invest.requests_per_minute == 480
    assert settings.storage.root_path == Path("data/market")
    assert settings.storage.catalog_path == Path("data/trading.duckdb")
    assert settings.storage.compression == "zstd"
    assert settings.aggregations.intervals == ("15m", "30m", "1h")
