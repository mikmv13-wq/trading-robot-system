from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from trading_system.application import HealthStatus, JobStatus
from trading_system.composition import ApplicationServices, build_application_services
from trading_system.config import Settings
from trading_system.observability import configure_logging

app = typer.Typer(no_args_is_help=True, help="Trading Robot System developer CLI.")
db_app = typer.Typer(no_args_is_help=True, help="DuckDB diagnostics.")
data_app = typer.Typer(no_args_is_help=True, help="Market data operations.")
instruments_app = typer.Typer(no_args_is_help=True, help="Universe instrument operations.")

app.add_typer(db_app, name="db")
app.add_typer(data_app, name="data")
data_app.add_typer(instruments_app, name="instruments")


def _settings(
    *,
    data_dir: Path | None = None,
    sql_dir: Path | None = None,
    config_dir: Path | None = None,
) -> Settings:
    settings = Settings()
    updates: dict[str, object] = {}
    if data_dir is not None:
        updates["data_dir"] = data_dir
    if sql_dir is not None:
        updates["sql_dir"] = sql_dir
    if config_dir is not None:
        updates["config_dir"] = config_dir
    return settings.model_copy(update=updates)


def _close(services: ApplicationServices) -> None:
    services.close()


def _format_ts(value: datetime | None) -> str:
    return "-" if value is None else value.isoformat()


