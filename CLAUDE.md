# CLAUDE.md

Notes for future Claude sessions working in this repo. Concise on purpose —
expand only when a fact is non-obvious or repeatedly useful.

## Build & release

The app is shipped as a multi-arch (amd64/arm64) Docker image,
`egeback/ha-tn-reporter` on Docker Hub, built by GitHub Actions
([release.yml](.github/workflows/release.yml)). Deployment happens elsewhere:
the image tag is pinned in a separate compose repo that Renovate bumps.

Release flow:

1. Bump `__version__` in [src/reporter/__init__.py](src/reporter/__init__.py).
2. Merge to `main` ([test.yml](.github/workflows/test.yml) runs the tests).
3. Publish a GitHub release tagged `vX.Y.Z` (same version). The workflow
   checks the tag against `__version__`, runs the tests and pushes
   `:X.Y.Z` + `:latest`. Needs the repo secret `DOCKERHUB_TOKEN`.

`./build.sh` still works for local builds (`SKIP_TESTS=1` skips tests,
`PUSH_IMAGE=1` pushes, but releases should go through Actions).

## Tests

`python -m pytest tests/` — 31 tests, all should pass. `build.sh` runs this
automatically unless `SKIP_TESTS=1`. Tests use `respx` to mock HA and TN HTTP
calls; no live network needed.

## Production config (what the running container uses)

Configured via env vars (`REPORTER_*`). Key choices in production:

- `REPORTER_INTERVAL=60` — one cycle per minute.
- `REPORTER_MAX_AGE=1800` — sensors stale after 30 min get dropped.
- `REPORTER_CALCULATION_MODE=min` — picks the coldest sensor in the group.
  Rationale: "shade temperature guarantee" — among multiple outdoor sensors,
  the coldest is most likely in shade (sun-exposed sensors read too warm).
  **Do not switch this to median/mean to "stabilize" the output** — that
  would defeat the whole point. Stability comes from the filters below, not
  from changing the aggregation.
- `REPORTER_OUTLIER_THRESHOLD_HIGH=15` and `REPORTER_OUTLIER_THRESHOLD_LOW=25`
  (°C from group median) + `REPORTER_TEMP_MIN/MAX` (sanity range, default
  −50…+60 °C). Added in 1.4.9–1.4.10 so a single stuck/broken sensor can no
  longer dominate `min`. Both filters run BEFORE aggregation, so the
  shade-temperature guarantee is preserved. Skipped when fewer than 3 valid
  sensors remain (median isn't robust at small N).
- **The outlier thresholds are intentionally asymmetric.** Upper is tight
  (15 °C) to catch sensors stuck at warm values; lower is generous (25 °C)
  so that a real shade sensor — which reads well below a mostly-sunny
  group — survives the filter. If both thresholds were symmetric 15 °C, a
  scenario like "5 sensors in sun at 35 °C, 1 in shade at 18 °C" would drop
  the shade sensor (17 °C below median) and `min()` would then report the
  sun reading — defeating the whole point of min-mode. Don't symmetrize
  these without thinking through that case.
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
  to `state.json` (mount `/app/data` to keep it).
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

- The compose file is **not** in this repo (`compose.yaml` is gitignored;
  see `compose.example.yaml`). Updating the running version means bumping
  the pin in the deployment repo, not here.
- `LOG_LEVEL` is set via env in the deployment, not in code. Don't change
  defaults in the Dockerfile to chase a logging question — check the
  container's env first.
