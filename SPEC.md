# HomeMeterHub Specification Summary

This repository implements the HomeMeterHub plan from the workspace specification in `HomeMeterHub.md`.

## Functional scope

- Collect YouLess LS120 P1 data from `/e` and `/f`.
- Collect periodic YouLess device metadata from `/d`.
- Listen to S0Tool water updates through the ESPHome Native API.
- Store normalized readings and optional raw payloads in PostgreSQL.
- Create missing tables and indexes without dropping existing data.
- Track collector health for database initialization, P1 collection, and water collection.

## Core runtime constraints

- The PostgreSQL database must already exist.
- All configuration is environment-based.
- P1 and water collectors can be enabled independently.
- Unknown or unrelated ESPHome keys are ignored.
- `/e` remains the authoritative write trigger for P1 measurement rows.
- `/f` failure must not block storing `/e` values.

## Required tables

- `p1_measurements`
- `p1_device_snapshots`
- `water_measurements`
- `collector_health`

## Delivery scope in this repository

- Python service under `src/homemeterhub`
- regression fixtures and tests under `tests`
- Dockerfile and compose example
- GitHub Actions workflows for CI and GHCR publishing
- Portainer-ready deployment files in `../docker/stacks/homemeterhub`
