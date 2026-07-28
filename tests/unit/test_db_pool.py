from __future__ import annotations

import pytest

from homemeterhub.config import DatabaseSettings
from homemeterhub.db import Database


class _FakeConnection:
    autocommit = False


class _FakePool:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.connection = _FakeConnection()
        self.put_calls: list[tuple[_FakeConnection, bool]] = []
        self.closed = False

    def getconn(self) -> _FakeConnection:
        return self.connection

    def putconn(self, connection: _FakeConnection, close: bool = False) -> None:
        self.put_calls.append((connection, close))

    def closeall(self) -> None:
        self.closed = True


def _settings() -> DatabaseSettings:
    return DatabaseSettings(
        DB_HOST="postgres",
        DB_NAME="energy",
        DB_USER="energy_user",
        DB_PASSWORD="secret",  # noqa: S106 - fixture-only value
    )


def test_connect_returns_healthy_connection_to_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("homemeterhub.db.psycopg2.pool.ThreadedConnectionPool", _FakePool)
    database = Database(_settings())

    with database.connect() as connection:
        assert connection.autocommit is True

    pool = database._pool
    assert isinstance(pool, _FakePool)
    assert pool.put_calls == [(pool.connection, False)]


def test_connect_discards_connection_after_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("homemeterhub.db.psycopg2.pool.ThreadedConnectionPool", _FakePool)
    database = Database(_settings())

    with pytest.raises(RuntimeError, match="database failure"):
        with database.connect():
            raise RuntimeError("database failure")

    pool = database._pool
    assert isinstance(pool, _FakePool)
    assert pool.put_calls == [(pool.connection, True)]
