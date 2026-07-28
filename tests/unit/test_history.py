from __future__ import annotations

from datetime import UTC, datetime, timedelta

from homemeterhub.db import effective_history_interval


def test_long_fine_grained_history_is_automatically_downsampled() -> None:
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=365)

    assert effective_history_interval("raw", start, end) == "day"
    assert effective_history_interval("hour", start, end) == "day"


def test_short_history_preserves_requested_interval() -> None:
    end = datetime.now(tz=UTC)
    start = end - timedelta(hours=1)

    assert effective_history_interval("raw", start, end) == "minute"
    assert effective_history_interval("minute", start, end) == "minute"
