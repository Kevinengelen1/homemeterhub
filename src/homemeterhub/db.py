from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any

import psycopg2
import psycopg2.pool
from psycopg2.extras import Json

from homemeterhub.config import DatabaseSettings

LOGGER = logging.getLogger(__name__)

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS p1_measurements (
    id BIGSERIAL PRIMARY KEY,
    measured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    youless_tm BIGINT,
    gas_timestamp_raw BIGINT,
    electricity_net_kwh NUMERIC(14, 3),
    electricity_delivered_t1_kwh NUMERIC(14, 3),
    electricity_delivered_t2_kwh NUMERIC(14, 3),
    electricity_returned_t1_kwh NUMERIC(14, 3),
    electricity_returned_t2_kwh NUMERIC(14, 3),
    gas_m3 NUMERIC(14, 3),
    power_w INTEGER,
    power_l1_w INTEGER,
    power_l2_w INTEGER,
    power_l3_w INTEGER,
    voltage_l1_v NUMERIC(8, 3),
    voltage_l2_v NUMERIC(8, 3),
    voltage_l3_v NUMERIC(8, 3),
    current_l1_a NUMERIC(8, 3),
    current_l2_a NUMERIC(8, 3),
    current_l3_a NUMERIC(8, 3),
    s0_timestamp BIGINT,
    s0_counter NUMERIC(14, 3),
    s0_power_w INTEGER,
    raw_e_json JSONB,
    raw_f_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_p1_measurements_measured_at
ON p1_measurements (measured_at DESC);

CREATE INDEX IF NOT EXISTS idx_p1_measurements_youless_tm
ON p1_measurements (youless_tm DESC);

CREATE TABLE IF NOT EXISTS p1_device_snapshots (
    id BIGSERIAL PRIMARY KEY,
    measured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    model TEXT,
    firmware TEXT,
    mac TEXT,
    raw_d_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_p1_device_snapshots_measured_at
ON p1_device_snapshots (measured_at DESC);

CREATE TABLE IF NOT EXISTS water_measurements (
    id BIGSERIAL PRIMARY KEY,
    measured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    watermeter_stand_m3 NUMERIC(14, 3),
    watermeter_total_m3 NUMERIC(14, 3),
    watermeter_flow_l_min NUMERIC(14, 3),
    pulse_detected BOOLEAN,
    wifi_signal_dbm NUMERIC(8, 2),
    event_source TEXT,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_water_measurements_measured_at
ON water_measurements (measured_at DESC);

CREATE INDEX IF NOT EXISTS idx_water_measurements_event_source
ON water_measurements (event_source);

CREATE TABLE IF NOT EXISTS collector_health (
    collector_name TEXT PRIMARY KEY,
    last_success_at TIMESTAMPTZ,
    last_error_at TIMESTAMPTZ,
    last_error_message TEXT,
    consecutive_error_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
""".strip()

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, SCHEMA_DDL),
    (
        2,
        """
        DELETE FROM p1_measurements AS duplicate
        USING p1_measurements AS retained
        WHERE duplicate.youless_tm = retained.youless_tm
          AND duplicate.youless_tm IS NOT NULL
          AND duplicate.id > retained.id;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_p1_measurements_youless_tm_unique
        ON p1_measurements (youless_tm)
        WHERE youless_tm IS NOT NULL;
        """.strip(),
    ),
)

MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
""".strip()


class Database:
    def __init__(self, settings: DatabaseSettings) -> None:
        self.settings = settings
        self._pool: Any | None = None
        self._pool_lock = Lock()

    def _get_pool(self) -> Any:
        with self._pool_lock:
            if self._pool is None:
                self._pool = psycopg2.pool.ThreadedConnectionPool(
                    self.settings.pool_min_size,
                    self.settings.pool_max_size,
                    host=self.settings.host,
                    port=self.settings.port,
                    dbname=self.settings.name,
                    user=self.settings.user,
                    password=self.settings.password,
                    sslmode=self.settings.sslmode,
                    connect_timeout=self.settings.connect_timeout_seconds,
                    application_name=self.settings.application_name,
                )
            return self._pool

    @contextmanager
    def connect(self) -> Iterator[Any]:
        pool = self._get_pool()
        connection = pool.getconn()
        discarded = False
        try:
            connection.autocommit = True
            yield connection
        except BaseException:
            # Never return a connection that failed during use to the pool.
            pool.putconn(connection, close=True)
            discarded = True
            raise
        finally:
            if not discarded:
                pool.putconn(connection)

    def close(self) -> None:
        """Dispose pooled connections; safe to call more than once."""
        with self._pool_lock:
            if self._pool is not None:
                self._pool.closeall()
                self._pool = None

    def ensure_schema(self) -> None:
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(MIGRATIONS_DDL)
            cursor.execute("SELECT version FROM schema_migrations")
            applied_versions = {row[0] for row in cursor.fetchall()}
            for version, ddl in MIGRATIONS:
                if version not in applied_versions:
                    LOGGER.info("Applying database migration %s", version)
                    cursor.execute(ddl)
                    cursor.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)", (version,)
                    )
            cursor.executemany(
                (
                    "INSERT INTO collector_health (collector_name) VALUES (%s) "
                    "ON CONFLICT (collector_name) DO NOTHING"
                ),
                [
                    ("p1_collector",),
                    ("water_collector",),
                    ("db_initializer",),
                    ("retention_job",),
                ],
            )

    def insert_p1_measurement(self, row: dict[str, Any]) -> bool:
        payload = dict(row)
        payload["raw_e_json"] = (
            Json(payload["raw_e_json"]) if payload.get("raw_e_json") is not None else None
        )
        payload["raw_f_json"] = (
            Json(payload["raw_f_json"]) if payload.get("raw_f_json") is not None else None
        )
        query = """
            INSERT INTO p1_measurements (
                youless_tm,
                gas_timestamp_raw,
                electricity_net_kwh,
                electricity_delivered_t1_kwh,
                electricity_delivered_t2_kwh,
                electricity_returned_t1_kwh,
                electricity_returned_t2_kwh,
                gas_m3,
                power_w,
                power_l1_w,
                power_l2_w,
                power_l3_w,
                voltage_l1_v,
                voltage_l2_v,
                voltage_l3_v,
                current_l1_a,
                current_l2_a,
                current_l3_a,
                s0_timestamp,
                s0_counter,
                s0_power_w,
                raw_e_json,
                raw_f_json
            ) VALUES (
                %(youless_tm)s,
                %(gas_timestamp_raw)s,
                %(electricity_net_kwh)s,
                %(electricity_delivered_t1_kwh)s,
                %(electricity_delivered_t2_kwh)s,
                %(electricity_returned_t1_kwh)s,
                %(electricity_returned_t2_kwh)s,
                %(gas_m3)s,
                %(power_w)s,
                %(power_l1_w)s,
                %(power_l2_w)s,
                %(power_l3_w)s,
                %(voltage_l1_v)s,
                %(voltage_l2_v)s,
                %(voltage_l3_v)s,
                %(current_l1_a)s,
                %(current_l2_a)s,
                %(current_l3_a)s,
                %(s0_timestamp)s,
                %(s0_counter)s,
                %(s0_power_w)s,
                %(raw_e_json)s,
                %(raw_f_json)s
            ) ON CONFLICT DO NOTHING
        """
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, payload)
            return cursor.rowcount == 1

    def insert_p1_device_snapshot(self, row: dict[str, Any]) -> None:
        payload = dict(row)
        payload["raw_d_json"] = (
            Json(payload["raw_d_json"]) if payload.get("raw_d_json") is not None else None
        )
        query = """
            INSERT INTO p1_device_snapshots (model, firmware, mac, raw_d_json)
            VALUES (%(model)s, %(firmware)s, %(mac)s, %(raw_d_json)s)
        """
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, payload)

    def insert_water_measurement(self, row: dict[str, Any]) -> None:
        payload = dict(row)
        payload["raw_payload"] = (
            Json(payload["raw_payload"]) if payload.get("raw_payload") is not None else None
        )
        query = """
            INSERT INTO water_measurements (
                watermeter_stand_m3,
                watermeter_total_m3,
                watermeter_flow_l_min,
                pulse_detected,
                wifi_signal_dbm,
                event_source,
                raw_payload
            ) VALUES (
                %(watermeter_stand_m3)s,
                %(watermeter_total_m3)s,
                %(watermeter_flow_l_min)s,
                %(pulse_detected)s,
                %(wifi_signal_dbm)s,
                %(event_source)s,
                %(raw_payload)s
            )
        """
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, payload)

    def mark_success(self, collector_name: str) -> None:
        query = """
            INSERT INTO collector_health (
                collector_name,
                last_success_at,
                last_error_at,
                last_error_message,
                consecutive_error_count,
                updated_at
            ) VALUES (%s, now(), NULL, NULL, 0, now())
            ON CONFLICT (collector_name)
            DO UPDATE SET
                last_success_at = now(),
                last_error_at = NULL,
                last_error_message = NULL,
                consecutive_error_count = 0,
                updated_at = now()
        """
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, (collector_name,))

    def mark_error(self, collector_name: str, message: str) -> None:
        query = """
            INSERT INTO collector_health (
                collector_name,
                last_error_at,
                last_error_message,
                consecutive_error_count,
                updated_at
            ) VALUES (%s, now(), %s, 1, now())
            ON CONFLICT (collector_name)
            DO UPDATE SET
                last_error_at = now(),
                last_error_message = EXCLUDED.last_error_message,
                consecutive_error_count = collector_health.consecutive_error_count + 1,
                updated_at = now()
        """
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, (collector_name, message[:2000]))

    def delete_old_p1_measurements(self, retention_days: int) -> int:
        query = "DELETE FROM p1_measurements WHERE measured_at < now() - (%s * INTERVAL '1 day')"
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, (retention_days,))
            return cursor.rowcount

    def delete_old_water_measurements(self, retention_days: int) -> int:
        query = "DELETE FROM water_measurements WHERE measured_at < now() - (%s * INTERVAL '1 day')"
        with self.connect() as connection, connection.cursor() as cursor:
            cursor.execute(query, (retention_days,))
            return cursor.rowcount
