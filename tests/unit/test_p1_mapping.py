from __future__ import annotations

from decimal import Decimal

from homemeterhub.p1_collector import build_p1_measurement_row


def test_e_list_payload_uses_first_item() -> None:
    row = build_p1_measurement_row(
        [{"tm": 1, "net": 10.5}, {"tm": 2, "net": 99.9}],
        None,
        store_raw_json=False,
    )
    assert row["youless_tm"] == 1
    assert row["electricity_net_kwh"] == Decimal("10.5")


def test_electricity_counters_map_correctly() -> None:
    row = build_p1_measurement_row(
        [{"net": 12747.710, "p1": 13007.849, "p2": 9601.165, "n1": 3121.863, "n2": 6739.441}],
        None,
        store_raw_json=False,
    )
    assert row["electricity_net_kwh"] == Decimal("12747.71")
    assert row["electricity_delivered_t1_kwh"] == Decimal("13007.849")
    assert row["electricity_delivered_t2_kwh"] == Decimal("9601.165")
    assert row["electricity_returned_t1_kwh"] == Decimal("3121.863")
    assert row["electricity_returned_t2_kwh"] == Decimal("6739.441")


def test_gas_value_maps_correctly() -> None:
    row = build_p1_measurement_row([{"gas": 5984.247}], None, store_raw_json=False)
    assert row["gas_m3"] == Decimal("5984.247")


def test_phase_values_map_correctly_and_allow_negative_values() -> None:
    row = build_p1_measurement_row(
        [{"tm": 1}],
        {
            "l1": 293,
            "l2": -8,
            "l3": 1171,
            "v1": 235.0,
            "v2": 236.0,
            "v3": 236.0,
            "i1": 1.0,
            "i2": 0.0,
            "i3": 5.0,
        },
        store_raw_json=False,
    )
    assert row["power_l1_w"] == 293
    assert row["power_l2_w"] == -8
    assert row["power_l3_w"] == 1171
    assert row["voltage_l1_v"] == Decimal("235.0")
    assert row["current_l3_a"] == Decimal("5.0")


def test_missing_f_payload_sets_phase_values_to_none() -> None:
    row = build_p1_measurement_row([{"tm": 1}], None, store_raw_json=False)
    assert row["power_l1_w"] is None
    assert row["voltage_l1_v"] is None


def test_raw_payloads_are_preserved_when_enabled() -> None:
    e_payload = [{"tm": 1}]
    f_payload = {"l1": 10}
    row = build_p1_measurement_row(e_payload, f_payload, store_raw_json=True)
    assert row["raw_e_json"] == e_payload
    assert row["raw_f_json"] == f_payload
