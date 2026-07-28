# HomeMeterHub

HomeMeterHub is a Dockerized Python service that polls a YouLess LS120 P1 meter and listens to an ESPHome-based S0Tool water meter, then stores normalized and raw readings in PostgreSQL.

## What is implemented

- environment-based configuration with fail-fast validation;
- PostgreSQL schema initialization for the required tables and indexes;
- YouLess `/e`, `/f`, and periodic `/d` collection;
- ESPHome state subscription with reconnect handling for water data;
- collector health tracking in `collector_health`;
- versioned, idempotent database migrations and duplicate P1 timestamp protection;
- stale-reading health checks and Prometheus-compatible runtime metrics;
- input-quality validation for implausible cumulative, voltage, flow, and Wi-Fi values;
- optional daily retention cleanup of old `p1_measurements`/`water_measurements` rows (`ENABLE_RETENTION_CLEANUP`);
- built-in status page and JSON endpoint for runtime visibility;
- unit, regression, and PostgreSQL integration tests;
- Docker build files and GitHub Actions workflows for CI and GHCR publishing;
- Portainer stack files under the workspace `docker/stacks/homebrew` folder (deployed alongside other services in that stack).

## Repository layout

```text
homemeterhub/
├── .github/workflows/
├── src/homemeterhub/
├── tests/
├── Dockerfile
├── docker-compose.example.yml
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── README.md
└── SPEC.md
```

## Local development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest
python -m homemeterhub.app --validate-config
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
pytest
python -m homemeterhub.app --validate-config
```

## Runtime configuration

The application reads all settings from environment variables. The most important variables are:

- `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE` to tune the shared PostgreSQL connection pool (defaults: `1`/`5`)
- `P1_BASE_URL`
- `S0TOOL_HOST`
- `S0TOOL_NOISE_PSK` when the ESPHome API is encrypted
- `APP_STATUS_ENABLED`, `APP_STATUS_HOST`, `APP_STATUS_PORT` for the built-in status page
- `APP_HEALTH_STARTUP_GRACE_SECONDS`, `APP_HEALTH_P1_MAX_AGE_SECONDS`, and
  `APP_HEALTH_WATER_MAX_AGE_SECONDS` for liveness thresholds

Use [docker-compose.example.yml](docker-compose.example.yml) as a starting point, and see the `homemeterhub` service definition in [../docker/stacks/homebrew/docker-compose.yml](../docker/stacks/homebrew/docker-compose.yml) for the actual deployment.

## GitHub setup

1. Create a private GitHub repository named `homemeterhub`.
2. Add this folder as the repository root.
3. Push the initial commit to `main`.
4. Enable GitHub Actions for the repository.
5. Keep the repository private if the GHCR package should stay private.

No custom registry secret is required for publishing to GHCR from Actions because the workflows use `GITHUB_TOKEN` with `packages: write` permission.

## Publishing to GHCR

Push to `main` after CI passes. The publish workflow will push:

- `ghcr.io/<owner>/homemeterhub:latest`
- `ghcr.io/<owner>/homemeterhub:sha-<commit>`
- tag-based images when you push `v*.*.*`

## Portainer deployment

The stack file is [../docker/stacks/homebrew/docker-compose.yml](../docker/stacks/homebrew/docker-compose.yml).

Recommended deployment flow:

1. Log in to `ghcr.io` on the Docker server with a token that can read packages.
2. Copy the stack `docker-compose.yml` and `.env` values into Portainer.
3. Ensure the Docker server can reach the PostgreSQL host, YouLess IP, and S0Tool IP.
4. Deploy the stack.
5. Check container logs and validate that rows appear in `p1_measurements`, `water_measurements`, and `collector_health`.

## Runtime visibility

When the status server is enabled, HomeMeterHub serves:

- `/` for a lightweight HTML status page
- `/status.json` for the raw runtime snapshot
- `/healthz` for a simple JSON health response
- `/metrics` for Prometheus-compatible collector counters and connection gauges
- `/api/history` for aggregated meter history (`metric`, `from`, `to`, `interval`, `aggregation`)
- `/api/history/drilldown` for the underlying readings in a selected time bucket

By default the server listens on `0.0.0.0:8080` inside the container.

The image includes a Docker health check against `/healthz`. After the startup grace period, it
returns HTTP 503 when an enabled collector has not produced a reading within its configured age
limit. Keep `APP_STATUS_ENABLED=true` in a container deployment; disabling the status server also
makes Docker report the container as unhealthy.

The status page includes a history explorer for electricity, gas, water totals, water flow, and
instantaneous power. Choose a time range, grouping, and aggregation; select a chart point to reveal
the source readings in that bucket. History requests are bounded by `APP_HISTORY_MAX_DAYS` (default:
365) and return at most 2,000 chart points.

## Security

The deployed stack reads `DB_PASSWORD` from its deployment environment and binds the status port to
localhost. Use a reverse proxy or an explicit trusted-network binding if remote status access is
required. The container runs as an unprivileged user.

Take a PostgreSQL backup before deploying a new version. Migration 2 removes historical P1 rows with the same
`youless_tm`, retaining the earliest row, before enforcing that timestamp as unique.

## Specification

[SPEC.md](SPEC.md) contains the implementation-oriented summary. The original planning document remains at the workspace root in `HomeMeterHub.md`.
