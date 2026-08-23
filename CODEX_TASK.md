# Codex Task: Shanghai Synthetic Population Mobility Simulator

## 1. Project goal

Build the next stage of a synthetic urban mobility simulator for Shanghai.

The project already has:

1. A synthetic population of **10,000 virtual people**.
2. Person attributes such as gender, age, family type, occupation, job title and hukou.
3. A behavior-template script defining daily behavior formulas for combinations of gender, family type and occupation.
4. Geographic fields (`home_place_id`, `work_place_id`, `school_place_id`) intentionally left blank.

The next task is to turn those abstract people and behavior templates into an **executable location simulation**.

The system is for synthetic simulation only. Do not infer or model real identifiable people's homes, workplaces or routines.

---

## 2. Existing files

### `shanghai_synthetic_population_10000.csv`
Primary population input.

Columns:

- `person_id`
- `姓名`
- `性别`
- `年龄`
- `年龄段`
- `家庭状态`
- `职业大类`
- `occupation_code`
- `具体职位`
- `户口类型`
- `户口省份`
- `home_place_id`
- `work_place_id`
- `school_place_id`

The three place IDs are currently blank.

### `shanghai_synthetic_population_10000.xlsx`
Same population in Excel form, with summary and generation-parameter sheets.

### `generate_population.py`
Reproducible generator for the synthetic population.

### `person_behavior_templates.py`
Behavior formulas for:

- gender: male / female
- family: single_no_kids / adult_children / minor_children
- occupation:
  - office_worker
  - freelancer
  - service_worker
  - manual_worker
  - university_student

The templates contain fixed skeletons, work-time rules, midday events, evening events and family modifiers.

---

## 3. Important modeling decisions already made

Do not redesign these unless a technical contradiction requires it.

### Population size

Start with exactly **10,000 people**.

### Age

Only ages **18 to 49** are modeled.

### Geographic binding

People currently have no home/work/school coordinates.

Geographic assignment must happen as a separate layer.

The person table should reference places by stable IDs rather than embedding names or coordinates directly.

Example:

```text
P00001.home_place_id = HOME_000123
P00001.work_place_id = PLACE_004281
```

### Behavior architecture

Keep these layers separate:

```text
Person Profile
    ↓
Behavior Engine
    ↓
Daily Events
    ↓
Place Resolver
    ↓
Concrete Places
    ↓
Route Resolver
    ↓
Movement Events
    ↓
World Engine
    ↓
lat/lng at arbitrary simulation time
```

### Storage strategy

Do **not** pre-store one GPS record per person per minute.

Store event/state information instead.

For movement events store roughly:

```text
person_id
start_time
end_time
origin_place_id
destination_place_id
route_id
```

Then calculate a person's location at an arbitrary time by interpolating along the route.

This allows 10,000 people to appear to move every minute without storing 14.4 million GPS records per day.

### Determinism

Simulation must be reproducible.

Random choices should derive from stable seeds such as:

```text
person_id + simulation_date + event_type
```

Running the same seed/date twice must return the same daily plan.

---

## 4. Behavior requirements

### Office worker example

Canonical base behavior:

```text
HOME → WORK → HOME
```

Time model:

```text
work_start ≈ 09:00 ± 20 min
work_duration ≈ 9 h ± 30 min
home_departure = work_start - route_travel_time
```

Midday:

```text
80% stay at work / eat at work
20% WORK → nearby restaurant → WORK
```

Evening baseline for a single/no-dependent-child office worker:

```text
60% → HOME
15% → RESTAURANT → HOME
10% → DATE_POI → HOME
10% → FRIEND_HOME → HOME
 5% → OTHER_POI → HOME
```

Only one major evening event should normally be selected per day.

### Minor children

People with minor children may require school/childcare drop-off or pickup.

Their probability of going directly home after work should be higher; nightlife/social events should be lower.

### Service workers

This is important.

Service workers must **not** behave like Mon-Fri office workers.

