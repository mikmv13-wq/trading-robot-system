import shutil
from pathlib import Path

from typer.testing import CliRunner

from trading_system.cli import app

runner = CliRunner()


def _copy_sql(tmp_path: Path) -> Path:
    source = Path(__file__).parents[2] / "sql"
    target = tmp_path / "sql"
    shutil.copytree(source, target)
    return target


def test_cli_bootstrap_and_db_status_use_same_application_services(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    sql_dir = _copy_sql(tmp_path)

    bootstrap = runner.invoke(
        app,
        [
            "bootstrap",
            "--data-dir",
            str(data_dir),
            "--sql-dir",
            str(sql_dir),
        ],
    )
    status = runner.invoke(app, ["db", "status", "--data-dir", str(data_dir)])

    assert bootstrap.exit_code == 0
    assert "market: applied migrations: 1" in bootstrap.stdout
    assert "research: applied migrations: 1" in bootstrap.stdout
    assert "live: applied migrations: 1" in bootstrap.stdout

    assert status.exit_code == 0
    assert "market: OK schema=2 baseline=stage-0" in status.stdout
    assert "research: OK schema=1 baseline=stage-0" in status.stdout
    assert "live: OK schema=1 baseline=stage-0" in status.stdout


def test_db_status_returns_nonzero_when_databases_are_missing(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["db", "status", "--data-dir", str(tmp_path / "missing")],
    )

    assert result.exit_code == 1
    assert "market: ERROR" in result.stderr
    assert "research: ERROR" in result.stderr
    assert "live: ERROR" in result.stderr
