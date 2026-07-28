# ruff: noqa: E501
from __future__ import annotations

import asyncio
import html
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from homemeterhub.config import AppSettings
from homemeterhub.db import HISTORY_AGGREGATIONS, HISTORY_INTERVALS, HISTORY_METRICS, Database
from homemeterhub.runtime_state import RuntimeState

LOGGER = logging.getLogger(__name__)


def _json_response(status_code: int, payload: object) -> bytes:
    body = json.dumps(payload, indent=2).encode("utf-8")
    headers = [
        f"HTTP/1.1 {status_code} {'OK' if status_code < 400 else 'Service Unavailable'}",
        "Content-Type: application/json; charset=utf-8",
        f"Content-Length: {len(body)}",
        "Connection: close",
        "",
        "",
    ]
    return "\r\n".join(headers).encode("utf-8") + body


def _text_response(status_code: int, body: str) -> bytes:
    payload = body.encode("utf-8")
    headers = [
        f"HTTP/1.1 {status_code} OK",
        "Content-Type: text/plain; version=0.0.4; charset=utf-8",
        f"Content-Length: {len(payload)}",
        "Connection: close",
        "",
        "",
    ]
    return "\r\n".join(headers).encode("utf-8") + payload


def health_payload(
    snapshot: dict[str, object], settings: AppSettings
) -> tuple[int, dict[str, object]]:
    started_at = datetime.fromisoformat(str(snapshot["started_at"]))
    age = (datetime.now(tz=UTC) - started_at).total_seconds()
    if age < settings.health_startup_grace_seconds:
        return 200, {
            "status": "starting",
            "grace_remaining_seconds": int(settings.health_startup_grace_seconds - age),
        }

    checks: dict[str, str] = {}
    limits = {
        "p1": (settings.enable_p1_collector, settings.health_p1_max_age_seconds),
        "water": (settings.enable_water_collector, settings.health_water_max_age_seconds),
    }
    collectors = snapshot["collectors"]
    now = datetime.now(tz=UTC)
    for name, (enabled, max_age) in limits.items():
        if not enabled:
            continue
        last_event_at = collectors[name]["last_event_at"]
        if last_event_at is None:
            checks[name] = "no readings received"
            continue
        reading_age = (now - datetime.fromisoformat(last_event_at)).total_seconds()
        if reading_age > max_age:
            checks[name] = f"stale for {int(reading_age)}s (limit {max_age}s)"
    if checks:
        return 503, {"status": "unhealthy", "checks": checks}
    return 200, {"status": "healthy"}


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def history_request(
    query: dict[str, list[str]], settings: AppSettings
) -> tuple[str, datetime, datetime, str, str]:
    now = datetime.now(tz=UTC)
    metric = query.get("metric", ["electricity_net_kwh"])[0]
    interval = query.get("interval", ["hour"])[0]
    aggregation = query.get("aggregation", ["last"])[0]
    start = _parse_datetime(query["from"][0]) if "from" in query else now - timedelta(days=1)
    end = _parse_datetime(query["to"][0]) if "to" in query else now
    if metric not in HISTORY_METRICS:
        raise ValueError(f"Unsupported metric: {metric}")
    if interval not in HISTORY_INTERVALS:
        raise ValueError(f"Unsupported interval: {interval}")
    if aggregation not in HISTORY_AGGREGATIONS:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
    if start >= end:
        raise ValueError("'from' must be earlier than 'to'")
    if end - start > timedelta(days=settings.history_max_days):
        raise ValueError(f"History range exceeds APP_HISTORY_MAX_DAYS ({settings.history_max_days})")
    return metric, start, end, interval, aggregation


def _html_response(status_code: int, body: str) -> bytes:
    payload = body.encode("utf-8")
    headers = [
        f"HTTP/1.1 {status_code} OK",
        "Content-Type: text/html; charset=utf-8",
        f"Content-Length: {len(payload)}",
        "Connection: close",
        "",
        "",
    ]
    return "\r\n".join(headers).encode("utf-8") + payload