They are generally more likely to work on weekends and holidays and take days off during weekdays.

Recommended first-pass work probability:

```text
Mon 0.60
Tue 0.60
Wed 0.65
Thu 0.70
Fri 0.80
Sat 0.92
Sun 0.88
holiday ~0.95
```

Prefer weekly days off on Mon-Thu.

Existing service-worker shift starts are approximately:

```text
07:00  weight 0.25
10:00  weight 0.35
14:00  weight 0.40
```

Work duration is approximately 8.5 hours with jitter.

### Freelancers

Flexible work start, optional cafe/coworking/work-from-home behavior.

### Manual workers

Typically earlier work start and worksite-based behavior.

### University students

Use campus/university instead of company/workplace.

---

## 5. Place system to implement

Implement a `Place` model and a `PlaceResolver`.

Suggested place schema:

```text
place_id
name
category
lat
lng
address
source
source_id
```

Potential categories:

```text
home
company
office_building
restaurant
cafe
mall
cinema
bar
gym
university
school
childcare
worksite
hotel
retail
friend_home
other
```

### Fixed places

Resolve once per person:

```text
HOME
WORK
UNIVERSITY
SCHOOL_OR_CHILDCARE
```

### Dynamic places

Resolve at simulation time / daily-plan generation time:

```text
RESTAURANT_NEAR_WORK
RESTAURANT
CAFE
DATE_POI
OTHER_POI
CHILD_ACTIVITY_POI
```

Example resolver API:

```python
resolve_place(
    destination_type="RESTAURANT_NEAR_WORK",
    person=person,
    current_place=work_place,
    timestamp=timestamp,
) -> Place
```

For nearby choices, support radius and origin rules.

Example:

```text
RESTAURANT_NEAR_WORK:
origin = WORK
radius ≈ 0.5-1.0 km

RESTAURANT after work:
origin = current location / commute corridor / home neighborhood
radius may be several km
```

---

## 6. Map / routing approach

The target architecture should support offline/open geographic data.

Preferred mapping stack:

- OpenStreetMap data for Shanghai
- OSRM for road routing, initially prepared outside Cloudflare Workers

Do not require Google Maps API.

The user intends the application itself to act as the API.

OSRM routes should be cached and referenced with a `route_id`.

Do not call OSRM again every simulated minute.

Example route cache key:

```text
(origin_place_id, destination_place_id, travel_mode)
```

A route object should contain at minimum:

```text
route_id
origin_place_id
destination_place_id
distance_m
duration_s
geometry/polyline
```

---

## 7. Simulation output model

Generate event plans for multiple days in advance.

Initial target:

```text
10,000 people × 7 days
```

Do not generate every minute as persistent records.

Suggested event schema:

```text
event_id
person_id
start_time
end_time
event_type
origin_place_id
destination_place_id
route_id
status
```

Event types could include:

```text
stay_home
work
study
commute
lunch_out
dinner_out
date
friend_visit
child_dropoff
child_pickup
shopping
other
```

---

## 8. Required simulation APIs/functions

Implement these functions first, independent of HTTP framework:

### `generate_day(person, date)`

Returns deterministic daily events for one person.

### `generate_period(person, start_date, days)`

Generates multiple days.

### `generate_population_period(people, start_date, days)`

Generates schedules for all 10,000 people.

### `get_location(person_id, timestamp)`

Returns one person's location at an arbitrary timestamp.

Expected shape:

```json
{
  "person_id": "P00001",
  "timestamp": "2026-08-20T08:37:00",
  "lat": 31.123,
  "lng": 121.456,
  "status": "commuting",
  "place_id": null,
  "destination_place_id": "PLACE_00123"
}
```

If stationary, return the place coordinates directly.

If moving, interpolate along a cached route based on elapsed time.

### `get_world(timestamp)`

Returns the current state of all 10,000 people in one call.

Keep the payload compact:

