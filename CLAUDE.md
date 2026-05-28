# CLAUDE.md

Notes for future Claude sessions working in this repo. Concise on purpose —
expand only when a fact is non-obvious or repeatedly useful.

## Build & deploy

The app is shipped as a Docker image to Docker Hub. Production runs on host
`carl` as the `temperature-reporter` container. Deployment is handled by
**dockhand** (auto-deploys when the compose repo is pushed). See memory for
the dockhand infra details since they span repos.

Release flow:

1. Bump `__version__` in [src/reporter/__init__.py](src/reporter/__init__.py).
2. Commit code changes (the `build.sh` runs the test suite before building).
3. Push image: `PUSH_IMAGE=1 ./build.sh` (tags `:VERSION` + `:latest`,
   multi-arch amd64/arm64). Requires `docker login docker.io` for the
   `egeback` namespace.
4. Update the pin in the separate `docker-infrastructure` gitea repo
   (`carl/ha-to-tn-reporter/compose.yaml` → `image: ...:NEW_VERSION`).
5. Push that repo to gitea — dockhand picks it up automatically.
6. Verify on Carl: `ssh carl "docker inspect temperature-reporter --format '{{.Config.Image}}'"`.

Skip `PUSH_IMAGE` for a local-only test build. Skip tests with `SKIP_TESTS=1`.

## Tests

`python -m pytest tests/` — 25 tests, all should pass. `build.sh` runs this
automatically unless `SKIP_TESTS=1`. Tests use `respx` to mock HA and TN HTTP
calls; no live network needed.

## Production config (what the running container uses)

Configured via env vars (`REPORTER_*`). Key choices in production:

- `REPORTER_INTERVAL=60` — one cycle per minute.
- `REPORTER_MAX_AGE=1800` — sensors stale after 30 min get dropped.
- `REPORTER_CALCULATION_MODE=min` — picks the coldest sensor in the group.
  Rationale: "shade temperature guarantee" — among multiple outdoor sensors,
  the coldest is most likely in shade. Brittle to outliers, but intentional.
- `LOG_LEVEL=ERROR` in production. Set to `INFO` temporarily to see the new
  per-cycle `Station 'X': reporting Y°C (mode=min, winner=...)` line that
  exposes which underlying HA sensor dominates over the day.

## Known transient errors in logs (don't chase these)

- **HA 502 → 503 → 404 cascade** typically around 04:30–07:00 — Home
  Assistant's own restart/backup window. Retries inside `sensor.py` smooth
  brief blips but not the full ~3 min outage.
- **TN error ~02:14 nightly** — temperatur.nu's maintenance window. The
  retry logic in `tn_client.py` (3 attempts, 2s + 5s backoff) handles most.
- **MQTT "Connection reset by peer"** — broker side, recoverable; the run
  loop reconnects automatically.

## Architecture sketch

- [main.py](src/reporter/main.py) — async producer loop. Fetches HA, calls
  `report_to_tn`, queues an update for MQTT.
- [model/sensor.py](src/reporter/model/sensor.py) — `TempSensor`: fetches
  N HA entities in parallel, filters stale, aggregates via `min|median|mean`.
  `_fetch_one` retries 5xx/timeouts once.
- [tn_client.py](src/reporter/tn_client.py) — single GET to temperatur.nu
  with retry on transient failures. Empty `str(e)` is logged as the
  exception type name.
- [mqtt.py](src/reporter/mqtt.py) — producer/consumer with `PriorityQueue`,
  publishes Home Assistant MQTT Discovery for all entities. Sequence number
  `_seq` is a tiebreaker so dicts never get compared.
- [state.py](src/reporter/state.py) — global `health_status` dict, persisted
  to `state.json` (mounted from host on Carl).
- [web.py](src/reporter/web.py) — `/health` endpoint for the container
  healthcheck.

## HA integration

MQTT Discovery is the only integration path. The reporter publishes a
device with these entities per configured station:

- `sensor.<station>_temperature` (with `raw_values` / `sensor_map` as JSON
  attributes — every HA-side sensor that was evaluated this cycle).
- `sensor.<station>_winning_sensor` — which underlying HA sensor won.
- `sensor.<station>_last_updated` — timestamp of that reading.
- A "status" diagnostic sensor plus 10 stats (uptime, lifetime success/
  errors, etc.).
- Bridge availability via LWT on `<base_topic>/bridge/state`.

Examples for HA visualization & alerts live in [examples/](examples/).

## Gotchas

- The git remote in this repo is named `master`, not `origin`.
  (`git remote -v` to confirm.)
- The compose file is **not** in this repo — it lives in a separate gitea
  repo. Updating image tags requires a push there, not here.
- `LOG_LEVEL` is set via env on Carl, not in code. Don't change defaults in
  the Dockerfile to chase a logging question — check Carl's env first
  (`docker inspect temperature-reporter`).
