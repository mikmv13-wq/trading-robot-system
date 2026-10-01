from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


def _refresh_style(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class StatusBadge(QLabel):
    def __init__(
        self,
        text: str = "—",
        *,
        tone: str = "muted",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setObjectName("statusBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status(text, tone=tone)

    def set_status(self, text: str, *, tone: str = "muted") -> None:
        self.setText(text.upper())
        self.setProperty("tone", tone)
        _refresh_style(self)


class MetricCard(QFrame):
    def __init__(
        self,
        title: str,
        value: str,
        *,
        subtitle: str = "",
        status: str = "ГОТОВО",
        tone: str = "muted",
        object_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        if object_name:
            self.setProperty("cardKey", object_name)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("metricTitle")
        header.addWidget(self.title_label)
        header.addStretch(1)

        self.badge = StatusBadge(status, tone=tone)
        header.addWidget(self.badge)
        layout.addLayout(header)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        layout.addWidget(self.value_label)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("cardSubtitle")
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.subtitle_label)

    def set_metric(
        self,
        *,
        value: str,
        subtitle: str | None = None,
        status: str | None = None,
        tone: str = "muted",
        tooltip: str = "",
    ) -> None:
        self.value_label.setText(value)
        if subtitle is not None:
            self.subtitle_label.setText(subtitle)
        if status is not None:
            self.badge.set_status(status, tone=tone)
        self.setToolTip(tooltip)


class SectionCard(QFrame):
    def __init__(
        self,
        title: str,
        *,
        subtitle: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sectionCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        header = QVBoxLayout()
        header.setSpacing(3)

        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        header.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("cardSubtitle")
            subtitle_label.setWordWrap(True)
            header.addWidget(subtitle_label)

        root.addLayout(header)

        self.content = QVBoxLayout()
        self.content.setSpacing(10)
        root.addLayout(self.content)


class JobPanel(QFrame):
    def __init__(
        self,
        *,
        title: str = "Фоновая задача",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sectionCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        header.addWidget(title_label)
        header.addStretch(1)

        self.status = StatusBadge("ОЖИДАНИЕ", tone="muted")
        header.addWidget(self.status)
        layout.addLayout(header)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.message = QLabel("Фоновые задачи не выполняются.")
        self.message.setObjectName("jobMessage")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

    def update_job(
        self,
        *,
        status: str,
        progress: int,
        message: str,
        tone: str,
    ) -> None:
        self.status.set_status(status, tone=tone)
        self.progress.setValue(progress)
        self.message.setText(message)