```json
{
  "time": "2026-08-20T14:32:00",
  "people": [
    {"id":"P00001","lat":31.1,"lng":121.4,"status":"work"},
    {"id":"P00002","lat":31.2,"lng":121.5,"status":"commuting"}
  ]
}
```

This is intended for a map UI where all points update every simulated minute.

---

## 9. Performance target

Target:

- 10,000 persons
- 7-day pre-generated schedule
- arbitrary timeline seek
- map position update every simulated minute
- support accelerated playback such as `1 real second = 1 simulated minute`

Avoid:

- 10,000 independent timers
- one database query per person per tick
- OSRM calls every minute
- persistent per-minute GPS rows

Prefer:

- one global simulation clock
- batched reads
- cached routes
- event-state lookup
- vectorized/batch location computation where useful

---

## 10. Cloudflare deployment direction

The eventual public application may be deployed on Cloudflare.

Expected separation:

```text
Cloudflare Worker
    API + simulation query logic

D1
    people / event metadata / place metadata

R2
    larger route geometries / simulation packages

OSRM
    local/offline preprocessing initially
    optional containerized routing service later
```

Do not attempt to load a full Shanghai OSRM road graph into a normal Cloudflare Worker.

For the first implementation, keep the simulator runnable locally and isolate storage/routing behind interfaces so Cloudflare adapters can be added later.

---

## 11. Deliverables for this task

Please implement the project incrementally.

### Phase A: Core models

Create clean Python models/modules for:

- Person
- Place
- DailyEvent / MovementEvent
- Route
- BehaviorTemplate

### Phase B: Population loader

Load `shanghai_synthetic_population_10000.csv` and normalize values into internal enums/codes.

### Phase C: Place resolver interface

Implement the interface and a simple mock/in-memory place provider first.

Do not block the simulator on obtaining real Shanghai map data.

### Phase D: Schedule engine

Connect `person_behavior_templates.py` to actual deterministic daily-event generation.

Add the service-industry weekday/weekend work-probability behavior described above.

### Phase E: Route abstraction

Implement route cache / route-provider interface.

Use a mock straight-line or test polyline provider initially if OSRM is not available.

Keep it replaceable with an OSRM implementation.

### Phase F: World engine

Implement:

```python
generate_population_period(...)
get_location(...)
get_world(...)
```

### Phase G: Tests

At minimum test:

1. Same person/date/seed produces identical plan.
2. Different dates can produce different disturbances.
3. Office worker normally goes to work on weekdays.
4. Service worker is more likely to work on weekends than Mon-Thu.
5. Minor-child templates can generate pickup/dropoff events.
6. `get_location` returns a fixed POI coordinate while stationary.
7. `get_location` returns an interpolated point while moving.
8. `get_world` returns exactly 10,000 people for the provided population.
9. No generated event overlaps the next event for the same person.
10. All generated locations reference valid place IDs/routes.

---

## 12. Coding requirements

- Python 3.11+ preferred.
- Keep simulation logic independent from web framework.
- Use type hints.
- Use dataclasses or Pydantic models where appropriate.
- Keep random-number generation explicit and seeded.
- Avoid global mutable state.
- Provide a `README.md` with setup/run/test commands.
- Provide a CLI demo such as:

```bash
python -m simulator.cli generate --population data/shanghai_synthetic_population_10000.csv --start 2026-08-24 --days 7
```

and:

```bash
python -m simulator.cli world --time 2026-08-24T18:30:00
```

- Prefer readable, modular code over premature optimization.
- Benchmark `get_world()` on 10,000 people and report timing.

---

## 13. Non-goals for the first implementation

Do not spend time yet on:

- satellite imagery
- Google Maps APIs
- perfect traffic modeling
- live weather effects
- exact public-transit simulation
- full Shanghai population (millions)
- real identifiable individuals
- high-frequency GPS noise
- frontend polish

The first milestone is a clean, deterministic **10,000-person / 7-day event simulator** with executable places and arbitrary-time location lookup.
