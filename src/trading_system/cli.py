from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from trading_system.adapters.duckdb import DuckDBBootstrapper
from trading_system.application import BootstrapDatabasesUseCase
from trading_system.config import Settings
from trading_system.observability import configure_logging

app = typer.Typer(no_args_is_help=True, help="Trading Robot System developer CLI.")


@app.callback()
def main() -> None:
    """Developer and diagnostics commands for Trading Robot System."""


@app.command()
def bootstrap(
    data_dir: Annotated[Path | None, typer.Option(help="Override runtime data directory.")] = None,
    sql_dir: Annotated[Path | None, typer.Option(help="Override SQL migrations directory.")] = None,
) -> None:
    """Create the three DuckDB files and apply pending migrations."""

    overrides: dict[str, object] = {}
    if data_dir is not None:
        overrides["data_dir"] = data_dir
    if sql_dir is not None:
        overrides["sql_dir"] = sql_dir

    settings = Settings(**overrides)
    configure_logging(settings)
    logger = logging.getLogger(__name__)

    result = BootstrapDatabasesUseCase(DuckDBBootstrapper(settings)).execute()
    for name, versions in result.applied_migrations.items():
        version_text = ", ".join(str(version) for version in versions) if versions else "none"
        typer.echo(f"{name}: applied migrations: {version_text}")
    logger.info("database bootstrap completed")
