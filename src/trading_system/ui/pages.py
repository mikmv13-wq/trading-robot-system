from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from trading_system.application import (
    DataApplicationService,
    DataUniverseNotFoundError,
    GetSystemStatusUseCase,
    HealthStatus,
    JobApplicationService,
    JobStatus,
    TInvestTokenService,
    TokenSource,
    TokenStorageError,
)
from trading_system.config import Settings
from trading_system.ui.widgets import MetricCard, SectionCard, StatusBadge


def _button(text: str, *, object_name: str, variant: str = "ghost") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(object_name)
    button.setProperty("variant", variant)
    return button


def _job_tone(status: JobStatus | str) -> str:
    value = status.value if isinstance(status, JobStatus) else str(status)
    if value == JobStatus.COMPLETED.value:
        return "success"
    if value in {JobStatus.FAILED.value, JobStatus.CANCELLED.value}:
        return "danger"
    if value in {JobStatus.RUNNING.value, JobStatus.PENDING.value}:
        return "info"
    return "muted"


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(16)

        copy = QVBoxLayout()
        copy.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)

        copy.addWidget(title_label)
        copy.addWidget(subtitle_label)
        layout.addLayout(copy, 1)

        self.action_layout = QHBoxLayout()
        self.action_layout.setSpacing(8)
        layout.addLayout(self.action_layout)


