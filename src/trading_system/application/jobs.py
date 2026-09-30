from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: str
    name: str
    status: JobStatus
    progress: float
    message: str | None
    result: object | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobContext(Protocol):
    def report_progress(self, progress: float, message: str | None = None) -> None: ...

    def is_cancel_requested(self) -> bool: ...

    def raise_if_cancelled(self) -> None: ...


JobTask = Callable[[JobContext], object | None]


class JobManager(Protocol):
    def submit(self, name: str, task: JobTask) -> str: ...

    def get(self, job_id: str) -> JobSnapshot: ...

    def list_jobs(self) -> tuple[JobSnapshot, ...]: ...

    def cancel(self, job_id: str) -> bool: ...

    def shutdown(self, *, wait: bool = True, cancel_running: bool = False) -> None: ...
