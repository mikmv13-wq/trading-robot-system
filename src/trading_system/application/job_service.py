from __future__ import annotations

import time
from collections.abc import Callable

from trading_system.application.jobs import JobContext, JobManager, JobSnapshot


class JobApplicationService:
    """Application-facing control surface for background jobs."""

    def __init__(
        self,
        manager: JobManager,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._manager = manager
        self._sleeper = sleeper

    def start_test_job(
        self,
        *,
        steps: int = 20,
        delay_seconds: float = 0.05,
    ) -> str:
        if steps <= 0:
            raise ValueError("steps must be positive")
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be non-negative")

        def task(context: JobContext) -> str:
            for step in range(1, steps + 1):
                context.raise_if_cancelled()
                self._sleeper(delay_seconds)
                context.raise_if_cancelled()
                context.report_progress(
                    step / steps,
                    f"Step {step}/{steps}",
                )
            return "test job completed"

        return self._manager.submit("Background test job", task)

    def get(self, job_id: str) -> JobSnapshot:
        return self._manager.get(job_id)

    def list_jobs(self) -> tuple[JobSnapshot, ...]:
        return self._manager.list_jobs()

    def cancel(self, job_id: str) -> bool:
        return self._manager.cancel(job_id)
