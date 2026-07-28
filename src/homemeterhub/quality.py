from __future__ import annotations

from decimal import Decimal
from typing import Any


def _non_negative(row: dict[str, Any], *fields: str) -> None:
    for field in fields:
        value = row.get(field)
        if value is not None and value < 0:
            raise ValueError(f"{field} must not be negative (received {value})")


def validate_p1_measurement(row: dict[str, Any]) -> None:
    _non_negative(
        row,
        "electricity_net_kwh",
        "electricity_delivered_t1_kwh",
        "electricity_delivered_t2_kwh",
        "electricity_returned_t1_kwh",
        "electricity_returned_t2_kwh",
        "gas_m3",
        "s0_counter",
    )
    for field in ("voltage_l1_v", "voltage_l2_v", "voltage_l3_v"):
        voltage = row.get(field)
        if voltage is not None and not Decimal("100") <= voltage <= Decimal("300"):
            raise ValueError(f"{field} is outside the expected 100-300V range (received {voltage})")


def validate_water_measurement(row: dict[str, Any]) -> None:
    _non_negative(
        row,
        "watermeter_stand_m3",
        "watermeter_total_m3",
        "watermeter_flow_l_min",
    )
    signal = row.get("wifi_signal_dbm")
    if signal is not None and not Decimal("-150") <= signal <= Decimal("0"):
        raise ValueError(
            f"wifi_signal_dbm is outside the expected -150-0dBm range (received {signal})"
        )
