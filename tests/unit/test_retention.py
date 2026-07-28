from __future__ import annotations

import asyncio

from homemeterhub.config import RetentionSettings
from homemeterhub.retention import RetentionJob


class _FakeDatabase:
    def __init__(self) -> None:
        self.p1_calls: list[int] = []
        self.water_calls: list[int] = []
        self.success_calls: list[str] = []

    def delete_old_p1_measurements(self, retention_days: int) -> int:
        self.p1_calls.append(retention_days)
        return 3

    def delete_old_water_measurements(self, retention_days: int) -> int:
        self.water_calls.append(retention_days)
        return 5

    def mark_success(self, collector_name: str) -> None:
        self.success_calls.append(collector_name)


def test_run_once_deletes_using_configured_retention_days() -> None:
    settings = RetentionSettings(
        ENABLE_RETENTION_CLEANUP=True,
        RETENTION_RAW_SECONDS_DATA_DAYS=90,
        RETENTION_WATER_EVENTS_DAYS=30,
    )
    database = _FakeDatabase()
    job = RetentionJob(settings, database)

    asyncio.run(job.run_once())

    assert database.p1_calls == [90]
    assert database.water_calls == [30]
    assert database.success_calls == ["retention_job"]
