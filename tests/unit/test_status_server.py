from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from homemeterhub.config import AppSettings
from homemeterhub.runtime_state import RuntimeState
from homemeterhub.status_server import (
    StatusServer,
    _json_response,
    _render_dashboard_html,
    _render_html,
    health_payload,
    history_request,
)


def test_render_html_contains_runtime_sections() -> None:
    snapshot = RuntimeState().snapshot()
    html = _render_html(snapshot)
    assert "HomeMeterHub Status" in html
    assert "P1 collector" in html
    assert "Water collector" in html
    assert "SolarEdge collector" in html
    assert "Version 0.2.0" in html
    assert "/status.json" in html
    assert "Open dashboard" in html


def test_dashboard_has_period_tiles_and_no_auto_refresh() -> None:
    html = _render_dashboard_html(RuntimeState().snapshot())

    assert "Net consumption" in html
    assert "High tariff" in html
    assert "Low tariff" in html
    assert "chart-electricity" in html
    assert "chart-gas" in html
    assert "chart-water" in html
    assert "http-equiv=\"refresh\"" not in html
    assert "toLocaleDateString" in html
    assert "Intl.NumberFormat('nl-NL'" in html


def test_status_card_formats_event_count_with_commas() -> None:
    snapshot = RuntimeState().snapshot()
    snapshot["collectors"]["p1"]["event_count"] = 12345

    assert "12.345" in _render_html(snapshot)


def test_health_reports_stale_enabled_collector() -> None:
    state = RuntimeState()
    snapshot = state.snapshot()
    snapshot["started_at"] = (datetime.now(tz=UTC) - timedelta(minutes=10)).isoformat()
    status, payload = health_payload(snapshot, AppSettings(APP_HEALTH_STARTUP_GRACE_SECONDS=0))

    assert status == 503
    assert payload["status"] == "unhealthy"
    assert "p1" in payload["checks"]


def test_metrics_exposes_collector_counters() -> None:
    assert "homemeterhub_collector_events_total" in RuntimeState().prometheus_metrics()


def test_json_response_converts_nan_to_null() -> None:
    body = _json_response(200, {"value": float("nan")}).split(b"\r\n\r\n", 1)[1]

    assert json.loads(body) == {"value": None}


def test_history_request_validates_the_range_and_defaults() -> None:
    metric, start, end, interval, aggregation = history_request({}, AppSettings())

    assert metric == "electricity_net_kwh"
    assert start < end
    assert interval == "hour"
    assert aggregation == "last"

    with pytest.raises(ValueError, match="Unsupported metric"):
        history_request({"metric": ["unknown"]}, AppSettings())


class _HistoryDatabase:
    def history(self, *args: object) -> dict[str, object]:
        return {"metric": args[0], "unit": "kWh", "points": []}


def test_history_api_returns_json() -> None:
    async def request() -> dict[str, object]:
        status = StatusServer("127.0.0.1", 0, RuntimeState(), AppSettings(), _HistoryDatabase())
        server = await asyncio.start_server(status._handle_client, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /api/history?metric=gas_m3 HTTP/1.1\r\nHost: test\r\n\r\n")
            await writer.drain()
            response = await reader.read()
            return json.loads(response.split(b"\r\n\r\n", 1)[1])
        finally:
            server.close()
            await server.wait_closed()

    assert asyncio.run(request())["metric"] == "gas_m3"
