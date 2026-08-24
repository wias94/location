# Greater Toronto Area Synthetic Mobility Simulator

Deterministic, event-based mobility simulation for the supplied 10,000-person synthetic population.

Runtime locations and drivable routes come from the local Greater Toronto OpenStreetMap extract. No per-minute GPS records are persisted; current locations are calculated from the real-time clock and the active event.

## Run

The CLI core requires Python 3.11+ with no third-party runtime dependencies. The API dependencies are listed in `requirements.txt`.

```bash
python -m unittest discover -s tests -v
python -m simulator.cli generate --start 2026-08-24 --days 1
python -m simulator.cli world --time 2026-08-24T18:30:00 --compact
python -m simulator.cli benchmark --time 2026-08-24T18:30:00
```

The default runtime inputs are `data/gta_population_with_places.csv` and `data/places.csv`.
They bind the supplied population to real OpenStreetMap locations.

## Rebuild places from OpenStreetMap

Put the custom BBBike extract at `data/gta-mobility.osm.pbf`, then run:

```bash
python scripts/extract_pbf_places.py
python scripts/build_road_network.py
python scripts/assign_places.py
python scripts/generate_personality_profiles.py
python scripts/validate_personality_profiles.py
python scripts/validate_places.py
python scripts/generate_relationships.py
python scripts/validate_relationships.py
python scripts/generate_external_contacts.py
```

This produces `places.csv`, `person_places.csv`, and `gta_population_with_places.csv`.
Homes are restricted to Markham and Scarborough. Workplaces use occupation and
job-title rules, while children are assigned to schools in their home district.

`generate_relationships.py` then writes:

- `organizations.csv`: synthetic organizations anchored to real OSM workplaces
- `person_organizations.csv`: organization and team membership for every person
- `relationships.csv`: sparse typed edges with deterministic Chinese descriptions
- `external_contacts.csv`: lightweight relatives/partners outside the 10,000-person sample
- `person_behavior_profiles.csv`: continuous traits plus a prompt-ready Chinese personality summary

By default, exactly 30% of people have at least one sampled family relationship.
Spouses share a HOME; parents and adult children, siblings, and extended family do
not require co-residence. Coworkers share an organization, while neighbor,
housemate, and friend edges use already-assigned locations and profiles.

The runtime population also appends ten `0..1` personality traits,
`communication_style`, and a final `personality_summary` column. The same traits
adjust schedule regularity, discretionary activity weights, travel radius, and
social acceptance, so future dialogue prompts and observed mobility remain
consistent. The downloaded source population CSV remains unchanged.

The generated `road_network.pkl` contains the largest connected drivable OSM
network. Routes use local A* search and persist actual road geometry in
`work/routes.sqlite`. Schedule generation uses a cheap duration estimate, while
the service continuously prewarms routes for the next 30 simulated minutes.
Activity destinations are selected from nearby real OSM POIs; friend visits use
the selected friend's bound HOME. A post-schedule social coordinator matches free
time for both participants before creating spouse dates, friend outings, visits,
and family visits. An in-sample host receives a synchronized event. An external
contact supplies a relationship and real HOME but is never added to the real-time
population.

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
- `GET /api/v1/world?bbox=-80.15,43.35,-78.65,44.05`
- `GET /api/v1/people/P00001/location`

Open `/admin` and use HTTP Basic username `admin` with `ADMIN_API_KEY` as the password. The page separately asks for the same key so JavaScript can call protected Admin endpoints. The visual editor controls work probabilities, evening activity weights, social acceptance/cancellation rules, clock speed, regeneration, and temporary person interactions. Advanced JSON remains available for backup and bulk editing.

Important environment variables:

- `ADMIN_API_KEY`: required in production, minimum 16 characters
- `PUBLIC_API_KEY`: optional; clients send it as `X-API-Key`
- `STATE_PATH`: persistent JSON state; `/data/simulator-state.json` in Railway
- `SIMULATION_START`: initial synthetic timestamp
- `SCHEDULE_DAYS`: rolling generated horizon, default `1`
- `CORS_ORIGINS`: comma-separated allowed App origins
- `POPULATION_PATH`: optional population CSV override; defaults to `data/gta_population_with_places.csv`
- `PLACES_PATH`: optional places CSV override; defaults to `data/places.csv`
- `RELATIONSHIPS_PATH`: defaults to `data/relationships.csv`
- `EXTERNAL_CONTACTS_PATH`: defaults to `data/external_contacts.csv`
- `ROAD_NETWORK_PATH`: defaults to `data/road_network.pkl`
- `ROUTE_CACHE_PATH`: defaults to `work/routes.sqlite`

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
- `person_behavior_profiles.csv`: stable personality features and natural-language character context
- `social`: conflict-free shared events for sampled and external contacts
- `routes`: cached replaceable route provider
- `world`: arbitrary-time interpolation and batched world state
- `cli`: generation, world query, and benchmark commands

Random streams derive from person ID, date, event type, and base seed, so repeated runs are stable while different dates vary.

## Reference benchmark

Measured in the Codex bundled Python runtime on 2026-08-23:

- 10,000 people × 7 days: 411,547 events in 16.49 seconds
- `get_world()` for 10,000 people: 0.0495 seconds (about 202,000 locations/second)

These figures are environment-specific; run the benchmark command above on the deployment host for a comparable result.
