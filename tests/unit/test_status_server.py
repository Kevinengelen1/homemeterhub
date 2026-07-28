from __future__ import annotations

from homemeterhub.runtime_state import RuntimeState
from homemeterhub.status_server import _render_html


def test_render_html_contains_runtime_sections() -> None:
    snapshot = RuntimeState().snapshot()
    html = _render_html(snapshot)
    assert "HomeMeterHub Status" in html
    assert "P1 collector" in html
    assert "Water collector" in html
    assert "/status.json" in html