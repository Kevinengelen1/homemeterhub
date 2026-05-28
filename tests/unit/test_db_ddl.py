from __future__ import annotations

from homemeterhub.db import SCHEMA_DDL


def test_ddl_contains_expected_table_names() -> None:
    assert "CREATE TABLE IF NOT EXISTS p1_measurements" in SCHEMA_DDL
    assert "CREATE TABLE IF NOT EXISTS p1_device_snapshots" in SCHEMA_DDL
    assert "CREATE TABLE IF NOT EXISTS water_measurements" in SCHEMA_DDL
    assert "CREATE TABLE IF NOT EXISTS collector_health" in SCHEMA_DDL


def test_ddl_contains_expected_indexes() -> None:
    assert "idx_p1_measurements_measured_at" in SCHEMA_DDL
    assert "idx_p1_measurements_youless_tm" in SCHEMA_DDL
    assert "idx_p1_device_snapshots_measured_at" in SCHEMA_DDL
    assert "idx_water_measurements_measured_at" in SCHEMA_DDL
    assert "idx_water_measurements_event_source" in SCHEMA_DDL


def test_ddl_contains_primary_keys() -> None:
    assert SCHEMA_DDL.count("PRIMARY KEY") >= 4


def test_ddl_does_not_drop_or_truncate_tables() -> None:
    assert "DROP TABLE" not in SCHEMA_DDL
    assert "TRUNCATE" not in SCHEMA_DDL
