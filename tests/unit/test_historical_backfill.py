from datetime import UTC, datetime, timedelta

import pytest

from trading_system.application import ChunkPlanner


def test_chunk_planner_splits_range_into_daily_chunks() -> None:
    planner = ChunkPlanner(max_span=timedelta(days=1))
    start = datetime(2026, 1, 1, 12, tzinfo=UTC)
    end = datetime(2026, 1, 3, 18, tzinfo=UTC)

    chunks = planner.plan(start, end)

    assert [(chunk.from_ts, chunk.to_ts) for chunk in chunks] == [
        (start, datetime(2026, 1, 2, 12, tzinfo=UTC)),
        (
            datetime(2026, 1, 2, 12, tzinfo=UTC),
            datetime(2026, 1, 3, 12, tzinfo=UTC),
        ),
        (datetime(2026, 1, 3, 12, tzinfo=UTC), end),
    ]


def test_chunk_planner_rejects_invalid_range() -> None:
    planner = ChunkPlanner()
    start = datetime(2026, 1, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="earlier"):
        planner.plan(start, start)
