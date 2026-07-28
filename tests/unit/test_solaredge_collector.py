from __future__ import annotations

from decimal import Decimal

from homemeterhub.solaredge_collector import build_solar_measurement_row


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
