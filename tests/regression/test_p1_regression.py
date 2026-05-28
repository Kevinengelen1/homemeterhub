from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from homemeterhub.p1_collector import build_p1_measurement_row

FIXTURES = Path(__file__).parent / "fixtures"


def test_known_youless_payload_maps_expected_values() -> None:
    e_payload = json.loads((FIXTURES / "youless_e.json").read_text())
    f_payload = json.loads((FIXTURES / "youless_f.json").read_text())
    row = build_p1_measurement_row(e_payload, f_payload, store_raw_json=True)
    assert row["electricity_net_kwh"] == Decimal("12747.71")
    assert row["electricity_delivered_t1_kwh"] == Decimal("13007.849")
    assert row["electricity_delivered_t2_kwh"] == Decimal("9601.165")
    assert row["electricity_returned_t1_kwh"] == Decimal("3121.863")
    assert row["electricity_returned_t2_kwh"] == Decimal("6739.441")
    assert row["gas_m3"] == Decimal("5984.247")
    assert row["power_l1_w"] == 293
    assert row["power_l2_w"] == -8
    assert row["power_l3_w"] == 1171
