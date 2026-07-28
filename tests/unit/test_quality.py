from __future__ import annotations

from decimal import Decimal

import pytest

from homemeterhub.quality import validate_p1_measurement, validate_water_measurement


def test_rejects_negative_p1_counter() -> None:
    with pytest.raises(ValueError, match="gas_m3"):
        validate_p1_measurement({"gas_m3": Decimal("-1")})


def test_rejects_implausible_voltage() -> None:
    with pytest.raises(ValueError, match="voltage_l1_v"):
        validate_p1_measurement({"voltage_l1_v": Decimal("400")})


def test_rejects_implausible_water_wifi_signal() -> None:
    with pytest.raises(ValueError, match="wifi_signal_dbm"):
        validate_water_measurement({"wifi_signal_dbm": Decimal("12")})
