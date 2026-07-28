from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from homemeterhub.config import load_settings
from homemeterhub.db import Database
from homemeterhub.health import DB_INITIALIZER
from homemeterhub.logging_config import configure_logging
from homemeterhub.p1_collector import P1Collector
from homemeterhub.retention import RetentionJob
from homemeterhub.runtime_state import RuntimeState
from homemeterhub.status_server import StatusServer
from homemeterhub.water_collector import WaterCollector

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HomeMeterHub")
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate configuration and exit without starting collectors.",
    )
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    settings = load_settings()
    configure_logging(settings.app.log_level)

    if args.validate_config:
        LOGGER.info("Configuration validation succeeded")
        return 0

    database = Database(settings.database)
    tasks: list[asyncio.Task[None]] = []
    stop_task: asyncio.Task[bool] | None = None
    try:
        runtime_state = RuntimeState()
        if settings.app.enable_db_init:
            try:
                database.ensure_schema()
                database.mark_success(DB_INITIALIZER)
            except Exception as error:  # noqa: BLE001
                database.mark_error(DB_INITIALIZER, str(error))
                raise

        if settings.app.enable_p1_collector:
            tasks.append(
                asyncio.create_task(
                    P1Collector(settings.p1, database, runtime_state).run(),
                    name="p1-collector",
                )
            )
        if settings.app.enable_water_collector:
            tasks.append(
                asyncio.create_task(
                    WaterCollector(settings.water, database, runtime_state).run(),
                    name="water-collector",
                )
            )
        if settings.app.enable_status_server:
            tasks.append(
                asyncio.create_task(
                    StatusServer(
                        settings.app.status_host,
                        settings.app.status_port,
                        runtime_state,
                        settings.app,
                    ).run(),
                    name="status-server",
                )
            )
        if settings.retention.enable_retention_cleanup:
            tasks.append(
                asyncio.create_task(
                    RetentionJob(settings.retention, database).run(),
                    name="retention-job",
                )
            )

        if not tasks:
            LOGGER.warning("All services are disabled; exiting")
            return 0

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(shutdown_signal, stop_event.set)
            except NotImplementedError:
                # Windows does not support loop signal handlers; Docker/Linux does.
                pass
        stop_task = asyncio.create_task(stop_event.wait(), name="shutdown-signal")
        done, _ = await asyncio.wait([*tasks, stop_task], return_when=asyncio.FIRST_COMPLETED)
        if stop_task in done:
            LOGGER.info("Shutdown signal received")
            return 0
        for task in done:
            task.result()
        LOGGER.error("A service task stopped unexpectedly")
        return 1
    finally:
        for task in tasks:
            task.cancel()
        if stop_task is not None:
            stop_task.cancel()
        if tasks or stop_task is not None:
            await asyncio.gather(
                *tasks, *([stop_task] if stop_task is not None else []), return_exceptions=True
            )
        database.close()


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
