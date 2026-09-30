from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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
    GetSystemStatusUseCase,
    HealthStatus,
    JobApplicationService,
    JobStatus,
    TInvestTokenService,
    TokenSource,
    TokenStorageError,
)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        title_label.setStyleSheet("font-size: 24px; font-weight: 600;")

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        subtitle_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)


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
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(PageHeader(title, subtitle))

        message = QLabel("Экран подготовлен. Функциональность будет добавлена на следующих этапах.")
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(message)
        layout.addStretch(1)


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
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        layout.addWidget(
            PageHeader(
                "Dashboard",
                "Состояние desktop-приложения и локальной инфраструктуры.",
            )
        )

        mode_row = QHBoxLayout()
        mode_caption = QLabel("Режим:")
        mode_value = QLabel("RESEARCH")
        mode_value.setObjectName("applicationMode")
        mode_value.setStyleSheet("font-weight: 600;")
        mode_row.addWidget(mode_caption)
        mode_row.addWidget(mode_value)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        database_title_row = QHBoxLayout()
        database_title = QLabel("DuckDB")
        database_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        database_title_row.addWidget(database_title)
        database_title_row.addStretch(1)

        refresh_button = QPushButton("Обновить")
        refresh_button.setObjectName("refreshDatabaseStatus")
        refresh_button.clicked.connect(self.refresh_status)
        database_title_row.addWidget(refresh_button)
        layout.addLayout(database_title_row)

        self._database_table = QTableWidget(0, 4)
        self._database_table.setObjectName("databaseStatusTable")
        self._database_table.setHorizontalHeaderLabels(
            ["Database", "Status", "Schema", "Baseline"]
        )
        self._database_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._database_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._database_table.verticalHeader().setVisible(False)

        header = self._database_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self._database_table)

        job_title = QLabel("Background jobs")
        job_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(job_title)

        job_controls = QHBoxLayout()
        self._run_job_button = QPushButton("Run test job")
        self._run_job_button.setObjectName("runTestJob")
        self._run_job_button.clicked.connect(self._start_test_job)
        job_controls.addWidget(self._run_job_button)

        self._cancel_job_button = QPushButton("Cancel")
        self._cancel_job_button.setObjectName("cancelTestJob")
        self._cancel_job_button.setEnabled(False)
        self._cancel_job_button.clicked.connect(self._cancel_test_job)
        job_controls.addWidget(self._cancel_job_button)
        job_controls.addStretch(1)
        layout.addLayout(job_controls)

        self._job_status = QLabel("IDLE")
        self._job_status.setObjectName("jobStatus")
        layout.addWidget(self._job_status)

        self._job_progress = QProgressBar()
        self._job_progress.setObjectName("jobProgress")
        self._job_progress.setRange(0, 100)
        self._job_progress.setValue(0)
        layout.addWidget(self._job_progress)

        self._job_message = QLabel("No background job running.")
        self._job_message.setObjectName("jobMessage")
        self._job_message.setWordWrap(True)
        layout.addWidget(self._job_message)
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

    def _start_test_job(self) -> None:
        self._current_job_id = self._jobs.start_test_job()
        self._run_job_button.setEnabled(False)
        self._cancel_job_button.setEnabled(True)
        self._job_progress.setValue(0)
        self._job_status.setText(JobStatus.PENDING.value)
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
        self._job_status.setText(snapshot.status.value)
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(
            PageHeader(
                "Data",
                "Universe, исторические 1m данные, coverage и контроль качества.",
            )
        )

        universe_row = QHBoxLayout()
        universe_row.addWidget(QLabel("Universe:"))
        self._universe = QComboBox()
        self._universe.setObjectName("dataUniverse")
        self._universe.currentIndexChanged.connect(self.refresh_status)
        universe_row.addWidget(self._universe, 1)

        self._sync_button = QPushButton("Sync instruments")
        self._sync_button.setObjectName("syncInstruments")
        self._sync_button.clicked.connect(self._start_sync)
        universe_row.addWidget(self._sync_button)

        self._refresh_button = QPushButton("Refresh")
        self._refresh_button.setObjectName("refreshDataStatus")
        self._refresh_button.clicked.connect(self.refresh_status)
        universe_row.addWidget(self._refresh_button)
        layout.addLayout(universe_row)

        controls = QHBoxLayout()
        self._backfill_button = QPushButton("Backfill 5 years")
        self._backfill_button.setObjectName("startDataBackfill")
        self._backfill_button.clicked.connect(self._start_backfill)
        controls.addWidget(self._backfill_button)

        self._resume_button = QPushButton("Resume")
        self._resume_button.setObjectName("resumeDataBackfill")
        self._resume_button.clicked.connect(self._resume_backfill)
        controls.addWidget(self._resume_button)

        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.setObjectName("cancelDataJob")
        self._cancel_button.setEnabled(False)
        self._cancel_button.clicked.connect(self._cancel_job)
        controls.addWidget(self._cancel_button)

        self._validate_button = QPushButton("Validate")
        self._validate_button.setObjectName("validateMarketData")
        self._validate_button.clicked.connect(self._start_validation)
        controls.addWidget(self._validate_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self._job_status = QLabel("IDLE")
        self._job_status.setObjectName("dataJobStatus")
        layout.addWidget(self._job_status)

        self._job_progress = QProgressBar()
        self._job_progress.setObjectName("dataJobProgress")
        self._job_progress.setRange(0, 100)
        self._job_progress.setValue(0)
        layout.addWidget(self._job_progress)

        self._job_message = QLabel("No data job running.")
        self._job_message.setObjectName("dataJobMessage")
        self._job_message.setWordWrap(True)
        layout.addWidget(self._job_message)

        self._summary = QLabel()
        self._summary.setObjectName("dataSummary")
        layout.addWidget(self._summary)

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
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, 1)

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
        self._set_enabled(bool(universes))

    def refresh_status(self) -> None:
        if self._data is None or self._universe.count() == 0:
            self._table.setRowCount(0)
            self._summary.setText("No universe selected.")
            return
        try:
            status = self._data.get_status(self._selected_universe())
        except Exception as exc:
            self._table.setRowCount(0)
            self._summary.setText(f"Data status unavailable: {exc}")
            return

        self._summary.setText(
            f"Rows: {status.total_rows:,}    Gaps: {status.total_gaps}    "
            f"Instruments: {len(status.instruments)}"
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
                self._table.setItem(row, column, QTableWidgetItem(value))

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
        self._start_job(self._data.start_sync(self._selected_universe()))

    def _start_backfill(self) -> None:
        if self._data is None:
            return
        self._start_job(self._data.start_backfill(self._selected_universe()))

    def _resume_backfill(self) -> None:
        if self._data is None:
            return
        self._start_job(self._data.resume_backfill(self._selected_universe()))

    def _start_validation(self) -> None:
        if self._data is None:
            return
        self._start_job(self._data.start_validation(self._selected_universe()))

    def _start_job(self, job_id: str) -> None:
        self._current_job_id = job_id
        self._job_status.setText(JobStatus.PENDING.value)
        self._job_progress.setValue(0)
        self._job_message.setText(f"Job {job_id} submitted.")
        self._set_controls_running(True)
        self._timer.start()
        self._poll_job()

    def _cancel_job(self) -> None:
        if self._data is None or self._current_job_id is None:
            return
        self._data.cancel_backfill(self._current_job_id)
        self._poll_job()

    def _poll_job(self) -> None:
        if self._data is None or self._current_job_id is None:
            return
        snapshot = self._data.get_job(self._current_job_id)
        self._job_status.setText(snapshot.status.value)
        self._job_progress.setValue(round(snapshot.progress * 100))
        self._job_message.setText(snapshot.error or snapshot.message or "")
        self.refresh_status()

        if snapshot.status.terminal:
            self._timer.stop()
            self._set_controls_running(False)
            self.refresh_status()

    def _set_controls_running(self, running: bool) -> None:
        self._sync_button.setEnabled(not running)
        self._backfill_button.setEnabled(not running)
        self._resume_button.setEnabled(not running)
        self._validate_button.setEnabled(not running)
        self._refresh_button.setEnabled(not running)
        self._universe.setEnabled(not running)
        self._cancel_button.setEnabled(running)

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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("page-settings")
        self._tinvest_token = tinvest_token

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(
            PageHeader(
                "Settings",
                "Локальные настройки и безопасное хранение T-Invest token.",
            )
        )

        token_title = QLabel("T-Invest token")
        token_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(token_title)

        self._token_status = QLabel()
        self._token_status.setObjectName("tinvestTokenStatus")
        layout.addWidget(self._token_status)

        self._keychain_status = QLabel()
        self._keychain_status.setObjectName("keychainStatus")
        layout.addWidget(self._keychain_status)

        self._token_input = QLineEdit()
        self._token_input.setObjectName("tinvestTokenInput")
        self._token_input.setPlaceholderText("Введите token")
        self._token_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._token_input)

        self._persist_checkbox = QCheckBox("Сохранить в OS keychain")
        self._persist_checkbox.setObjectName("persistToken")
        self._persist_checkbox.setChecked(True)
        layout.addWidget(self._persist_checkbox)

        controls = QHBoxLayout()
        self._save_button = QPushButton("Сохранить")
        self._save_button.setObjectName("saveTinInvestToken")
        self._save_button.clicked.connect(self._save_token)
        controls.addWidget(self._save_button)

        self._clear_button = QPushButton("Удалить")
        self._clear_button.setObjectName("clearTinInvestToken")
        self._clear_button.clicked.connect(self._clear_token)
        controls.addWidget(self._clear_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self._token_message = QLabel()
        self._token_message.setObjectName("tinvestTokenMessage")
        self._token_message.setWordWrap(True)
        layout.addWidget(self._token_message)
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
