from __future__ import annotations

from decimal import Decimal

from homemeterhub.solaredge_collector import (
    build_home_assistant_solar_measurement_row,
    build_solar_measurement_row,
)


def test_solaredge_overview_maps_to_solar_measurement() -> None:
    row = build_solar_measurement_row(
        {
            "overview": {
                "currentPower": {"power": 2345},
                "lastDayData": {"energy": 12345.6},
                "lastMonthData": {"energy": 45678.9},
                "lastYearData": {"energy": 123456.7},
                "lifeTimeData": {"energy": 987654.3},
            }
        }
    )

    assert row["current_power_w"] == Decimal("2345")
    assert row["daily_energy_wh"] == Decimal("12345.6")
    assert row["lifetime_energy_wh"] == Decimal("987654.3")


def test_home_assistant_states_map_to_solar_measurement() -> None:
    states = {
        "sensor.power": {"state": "3064"},
        "sensor.today": {"state": "18228"},
        "sensor.month": {"state": "653417"},
        "sensor.year": {"state": "3276922"},
        "sensor.lifetime": {"state": "16896454"},
    }
    row = build_home_assistant_solar_measurement_row(states)

    assert row["current_power_w"] == Decimal("3064")
    assert row["daily_energy_wh"] == Decimal("18228")
