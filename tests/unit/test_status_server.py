from __future__ import annotations

from datetime import UTC, datetime, timedelta

from homemeterhub.config import AppSettings
from homemeterhub.runtime_state import RuntimeState
from homemeterhub.status_server import _render_html, health_payload


def test_render_html_contains_runtime_sections() -> None:
    snapshot = RuntimeState().snapshot()
    html = _render_html(snapshot)
    assert "HomeMeterHub Status" in html
    assert "P1 collector" in html
    assert "Water collector" in html
    assert "/status.json" in html


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