class PlaceholderPage(QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str,
        *,
        page_key: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(f"page-{page_key}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(18)
        layout.addWidget(PageHeader(title, subtitle))

        empty = QFrame()
        empty.setObjectName("emptyState")
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(28, 28, 28, 28)
        empty_layout.setSpacing(8)

        heading = QLabel("Workspace is ready")
        heading.setObjectName("sectionTitle")
        empty_layout.addWidget(heading)

        message = QLabel(
            "Экран уже включён в единую навигацию. "
            "Функциональность будет подключаться на следующих этапах разработки."
        )
        message.setObjectName("mutedText")
        message.setWordWrap(True)
        empty_layout.addWidget(message)
        empty_layout.addStretch(1)

        layout.addWidget(empty, 1)


class DashboardPage(QWidget):
    def __init__(
        self,
        get_system_status: GetSystemStatusUseCase,
        jobs: JobApplicationService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page-dashboard")
        self._get_system_status = get_system_status
        self._jobs = jobs
        self._current_job_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(18)

        header = PageHeader(
            "Dashboard",
            "Состояние desktop-приложения, локального хранилища и фоновых задач.",
        )
        refresh_button = _button(
            "↻  Refresh",
            object_name="refreshDatabaseStatus",
            variant="ghost",
        )
        refresh_button.clicked.connect(self.refresh_status)
        header.action_layout.addWidget(refresh_button)
        layout.addWidget(header)

        cards = QGridLayout()
        cards.setHorizontalSpacing(14)
        cards.setVerticalSpacing(14)

        self._database_cards: dict[str, MetricCard] = {}
        for column, database_name in enumerate(("market", "research", "live")):
            card = MetricCard(
                f"{database_name.capitalize()} DB",
                "Checking…",
                subtitle="DuckDB local storage",
                status="CHECKING",
                tone="info",
                object_name=f"database-{database_name}",
            )
            card.setMinimumHeight(132)
            cards.addWidget(card, 0, column)
            self._database_cards[database_name] = card

        app_card = MetricCard(
            "Application mode",
            "RESEARCH",
            subtitle="Safe local research workspace",
            status="ACTIVE",
            tone="success",
            object_name="application-mode",
        )
        app_card.setMinimumHeight(132)
        cards.addWidget(app_card, 0, 3)
        cards.setColumnStretch(0, 1)
        cards.setColumnStretch(1, 1)
        cards.setColumnStretch(2, 1)
        cards.setColumnStretch(3, 1)
        layout.addLayout(cards)

        self._database_table = QTableWidget(0, 4, self)
        self._database_table.setObjectName("databaseStatusTable")
        self._database_table.setHorizontalHeaderLabels(
            ["Database", "Status", "Schema", "Baseline"]
        )
        self._database_table.setVisible(False)

        job_card = SectionCard(
            "Active job",
            subtitle="Длительные операции выполняются в фоне и не блокируют интерфейс.",
        )

        job_controls = QHBoxLayout()
        self._run_job_button = _button(
            "Run test job",
            object_name="runTestJob",
            variant="primary",
        )
        self._run_job_button.clicked.connect(self._start_test_job)
        job_controls.addWidget(self._run_job_button)

        self._cancel_job_button = _button(
            "Cancel",
            object_name="cancelTestJob",
            variant="danger",
        )
        self._cancel_job_button.setEnabled(False)
        self._cancel_job_button.clicked.connect(self._cancel_test_job)
        job_controls.addWidget(self._cancel_job_button)
        job_controls.addStretch(1)

        self._job_status = StatusBadge("IDLE", tone="muted")
        self._job_status.setObjectName("jobStatus")
        job_controls.addWidget(self._job_status)
        job_card.content.addLayout(job_controls)

        self._job_progress = QProgressBar()
        self._job_progress.setObjectName("jobProgress")
        self._job_progress.setRange(0, 100)
        self._job_progress.setValue(0)
        job_card.content.addWidget(self._job_progress)

        self._job_message = QLabel("No background job running.")
        self._job_message.setObjectName("jobMessage")
        self._job_message.setWordWrap(True)
        job_card.content.addWidget(self._job_message)
        layout.addWidget(job_card)

        overview = SectionCard(
            "Workspace",
            subtitle="Research-first desktop workflow without a web layer.",
        )
        overview_grid = QGridLayout()
        overview_grid.setHorizontalSpacing(18)
        overview_grid.setVerticalSpacing(8)

        for row, (title, text) in enumerate(
            (
                ("Data", "Universe, historical 1m candles and data quality."),
                ("Backtest", "Strategy simulation and trade-level analysis."),
                ("Optimization", "Stable parameter search across folds and instruments."),
                ("Validation", "Frozen candidate holdout and stress validation."),
            )
        ):
            title_label = QLabel(title)
            title_label.setObjectName("metricTitle")
            text_label = QLabel(text)
            text_label.setObjectName("mutedText")
            text_label.setWordWrap(True)
            overview_grid.addWidget(title_label, row, 0)
            overview_grid.addWidget(text_label, row, 1)
        overview_grid.setColumnStretch(1, 1)
        overview.content.addLayout(overview_grid)
        layout.addWidget(overview)
        layout.addStretch(1)

        self._job_timer = QTimer(self)
        self._job_timer.setInterval(100)
        self._job_timer.timeout.connect(self._poll_job)

        self.refresh_status()

    def refresh_status(self) -> None:
        result = self._get_system_status.execute()
        self._database_table.setRowCount(len(result.databases))

        for row, database in enumerate(result.databases):
            status_text = database.status.value
            schema_text = (
                str(database.schema_version)
                if database.schema_version is not None
                else "—"
            )
            baseline = database.metadata.get("schema_baseline", "—")

            values = (database.name, status_text, schema_text, baseline)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if database.status is HealthStatus.ERROR and database.error:
                    item.setToolTip(database.error)
                self._database_table.setItem(row, column, item)

            card = self._database_cards.get(database.name)
            if card is None:
                continue
            if database.status is HealthStatus.ERROR:
                card.set_metric(
                    value="Unavailable",
                    subtitle=f"Schema {schema_text} · {baseline}",
                    status="ERROR",
                    tone="danger",
                    tooltip=database.error or "",
                )
            else:
                card.set_metric(
                    value=f"Schema v{schema_text}",
                    subtitle=f"{baseline} · local DuckDB",
                    status=status_text,
                    tone="success",
                )

    def _start_test_job(self) -> None:
        self._current_job_id = self._jobs.start_test_job()
        self._run_job_button.setEnabled(False)
        self._cancel_job_button.setEnabled(True)
        self._job_progress.setValue(0)
        self._job_status.set_status(JobStatus.PENDING.value, tone="info")
        self._job_message.setText("Test job submitted.")
        self._job_timer.start()
        self._poll_job()

    def _cancel_test_job(self) -> None:
        if self._current_job_id is None:
            return
        self._jobs.cancel(self._current_job_id)
        self._poll_job()

    def _poll_job(self) -> None:
        if self._current_job_id is None:
            return

        snapshot = self._jobs.get(self._current_job_id)
        self._job_status.set_status(
            snapshot.status.value,
            tone=_job_tone(snapshot.status),
        )
        self._job_progress.setValue(round(snapshot.progress * 100))

        message = snapshot.message
        if snapshot.error:
            message = snapshot.error
        elif snapshot.status is JobStatus.COMPLETED and snapshot.result is not None:
            message = str(snapshot.result)
        self._job_message.setText(message or "")

        if snapshot.status.terminal:
            self._job_timer.stop()
            self._run_job_button.setEnabled(True)
            self._cancel_job_button.setEnabled(False)


class DataPage(QWidget):
    def __init__(
        self,
        data: DataApplicationService | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page-data")
        self._data = data
        self._current_job_id: str | None = None
        self._current_job_kind: str | None = None
        self._pending_action: str | None = None
        self._job_running = False
        self._universe_synchronized = False
        self._has_checkpoint = False
        self._has_data = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(16)

        header = PageHeader(
            "Market Data",
            "Universe, исторические 1m данные, coverage и контроль качества.",
        )
        self._refresh_button = _button(
            "↻  Refresh",
            object_name="refreshDataStatus",
            variant="ghost",
        )
        self._refresh_button.clicked.connect(self.refresh_status)
        header.action_layout.addWidget(self._refresh_button)
        layout.addWidget(header)

        controls_card = SectionCard(
            "Data controls",
            subtitle="Управление universe и исторической загрузкой T-Invest.",
        )
        universe_row = QHBoxLayout()
        universe_label = QLabel("Universe")
        universe_label.setObjectName("metricTitle")
        universe_row.addWidget(universe_label)

        self._universe = QComboBox()
        self._universe.setObjectName("dataUniverse")
        self._universe.setMinimumWidth(230)
        self._universe.currentIndexChanged.connect(self.refresh_status)
        universe_row.addWidget(self._universe)

        universe_row.addStretch(1)

        self._sync_button = _button(
            "Sync instruments",
            object_name="syncInstruments",
            variant="ghost",
        )
        self._sync_button.clicked.connect(self._start_sync)
        universe_row.addWidget(self._sync_button)

        self._backfill_button = _button(
            "Backfill 5 years",
            object_name="startDataBackfill",
            variant="primary",
        )
        self._backfill_button.clicked.connect(self._start_backfill)
        universe_row.addWidget(self._backfill_button)

        self._resume_button = _button(
            "Resume",
            object_name="resumeDataBackfill",
            variant="ghost",
        )
        self._resume_button.clicked.connect(self._resume_backfill)
        universe_row.addWidget(self._resume_button)

        self._validate_button = _button(
            "Validate",
            object_name="validateMarketData",
            variant="ghost",
        )
        self._validate_button.clicked.connect(self._start_validation)
        universe_row.addWidget(self._validate_button)

        self._cancel_button = _button(
            "Cancel",
            object_name="cancelDataJob",
            variant="danger",
        )
        self._cancel_button.setEnabled(False)
        self._cancel_button.clicked.connect(self._cancel_job)
        universe_row.addWidget(self._cancel_button)

        controls_card.content.addLayout(universe_row)
        layout.addWidget(controls_card)

        summary_grid = QGridLayout()
        summary_grid.setHorizontalSpacing(14)

        self._rows_card = MetricCard(
            "Candles",
            "—",
            subtitle="1 minute OHLCV rows",
            status="WAITING",
            tone="muted",
        )
        self._gaps_card = MetricCard(
            "Data gaps",
            "—",
            subtitle="Detected missing intervals",
            status="WAITING",
            tone="muted",
        )
        self._instruments_card = MetricCard(
            "Instruments",
            "—",
            subtitle="Universe coverage",
            status="WAITING",
            tone="muted",
        )
        summary_grid.addWidget(self._rows_card, 0, 0)
        summary_grid.addWidget(self._gaps_card, 0, 1)
        summary_grid.addWidget(self._instruments_card, 0, 2)
        summary_grid.setColumnStretch(0, 1)
        summary_grid.setColumnStretch(1, 1)
        summary_grid.setColumnStretch(2, 1)
        layout.addLayout(summary_grid)

        job_card = SectionCard(
            "Background job",
            subtitle="Загрузка и validation продолжаются без блокировки интерфейса.",
        )
        job_row = QHBoxLayout()

        self._job_status = StatusBadge("IDLE", tone="muted")
        self._job_status.setObjectName("dataJobStatus")
        job_row.addWidget(self._job_status)

        self._job_message = QLabel("No data job running.")
        self._job_message.setObjectName("dataJobMessage")
        self._job_message.setWordWrap(True)
        job_row.addWidget(self._job_message, 1)
        job_card.content.addLayout(job_row)

        self._job_progress = QProgressBar()
        self._job_progress.setObjectName("dataJobProgress")
        self._job_progress.setRange(0, 100)
        self._job_progress.setValue(0)
        job_card.content.addWidget(self._job_progress)
        layout.addWidget(job_card)

        coverage_card = SectionCard(
            "Market data coverage",
            subtitle="Покрытие, checkpoints и найденные gaps по каждому инструменту.",
        )

        self._summary = QLabel()
        self._summary.setObjectName("dataSummary")
        self._summary.setWordWrap(True)
        coverage_card.content.addWidget(self._summary)

        self._table = QTableWidget(0, 9)
        self._table.setObjectName("dataCoverageTable")
        self._table.setHorizontalHeaderLabels(
            [
                "Ticker",
                "UID",
                "Rows",
                "From",
                "To",
                "Gaps",
                "Missing min",
                "Checkpoint",
                "Progress",
            ]
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(38)

        table_header = self._table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)

        coverage_card.content.addWidget(self._table, 1)
        layout.addWidget(coverage_card, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._poll_job)

        self._load_universes()
        self.refresh_status()

    def _selected_universe(self) -> str:
        value = self._universe.currentData()
        return str(value) if value is not None else "default"

    def _load_universes(self) -> None:
        self._universe.clear()
        if self._data is None:
            self._set_enabled(False)
            self._job_message.setText("Data application service is unavailable.")
            return
        try:
            universes = self._data.list_universes()
        except Exception as exc:
            self._set_enabled(False)
            self._job_message.setText(str(exc))
            return
        for universe in universes:
            self._universe.addItem(
                f"{universe.name} ({universe.universe_id})",
                universe.universe_id,
            )
        self._update_controls()

    def refresh_status(self) -> None:
        if self._data is None or self._universe.count() == 0:
            self._table.setRowCount(0)
            self._summary.setText("No universe selected.")
            self._set_summary_cards_empty()
            return
        try:
            status = self._data.get_status(self._selected_universe())
        except DataUniverseNotFoundError:
            self._universe_synchronized = False
            self._has_checkpoint = False
            self._has_data = False
            self._table.setRowCount(0)
            self._summary.setText(
                "Universe is not synchronized yet. "
                "Use Backfill 5 years to synchronize instruments automatically "
                "and start loading data, or use Sync instruments only."
            )
            self._set_summary_cards_empty()
            self._update_controls()
            return
        except Exception as exc:
            self._table.setRowCount(0)
            self._summary.setText(f"Unable to read data status: {exc}")
            self._set_summary_cards_empty()
            self._update_controls()
            return

        self._universe_synchronized = True
        self._has_checkpoint = any(
            item.checkpoint_status is not None for item in status.instruments
        )
        self._has_data = status.total_rows > 0
        self._summary.setText(
            f"Rows: {status.total_rows:,}    Gaps: {status.total_gaps}    "
            f"Instruments: {len(status.instruments)}"
        )

        gap_tone = "success" if status.total_gaps == 0 else "warning"
        gap_status = "CLEAN" if status.total_gaps == 0 else "REVIEW"
        self._rows_card.set_metric(
            value=f"{status.total_rows:,}",
            status="READY" if self._has_data else "EMPTY",
            tone="success" if self._has_data else "muted",
        )
        self._gaps_card.set_metric(
            value=str(status.total_gaps),
            status=gap_status,
            tone=gap_tone,
        )
        self._instruments_card.set_metric(
            value=str(len(status.instruments)),
            status="SYNCED",
            tone="success",
        )

        self._table.setRowCount(len(status.instruments))
        for row, item in enumerate(status.instruments):
            progress = item.progress
            values = (
                item.ticker,
                item.instrument_uid,
                f"{item.row_count:,}",
                self._format_timestamp(item.min_timestamp),
                self._format_timestamp(item.max_timestamp),
                str(item.gap_count),
                str(item.missing_minutes),
                "-" if item.checkpoint_status is None else item.checkpoint_status.value,
                "-" if progress is None else f"{round(progress * 100)}%",
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column == 0:
                    font = cell.font()
                    font.setBold(True)
                    cell.setFont(font)
                if column in {5, 6} and value not in {"0", "-"}:
                    cell.setToolTip("Data quality issue detected")
                self._table.setItem(row, column, cell)
        self._update_controls()

    def _set_summary_cards_empty(self) -> None:
        self._rows_card.set_metric(value="—", status="WAITING", tone="muted")
        self._gaps_card.set_metric(value="—", status="WAITING", tone="muted")
        self._instruments_card.set_metric(value="—", status="WAITING", tone="muted")

    @staticmethod
    def _format_timestamp(value: object) -> str:
        if value is None:
            return "-"
        if hasattr(value, "isoformat"):
            return str(value.isoformat())
        return str(value)

    def _start_sync(self) -> None:
        if self._data is None:
            return
        self._pending_action = None
        self._start_job(
            self._data.start_sync(self._selected_universe()),
            kind="sync",
            message="Synchronizing instruments with T-Invest...",
        )

    def _start_backfill(self) -> None:
        if self._data is None:
            return
        if not self._universe_synchronized:
            self._pending_action = "backfill"
            self._start_job(
                self._data.start_sync(self._selected_universe()),
                kind="sync",
                message=(
                    "Universe is not synchronized. "
                    "Synchronizing instruments before 5-year backfill..."
                ),
            )
            return
        self._start_backfill_job()

    def _start_backfill_job(self) -> None:
        if self._data is None:
            return
        self._start_job(
            self._data.start_backfill(self._selected_universe()),
            kind="backfill",
            message="Starting 5-year historical backfill...",
        )

    def _resume_backfill(self) -> None:
        if self._data is None:
            return
        if not self._universe_synchronized or not self._has_checkpoint:
            self._job_message.setText(
                "Nothing to resume yet. Run Backfill 5 years first."
            )
            return
        self._start_job(
            self._data.resume_backfill(self._selected_universe()),
            kind="resume",
            message="Resuming historical backfill from checkpoint...",
        )

    def _start_validation(self) -> None:
        if self._data is None:
            return
        if not self._universe_synchronized or not self._has_data:
            self._job_message.setText(
                "No historical data to validate. Run Backfill 5 years first."
            )
            return
        self._start_job(
            self._data.start_validation(self._selected_universe()),
            kind="validate",
            message="Validating historical market data...",
        )

    def _start_job(
        self,
        job_id: str,
        *,
        kind: str,
        message: str,
    ) -> None:
        self._current_job_id = job_id
        self._current_job_kind = kind
        self._job_running = True
        self._job_status.set_status(JobStatus.PENDING.value, tone="info")
        self._job_progress.setValue(0)
        self._job_message.setText(message)
        self._update_controls()
        self._timer.start()
        self._poll_job()

    def _cancel_job(self) -> None:
        if self._data is None or self._current_job_id is None:
            return
        self._pending_action = None
        self._data.cancel_backfill(self._current_job_id)
        self._poll_job()

    def _poll_job(self) -> None:
        if self._data is None or self._current_job_id is None:
            return
        snapshot = self._data.get_job(self._current_job_id)
        self._job_status.set_status(
            snapshot.status.value,
            tone=_job_tone(snapshot.status),
        )
        self._job_progress.setValue(round(snapshot.progress * 100))
        self._job_message.setText(snapshot.error or snapshot.message or "")

        if snapshot.status.terminal:
            completed_kind = self._current_job_kind
            pending_action = self._pending_action
            self._timer.stop()
            self._job_running = False
            self.refresh_status()

            if (
                snapshot.status is JobStatus.COMPLETED
                and completed_kind == "sync"
                and pending_action == "backfill"
            ):
                self._pending_action = None
                self._start_backfill_job()
                return

            self._pending_action = None
            self._update_controls()
            return

        self.refresh_status()
        self._update_controls()

    def _update_controls(self) -> None:
        enabled = self._data is not None and self._universe.count() > 0
        if not enabled:
            self._universe.setEnabled(False)
            self._sync_button.setEnabled(False)
            self._backfill_button.setEnabled(False)
            self._resume_button.setEnabled(False)
            self._validate_button.setEnabled(False)
            self._refresh_button.setEnabled(False)
            self._cancel_button.setEnabled(False)
            return

        if self._job_running:
            self._universe.setEnabled(False)
            self._sync_button.setEnabled(False)
            self._backfill_button.setEnabled(False)
            self._resume_button.setEnabled(False)
            self._validate_button.setEnabled(False)
            self._refresh_button.setEnabled(False)
            self._cancel_button.setEnabled(True)
            return

        self._universe.setEnabled(True)
        self._sync_button.setEnabled(True)
        self._backfill_button.setEnabled(True)
        self._resume_button.setEnabled(
            self._universe_synchronized and self._has_checkpoint
        )
        self._validate_button.setEnabled(
            self._universe_synchronized and self._has_data
        )
        self._refresh_button.setEnabled(True)
        self._cancel_button.setEnabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        self._universe.setEnabled(enabled)
        self._sync_button.setEnabled(enabled)
        self._backfill_button.setEnabled(enabled)
        self._resume_button.setEnabled(enabled)
        self._validate_button.setEnabled(enabled)
        self._refresh_button.setEnabled(enabled)
        self._cancel_button.setEnabled(False)


class SettingsPage(QWidget):
    def __init__(
        self,
        tinvest_token: TInvestTokenService | None,
        settings: Settings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page-settings")
        self._tinvest_token = tinvest_token
        self._settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(18)
        layout.addWidget(
            PageHeader(
                "Settings",
                "Локальные настройки и безопасное хранение T-Invest token.",
            )
        )

        token_card = SectionCard(
            "T-Invest connection",
            subtitle="Токен хранится в OS keychain и не записывается в DuckDB.",
        )

        status_row = QHBoxLayout()
        self._token_status = QLabel()
        self._token_status.setObjectName("tinvestTokenStatus")
        status_row.addWidget(self._token_status)

        self._keychain_status = QLabel()
        self._keychain_status.setObjectName("keychainStatus")
        self._keychain_status.setProperty("tone", "muted")
        status_row.addWidget(self._keychain_status)
        status_row.addStretch(1)
        token_card.content.addLayout(status_row)

        self._token_input = QLineEdit()
        self._token_input.setObjectName("tinvestTokenInput")
        self._token_input.setPlaceholderText("Введите T-Invest token")
        self._token_input.setEchoMode(QLineEdit.EchoMode.Password)
        token_card.content.addWidget(self._token_input)

        self._persist_checkbox = QCheckBox("Сохранить в OS keychain")
        self._persist_checkbox.setObjectName("persistToken")
        self._persist_checkbox.setChecked(True)
        token_card.content.addWidget(self._persist_checkbox)

        controls = QHBoxLayout()
        self._save_button = _button(
            "Сохранить",
            object_name="saveTinInvestToken",
            variant="primary",
        )
        self._save_button.clicked.connect(self._save_token)
        controls.addWidget(self._save_button)

        self._clear_button = _button(
            "Удалить",
            object_name="clearTinInvestToken",
            variant="danger",
        )
        self._clear_button.clicked.connect(self._clear_token)
        controls.addWidget(self._clear_button)
        controls.addStretch(1)
        token_card.content.addLayout(controls)

        self._token_message = QLabel()
        self._token_message.setObjectName("tinvestTokenMessage")
        self._token_message.setWordWrap(True)
        token_card.content.addWidget(self._token_message)

        layout.addWidget(token_card)

        transport_card = SectionCard(
            "T-Invest transport",
            subtitle="Официальный Python SDK T-Invest поверх gRPC.",
        )
        transport_label = QLabel(
            "TLS: проверка сертификата SDK включена (SSL_TBANK_VERIFY=True). "
            "Используется сертификат НУЦ Минцифры, встроенный в SDK."
        )
        transport_label.setObjectName("tinvestTransportStatus")
        transport_label.setWordWrap(True)
        transport_label.setProperty("tone", "muted")
        transport_card.content.addWidget(transport_label)
        layout.addWidget(transport_card)
        layout.addStretch(1)

        enabled = self._tinvest_token is not None
        self._token_input.setEnabled(enabled)
        self._persist_checkbox.setEnabled(enabled)
        self._save_button.setEnabled(enabled)
        self._clear_button.setEnabled(enabled)
        self.refresh_token_status()

    def refresh_token_status(self) -> None:
        if self._tinvest_token is None:
            self._token_status.setText("Token: Unavailable")
            self._keychain_status.setText("OS keychain: Unavailable")
            return

        status = self._tinvest_token.status()
        configured = "Configured" if status.configured else "Not configured"
        self._token_status.setText(f"Token: {configured} ({status.source.value})")
        keychain = "Available" if status.keychain_available else "Unavailable"
        self._keychain_status.setText(f"OS keychain: {keychain}")
        if status.error:
            self._keychain_status.setToolTip(status.error)
        else:
            self._keychain_status.setToolTip("")

    def _save_token(self) -> None:
        if self._tinvest_token is None:
            return
        try:
            self._tinvest_token.set_token(
                self._token_input.text(),
                persist=self._persist_checkbox.isChecked(),
            )
        except (TokenStorageError, ValueError) as exc:
            self._token_message.setText(str(exc))
            self.refresh_token_status()
            return

        self._token_input.clear()
        source = TokenSource.KEYCHAIN if self._persist_checkbox.isChecked() else TokenSource.SESSION
        self._token_message.setText(f"Token configured for {source.value.lower()}.")
        self.refresh_token_status()

    def _clear_token(self) -> None:
        if self._tinvest_token is None:
            return
        try:
            self._tinvest_token.clear()
        except TokenStorageError as exc:
            self._token_message.setText(str(exc))
            self.refresh_token_status()
            return

        self._token_input.clear()
        self._token_message.setText("Token removed.")
        self.refresh_token_status()
