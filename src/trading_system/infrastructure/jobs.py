from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event, Lock
from uuid import uuid4

from trading_system.application import JobContext, JobSnapshot, JobStatus, JobTask

logger = logging.getLogger(__name__)


class JobNotFoundError(KeyError):
    pass


class JobManagerClosedError(RuntimeError):
    pass


class JobCancelledError(RuntimeError):
    pass


@dataclass(slots=True)
class _JobRecord:
    job_id: str
    name: str
    cancel_event: Event
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    message: str | None = None
    result: object | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def snapshot(self) -> JobSnapshot:
        return JobSnapshot(
            job_id=self.job_id,
            name=self.name,
            status=self.status,
            progress=self.progress,
            message=self.message,
            result=self.result,
            error=self.error,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )


class _ThreadJobContext:
    def __init__(self, manager: ThreadJobManager, job_id: str) -> None:
        self._manager = manager
        self._job_id = job_id

    def report_progress(self, progress: float, message: str | None = None) -> None:
        self._manager._report_progress(self._job_id, progress, message)

    def is_cancel_requested(self) -> bool:
        return self._manager._is_cancel_requested(self._job_id)

    def raise_if_cancelled(self) -> None:
        if self.is_cancel_requested():
            raise JobCancelledError("job cancellation requested")


class ThreadJobManager:
    """Thread-backed job manager for short/IO-bound desktop background tasks.

    CPU-heavy research jobs can later use a process-backed implementation while
    preserving the same application contract.
    """

    def __init__(self, *, max_workers: int = 2) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="trading-job",
        )
        self._lock = Lock()
        self._records: dict[str, _JobRecord] = {}
        self._closed = False

    def submit(self, name: str, task: JobTask) -> str:
        if not name.strip():
            raise ValueError("job name must not be empty")

        with self._lock:
            if self._closed:
                raise JobManagerClosedError("job manager is shut down")
            job_id = uuid4().hex
            record = _JobRecord(
                job_id=job_id,
                name=name,
                cancel_event=Event(),
            )
            self._records[job_id] = record
            self._executor.submit(self._run, job_id, task)
            return job_id

    def get(self, job_id: str) -> JobSnapshot:
        with self._lock:
            return self._record(job_id).snapshot()

    def list_jobs(self) -> tuple[JobSnapshot, ...]:
        with self._lock:
            records = sorted(
                self._records.values(),
                key=lambda record: record.created_at,
                reverse=True,
            )
            return tuple(record.snapshot() for record in records)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            record = self._record(job_id)
            if record.status.terminal:
                return False
            record.cancel_event.set()
            record.status = JobStatus.CANCELLING
            record.message = "Cancellation requested"
            return True

    def shutdown(self, *, wait: bool = True, cancel_running: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if cancel_running:
                for record in self._records.values():
                    if not record.status.terminal:
                        record.cancel_event.set()
                        record.status = JobStatus.CANCELLING
                        record.message = "Application shutdown requested"
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _run(self, job_id: str, task: JobTask) -> None:
        with self._lock:
            record = self._record(job_id)
            if record.cancel_event.is_set():
                self._finish_cancelled(record)
                return
            record.status = JobStatus.RUNNING
            record.started_at = datetime.now(UTC)

        context: JobContext = _ThreadJobContext(self, job_id)
        try:
            result = task(context)
            with self._lock:
                record = self._record(job_id)
                if record.cancel_event.is_set():
                    self._finish_cancelled(record)
                else:
                    record.status = JobStatus.COMPLETED
                    record.progress = 1.0
                    record.result = result
                    record.finished_at = datetime.now(UTC)
        except JobCancelledError:
            with self._lock:
                self._finish_cancelled(self._record(job_id))
        except Exception as exc:
            logger.exception("background job failed", extra={"job_id": job_id})
            with self._lock:
                record = self._record(job_id)
                record.status = JobStatus.FAILED
                record.error = f"{type(exc).__name__}: {exc}"
                record.finished_at = datetime.now(UTC)

    def _report_progress(
        self,
        job_id: str,
        progress: float,
        message: str | None,
    ) -> None:
        if not 0.0 <= progress <= 1.0:
            raise ValueError("job progress must be between 0.0 and 1.0")
        with self._lock:
            record = self._record(job_id)
            if record.status.terminal:
                return
            if progress < record.progress:
                raise ValueError("job progress must not move backwards")
            record.progress = progress
            record.message = message

    def _is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            return self._record(job_id).cancel_event.is_set()

    def _record(self, job_id: str) -> _JobRecord:
        try:
            return self._records[job_id]
        except KeyError as exc:
            raise JobNotFoundError(job_id) from exc

    @staticmethod
    def _finish_cancelled(record: _JobRecord) -> None:
        record.status = JobStatus.CANCELLED
        record.message = "Cancelled"
        record.finished_at = datetime.now(UTC)
