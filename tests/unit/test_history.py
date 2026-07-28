from __future__ import annotations

from datetime import UTC, datetime, timedelta

from homemeterhub.db import Database, effective_history_interval


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


def test_history_sql_does_not_contain_lint_comments() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.query = ""

        def execute(self, query: str, params: tuple[object, ...]) -> None:
            self.query = query

        def fetchall(self) -> list[tuple[object, object]]:
            return []

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class Connection:
        def __init__(self) -> None:
            self.cursor_instance = Cursor()

        def cursor(self) -> Cursor:
            return self.cursor_instance

    class TestDatabase(Database):
        def __init__(self) -> None:
            self.connection = Connection()

        def connect(self):  # type: ignore[no-untyped-def]
            connection = self.connection

            class Context:
                def __enter__(self) -> Connection:
                    return connection

                def __exit__(self, *args: object) -> None:
                    return None

            return Context()

    end = datetime.now(tz=UTC)
    database = TestDatabase()
    database.history("gas_m3", end - timedelta(days=1), end, "hour", "last")

    assert "noqa" not in database.connection.cursor_instance.query.lower()
