from __future__ import annotations

import asyncio
import logging

from homemeterhub.config import RetentionSettings
from homemeterhub.db import Database
from homemeterhub.health import RETENTION_JOB

LOGGER = logging.getLogger(__name__)

# Retention only needs to run periodically, not on every poll cycle. Once a day
# is frequent enough to keep the raw tables bounded without adding meaningful
# database load.
CHECK_INTERVAL_SECONDS = 24 * 60 * 60


class RetentionJob:
    def __init__(self, settings: RetentionSettings, database: Database) -> None:
        self.settings = settings
        self.database = database

    async def run_once(self) -> None:
        deleted_p1 = await asyncio.to_thread(
            self.database.delete_old_p1_measurements,
            self.settings.raw_seconds_data_days,
        )
        deleted_water = await asyncio.to_thread(
            self.database.delete_old_water_measurements,
            self.settings.water_events_days,
        )
        await asyncio.to_thread(self.database.mark_success, RETENTION_JOB)
        if deleted_p1 or deleted_water:
            LOGGER.info(
                "Retention cleanup removed %s p1_measurements row(s) older than %sd "
                "and %s water_measurements row(s) older than %sd",
                deleted_p1,
                self.settings.raw_seconds_data_days,
                deleted_water,
                self.settings.water_events_days,
            )

    async def run(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                LOGGER.exception("Retention cleanup cycle failed")
                await asyncio.to_thread(self.database.mark_error, RETENTION_JOB, str(error))
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
