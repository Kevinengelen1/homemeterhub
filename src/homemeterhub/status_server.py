# ruff: noqa: E501
from __future__ import annotations

import asyncio
import csv
import html
import io
import json
import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from homemeterhub.config import AppSettings
from homemeterhub.db import HISTORY_AGGREGATIONS, HISTORY_INTERVALS, HISTORY_METRICS, Database
from homemeterhub.runtime_state import RuntimeState

LOGGER = logging.getLogger(__name__)


def _json_safe(value: object) -> object:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _json_response(status_code: int, payload: object) -> bytes:
    body = json.dumps(_json_safe(payload), indent=2, allow_nan=False).encode("utf-8")
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


def _csv_response(filename: str, rows: list[dict[str, object]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=("at", "value"))
    writer.writeheader()
    writer.writerows(rows)
    payload = output.getvalue().encode("utf-8")
    headers = [
        "HTTP/1.1 200 OK",
        "Content-Type: text/csv; charset=utf-8",
        f'Content-Disposition: attachment; filename="{filename}"',
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


def pagination_request(query: dict[str, list[str]]) -> tuple[int, int]:
    try:
        page = int(query.get("page", ["1"])[0])
        page_size = int(query.get("page_size", ["100"])[0])
    except ValueError as error:
        raise ValueError("Pagination values must be integers") from error
    if page < 1 or not 1 <= page_size <= 500:
        raise ValueError("page must be positive and page_size must be 1-500")
    return page, page_size


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
        <div class="drill-controls"><button id="history-previous" type="button" disabled>Previous</button><span id="history-page"></span><button id="history-next" type="button" disabled>Next</button><a id="history-export" href="#">Download selected readings as CSV</a></div>
        <div class="table-wrap"><table><thead><tr><th>Timestamp</th><th id="history-value-heading">Value</th></tr></thead><tbody id="history-rows"></tbody></table></div>
      </section>
      <script>
      (() => {
        const $ = id => document.getElementById(id);
        const controls = ['history-metric','history-range','history-interval','history-aggregation'].map($);
        const svg = $('history-chart'), plot = $('history-plot'), summary = $('history-summary');
        let points = [], unit = '', interval = 'hour', selection = null;
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
          const grouped = data.requested_interval === data.interval ? '' : ` · automatically grouped by ${data.interval}`;
          summary.textContent = `${points.length} points · ${data.aggregation} ${data.metric.replaceAll('_',' ')} (${unit})${grouped}`;
        }
        function endOfBucket(at) { const date = new Date(at); if(interval==='day') date.setUTCDate(date.getUTCDate()+1); else if(interval==='hour') date.setUTCHours(date.getUTCHours()+1); else date.setUTCMinutes(date.getUTCMinutes()+(interval==='minute'?1:5)); return date; }
        async function drill(point, page=1) { if(point) selection={point,start:new Date(point.at),end:endOfBucket(point.at)}; if(!selection)return; const {start,end}=selection; $('history-selection').textContent=`${start.toLocaleString()} · ${selection.point.value} ${unit}`; const args={metric:$('history-metric').value,from:iso(start),to:iso(end),page}; const response=await fetch(endpoint('/api/history/drilldown',args)); const data=await response.json(); if(!response.ok) throw new Error(data.error||'Unable to load source readings'); $('history-value-heading').textContent=`Value (${data.unit||unit})`; $('history-rows').innerHTML=(data.rows||[]).map(row=>`<tr><td>${escape(new Date(row.at).toLocaleString())}</td><td>${escape(row.value)}</td></tr>`).join('') || '<tr><td colspan="2">No source rows</td></tr>'; $('history-page').textContent=`Page ${data.page} · ${data.total} readings`; $('history-previous').disabled=data.page<=1; $('history-next').disabled=data.page*data.page_size>=data.total; $('history-previous').onclick=()=>drill(null,data.page-1); $('history-next').onclick=()=>drill(null,data.page+1); $('history-export').href=endpoint('/api/history/export',{metric:$('history-metric').value,from:iso(start),to:iso(end)}); }
        async function load() { $('history-error').textContent=''; const [start,end]=range(); const args={metric:$('history-metric').value,from:iso(start),to:iso(end),interval:$('history-interval').value,aggregation:$('history-aggregation').value}; try { const response=await fetch(endpoint('/api/history',args)); const data=await response.json(); if(!response.ok) throw new Error(data.error||'Unable to load history'); draw(data); $('history-rows').innerHTML=''; $('history-selection').textContent='Select a point on the chart to inspect its source readings.'; } catch(error) { $('history-error').textContent=error.message; summary.textContent='History unavailable'; plot.replaceChildren(); } }
        controls.forEach(control=>control.addEventListener('change',load)); $('history-refresh').addEventListener('click',load); load();
      })();
      </script>
    """


def _dashboard_overview() -> str:
    return """
      <section class="dashboard-toolbar" aria-labelledby="dashboard-heading">
        <div><p class="eyebrow">Consumption overview</p><h2 id="dashboard-heading">Your selected period</h2><div id="dashboard-period" class="period" aria-live="polite">Loading period…</div></div>
        <div class="period-controls"><label for="dashboard-range">Period</label><select id="dashboard-range"><option value="1">Today</option><option value="7">Last 7 days</option><option value="30" selected>Last 30 days</option><option value="90">Last 90 days</option><option value="365">Last year</option></select><button id="dashboard-refresh" type="button">Update dashboard</button></div>
      </section>
      <section class="summary-grid" aria-label="Period summary">
        <article class="summary-tile"><span>Net consumption</span><strong id="summary-net" aria-live="polite">—</strong><small>Electricity used</small></article>
        <article class="summary-tile"><span>High tariff</span><strong id="summary-high" aria-live="polite">—</strong><small>Tariff 1</small></article>
        <article class="summary-tile"><span>Low tariff</span><strong id="summary-low" aria-live="polite">—</strong><small>Tariff 2</small></article>
        <article class="summary-tile"><span>Gas</span><strong id="summary-gas" aria-live="polite">—</strong><small>Meter change</small></article>
        <article class="summary-tile"><span>Water</span><strong id="summary-water" aria-live="polite">—</strong><small>Meter change</small></article>
      </section>
      <div id="dashboard-error" class="error" role="alert"></div>
      <section class="dashboard-charts">
        <figure class="chart-panel"><figcaption><h2>Electricity</h2><p>Net consumption per selected bucket.</p></figcaption><svg id="chart-electricity" viewBox="0 0 900 250" role="img" aria-label="Electricity consumption chart"></svg></figure>
        <figure class="chart-panel"><figcaption><h2>Gas</h2><p>Gas consumption per selected bucket.</p></figcaption><svg id="chart-gas" viewBox="0 0 900 250" role="img" aria-label="Gas consumption chart"></svg></figure>
        <figure class="chart-panel"><figcaption><h2>Water</h2><p>Water consumption per selected bucket.</p></figcaption><svg id="chart-water" viewBox="0 0 900 250" role="img" aria-label="Water consumption chart"></svg></figure>
      </section>
      <section class="explorer-section" aria-labelledby="explorer-heading"><p class="eyebrow">Details</p><h2 id="explorer-heading">Explore a trend</h2><p>Choose a metric, aggregation, and grouping below. Select a point to inspect and export its source readings.</p></section>
      <script>
      (() => {
        const $ = id => document.getElementById(id);
        const metricCharts = [['chart-electricity','electricity_net_kwh'],['chart-gas','gas_m3'],['chart-water','watermeter_total_m3']];
        const format = (value, unit) => value === null || value === undefined ? '—' : `${Number(value).toFixed(3)} ${unit}`;
        const dates = () => { const end=new Date(), start=new Date(end); start.setDate(start.getDate()-Number($('dashboard-range').value)); return [start,end]; };
        const query = args => new URLSearchParams(args);
        function line(svg, points, unit) { svg.replaceChildren(); if(!points.length){svg.textContent='No readings in this period'; return;} const values=points.map(point=>point.value), min=Math.min(...values), max=Math.max(...values), span=max-min||1, left=56,right=880,top=18,bottom=210,width=right-left,height=bottom-top; const ns='http://www.w3.org/2000/svg'; for(const [value,y] of [[max,top],[min,bottom]]){const label=document.createElementNS(ns,'text');label.setAttribute('x','4');label.setAttribute('y',String(y+4));label.textContent=`${value.toFixed(2)} ${unit}`;svg.append(label);const grid=document.createElementNS(ns,'line');grid.setAttribute('x1',String(left));grid.setAttribute('x2',String(right));grid.setAttribute('y1',String(y));grid.setAttribute('y2',String(y));grid.setAttribute('class','chart-grid');svg.append(grid);} const path=document.createElementNS(ns,'path');path.setAttribute('class','dashboard-trend');path.setAttribute('d',points.map((point,index)=>`${index?'L':'M'}${left+(index/Math.max(points.length-1,1))*width} ${bottom-((point.value-min)/span)*height}`).join(' '));svg.append(path);}
        async function load() { const [start,end]=dates(), from=start.toISOString(), to=end.toISOString(), days=Number($('dashboard-range').value), interval=days<=2?'hour':days<=90?'day':'day'; $('dashboard-error').textContent=''; $('dashboard-period').textContent=`${start.toLocaleDateString()} – ${end.toLocaleDateString()}`; try { const summary=await fetch('/api/summary?'+query({from,to})).then(response=>response.json()); if(summary.error)throw new Error(summary.error); $('summary-net').textContent=format(summary.net_consumption_kwh,'kWh');$('summary-high').textContent=format(summary.high_tariff_kwh,'kWh');$('summary-low').textContent=format(summary.low_tariff_kwh,'kWh');$('summary-gas').textContent=format(summary.gas_m3,'m³');$('summary-water').textContent=format(summary.water_m3,'m³'); await Promise.all(metricCharts.map(async ([id,metric])=>{const response=await fetch('/api/history?'+query({metric,from,to,interval,aggregation:'delta'}));const data=await response.json();if(!response.ok)throw new Error(data.error||'Unable to load chart');line($(id),data.points,data.unit);})); } catch(error) { $('dashboard-error').textContent=error.message; } }
        $('dashboard-range').addEventListener('change',load); $('dashboard-refresh').addEventListener('click',load); load();
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
      .drill-controls {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 10px; }}
      .drill-controls button {{ padding: 6px 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--panel); color: var(--ink); }}
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
      <section class=\"card\"><div class=\"label\">Consumption history</div><a href=\"/dashboard\">Open the dashboard</a></section>
      <section class=\"card\">
        <div class=\"label\">Raw runtime snapshot</div>
        <pre>{pretty_json}</pre>
        <a href=\"/status.json\">status.json</a>
      </section>
    </main>
  </body>
</html>
"""


def _render_dashboard_html(snapshot: dict[str, object]) -> str:
    application = snapshot["application"]
    version_text = f"Version {html.escape(application['version'])} · revision {html.escape(application['revision'])}"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>HomeMeterHub Dashboard</title><style>
:root {{ --bg:#f4f7fb;--surface:#ffffff;--ink:#16233a;--accent:#005fcc;--accent-dark:#004a9e;--muted:#526176;--border:#c8d1df;--focus:#ffbf47; }}
* {{ box-sizing:border-box; }} body {{ margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;background:linear-gradient(180deg,#eef5ff 0,var(--bg) 340px);color:var(--ink); }} main {{ max-width:1180px;margin:0 auto;padding:32px 24px 56px; }} h1,h2,p {{ margin-top:0; }} h1 {{ font-size:clamp(1.7rem,4vw,2.35rem);margin-bottom:4px; }} h2 {{ font-size:1.15rem;margin-bottom:4px; }} p,.label,.selection,small {{ color:var(--muted); }} .top {{ display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap;margin-bottom:30px; }} a {{ color:var(--accent-dark);font-weight:600; }} button,select {{ min-height:42px;padding:9px 12px;border:1px solid var(--border);border-radius:9px;background:var(--surface);color:var(--ink);font:inherit; }} button {{ cursor:pointer;background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600; }} button:hover {{ background:var(--accent-dark); }} button:disabled {{ cursor:not-allowed;opacity:.55; }} button:focus-visible,select:focus-visible,a:focus-visible,.dot:focus-visible {{ outline:3px solid var(--focus);outline-offset:3px; }}
.eyebrow {{ margin-bottom:6px;color:var(--accent-dark);font-size:.78rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase; }} .period {{ font-size:1rem;font-weight:600; }} .dashboard-toolbar {{ display:flex;gap:18px;align-items:end;justify-content:space-between;flex-wrap:wrap;margin-bottom:20px;padding-bottom:20px;border-bottom:1px solid var(--border); }} .period-controls {{ display:flex;gap:9px;align-items:end;flex-wrap:wrap; }} .period-controls label {{ display:grid;gap:5px;color:var(--ink);font-size:.88rem;font-weight:600; }}
.summary-grid {{ display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:26px; }} .summary-tile,.chart-panel,.history {{ background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:18px;box-shadow:0 6px 18px rgba(22,35,58,.06); }} .summary-tile span {{ display:block;color:var(--muted);font-size:.86rem;font-weight:600; }} .summary-tile strong {{ display:block;font-size:clamp(1.15rem,2vw,1.5rem);margin:8px 0 5px;overflow-wrap:anywhere; }} .summary-tile small {{ font-size:.78rem; }}
.dashboard-charts {{ display:grid;gap:16px; }} .chart-panel {{ margin:0; }} .chart-panel p {{ margin-bottom:14px; }} .chart-panel svg,.history-chart {{ width:100%;height:auto;border-bottom:1px solid var(--border); }} .chart-panel text,.history-chart text {{ fill:var(--muted);font-size:13px; }} .chart-grid,.grid {{ stroke:var(--border);stroke-width:1; }} .dashboard-trend,.trend {{ fill:none;stroke:var(--accent);stroke-width:3;stroke-linejoin:round;stroke-linecap:round; }} .dot {{ fill:var(--accent);cursor:pointer; }} .error {{ color:#9d1c1c;font-weight:600;min-height:1.2em;margin:8px 0; }}
.explorer-section {{ margin:38px 0 14px; }} .history-head,.controls,.drill-controls {{ display:flex;gap:10px;flex-wrap:wrap;align-items:end;justify-content:space-between; }} .controls label {{ display:grid;gap:5px;color:var(--ink);font-size:.85rem;font-weight:600; }} .table-wrap {{ overflow-x:auto;margin-top:12px; }} table {{ width:100%;border-collapse:collapse;text-align:left; }} th,td {{ padding:10px 8px;border-bottom:1px solid var(--border); }} th {{ color:var(--muted);font-size:.82rem;text-transform:uppercase;letter-spacing:.04em; }}
@media (max-width:820px) {{ main {{ padding:24px 16px 40px; }} .summary-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .summary-tile:last-child {{ grid-column:span 2; }} .dashboard-toolbar {{ align-items:stretch; }} .period-controls {{ width:100%; }} .period-controls select {{ flex:1; }} }} @media (max-width:420px) {{ .summary-grid {{ grid-template-columns:1fr; }} .summary-tile:last-child {{ grid-column:auto; }} .period-controls button {{ width:100%; }} .chart-panel,.history,.summary-tile {{ padding:14px; }} }}
</style></head><body><main><div class="top"><div><h1>HomeMeterHub Dashboard</h1><div class="label">{version_text}</div></div><a href="/">Operational status</a></div>{_dashboard_overview()}{_history_dashboard()}</main></body></html>"""


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
                elif path == "/api/summary":
                    _, start, end, _, _ = history_request(parse_qs(parsed_target.query), self.settings)
                    payload = await asyncio.to_thread(self.database.period_summary, start, end)
                    response = _json_response(200, payload)
                elif path in {"/api/history", "/api/history/drilldown", "/api/history/export"}:
                    metric, start, end, interval, aggregation = history_request(
                        parse_qs(parsed_target.query), self.settings
                    )
                    if path == "/api/history":
                        payload = await asyncio.to_thread(
                            self.database.history, metric, start, end, interval, aggregation
                        )
                        response = _json_response(200, payload)
                    elif path == "/api/history/drilldown":
                        page, page_size = pagination_request(parse_qs(parsed_target.query))
                        payload = await asyncio.to_thread(
                            self.database.history_drilldown, metric, start, end, page, page_size
                        )
                        response = _json_response(200, payload)
                    else:
                        payload = await asyncio.to_thread(
                            self.database.history_export,
                            metric,
                            start,
                            end,
                            self.settings.history_export_max_rows,
                        )
                        response = _csv_response(f"homemeterhub-{metric}.csv", payload["rows"])
                elif path == "/":
                    response = _html_response(200, _render_html(snapshot))
                elif path == "/dashboard":
                    response = _html_response(200, _render_dashboard_html(snapshot))
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
