from __future__ import annotations

import asyncio
import html
import json
import logging
from datetime import UTC, datetime
from typing import Any

from homemeterhub.runtime_state import RuntimeState

LOGGER = logging.getLogger(__name__)


def _json_response(status_code: int, payload: dict[str, object]) -> bytes:
    body = json.dumps(payload, indent=2).encode("utf-8")
    headers = [
        f"HTTP/1.1 {status_code} OK",
        "Content-Type: application/json; charset=utf-8",
        f"Content-Length: {len(body)}",
        "Connection: close",
        "",
        "",
    ]
    return "\r\n".join(headers).encode("utf-8") + body


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
      <div class=\"value\">{snapshot['event_count']}</div>
    </section>
  """


def _render_html(snapshot: dict[str, object]) -> str:
    pretty_json = html.escape(json.dumps(snapshot, indent=2))
    generated_at = datetime.now(tz=UTC).isoformat()
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
    </style>
  </head>
  <body>
    <main>
      <h1>HomeMeterHub Status</h1>
      <div class=\"meta\">Generated at {html.escape(generated_at)}. Refreshes every 5 seconds.</div>
      <div class=\"grid\">
        {p1_card}
        {water_card}
      </div>
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
    def __init__(self, host: str, port: int, runtime_state: RuntimeState) -> None:
        self.host = host
        self.port = port
        self.runtime_state = runtime_state

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
            path = parts[1] if len(parts) >= 2 else "/"
            snapshot = self.runtime_state.snapshot()

            if path in {"/status.json", "/healthz"}:
                response = _json_response(200, snapshot)
            elif path == "/":
                response = _html_response(200, _render_html(snapshot))
            else:
                response = _json_response(404, {"error": "not found", "path": path})

            writer.write(response)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
