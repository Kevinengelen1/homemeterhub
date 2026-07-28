from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from threading import Lock
from typing import Any


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _sanitize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


class RuntimeState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._state: dict[str, Any] = {
            "started_at": _utc_now(),
            "collectors": {
                "p1": {
                    "connected": False,
                    "event_count": 0,
                    "last_event_at": None,
                    "last_error": None,
                    "last_summary": None,
                },
                "water": {
                    "connected": False,
                    "event_count": 0,
                    "last_event_at": None,
                    "last_error": None,
                    "last_summary": None,
                },
            },
        }

    def set_connected(self, collector: str, connected: bool) -> None:
        with self._lock:
            self._state["collectors"][collector]["connected"] = connected

    def record_error(self, collector: str, message: str) -> None:
        with self._lock:
            target = self._state["collectors"][collector]
            target["last_error"] = {"at": _utc_now(), "message": message}
            target["connected"] = False

    def record_p1_measurement(self, row: dict[str, Any]) -> None:
        summary = {
            "power_w": row.get("power_w"),
            "electricity_net_kwh": row.get("electricity_net_kwh"),
            "gas_m3": row.get("gas_m3"),
            "youless_tm": row.get("youless_tm"),
        }
        with self._lock:
            target = self._state["collectors"]["p1"]
            target["connected"] = True
            target["event_count"] += 1
            target["last_event_at"] = _utc_now()
            target["last_summary"] = _sanitize(summary)

    def record_water_event(self, row: dict[str, Any]) -> None:
        summary = {
            "event_source": row.get("event_source"),
            "watermeter_stand_m3": row.get("watermeter_stand_m3"),
            "watermeter_total_m3": row.get("watermeter_total_m3"),
            "watermeter_flow_l_min": row.get("watermeter_flow_l_min"),
            "pulse_detected": row.get("pulse_detected"),
            "wifi_signal_dbm": row.get("wifi_signal_dbm"),
        }
        with self._lock:
            target = self._state["collectors"]["water"]
            target["connected"] = True
            target["event_count"] += 1
            target["last_event_at"] = _utc_now()
            target["last_summary"] = _sanitize(summary)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)
