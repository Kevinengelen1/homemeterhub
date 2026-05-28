from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from homemeterhub.config import WaterKeySettings
from homemeterhub.water_collector import WaterStateTracker

FIXTURES = Path(__file__).parent / "fixtures"


def test_known_s0tool_events_map_and_ignore_non_water_keys() -> None:
    tracker = WaterStateTracker(WaterKeySettings(), store_raw_payload=True)
    events = json.loads((FIXTURES / "s0tool_state_events.json").read_text())
    rows = [tracker.apply_state(event) for event in events]

    assert rows[0] is not None
    assert rows[0]["watermeter_stand_m3"] == Decimal("132.456")
    assert rows[1] is not None
    assert rows[1]["watermeter_total_m3"] == Decimal("12.3")
    assert rows[2] is not None
    assert rows[2]["watermeter_flow_l_min"] == Decimal("5.1")
    assert rows[3] is not None
    assert rows[3]["pulse_detected"] is True
    assert rows[4] is None
    assert rows[5] is None