def _parse_utc_datetime(value: str | None, option_name: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        _fail(ValueError(f"{option_name} must be an RFC3339 timestamp"))
        raise AssertionError("unreachable") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(ValueError(f"{option_name} must include a timezone"))
    return parsed.astimezone(UTC)


def _fail(exc: Exception) -> None:
    typer.echo(f"ERROR: {exc}", err=True)
    raise typer.Exit(code=1)


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
    try:
        result = services.bootstrap_databases.execute()
        for name, versions in result.applied_migrations.items():
            version_text = (
                ", ".join(str(version) for version in versions) if versions else "none"
            )
            typer.echo(f"{name}: applied migrations: {version_text}")
        logger.info("database bootstrap completed")
    finally:
        _close(services)


@db_app.command("status")
def db_status(
    data_dir: Annotated[Path | None, typer.Option(help="Override runtime data directory.")] = None,
) -> None:
    """Show health and schema version for all application databases."""

    settings = _settings(data_dir=data_dir)
    services = build_application_services(settings)
    try:
        result = services.get_system_status.execute()

        for database in result.databases:
            if database.status is HealthStatus.OK:
                baseline = database.metadata.get("schema_baseline", "unknown")
                typer.echo(
                    f"{database.name}: OK schema={database.schema_version} "
                    f"baseline={baseline}"
                )
            else:
                typer.echo(f"{database.name}: ERROR {database.error}", err=True)

        if not result.healthy:
            raise typer.Exit(code=1)
    finally:
        _close(services)


@instruments_app.command("sync")
def data_instruments_sync(
    universe: Annotated[str, typer.Option(help="Universe identifier.")] = "default",
    data_dir: Annotated[Path | None, typer.Option(help="Override runtime data directory.")] = None,
    config_dir: Annotated[Path | None, typer.Option(help="Override config directory.")] = None,
) -> None:
    """Resolve configured tickers to T-Invest broker UIDs and persist the universe."""

    services = build_application_services(
        _settings(data_dir=data_dir, config_dir=config_dir)
    )
    try:
        try:
            result = services.data.sync_instruments(universe)
        except Exception as exc:
            _fail(exc)
        typer.echo(
            f"universe={result.universe.universe_id} "
            f"instruments={len(result.instruments)}"
        )
        for instrument in result.instruments:
            typer.echo(
                f"{instrument.ticker}: uid={instrument.instrument_uid} "
                f"figi={instrument.figi or '-'} lot={instrument.lot_size}"
            )
    finally:
        _close(services)


@data_app.command("backfill")
def data_backfill(
    universe: Annotated[str, typer.Option(help="Universe identifier.")] = "default",
    resume: Annotated[bool, typer.Option(help="Resume from persisted checkpoints.")] = False,
    from_ts: Annotated[
        str | None,
        typer.Option(help="RFC3339 range start. Omit for default 5-year range."),
    ] = None,
    to_ts: Annotated[
        str | None,
        typer.Option(help="RFC3339 range end. Omit for default 5-year range."),
    ] = None,
    data_dir: Annotated[Path | None, typer.Option(help="Override runtime data directory.")] = None,
) -> None:
    """Run or resume historical 1m backfill and wait for completion."""

    if resume and (from_ts is not None or to_ts is not None):
        _fail(ValueError("--resume cannot be combined with --from-ts/--to-ts"))

    services = build_application_services(_settings(data_dir=data_dir))
    try:
        try:
            parsed_from = _parse_utc_datetime(from_ts, "--from-ts")
            parsed_to = _parse_utc_datetime(to_ts, "--to-ts")
            job_id = (
                services.data.resume_backfill(universe)
                if resume
                else services.data.start_backfill(
                    universe,
                    from_ts=parsed_from,
                    to_ts=parsed_to,
                )
            )
            typer.echo(f"job={job_id} started")
            snapshot = services.data.wait_for_job(job_id)
        except Exception as exc:
            _fail(exc)

        if snapshot.status is not JobStatus.COMPLETED:
            typer.echo(
                f"job={job_id} status={snapshot.status.value} "
                f"error={snapshot.error or '-'}",
                err=True,
            )
            raise typer.Exit(code=1)

        result = snapshot.result
        typer.echo(f"job={job_id} status=COMPLETED progress={snapshot.progress:.0%}")
        if result is not None:
            total_requests = getattr(result, "total_requests", None)
            total_fetched = getattr(result, "total_fetched_candles", None)
            if total_requests is not None and total_fetched is not None:
                typer.echo(
                    f"requests={total_requests} fetched_candles={total_fetched}"
                )
    finally:
        _close(services)


@data_app.command("validate")
def data_validate(
    universe: Annotated[str, typer.Option(help="Universe identifier.")] = "default",
    from_ts: Annotated[
        str | None,
        typer.Option(help="RFC3339 validation range start."),
    ] = None,
    to_ts: Annotated[
        str | None,
        typer.Option(help="RFC3339 validation range end."),
    ] = None,
    data_dir: Annotated[Path | None, typer.Option(help="Override runtime data directory.")] = None,
) -> None:
    """Validate coverage, suspicious gaps and candle quality."""

    services = build_application_services(_settings(data_dir=data_dir))
    try:
        try:
            report = services.data.validate(
                universe,
                from_ts=_parse_utc_datetime(from_ts, "--from-ts"),
                to_ts=_parse_utc_datetime(to_ts, "--to-ts"),
            )
        except Exception as exc:
            _fail(exc)

        typer.echo(
            f"run={report.run_id} universe={report.universe_id} "
            f"status={report.status.value}"
        )
        typer.echo(f"range={report.from_ts.isoformat()}..{report.to_ts.isoformat()}")
        for item in report.instruments:
            typer.echo(
                f"{item.instrument_uid}: status={item.status.value} "
                f"rows={item.stats.row_count} gaps={item.gap_count} "
                f"missing_minutes={item.missing_minutes} "
                f"min={_format_ts(item.stats.min_timestamp)} "
                f"max={_format_ts(item.stats.max_timestamp)}"
            )
    finally:
        _close(services)


@data_app.command("status")
def data_status(
    universe: Annotated[str, typer.Option(help="Universe identifier.")] = "default",
    data_dir: Annotated[Path | None, typer.Option(help="Override runtime data directory.")] = None,
) -> None:
    """Show persisted 1m coverage, gaps and backfill checkpoint state."""

    services = build_application_services(_settings(data_dir=data_dir))
    try:
        try:
            status = services.data.get_status(universe)
        except Exception as exc:
            _fail(exc)

        typer.echo(
            f"universe={status.universe_id} instruments={len(status.instruments)} "
            f"rows={status.total_rows} gaps={status.total_gaps}"
        )
        for item in status.instruments:
            checkpoint = (
                "-" if item.checkpoint_status is None else item.checkpoint_status.value
            )
            typer.echo(
                f"{item.ticker}: uid={item.instrument_uid} rows={item.row_count} "
                f"min={_format_ts(item.min_timestamp)} "
                f"max={_format_ts(item.max_timestamp)} "
                f"gaps={item.gap_count} missing_minutes={item.missing_minutes} "
                f"checkpoint={checkpoint} "
                f"completed_until={_format_ts(item.completed_until)}"
            )
    finally:
        _close(services)
