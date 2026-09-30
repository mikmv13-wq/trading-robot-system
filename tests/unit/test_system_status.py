from collections.abc import Mapping

from trading_system.application import GetSystemStatusUseCase, HealthStatus


class FakeRepository:
    def __init__(
        self,
        *,
        schema_version: int = 1,
        metadata: Mapping[str, str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._schema_version = schema_version
        self._metadata = dict(metadata or {"schema_baseline": "stage-0"})
        self._error = error

    def healthcheck(self) -> None:
        if self._error is not None:
            raise self._error

    def schema_version(self) -> int:
        return self._schema_version

    def metadata(self) -> Mapping[str, str]:
        return self._metadata


def test_system_status_reports_all_healthy_repositories() -> None:
    use_case = GetSystemStatusUseCase(
        {
            "market": FakeRepository(),
            "research": FakeRepository(schema_version=2),
        }
    )

    result = use_case.execute()

    assert result.healthy is True
    assert [status.name for status in result.databases] == ["market", "research"]
    assert [status.schema_version for status in result.databases] == [1, 2]
    assert all(status.status is HealthStatus.OK for status in result.databases)


def test_system_status_isolates_repository_failure() -> None:
    use_case = GetSystemStatusUseCase(
        {
            "market": FakeRepository(error=RuntimeError("unavailable")),
            "research": FakeRepository(),
        }
    )

    result = use_case.execute()

    assert result.healthy is False
    assert result.databases[0].status is HealthStatus.ERROR
    assert result.databases[0].schema_version is None
    assert result.databases[0].metadata == {}
    assert result.databases[0].error == "RuntimeError: unavailable"
    assert result.databases[1].status is HealthStatus.OK