def _collector_card(title: str, snapshot: dict[str, Any]) -> str:
    connected = bool(snapshot["connected"])
    status_class = "connected" if connected else "disconnected"
    status_text = "Connected" if connected else "Disconnected"
    return f"""
    <section class=\"card\">
      <div class=\"label\">{html.escape(title)}</div>
      <div class=\"value {status_class}\">{status_text}</div>
      <div class=\"label\">Events stored</div>
      <div class=\"value\">{snapshot["event_count"]}</div>
    </section>
  """


def _history_dashboard() -> str:
    return """
      <section class="card history">
        <div class="history-head">
          <div><div class="label">History explorer</div><div id="history-summary" class="value">Loading trend…</div></div>
          <div class="controls" aria-label="History controls">
            <label>Metric <select id="history-metric"><option value="electricity_net_kwh">Electricity net</option><option value="power_w">Power</option><option value="gas_m3">Gas</option><option value="watermeter_total_m3">Water total</option><option value="watermeter_flow_l_min">Water flow</option></select></label>
            <label>Range <select id="history-range"><option value="1">24 hours</option><option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option><option value="365">1 year</option></select></label>
            <label>Group <select id="history-interval"><option value="raw">Raw</option><option value="minute">Minute</option><option value="hour" selected>Hour</option><option value="day">Day</option></select></label>
            <label>Aggregate <select id="history-aggregation"><option value="last" selected>Last</option><option value="avg">Average</option><option value="min">Minimum</option><option value="max">Maximum</option><option value="delta">Change</option></select></label>
            <button id="history-refresh" type="button">Refresh</button>
          </div>
        </div>
        <div id="history-error" class="error" role="alert"></div>
        <svg id="history-chart" class="history-chart" viewBox="0 0 900 320" role="img" aria-labelledby="chart-title chart-desc"><title id="chart-title">Meter history</title><desc id="chart-desc">Choose controls to display an aggregated meter trend. Select a point to inspect source readings.</desc><g id="history-plot"></g></svg>
        <div id="history-selection" class="selection">Select a point on the chart to inspect its source readings.</div>
        <div class="table-wrap"><table><thead><tr><th>Timestamp</th><th id="history-value-heading">Value</th></tr></thead><tbody id="history-rows"></tbody></table></div>
      </section>
      <script>
      (() => {
        const $ = id => document.getElementById(id);
        const controls = ['history-metric','history-range','history-interval','history-aggregation'].map($);
        const svg = $('history-chart'), plot = $('history-plot'), summary = $('history-summary');
        let points = [], unit = '', interval = 'hour';
        const iso = date => date.toISOString();
        const range = () => { const end = new Date(), start = new Date(end); start.setDate(start.getDate() - Number($('history-range').value)); return [start,end]; };
        const endpoint = (path, args) => path + '?' + new URLSearchParams(args);
        const escape = value => String(value).replace(/[&<>]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[char]));
        function draw(data) {
          points = data.points; unit = data.unit; interval = data.interval;
          plot.replaceChildren();
          if (!points.length) { summary.textContent = 'No readings in this range'; return; }
          const values = points.map(p => p.value), min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
          const left=58, right=878, top=20, bottom=270, width=right-left, height=bottom-top;
          const line = document.createElementNS('http://www.w3.org/2000/svg','path');
          line.setAttribute('class','trend');
          line.setAttribute('d', points.map((p,i) => `${i?'L':'M'}${left+(i/(Math.max(points.length-1,1))*width)} ${bottom-((p.value-min)/span*height)}`).join(' ')); plot.append(line);
          [[max,top],[min,bottom]].forEach(([value,y]) => { const text=document.createElementNS('http://www.w3.org/2000/svg','text'); text.setAttribute('x','4'); text.setAttribute('y',String(y+4)); text.textContent=`${value.toFixed(2)} ${unit}`; plot.append(text); const grid=document.createElementNS('http://www.w3.org/2000/svg','line'); grid.setAttribute('x1',String(left));grid.setAttribute('x2',String(right));grid.setAttribute('y1',String(y));grid.setAttribute('y2',String(y));grid.setAttribute('class','grid');plot.append(grid); });
          points.forEach((p,i) => { const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');dot.setAttribute('cx',String(left+(i/(Math.max(points.length-1,1))*width)));dot.setAttribute('cy',String(bottom-((p.value-min)/span*height)));dot.setAttribute('r','5');dot.setAttribute('class','dot');dot.setAttribute('tabindex','0');dot.setAttribute('role','button');dot.setAttribute('aria-label',`${new Date(p.at).toLocaleString()}: ${p.value} ${unit}`);dot.addEventListener('click',()=>drill(p));dot.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();drill(p)}});plot.append(dot); });
          summary.textContent = `${points.length} points · ${data.aggregation} ${data.metric.replaceAll('_',' ')} (${unit})`;
        }
        function endOfBucket(at) { const date = new Date(at); if(interval==='day') date.setUTCDate(date.getUTCDate()+1); else if(interval==='hour') date.setUTCHours(date.getUTCHours()+1); else date.setUTCMinutes(date.getUTCMinutes()+(interval==='minute'?1:5)); return date; }
        async function drill(point) { const start=new Date(point.at), end=endOfBucket(point.at); $('history-selection').textContent=`${start.toLocaleString()} · ${point.value} ${unit}`; const args={metric:$('history-metric').value,from:iso(start),to:iso(end)}; const response=await fetch(endpoint('/api/history/drilldown',args)); const data=await response.json(); $('history-value-heading').textContent=`Value (${data.unit||unit})`; $('history-rows').innerHTML=(data.rows||[]).map(row=>`<tr><td>${escape(new Date(row.at).toLocaleString())}</td><td>${escape(row.value)}</td></tr>`).join('') || '<tr><td colspan="2">No source rows</td></tr>'; }
        async function load() { $('history-error').textContent=''; const [start,end]=range(); const args={metric:$('history-metric').value,from:iso(start),to:iso(end),interval:$('history-interval').value,aggregation:$('history-aggregation').value}; try { const response=await fetch(endpoint('/api/history',args)); const data=await response.json(); if(!response.ok) throw new Error(data.error||'Unable to load history'); draw(data); $('history-rows').innerHTML=''; $('history-selection').textContent='Select a point on the chart to inspect its source readings.'; } catch(error) { $('history-error').textContent=error.message; summary.textContent='History unavailable'; plot.replaceChildren(); } }
        controls.forEach(control=>control.addEventListener('change',load)); $('history-refresh').addEventListener('click',load); load();
      })();
      </script>
    """


