from trading_system.application import JobApplicationService, JobStatus
from trading_system.infrastructure import ThreadJobManager


def test_test_job_reports_completed_progress_without_real_sleep() -> None:
    manager = ThreadJobManager(max_workers=1)
    service = JobApplicationService(manager, sleeper=lambda _: None)

    try:
        job_id = service.start_test_job(steps=4, delay_seconds=0)

        while not service.get(job_id).status.terminal:
            pass

        snapshot = service.get(job_id)
        assert snapshot.status is JobStatus.COMPLETED
        assert snapshot.progress == 1.0
        assert snapshot.message == "Step 4/4"
        assert snapshot.result == "test job completed"
    finally:
        manager.shutdown()
