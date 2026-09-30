import os
from datetime import UTC, datetime

from PySide6.QtWidgets import QApplication, QComboBox, QProgressBar, QPushButton, QTableWidget

from trading_system.application import (
    InstrumentDataStatus,
    JobSnapshot,
    JobStatus,
    UniverseDataStatus,
)
from trading_system.config import UniverseDefinition
from trading_system.domain import IngestionStatus
from trading_system.ui.pages import DataPage

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qt_app() -> QApplication:
    instance = QApplication.instance()
    if instance is not None:
        return instance
    return QApplication([])


class FakeDataService:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.snapshot = JobSnapshot(
            job_id="job-1",
            name="Historical 1m backfill: default",
            status=JobStatus.RUNNING,
            progress=0.5,
            message="Instrument 1/1 AAA; chunk 5/10",
            result=None,
            error=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            finished_at=None,
        )

    def list_universes(self) -> tuple[UniverseDefinition, ...]:
        return (UniverseDefinition("default", "Default", ("AAA",)),)

    def get_status(self, universe_id: str = "default") -> UniverseDataStatus:
        return UniverseDataStatus(
            universe_id=universe_id,
            name="Default",
            instruments=(
                InstrumentDataStatus(
                    instrument_uid="uid-a",
                    ticker="AAA",
                    row_count=123,
                    min_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
                    max_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                    gap_count=2,
                    missing_minutes=3,
                    checkpoint_status=IngestionStatus.RUNNING,
                    requested_from=datetime(2025, 1, 1, tzinfo=UTC),
                    requested_to=datetime(2027, 1, 1, tzinfo=UTC),
                    completed_until=datetime(2026, 1, 1, tzinfo=UTC),
                ),
            ),
        )

    def start_sync(self, universe_id: str = "default") -> str:
        self.started.append("sync")
        return "job-1"

    def start_backfill(self, universe_id: str = "default") -> str:
        self.started.append("backfill")
        return "job-1"

    def resume_backfill(self, universe_id: str = "default") -> str:
        self.started.append("resume")
        return "job-1"

    def start_validation(self, universe_id: str = "default") -> str:
        self.started.append("validate")
        return "job-1"

    def cancel_backfill(self, job_id: str) -> bool:
        self.started.append("cancel")
        return True

    def get_job(self, job_id: str) -> JobSnapshot:
        return self.snapshot


def test_data_page_renders_universe_coverage_and_progress() -> None:
    _qt_app()
    service = FakeDataService()
    page = DataPage(service)  # type: ignore[arg-type]

    try:
        universe = page.findChild(QComboBox, "dataUniverse")
        table = page.findChild(QTableWidget, "dataCoverageTable")

        assert universe is not None
        assert universe.count() == 1
        assert universe.currentData() == "default"
        assert table is not None
        assert table.rowCount() == 1
        assert table.item(0, 0).text() == "AAA"
        assert table.item(0, 2).text() == "123"
        assert table.item(0, 5).text() == "2"
        assert table.item(0, 7).text() == "RUNNING"
        assert table.item(0, 8).text() == "50%"
    finally:
        page.close()


def test_data_page_starts_backfill_and_polls_progress() -> None:
    qt_app = _qt_app()
    service = FakeDataService()
    page = DataPage(service)  # type: ignore[arg-type]

    try:
        button = page.findChild(QPushButton, "startDataBackfill")
        progress = page.findChild(QProgressBar, "dataJobProgress")

        assert button is not None
        assert progress is not None

        button.click()
        qt_app.processEvents()

        assert service.started == ["backfill"]
        assert progress.value() == 50

        service.snapshot = JobSnapshot(
            job_id="job-1",
            name="Historical 1m backfill: default",
            status=JobStatus.COMPLETED,
            progress=1.0,
            message="Completed",
            result=None,
            error=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            finished_at=datetime(2026, 1, 1, 1, tzinfo=UTC),
        )
        page._poll_job()
        assert progress.value() == 100
        assert button.isEnabled()
    finally:
        page.close()


def test_data_page_validate_runs_as_background_job() -> None:
    _qt_app()
    service = FakeDataService()
    page = DataPage(service)  # type: ignore[arg-type]

    try:
        button = page.findChild(QPushButton, "validateMarketData")
        assert button is not None
        button.click()
        assert service.started == ["validate"]
    finally:
        page.close()
