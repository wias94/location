from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .behavior import ScheduleEngine
from .clock import SimulationClock, utc_now
from .config import BehaviorConfig
from .population import load_population
from .places import PlaceResolver, load_place_provider
from .routes import RouteCache, route_provider_for_mode
from .world import WorldEngine


@dataclass(slots=True)
class Interaction:
    interaction_id: str
    person_id: str
    start_time: datetime
    end_time: datetime
    lat: float
    lng: float
    status: str

    def active(self, timestamp: datetime) -> bool:
        return self.start_time <= timestamp < self.end_time

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["start_time"], result["end_time"] = self.start_time.isoformat(), self.end_time.isoformat()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Interaction":
        return cls(str(data["interaction_id"]), str(data["person_id"]), datetime.fromisoformat(data["start_time"]),
                   datetime.fromisoformat(data["end_time"]), float(data["lat"]), float(data["lng"]), str(data["status"]))


class JsonStateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)


class SimulatorService:
    def __init__(self, population_path: str | Path, state_path: str | Path, days: int = 1,
                 places_path: str | Path | None = None, relationships_path: str | Path | None = None,
                 road_network_path: str | Path | None = None, route_cache_path: str | Path | None = None,
                 external_contacts_path: str | Path | None = None, routing_mode: str = "straight") -> None:
        self.store = JsonStateStore(state_path)
        saved = self.store.load()
        initial_simulation = datetime.fromisoformat(os.getenv("SIMULATION_START", datetime.now().date().isoformat() + "T00:00:00"))
        self.clock = SimulationClock.from_dict(saved["clock"]) if saved.get("clock") else SimulationClock(initial_simulation, utc_now(), 1)
        self.behavior = BehaviorConfig.from_dict(saved.get("behavior"))
        self.people_list = load_population(population_path)
        self.people = {person.person_id: person for person in self.people_list}
        self.days = int(days)
        self.version = int(saved.get("version", 1))
        self.schedule_start = date.fromisoformat(saved["schedule_start"]) if saved.get("schedule_start") else self.clock.now().date()
        self.interactions = [Interaction.from_dict(item) for item in saved.get("interactions", [])]
        self.place_provider = load_place_provider(places_path) if places_path else None
        self.relationships_path = relationships_path
        self.external_contacts_path = external_contacts_path
        self.requested_routing_mode = routing_mode.strip().lower()
        self.route_provider = route_provider_for_mode(self.requested_routing_mode, road_network_path)
        self.routing_mode = "road" if self.route_provider else "straight"
        self.route_cache = RouteCache(self.route_provider, route_cache_path) if self.route_provider else RouteCache()
        self.world = self._new_world()
        self._cache: dict[tuple[str, int], dict[str, object]] = {}
        self._lock = threading.RLock()
        self._generation_lock = threading.Lock()

    def _new_world(self) -> WorldEngine:
        places = PlaceResolver(provider=self.place_provider, people=self.people,
                               relationships_path=self.relationships_path,
                               external_contacts_path=self.external_contacts_path) if self.place_provider else None
        return WorldEngine(ScheduleEngine(config=self.behavior, places=places, routes=self.route_cache))

    def start(self) -> None:
        if not self.schedule_start <= self.clock.now().date() < self.schedule_start + timedelta(days=self.days):
            self.schedule_start = self.clock.now().date()
        self.world.generate_population_period(self.people_list, self.schedule_start, self.days)
        self.save()

    def save(self) -> None:
        self.route_cache.flush()
        self.store.save({"clock": self.clock.to_dict(), "behavior": self.behavior.to_dict(), "days": self.days,
                         "version": self.version, "schedule_start": self.schedule_start.isoformat(),
                         "interactions": [item.to_dict() for item in self.interactions]})

    def close(self) -> None:
        self.save(); self.route_cache.close()
        close_places = getattr(self.place_provider, "close", None)
        if close_places:
            close_places()

    def regenerate(self, start_date: date | None = None) -> dict[str, object]:
        with self._generation_lock:
            target_start = start_date or self.clock.now().date()
            new_world = self._new_world()
            schedules = new_world.generate_population_period(self.people_list, target_start, self.days)
            with self._lock:
                self.schedule_start = target_start
                self.world = new_world
                self.version += 1
                self._cache.clear()
                self.save()
                return {"people": len(self.people), "days": self.days, "events": sum(map(len, schedules.values())),
                        "social_events": len(new_world.social_events), "version": self.version}

    def ensure_coverage(self, timestamp: datetime) -> None:
        if not self.schedule_start <= timestamp.date() < self.schedule_start + timedelta(days=self.days):
            self.regenerate(timestamp.date())

    def _interaction(self, person_id: str, timestamp: datetime) -> Interaction | None:
        return next((item for item in reversed(self.interactions) if item.person_id == person_id and item.active(timestamp)), None)

    def location(self, person_id: str, timestamp: datetime | None = None) -> dict[str, object]:
        target = timestamp or self.clock.now()
        self.ensure_coverage(target)
        interaction = self._interaction(person_id, target)
        if interaction:
            return {"person_id": person_id, "timestamp": target.isoformat(), "lat": interaction.lat, "lng": interaction.lng,
                    "status": interaction.status, "place_id": None, "destination_place_id": None,
                    "interaction_id": interaction.interaction_id}
        return self.world.get_location(person_id, target)

    def snapshot(self, timestamp: datetime | None = None) -> dict[str, object]:
        target = timestamp or self.clock.now()
        self.ensure_coverage(target)
        minute = target.replace(second=0, microsecond=0)
        key = (minute.isoformat(), self.version)
        with self._lock:
            if key not in self._cache:
                result = self.world.get_world(minute)
                active = {item.person_id: item for item in self.interactions if item.active(minute)}
                for point in result["people"]:
                    if point["id"] in active:
                        item = active[point["id"]]
                        point.update(lat=item.lat, lng=item.lng, status=item.status)
                result["version"] = self.version
                self._cache[key] = result
                while len(self._cache) > 5:
                    self._cache.pop(next(iter(self._cache)))
            return self._cache[key]

    def status(self) -> dict[str, object]:
        return {"status": "paused" if self.clock.paused else "running", "simulation_time": self.clock.now().isoformat(),
                "speed": self.clock.speed, "population": len(self.people), "routing_mode": self.routing_mode,
                "schedule_start": self.schedule_start.isoformat(),
                "schedule_end": (self.schedule_start + timedelta(days=self.days)).isoformat(), "version": self.version,
                "interactions": len(self.interactions), "social_events": len(self.world.social_events)}

    def prewarm_routes(self, timestamp: datetime | None = None, horizon_minutes: int = 30, limit: int = 300) -> dict[str, int]:
        if not self.route_provider:
            return {"candidates": 0, "materialized": 0}
        target = timestamp or self.clock.now()
        horizon = target + timedelta(minutes=horizon_minutes)
        candidates = {}
        for events in self.world.events.values():
            for event in events:
                if event.route_id and event.end_time > target and event.start_time < horizon:
                    candidates[event.route_id] = min(event.start_time, candidates.get(event.route_id, event.start_time))
        pending = [route_id for route_id, _ in sorted(candidates.items(), key=lambda item: item[1])
                   if not self.route_cache.is_materialized(route_id)]
        for route_id in pending[:limit]:
            self.route_cache.materialize(route_id)
        self.route_cache.flush()
        return {"candidates": len(candidates), "materialized": min(len(pending), limit)}

    def add_interaction(self, person_id: str, lat: float, lng: float, status: str, duration_minutes: int,
                        start_time: datetime | None = None) -> Interaction:
        if person_id not in self.people:
            raise KeyError(person_id)
        if not (-90 <= lat <= 90 and -180 <= lng <= 180 and 1 <= duration_minutes <= 10_080):
            raise ValueError("Invalid location or duration")
        start = start_time or self.clock.now()
        item = Interaction(f"INT_{self.version + 1}_{len(self.interactions) + 1}", person_id, start,
                           start + timedelta(minutes=duration_minutes), lat, lng, status[:40])
        self.interactions.append(item)
        self.version += 1
        self._cache.clear()
        self.save()
        return item

    def update_behavior(self, data: dict[str, Any]) -> None:
        self.behavior = BehaviorConfig.from_dict(data)
        self.save()
