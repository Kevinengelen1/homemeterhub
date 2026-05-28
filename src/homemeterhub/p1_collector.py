from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

import requests

from homemeterhub.config import P1Settings
from homemeterhub.db import Database
from homemeterhub.health import P1_COLLECTOR

LOGGER = logging.getLogger(__name__)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def build_p1_measurement_row(
    e_payload: list[dict[str, Any]] | dict[str, Any],
    f_payload: dict[str, Any] | None,
    *,
    store_raw_json: bool,
) -> dict[str, Any]:
    e_row = e_payload[0] if isinstance(e_payload, list) else e_payload
    f_row = f_payload or {}
    return {
        "youless_tm": _to_int(e_row.get("tm")),
        "gas_timestamp_raw": _to_int(e_row.get("gts")),
        "electricity_net_kwh": _to_decimal(e_row.get("net")),
        "electricity_delivered_t1_kwh": _to_decimal(e_row.get("p1")),
        "electricity_delivered_t2_kwh": _to_decimal(e_row.get("p2")),
        "electricity_returned_t1_kwh": _to_decimal(e_row.get("n1")),
        "electricity_returned_t2_kwh": _to_decimal(e_row.get("n2")),
        "gas_m3": _to_decimal(e_row.get("gas")),
        "power_w": _to_int(e_row.get("pwr")),
        "power_l1_w": _to_int(f_row.get("l1")),
        "power_l2_w": _to_int(f_row.get("l2")),
        "power_l3_w": _to_int(f_row.get("l3")),
        "voltage_l1_v": _to_decimal(f_row.get("v1")),
        "voltage_l2_v": _to_decimal(f_row.get("v2")),
        "voltage_l3_v": _to_decimal(f_row.get("v3")),
        "current_l1_a": _to_decimal(f_row.get("i1")),
        "current_l2_a": _to_decimal(f_row.get("i2")),
        "current_l3_a": _to_decimal(f_row.get("i3")),
        "s0_timestamp": _to_int(e_row.get("ts0")),
        "s0_counter": _to_decimal(e_row.get("cs0")),
        "s0_power_w": _to_int(e_row.get("ps0")),
        "raw_e_json": e_payload if store_raw_json else None,
        "raw_f_json": f_payload if store_raw_json else None,
    }


def build_p1_device_snapshot_row(d_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": d_payload.get("model") or d_payload.get("type"),
        "firmware": d_payload.get("firmware") or d_payload.get("fw"),
        "mac": d_payload.get("mac"),
        "raw_d_json": d_payload,
    }


class P1Collector:
    def __init__(self, settings: P1Settings, database: Database) -> None:
        self.settings = settings
        self.database = database
        self._last_device_snapshot = 0.0

    def _fetch_json(self, endpoint: str) -> Any:
        url = f"{self.settings.base_url.rstrip('/')}{endpoint}"
        response = requests.get(url, timeout=self.settings.http_timeout_seconds)
        response.raise_for_status()
        return response.json()

    async def _maybe_store_device_info(self) -> None:
        now = asyncio.get_running_loop().time()
        if now - self._last_device_snapshot < self.settings.device_info_interval_seconds:
            return
        d_payload = await asyncio.to_thread(self._fetch_json, self.settings.endpoint_d)
        row = build_p1_device_snapshot_row(d_payload)
        await asyncio.to_thread(self.database.insert_p1_device_snapshot, row)
        self._last_device_snapshot = now

    async def collect_once(self) -> None:
        e_payload = await asyncio.to_thread(self._fetch_json, self.settings.endpoint_e)
        try:
            f_payload = await asyncio.to_thread(self._fetch_json, self.settings.endpoint_f)
        except Exception as error:  # noqa: BLE001
            LOGGER.warning("P1 phase poll failed; storing /e row without phase values: %s", error)
            f_payload = None
        row = build_p1_measurement_row(
            e_payload,
            f_payload,
            store_raw_json=self.settings.store_raw_json,
        )
        await asyncio.to_thread(self.database.insert_p1_measurement, row)
        await asyncio.to_thread(self.database.mark_success, P1_COLLECTOR)
        await self._maybe_store_device_info()

    async def run(self) -> None:
        while True:
            try:
                await self.collect_once()
                await asyncio.sleep(self.settings.poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                LOGGER.exception("P1 collector cycle failed")
                await asyncio.to_thread(self.database.mark_error, P1_COLLECTOR, str(error))
                await asyncio.sleep(self.settings.retry_delay_seconds)
