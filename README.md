# HomeMeterHub

HomeMeterHub is a Dockerized Python service that polls a YouLess LS120 P1 meter and listens to an ESPHome-based S0Tool water meter, then stores normalized and raw readings in PostgreSQL.

## What is implemented

- environment-based configuration with fail-fast validation;
- PostgreSQL schema initialization for the required tables and indexes;
- YouLess `/e`, `/f`, and periodic `/d` collection;
- ESPHome state subscription with reconnect handling for water data;
- collector health tracking in `collector_health`;
- unit, regression, and PostgreSQL integration tests;
- Docker build files and GitHub Actions workflows for CI and GHCR publishing;
- Portainer stack files under the workspace `docker/stacks/homemeterhub` folder.

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
- `P1_BASE_URL`
- `S0TOOL_HOST`
- `S0TOOL_NOISE_PSK` when the ESPHome API is encrypted

Use [docker-compose.example.yml](docker-compose.example.yml) and [docker/stacks/homemeterhub/.env.example](../docker/stacks/homemeterhub/.env.example) as starting points.

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

The stack files are in [../docker/stacks/homemeterhub](../docker/stacks/homemeterhub).

Recommended deployment flow:

1. Log in to `ghcr.io` on the Docker server with a token that can read packages.
2. Copy the stack `docker-compose.yml` and `.env` values into Portainer.
3. Ensure the Docker server can reach the PostgreSQL host, YouLess IP, and S0Tool IP.
4. Deploy the stack.
5. Check container logs and validate that rows appear in `p1_measurements`, `water_measurements`, and `collector_health`.

## Specification

[SPEC.md](SPEC.md) contains the implementation-oriented summary. The original planning document remains at the workspace root in `HomeMeterHub.md`.
