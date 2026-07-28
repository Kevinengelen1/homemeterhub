from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from aioesphomeapi import APIClient

from homemeterhub.config import WaterKeySettings, WaterSettings
from homemeterhub.db import Database
from homemeterhub.health import WATER_COLLECTOR
from homemeterhub.quality import validate_water_measurement
from homemeterhub.runtime_state import RuntimeState

LOGGER = logging.getLogger(__name__)


def _coerce_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"true", "on", "1"}:
        return True
    if normalized in {"false", "off", "0"}:
        return False
    return None


def serialize_state(state: Any) -> dict[str, Any]:
    if isinstance(state, dict):
        return state
    payload: dict[str, Any] = {}
    for name in dir(state):
        if name.startswith("_"):
            continue
        try:
            value = getattr(state, name)
        except Exception as error:  # noqa: BLE001
            LOGGER.debug("Skipping unreadable ESPHome state attribute %s: %s", name, error)
            continue
        if callable(value):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            payload[name] = value
        else:
            payload[name] = str(value)
    return payload


def get_state_key(state: Any) -> int | None:
    value = serialize_state(state).get("key")
    if value is None:
        return None
    return int(value)


def get_state_value(state: Any) -> Any:
    payload = serialize_state(state)
    return payload.get("state")


class WaterStateTracker:
    def __init__(self, keys: WaterKeySettings, *, store_raw_payload: bool) -> None:
        self.keys = keys
        self.store_raw_payload = store_raw_payload
        self.latest: dict[str, Any] = {
            "watermeter_stand_m3": None,
            "watermeter_total_m3": None,
            "watermeter_flow_l_min": None,
            "pulse_detected": None,
            "wifi_signal_dbm": None,
        }

    def apply_state(self, state: Any) -> dict[str, Any] | None:
        key = get_state_key(state)
        value = get_state_value(state)
        if key is None:
            return None

        if key == self.keys.water_stand:
            self.latest["watermeter_stand_m3"] = _coerce_decimal(value)
            event_source = "watermeter_stand"
        elif key == self.keys.water_total:
            self.latest["watermeter_total_m3"] = _coerce_decimal(value)
            event_source = "watermeter_total"
        elif key == self.keys.water_flow:
            self.latest["watermeter_flow_l_min"] = _coerce_decimal(value)
            event_source = "watermeter_flow"
        elif key == self.keys.water_status:
            self.latest["pulse_detected"] = _coerce_bool(value)
            event_source = "water_sensor_status"
        elif key == self.keys.wifi_signal:
            self.latest["wifi_signal_dbm"] = _coerce_decimal(value)
            event_source = "wifi_signal"
        else:
            return None

        return {
            **self.latest,
            "event_source": event_source,
            "raw_payload": serialize_state(state) if self.store_raw_payload else None,
        }


class WaterCollector:
    def __init__(
        self,
        settings: WaterSettings,
        database: Database,
        runtime_state: RuntimeState,
    ) -> None:
        self.settings = settings
        self.database = database
        self.runtime_state = runtime_state
        self.tracker = WaterStateTracker(
            settings.keys,
            store_raw_payload=settings.store_raw_payload,
        )

    async def run(self) -> None:
        while True:
            disconnect_event = asyncio.Event()

            async def on_stop(
                expected_disconnect: bool,
                _disconnect_event: asyncio.Event = disconnect_event,
            ) -> None:
                if not expected_disconnect:
                    LOGGER.warning("ESPHome connection stopped unexpectedly")
                _disconnect_event.set()

            client = APIClient(
                self.settings.host,
                self.settings.port,
                noise_psk=self.settings.noise_psk or None,
                keepalive=10,
                client_info="homemeterhub",
            )
            try:
                await client.connect(on_stop=on_stop, login=True)
                client.subscribe_states(self._build_state_callback())
                await asyncio.to_thread(self.database.mark_success, WATER_COLLECTOR)
                self.runtime_state.set_connected("water", True)
                LOGGER.info(
                    "Connected to S0Tool ESPHome API at %s:%s",
                    self.settings.host,
                    self.settings.port,
                )
                await disconnect_event.wait()
            except asyncio.CancelledError:
                await client.disconnect(force=True)
                raise
            except Exception as error:  # noqa: BLE001
                LOGGER.exception("Water collector connection failed")
                self.runtime_state.record_error("water", str(error))
                await asyncio.to_thread(self.database.mark_error, WATER_COLLECTOR, str(error))
            finally:
                self.runtime_state.set_connected("water", False)
                await client.disconnect(force=True)

            await asyncio.sleep(self.settings.reconnect_delay_seconds)

    def _build_state_callback(self):
        loop = asyncio.get_running_loop()

        def _store(row: dict[str, Any]) -> None:
            validate_water_measurement(row)
            self.database.insert_water_measurement(row)
            self.database.mark_success(WATER_COLLECTOR)
            self.runtime_state.record_water_event(row)
            LOGGER.info(
                "Stored water event: source=%s stand_m3=%s total_m3=%s flow_l_min=%s pulse=%s",
                row.get("event_source"),
                row.get("watermeter_stand_m3"),
                row.get("watermeter_total_m3"),
                row.get("watermeter_flow_l_min"),
                row.get("pulse_detected"),
            )

        def _on_store_done(future: asyncio.Future[None]) -> None:
            error = future.exception()
            if error is not None:
                LOGGER.exception("Failed to store water event", exc_info=error)
                self.runtime_state.record_error("water", str(error))
                self.database.mark_error(WATER_COLLECTOR, str(error))

        def on_state(state: Any) -> None:
            row = self.tracker.apply_state(state)
            if row is None:
                return
            # aioesphomeapi invokes this callback synchronously on the asyncio
            # event loop thread. insert_water_measurement() does blocking network
            # I/O against PostgreSQL, so it must run in a worker thread instead of
            # inline here, otherwise every water event would stall the entire
            # event loop (P1 polling, status page, etc.) until the DB round trip
            # completes.
            future = loop.run_in_executor(None, _store, row)
            future.add_done_callback(_on_store_done)

        return on_state
