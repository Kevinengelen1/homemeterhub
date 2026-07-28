from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

import requests

from homemeterhub.config import SolarEdgeSettings
from homemeterhub.db import Database
from homemeterhub.health import SOLAREDGE_COLLECTOR

LOGGER = logging.getLogger(__name__)
SOLAREDGE_API_BASE_URL = "https://monitoringapi.solaredge.com"


def _decimal(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def build_solar_measurement_row(payload: dict[str, Any]) -> dict[str, Any]:
    overview = payload.get("overview", payload)
    return {
        "current_power_w": _decimal((overview.get("currentPower") or {}).get("power")),
        "daily_energy_wh": _decimal((overview.get("lastDayData") or {}).get("energy")),
        "monthly_energy_wh": _decimal((overview.get("lastMonthData") or {}).get("energy")),
        "yearly_energy_wh": _decimal((overview.get("lastYearData") or {}).get("energy")),
        "lifetime_energy_wh": _decimal((overview.get("lifeTimeData") or {}).get("energy")),
        "raw_overview_json": payload,
    }


def build_home_assistant_solar_measurement_row(states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def state(entity_id: str) -> Decimal:
        value = states[entity_id].get("state")
        if value in {None, "unknown", "unavailable"}:
            raise ValueError(f"Home Assistant entity {entity_id} has no numeric state")
        return Decimal(str(value))

    entity_ids = tuple(states)
    return {
        "current_power_w": state(entity_ids[0]),
        "daily_energy_wh": state(entity_ids[1]),
        "monthly_energy_wh": state(entity_ids[2]),
        "yearly_energy_wh": state(entity_ids[3]),
        "lifetime_energy_wh": state(entity_ids[4]),
        "raw_overview_json": {"source": "home_assistant", "states": states},
    }


class SolarEdgeCollector:
    def __init__(self, settings: SolarEdgeSettings, database: Database) -> None:
        self.settings = settings
        self.database = database
        self.session = requests.Session()

    def _fetch_overview(self) -> dict[str, Any]:
        response = self.session.get(
            f"{SOLAREDGE_API_BASE_URL}/site/{self.settings.site_id}/overview",
            params={"api_key": self.settings.api_key},
            timeout=self.settings.http_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    async def collect_once(self) -> None:
        payload = await asyncio.to_thread(self._fetch_overview)
        row = build_solar_measurement_row(payload)
        await asyncio.to_thread(self.database.insert_solar_measurement, row)
        await asyncio.to_thread(self.database.mark_success, SOLAREDGE_COLLECTOR)
        LOGGER.info(
            "Stored SolarEdge measurement: current_power_w=%s daily_energy_wh=%s",
            row["current_power_w"],
            row["daily_energy_wh"],
        )

    async def run(self) -> None:
        while True:
            try:
                await self.collect_once()
                await asyncio.sleep(self.settings.poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                LOGGER.warning("SolarEdge collector cycle failed: %s", error)
                await asyncio.to_thread(self.database.mark_error, SOLAREDGE_COLLECTOR, str(error))
                await asyncio.sleep(self.settings.retry_delay_seconds)


class HomeAssistantSolarEdgeCollector(SolarEdgeCollector):
    def _fetch_overview(self) -> dict[str, Any]:
        entity_ids = (
            self.settings.home_assistant_current_power_entity,
            self.settings.home_assistant_today_energy_entity,
            self.settings.home_assistant_month_energy_entity,
            self.settings.home_assistant_year_energy_entity,
            self.settings.home_assistant_lifetime_energy_entity,
        )
        headers = {"Authorization": f"Bearer {self.settings.home_assistant_token}"}
        base_url = self.settings.home_assistant_url.rstrip("/")
        states: dict[str, dict[str, Any]] = {}
        for entity_id in entity_ids:
            response = self.session.get(
                f"{base_url}/api/states/{entity_id}",
                headers=headers,
                timeout=self.settings.http_timeout_seconds,
            )
            response.raise_for_status()
            states[entity_id] = response.json()
        return {"home_assistant_states": states}

    async def collect_once(self) -> None:
        payload = await asyncio.to_thread(self._fetch_overview)
        row = build_home_assistant_solar_measurement_row(payload["home_assistant_states"])
        await asyncio.to_thread(self.database.insert_solar_measurement, row)
        await asyncio.to_thread(self.database.mark_success, SOLAREDGE_COLLECTOR)
        LOGGER.info(
            "Stored Home Assistant SolarEdge measurement: current_power_w=%s daily_energy_wh=%s",
            row["current_power_w"],
            row["daily_energy_wh"],
        )
