import time
from threading import Event

from trading_system.application import JobContext, JobStatus
from trading_system.infrastructure import ThreadJobManager


def _wait_for_terminal(manager: ThreadJobManager, job_id: str) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if manager.get(job_id).status.terminal:
            return
        time.sleep(0.01)
    raise AssertionError("job did not reach terminal state")


def test_job_manager_runs_task_in_background_and_reports_result() -> None:
    manager = ThreadJobManager(max_workers=1)
    started = Event()
    release = Event()

    def task(context: JobContext) -> str:
        started.set()
        release.wait(timeout=1.0)
        return "done"

    try:
        job_id = manager.submit("test", task)

        assert started.wait(timeout=1.0)
        assert manager.get(job_id).status is JobStatus.RUNNING

        release.set()
        _wait_for_terminal(manager, job_id)

        snapshot = manager.get(job_id)
        assert snapshot.status is JobStatus.COMPLETED
        assert snapshot.progress == 1.0
        assert snapshot.result == "done"
        assert snapshot.error is None
    finally:
        release.set()
        manager.shutdown()


def test_job_manager_captures_progress_and_failure() -> None:
    manager = ThreadJobManager(max_workers=1)

    def task(context: JobContext) -> None:
        context.report_progress(0.5, "halfway")
        raise RuntimeError("boom")

    try:
        job_id = manager.submit("failing", task)
        _wait_for_terminal(manager, job_id)

        snapshot = manager.get(job_id)
        assert snapshot.status is JobStatus.FAILED
        assert snapshot.progress == 0.5
        assert snapshot.message == "halfway"
        assert snapshot.error == "RuntimeError: boom"
    finally:
        manager.shutdown()


def test_job_manager_supports_cooperative_cancel() -> None:
    manager = ThreadJobManager(max_workers=1)
    started = Event()

    def task(context: JobContext) -> None:
        started.set()
        while True:
            context.raise_if_cancelled()
            time.sleep(0.01)

    try:
        job_id = manager.submit("cancellable", task)
        assert started.wait(timeout=1.0)

        assert manager.cancel(job_id) is True
        _wait_for_terminal(manager, job_id)

        snapshot = manager.get(job_id)
        assert snapshot.status is JobStatus.CANCELLED
        assert snapshot.finished_at is not None
        assert manager.cancel(job_id) is False
    finally:
        manager.shutdown()
