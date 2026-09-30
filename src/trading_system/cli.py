from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from trading_system.application import HealthStatus
from trading_system.composition import build_application_services
from trading_system.config import Settings
from trading_system.observability import configure_logging

app = typer.Typer(no_args_is_help=True, help="Trading Robot System developer CLI.")
db_app = typer.Typer(no_args_is_help=True, help="DuckDB diagnostics.")
app.add_typer(db_app, name="db")


def _settings(
    *,
    data_dir: Path | None = None,
    sql_dir: Path | None = None,
) -> Settings:
    if data_dir is not None and sql_dir is not None:
        return Settings(data_dir=data_dir, sql_dir=sql_dir)
    if data_dir is not None:
        return Settings(data_dir=data_dir)
    if sql_dir is not None:
        return Settings(sql_dir=sql_dir)
    return Settings()


@app.callback()
def main() -> None:
    """Developer and diagnostics commands for Trading Robot System."""


@app.command()
def bootstrap(
    data_dir: Annotated[Path | None, typer.Option(help="Override runtime data directory.")] = None,
    sql_dir: Annotated[Path | None, typer.Option(help="Override SQL migrations directory.")] = None,
) -> None:
    """Create the three DuckDB files and apply pending migrations."""

    settings = _settings(data_dir=data_dir, sql_dir=sql_dir)
    configure_logging(settings)
    logger = logging.getLogger(__name__)

    services = build_application_services(settings)
    result = services.bootstrap_databases.execute()
    for name, versions in result.applied_migrations.items():
        version_text = ", ".join(str(version) for version in versions) if versions else "none"
        typer.echo(f"{name}: applied migrations: {version_text}")
    logger.info("database bootstrap completed")


@db_app.command("status")
def db_status(
    data_dir: Annotated[Path | None, typer.Option(help="Override runtime data directory.")] = None,
) -> None:
    """Show health and schema version for all application databases."""

    settings = _settings(data_dir=data_dir)
    services = build_application_services(settings)
    result = services.get_system_status.execute()

    for database in result.databases:
        if database.status is HealthStatus.OK:
            baseline = database.metadata.get("schema_baseline", "unknown")
            typer.echo(
                f"{database.name}: OK schema={database.schema_version} baseline={baseline}"
            )
        else:
            typer.echo(f"{database.name}: ERROR {database.error}", err=True)

    if not result.healthy:
        raise typer.Exit(code=1)
