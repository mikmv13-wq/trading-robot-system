from pathlib import Path

from trading_system.config import Settings


def test_database_paths_are_derived_from_data_dir(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "db", log_dir=tmp_path / "logs", sql_dir=tmp_path / "sql")

    assert settings.market_db_path == tmp_path / "db" / "market.duckdb"
    assert settings.research_db_path == tmp_path / "db" / "research.duckdb"
    assert settings.live_db_path == tmp_path / "db" / "live.duckdb"
