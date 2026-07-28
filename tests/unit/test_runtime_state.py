from __future__ import annotations

from decimal import Decimal

from homemeterhub.runtime_state import RuntimeState


def test_runtime_state_tracks_water_and_p1_activity() -> None:
    state = RuntimeState()
    assert state.snapshot()["application"]["version"] == "0.2.0"
    state.record_p1_measurement(
        {
            "power_w": 1234,
            "electricity_net_kwh": Decimal("12.345"),
            "gas_m3": Decimal("6.789"),
            "youless_tm": 123,
        }
    )
    state.record_water_event(
        {
            "event_source": "watermeter_flow",
            "watermeter_stand_m3": Decimal("101.200"),
            "watermeter_total_m3": Decimal("4.200"),
            "watermeter_flow_l_min": Decimal("3.4"),
            "pulse_detected": True,
            "wifi_signal_dbm": Decimal("-65.5"),
        }
    )

    snapshot = state.snapshot()
    assert snapshot["collectors"]["p1"]["event_count"] == 1
    assert snapshot["collectors"]["p1"]["last_summary"]["power_w"] == 1234
    assert snapshot["collectors"]["p1"]["last_summary"]["gas_m3"] == "6.789"
    assert snapshot["collectors"]["water"]["event_count"] == 1
    assert snapshot["collectors"]["water"]["last_summary"]["event_source"] == "watermeter_flow"
    assert snapshot["collectors"]["water"]["last_summary"]["wifi_signal_dbm"] == "-65.5"