def _render_html(snapshot: dict[str, object]) -> str:
    pretty_json = html.escape(json.dumps(snapshot, indent=2))
    generated_at = datetime.now(tz=UTC).isoformat()
    application = snapshot["application"]
    version_text = " · ".join(
        (
            f"Version {html.escape(application['version'])}",
            f"revision {html.escape(application['revision'])}",
            f"generated at {html.escape(generated_at)}",
        )
    )
    collectors = snapshot["collectors"]
    p1_card = _collector_card("P1 collector", collectors["p1"])
    water_card = _collector_card("Water collector", collectors["water"])
    return f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
    <meta http-equiv=\"refresh\" content=\"5\">
    <title>HomeMeterHub Status</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f4efe8;
        --panel: #fffaf2;
        --ink: #1d2a33;
        --accent: #1d6b57;
        --muted: #6b7280;
        --border: #d9cbb8;
      }}
      body {{
        margin: 0;
        font-family: Georgia, "Times New Roman", serif;
        background: radial-gradient(circle at top, #fffaf2, var(--bg));
        color: var(--ink);
      }}
      main {{
        max-width: 960px;
        margin: 0 auto;
        padding: 24px;
      }}
      h1 {{
        margin-bottom: 8px;
      }}
      .meta {{
        color: var(--muted);
        margin-bottom: 20px;
      }}
      .grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
        gap: 16px;
        margin-bottom: 16px;
      }}
      .card {{
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 12px 30px rgba(29, 42, 51, 0.08);
      }}
      .label {{
        color: var(--muted);
        font-size: 0.9rem;
        margin-bottom: 6px;
      }}
      .value {{
        font-size: 1.1rem;
      }}
      .connected {{ color: var(--accent); }}
      .disconnected {{ color: #a33a2b; }}
      pre {{
        background: #1d2a33;
        color: #edf6f4;
        border-radius: 16px;
        padding: 16px;
        overflow: auto;
      }}
      a {{ color: var(--accent); }}
      .history {{ margin-top: 16px; }}
      .history-head {{ display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }}
      .controls {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: end; }}
      .controls label {{ display: grid; gap: 3px; color: var(--muted); font-size: .82rem; }}
      .controls select, .controls button {{ padding: 7px; border: 1px solid var(--border); border-radius: 7px; background: var(--panel); color: var(--ink); }}
      .controls button {{ cursor: pointer; background: var(--accent); color: white; }}
      .history-chart {{ width: 100%; height: auto; margin-top: 18px; border-bottom: 1px solid var(--border); }}
      .history-chart text {{ fill: var(--muted); font-size: 13px; }}
      .grid {{ stroke: var(--border); stroke-width: 1; }}
      .trend {{ fill: none; stroke: var(--accent); stroke-width: 3; stroke-linejoin: round; stroke-linecap: round; }}
      .dot {{ fill: var(--accent); cursor: pointer; }}
      .dot:focus {{ stroke: var(--ink); stroke-width: 3; outline: none; }}
      .selection {{ margin-top: 12px; color: var(--muted); }}
      .table-wrap {{ overflow-x: auto; margin-top: 10px; }}
      table {{ width: 100%; border-collapse: collapse; text-align: left; }}
      th, td {{ padding: 8px; border-bottom: 1px solid var(--border); }}
      .error {{ color: #a33a2b; min-height: 1.2em; margin-top: 8px; }}
    </style>
  </head>
  <body>
    <main>
      <h1>HomeMeterHub Status</h1>
      <div class=\"meta\">{version_text}. Refreshes every 5 seconds.</div>
      <div class=\"grid\">
        {p1_card}
        {water_card}
      </div>
      {_history_dashboard()}
      <section class=\"card\">
        <div class=\"label\">Raw runtime snapshot</div>
        <pre>{pretty_json}</pre>
        <a href=\"/status.json\">status.json</a>
      </section>
    </main>
  </body>
</html>
"""


class StatusServer:
    def __init__(
        self,
        host: str,
        port: int,
        runtime_state: RuntimeState,
        settings: AppSettings,
        database: Database,
    ) -> None:
        self.host = host
        self.port = port
        self.runtime_state = runtime_state
        self.settings = settings
        self.database = database

    async def run(self) -> None:
        server = await asyncio.start_server(self._handle_client, self.host, self.port)
        LOGGER.info("Status server listening on %s:%s", self.host, self.port)
        async with server:
            await server.serve_forever()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                return
            parts = request_line.decode("utf-8", errors="replace").strip().split()
            target = parts[1] if len(parts) >= 2 else "/"
            parsed_target = urlsplit(target)
            path = parsed_target.path
            snapshot = self.runtime_state.snapshot()

            try:
                if path == "/status.json":
                    response = _json_response(200, snapshot)
                elif path == "/healthz":
                    status_code, payload = health_payload(snapshot, self.settings)
                    response = _json_response(status_code, payload)
                elif path == "/metrics":
                    response = _text_response(200, self.runtime_state.prometheus_metrics())
                elif path in {"/api/history", "/api/history/drilldown"}:
                    metric, start, end, interval, aggregation = history_request(
                        parse_qs(parsed_target.query), self.settings
                    )
                    if path == "/api/history":
                        payload = await asyncio.to_thread(
                            self.database.history, metric, start, end, interval, aggregation
                        )
                    else:
                        payload = await asyncio.to_thread(
                            self.database.history_drilldown, metric, start, end
                        )
                    response = _json_response(200, payload)
                elif path == "/":
                    response = _html_response(200, _render_html(snapshot))
                else:
                    response = _json_response(404, {"error": "not found", "path": path})
            except ValueError as error:
                response = _json_response(400, {"error": str(error)})
            except Exception:  # noqa: BLE001
                LOGGER.exception("History request failed")
                response = _json_response(500, {"error": "history query failed"})

            writer.write(response)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
