import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from typer.testing import CliRunner

from trading_system.adapters.duckdb import DuckDBBootstrapper, DuckDBMarketRepository
from trading_system.application import BootstrapDatabasesUseCase
from trading_system.cli import app
from trading_system.config import Settings
from trading_system.domain import Candle1m, Instrument, Universe

runner = CliRunner()


def _runtime(tmp_path: Path) -> tuple[Path, Path]:
    source = Path(__file__).parents[2] / "sql"
    sql_dir = tmp_path / "sql"
    shutil.copytree(source, sql_dir)
    data_dir = tmp_path / "data"
    settings = Settings(
        data_dir=data_dir,
        log_dir=tmp_path / "logs",
        sql_dir=sql_dir,
    )
    BootstrapDatabasesUseCase(DuckDBBootstrapper(settings)).execute()
    repository = DuckDBMarketRepository(settings.market_db_path)
    repository.sync_universe(
        Universe("default", "Default", ("uid-a", "uid-b")),
        (
            Instrument("uid-a", "AAA", 1),
            Instrument("uid-b", "BBB", 1),
        ),
    )
    start = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)
    repository.upsert_candles(
        (
            Candle1m(
                "uid-a",
                start,
                Decimal("100"),
                Decimal("101"),
                Decimal("99"),
                Decimal("100.5"),
                10,
            ),
            Candle1m(
                "uid-b",
                start,
                Decimal("100"),
                Decimal("101"),
                Decimal("99"),
                Decimal("100.5"),
                10,
            ),
            Candle1m(
                "uid-b",
                start + timedelta(minutes=1),
                Decimal("100"),
                Decimal("101"),
                Decimal("99"),
                Decimal("100.5"),
                10,
            ),
        )
    )
    return data_dir, sql_dir


def test_cli_data_status_reports_coverage(tmp_path: Path) -> None:
    data_dir, _ = _runtime(tmp_path)

    result = runner.invoke(
        app,
        ["data", "status", "--data-dir", str(data_dir)],
    )

    assert result.exit_code == 0
    assert "universe=default instruments=2 rows=3 gaps=0" in result.stdout
    assert "AAA: uid=uid-a rows=1" in result.stdout
    assert "BBB: uid=uid-b rows=2" in result.stdout


def test_cli_data_validate_reports_gap_warning(tmp_path: Path) -> None:
    data_dir, _ = _runtime(tmp_path)

    result = runner.invoke(
        app,
        [
            "data",
            "validate",
            "--data-dir",
            str(data_dir),
            "--from-ts",
            "2026-01-05T07:00:00Z",
            "--to-ts",
            "2026-01-05T07:02:00Z",
        ],
    )

    assert result.exit_code == 0
    assert "status=WARNING" in result.stdout
    assert "uid-a: status=WARNING rows=1 gaps=1 missing_minutes=1" in result.stdout
    assert "uid-b: status=PASS rows=2 gaps=0 missing_minutes=0" in result.stdout


def test_cli_backfill_resume_rejects_explicit_range() -> None:
    result = runner.invoke(
        app,
        [
            "data",
            "backfill",
            "--resume",
            "--from-ts",
            "2026-01-01T00:00:00Z",
        ],
    )

    assert result.exit_code == 1
    assert "--resume cannot be combined" in result.stderr
