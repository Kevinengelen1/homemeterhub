from __future__ import annotations

from decimal import Decimal

from homemeterhub.config import WaterKeySettings
from homemeterhub.water_collector import WaterStateTracker


def tracker() -> WaterStateTracker:
    return WaterStateTracker(WaterKeySettings(), store_raw_payload=True)


def test_water_stand_key_maps_to_watermeter_stand() -> None:
    row = tracker().apply_state({"key": 2881466520, "state": 123.456})
    assert row is not None
    assert row["watermeter_stand_m3"] == Decimal("123.456")


def test_water_total_key_maps_to_watermeter_total() -> None:
    row = tracker().apply_state({"key": 2086030061, "state": 7.89})
    assert row is not None
    assert row["watermeter_total_m3"] == Decimal("7.89")


def test_flow_key_maps_to_flow_column() -> None:
    row = tracker().apply_state({"key": 3581156864, "state": 4.2})
    assert row is not None
    assert row["watermeter_flow_l_min"] == Decimal("4.2")


def test_pulse_key_maps_to_boolean_column() -> None:
    row = tracker().apply_state({"key": 413848536, "state": True})
    assert row is not None
    assert row["pulse_detected"] is True


def test_kwh_key_is_ignored() -> None:
    assert tracker().apply_state({"key": 1419664774, "state": 999}) is None


def test_boolean_string_values_are_handled() -> None:
    row = tracker().apply_state({"key": 413848536, "state": "on"})
    assert row is not None
    assert row["pulse_detected"] is True


def test_unknown_keys_are_ignored_safely() -> None:
    assert tracker().apply_state({"key": 999999, "state": 1}) is None
