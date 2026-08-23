# Shanghai Synthetic Mobility Simulator

Deterministic, event-based mobility simulation for the supplied 10,000-person synthetic population. It implements Phases A–G in `CODEX_TASK.md` without changing the population generator or behavior formulas.

The geographic and route providers are deterministic in-memory mocks around Shanghai. Their interfaces can be replaced by OSM/OSRM adapters. No per-minute GPS records are persisted.

## Run

The CLI core requires Python 3.11+ with no third-party runtime dependencies. The API dependencies are listed in `requirements.txt`.

```bash
python -m unittest discover -s tests -v
python -m simulator.cli generate --population data/shanghai_synthetic_population_10000.csv --start 2026-08-24 --days 7
python -m simulator.cli world --time 2026-08-24T18:30:00 --compact
python -m simulator.cli benchmark --time 2026-08-24T18:30:00
```

## FastAPI service and Admin

Install the API dependencies and start one process:

```bash
pip install -r requirements.txt
set ADMIN_API_KEY=replace-with-a-long-random-secret
uvicorn simulator.api:app --host 0.0.0.0 --port 8000 --workers 1
```

Public API:

- `GET /health`
- `GET /api/v1/simulation`
- `GET /api/v1/world?compact=true`
- `GET /api/v1/world?bbox=121.30,31.10,121.70,31.40`
- `GET /api/v1/people/P00001/location`

Open `/admin` and use HTTP Basic username `admin` with `ADMIN_API_KEY` as the password. The page separately asks for the same key so JavaScript can call protected Admin endpoints. Admin supports clock control, speed/seek, behavior configuration, regeneration, and temporary person interactions.

Important environment variables:

- `ADMIN_API_KEY`: required in production, minimum 16 characters
- `PUBLIC_API_KEY`: optional; clients send it as `X-API-Key`
- `STATE_PATH`: persistent JSON state; `/data/simulator-state.json` in Railway
- `SIMULATION_START`: initial synthetic timestamp
- `SCHEDULE_DAYS`: generated horizon, default `7`
- `CORS_ORIGINS`: comma-separated allowed App origins

## Railway

Deploy the repository using its `Dockerfile`. In Railway:

1. Set `ADMIN_API_KEY` and optionally `PUBLIC_API_KEY`.
2. Attach a persistent Volume mounted at `/data`.
3. Generate a public domain in the service Networking settings.
4. Keep exactly one replica/worker until shared Redis/PostgreSQL state is implemented.

The service regenerates deterministic schedules after restart and stores only clock, behavior, interaction, and version state in the Volume.

Add `--output events.jsonl` to `generate` to persist event metadata. Without it, the command only reports counts and timing.

## Architecture

- `models`: typed people, places, events, routes, and behavior templates
- `population`: CSV normalization and loading
- `places`: fixed/dynamic place resolver and in-memory provider
- `behavior`: template-backed deterministic schedule generation
- `routes`: cached replaceable route provider
- `world`: arbitrary-time interpolation and batched world state
- `cli`: generation, world query, and benchmark commands

Random streams derive from person ID, date, event type, and base seed, so repeated runs are stable while different dates vary.

## Reference benchmark

Measured in the Codex bundled Python runtime on 2026-08-23:

- 10,000 people × 7 days: 411,547 events in 16.49 seconds
- `get_world()` for 10,000 people: 0.0495 seconds (about 202,000 locations/second)

These figures are environment-specific; run the benchmark command above on the deployment host for a comparable result.
