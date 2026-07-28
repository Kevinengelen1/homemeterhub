# HomeMeterHub follow-up hardening plan

This plan captures the remaining findings from the code review in this session (water_collector blocking fix, retention cleanup, and README fixes are already implemented). It covers the items that still need a decision/implementation.

## 1. Reuse/pool PostgreSQL connections in `Database`

**Priority:** High

`Database.connect()` (`src/homemeterhub/db.py`) opens a brand-new `psycopg2` connection for every single call — every P1 measurement insert, every `mark_success`/`mark_error`, every water event, every retention sweep. With the default `P1_POLL_INTERVAL_SECONDS=1` and per-event water writes, this means a fresh TCP handshake + auth round trip to PostgreSQL roughly once a second (or more), adding avoidable latency and connection churn on the DB server.

Affected files:

- `src/homemeterhub/db.py`

Requirements:

- Replace ad-hoc `psycopg2.connect()`-per-call with a small connection pool (e.g. `psycopg2.pool.ThreadedConnectionPool`, sized via a new optional env var such as `DB_POOL_MIN_SIZE`/`DB_POOL_MAX_SIZE` with sane defaults like 1/5) since calls originate from multiple threads (`asyncio.to_thread` and the water collector's executor callback).
- `connect()` should keep its current `@contextmanager` interface (callers use `with self.connect() as connection`) so no call sites need to change — only the implementation swaps between pooled getconn/putconn and raw `psycopg2.connect`.
- On a connection error, the pool must not get stuck handing out a broken connection: use `pool.putconn(conn, close=True)` (or discard/recreate) when the connection raised an error, otherwise return it normally.
- Preserve existing behavior: `autocommit = True`, `connect_timeout`, `sslmode`, `application_name` settings must still apply.
- Close/dispose the pool cleanly on process shutdown if `app.py` gains a shutdown path (best-effort; not required if the process is only ever killed, matching current behavior).

Verification:

- Existing unit/regression tests must keep passing (`pytest tests/unit tests/regression`).
- Add a unit test that stubs out `psycopg2.pool` (or exercises the pool against a fake) to confirm `connect()` still yields a usable connection and that a connection marked broken is not reused.
- Manually verify against the Postgres integration test (`tests/integration/test_postgres_schema.py`) that repeated inserts still work end-to-end.

## 2. Add a Docker `HEALTHCHECK` for the `homemeterhub` container

**Priority:** Medium

The container has no `HEALTHCHECK`, so Docker/Portainer can't detect a wedged process (e.g. event loop deadlock, crashed collectors) beyond the process still being alive.

Affected files:

- `homemeterhub/Dockerfile`
- `docker/stacks/homebrew/docker-compose.yml` (only if the compose-level `healthcheck:` override is preferred instead of/in addition to the Dockerfile one)

Requirements:

- Add a `HEALTHCHECK` that calls the existing `/healthz` endpoint on `APP_STATUS_PORT` (default `8080`), e.g. using `curl -f http://127.0.0.1:8080/healthz || exit 1`. Since the base image may not have `curl`, verify what's available in the runtime image (`python:3.12-slim` or similar) — fall back to a small `python -c "import urllib.request; ..."` one-liner if `curl` isn't installed, to avoid adding a new package just for this.
- Set reasonable `--interval`, `--timeout`, `--start-period`, and `--retries` values (e.g. interval 30s, timeout 5s, start-period 15s, retries 3).
- Confirm behavior when `APP_STATUS_ENABLED=false` — the healthcheck would then always fail, so document that disabling the status server also disables container health reporting (or make the healthcheck conditional/skip in that case if practical).

Verification:

- `docker build` the image and run `docker inspect --format='{{json .State.Health}}' <container>` to confirm the healthcheck transitions to `healthy`.
- Confirm `docker compose ps` / Portainer shows a health status for the service after redeploying the stack.

## 3. Optional / lower priority

These were noted during review but are not required for correctness — pick up only if there's time:

- **Parallelize `/e` and `/f` YouLess polls** in `P1Collector.collect_once()` using `asyncio.gather` instead of two sequential `asyncio.to_thread` calls, shaving a bit of latency off each poll cycle.
- **Track retention job status in `collector_health`** the same way `p1_collector`/`water_collector` do, so the status page shows the last successful/failed cleanup run instead of only log lines.
