from __future__ import annotations

import pytest
from docker.errors import DockerException
from testcontainers.postgres import PostgresContainer

from homemeterhub.config import DatabaseSettings
from homemeterhub.db import Database


def test_schema_initialization_and_inserts_work() -> None:
    try:
        postgres_context = PostgresContainer("postgres:16-alpine")
    except DockerException as error:
        pytest.skip(f"Docker is unavailable for integration tests: {error}")

    try:
        postgres_manager = postgres_context.__enter__()
    except DockerException as error:
        pytest.skip(f"Docker is unavailable for integration tests: {error}")

    try:
        postgres = postgres_manager
        settings = DatabaseSettings(
            DB_HOST=postgres.get_container_host_ip(),
            DB_PORT=int(postgres.get_exposed_port(5432)),
            DB_NAME=postgres.dbname,
            DB_USER=postgres.username,
            DB_PASSWORD=postgres.password,
            DB_SSLMODE="disable",
            DB_CONNECT_TIMEOUT_SECONDS=10,
            DB_APPLICATION_NAME="homemeterhub-test",
        )
        database = Database(settings)
        database.ensure_schema()

        database.insert_p1_measurement(
            {
                "youless_tm": 1,
                "gas_timestamp_raw": 2,
                "electricity_net_kwh": 3,
                "electricity_delivered_t1_kwh": 4,
                "electricity_delivered_t2_kwh": 5,
                "electricity_returned_t1_kwh": 6,
                "electricity_returned_t2_kwh": 7,
                "gas_m3": 8,
                "power_w": 9,
                "power_l1_w": 10,
                "power_l2_w": 11,
                "power_l3_w": 12,
                "voltage_l1_v": 13,
                "voltage_l2_v": 14,
                "voltage_l3_v": 15,
                "current_l1_a": 16,
                "current_l2_a": 17,
                "current_l3_a": 18,
                "s0_timestamp": 19,
                "s0_counter": 20,
                "s0_power_w": 21,
                "raw_e_json": {"tm": 1},
                "raw_f_json": {"l1": 10},
            }
        )
        database.insert_water_measurement(
            {
                "watermeter_stand_m3": 1.23,
                "watermeter_total_m3": 4.56,
                "watermeter_flow_l_min": 7.89,
                "pulse_detected": True,
                "wifi_signal_dbm": -56.5,
                "event_source": "watermeter_stand",
                "raw_payload": {"key": 1, "state": 1.23},
            }
        )
        database.ensure_schema()

        with database.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.p1_measurements')")
            assert cursor.fetchone()[0] == "p1_measurements"

            cursor.execute("SELECT to_regclass('public.water_measurements')")
            assert cursor.fetchone()[0] == "water_measurements"

            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
                "AND tablename = 'p1_measurements'"
            )
            index_names = {row[0] for row in cursor.fetchall()}
            assert "idx_p1_measurements_measured_at" in index_names
            assert "idx_p1_measurements_youless_tm" in index_names

            cursor.execute("SELECT raw_e_json, raw_f_json FROM p1_measurements")
            raw_e_json, raw_f_json = cursor.fetchone()
            assert raw_e_json == {"tm": 1}
            assert raw_f_json == {"l1": 10}

            cursor.execute("SELECT COUNT(*) FROM water_measurements")
            assert cursor.fetchone()[0] == 1
    finally:
        postgres_context.__exit__(None, None, None)
