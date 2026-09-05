from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .behavior import ScheduleEngine
from .clock import SimulationClock, utc_now
from .config import BehaviorConfig
from .models import Family, Gender, Occupation, Person, Place
from .population import (age_group_for, generated_personality, load_population, person_from_dict, person_to_dict,
                         summarize_personality)
from .randomness import stable_seed
from .places import PlaceResolver, load_place_provider
from .routes import RouteCache, route_provider_for_mode
from .world import WorldEngine
from .history import HistoryStore


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
    WORK_CATEGORIES = {
        Occupation.OFFICE: ("office", "commercial"),
        Occupation.SERVICE: ("restaurant", "retail", "hotel", "supermarket", "gym"),
        Occupation.MANUAL: ("industrial", "commercial"),
        Occupation.FREELANCER: ("residential", "cafe", "office"),
        Occupation.STUDENT: ("university", "college"),
    }

    def __init__(self, population_path: str | Path, state_path: str | Path, days: int = 1,
                 places_path: str | Path | None = None, relationships_path: str | Path | None = None,
                 road_network_path: str | Path | None = None, route_cache_path: str | Path | None = None,
                 external_contacts_path: str | Path | None = None, routing_mode: str = "straight") -> None:
        self.store = JsonStateStore(state_path)
        self.history = HistoryStore(Path(state_path).with_name("history.sqlite"))
        saved = self.store.load()
        initial_simulation = datetime.fromisoformat(os.getenv("SIMULATION_START", datetime.now().date().isoformat() + "T00:00:00"))
        self.clock = SimulationClock.from_dict(saved["clock"]) if saved.get("clock") else SimulationClock(initial_simulation, utc_now(), 1)
        self.behavior = BehaviorConfig.from_dict(saved.get("behavior"))
        base_people = load_population(population_path)
        base_ids = {person.person_id for person in base_people}
        self.person_place_overrides = dict(saved.get("person_place_overrides", {}))
        self.added_people = [person_from_dict(item) for item in saved.get("added_people", [])
                             if item.get("person_id") not in base_ids]
        self.people_list = [*base_people, *self.added_people]
        self.people_list = [replace(person, **self.person_place_overrides.get(person.person_id, {}))
                            for person in self.people_list]
        added_ids = {person.person_id for person in self.added_people}
        self.added_people = [person for person in self.people_list if person.person_id in added_ids]
        self.people = {person.person_id: person for person in self.people_list}
        self.days = int(days)
        self.version = int(saved.get("version", 1))
        self.schedule_start = date.fromisoformat(saved["schedule_start"]) if saved.get("schedule_start") else self.clock.now().date()
        self.interactions = [Interaction.from_dict(item) for item in saved.get("interactions", [])]
        self.admin_relationships = list(saved.get("admin_relationships", []))
        self.schedule_overrides = dict(saved.get("schedule_overrides", {}))
        self.favorite_places = list(saved.get("favorite_places", []))
        self.custom_places = [Place(**item) for item in saved.get("custom_places", [])]
        self.place_provider = load_place_provider(places_path) if places_path else None
        if self.place_provider:
            for place in self.custom_places:
                self.place_provider.put(place)
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
                               external_contacts_path=self.external_contacts_path,
                               admin_relationships=self.admin_relationships,
                               favorite_places=self.favorite_places) if self.place_provider else None
        return WorldEngine(ScheduleEngine(config=self.behavior, places=places, routes=self.route_cache,
                                          schedule_overrides=self.schedule_overrides))

    def start(self) -> None:
        if not self.schedule_start <= self.clock.now().date() < self.schedule_start + timedelta(days=self.days):
            self.schedule_start = self.clock.now().date()
        self.world.generate_population_period(self.people_list, self.schedule_start, self.days)
        self.save()

    def save(self) -> None:
        self.route_cache.flush()
        state = {"clock": self.clock.to_dict(), "behavior": self.behavior.to_dict(), "days": self.days,
                         "version": self.version, "schedule_start": self.schedule_start.isoformat(),
                         "interactions": [item.to_dict() for item in self.interactions],
                         "added_people": [person_to_dict(person) for person in self.added_people],
                         "admin_relationships": self.admin_relationships,
                         "schedule_overrides": self.schedule_overrides,
                         "favorite_places": self.favorite_places,
                         "custom_places": [asdict(place) for place in self.custom_places],
                         "person_place_overrides": self.person_place_overrides}
        self.history.state(state)
        self.store.save(state)

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

    def _next_person_id(self) -> str:
        numbers = [int(pid[1:]) for pid in self.people if pid.startswith("P") and pid[1:].isdigit()]
        return f"P{max(numbers, default=0) + 1:05d}"

    def _donor(self, key: str, candidates: list[Person]) -> Person:
        if not candidates:
            raise ValueError("No suitable existing person is available for automatic place assignment")
        return candidates[stable_seed(key, "place_assignment") % len(candidates)]

    def _validated_place_id(self, place_id: str | None) -> str | None:
        value = (place_id or "").strip() or None
        if value and self.place_provider:
            try:
                self.place_provider.get(value)
            except KeyError:
                raise ValueError(f"Unknown place_id: {value}") from None
        return value

    def search_places(self, query: str, role: str, occupation: Occupation | None = None,
                      limit: int = 8, category: str | None = None) -> list[dict[str, Any]]:
        if not self.place_provider:
            return []
        role_key = role.strip().lower()
        if role_key == "home":
            categories = ("residential",)
        elif role_key == "school":
            categories = ("school", "childcare", "kindergarten", "university", "college")
        elif role_key == "work":
            categories = self.WORK_CATEGORIES.get(occupation or Occupation.OFFICE, ("office", "commercial"))
        elif role_key == "favorite" and category:
            categories = (category.strip().lower(),)
        else:
            raise ValueError("role must be home, work, school, or favorite with a category")
        search = getattr(self.place_provider, "search", None)
        return [asdict(place) for place in (search(query, categories, limit) if search else [])]

    def add_person(self, *, person_id: str | None, name: str, gender: Gender, age: int, family: Family,
                   occupation: Occupation, job_title: str, home_place_id: str | None = None,
                   work_place_id: str | None = None, school_place_id: str | None = None,
                   employer_id: str | None = None, company_name: str | None = None,
                   personality_traits: dict[str, float] | None = None,
                   communication_style: str | None = None, personality_summary: str | None = None,
                   background: str | None = None, interests: str | None = None, goals: str | None = None,
                   dialogue_notes: str | None = None) -> dict[str, Any]:
        """Persist one admin-created person and add only their schedule to the live world."""
        with self._generation_lock:
            pid = (person_id or "").strip().upper() or self._next_person_id()
            if not pid.startswith("P") or not pid[1:].isdigit() or len(pid) > 12:
                raise ValueError("person_id must use the format P followed by digits")
            if pid in self.people:
                raise ValueError(f"person_id already exists: {pid}")

            requested_home = self._validated_place_id(home_place_id)
            requested_work = self._validated_place_id(work_place_id)
            requested_school = self._validated_place_id(school_place_id)
            home_donor = self._donor(pid + "HOME", [p for p in self.people_list if p.home_place_id])
            work_candidates = [p for p in self.people_list if p.occupation == occupation and p.work_place_id]
            same_job = [p for p in work_candidates if p.job_title == job_title]
            work_donor = self._donor(pid + "WORK", same_job or work_candidates)
            assigned_home = requested_home or home_donor.home_place_id
            assigned_work = requested_work or work_donor.work_place_id
            assigned_school = requested_school
            if occupation == Occupation.STUDENT:
                assigned_school = assigned_school or assigned_work
            elif family == Family.MINOR_CHILDREN and not assigned_school:
                school_candidates = [p for p in self.people_list if p.school_place_id and
                                     p.family == Family.MINOR_CHILDREN]
                assigned_school = self._donor(pid + "SCHOOL", school_candidates).school_place_id

            profile = generated_personality(pid, age, family, occupation)
            if personality_traits:
                if any(not 0 <= value <= 1 for value in personality_traits.values()):
                    raise ValueError("Personality traits must be between 0 and 1")
                profile.update(personality_traits)
            if communication_style and communication_style.strip():
                profile["communication_style"] = communication_style.strip()
            if personality_summary and personality_summary.strip():
                profile["personality_summary"] = personality_summary.strip()
            elif personality_traits or communication_style:
                profile["personality_summary"] = summarize_personality(profile, profile["communication_style"])
            assigned_employer = employer_id or (f"ORG_CUSTOM_{pid}" if company_name and requested_work else
                                                work_donor.employer_id if not requested_work else None)
            person = Person(pid, name.strip(), gender, age, age_group_for(age), family, occupation,
                            job_title.strip(), "", "", assigned_home, assigned_work, assigned_school,
                            assigned_employer, **profile, company_name=(company_name or "").strip(),
                            background=(background or "").strip(), interests=(interests or "").strip(),
                            goals=(goals or "").strip(), dialogue_notes=(dialogue_notes or "").strip())
            events = self.world.schedule.generate_period(person, self.schedule_start, self.days)
            with self._lock:
                self.added_people.append(person)
                self.people_list.append(person)
                self.people[pid] = person
                self.world.people[pid] = person
                self.world.events[pid] = events
                self.world._starts[pid] = [event.start_time for event in events]
                self.version += 1
                self._cache.clear()
                self.save()
            places = {}
            if self.place_provider:
                for role, place_id_value in (("home", assigned_home), ("work", assigned_work),
                                             ("school", assigned_school)):
                    if place_id_value:
                        places[role] = asdict(self.place_provider.get(place_id_value))
            return {"person": person_to_dict(person), "places": places, "events": len(events),
                    "population": len(self.people), "version": self.version}

    def add_custom_place(self, name: str, category: str, lat: float, lng: float,
                         address: str = "") -> dict[str, Any]:
        if not name.strip() or not category.strip() or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("Invalid custom place")
        key = stable_seed(name.strip(), category.strip(), round(lat, 7), round(lng, 7), "custom_place")
        place_id = f"USR_{key % 10**15:015d}"
        try:
            place = self.place_provider.get(place_id) if self.place_provider else None
        except KeyError:
            place = None
        if place is None:
            place = Place(place_id, name.strip(), category.strip().lower(), lat, lng, address.strip(), "admin")
            self.custom_places.append(place)
            if self.place_provider:
                self.place_provider.put(place)
            self.version += 1
            self._cache.clear()
            self.save()
        return asdict(place)

    def _replace_person(self, person_id: str, **changes: Any) -> Person:
        updated = replace(self.people[person_id], **changes)
        self.people[person_id] = updated
        self.people_list = [updated if person.person_id == person_id else person for person in self.people_list]
        self.added_people = [updated if person.person_id == person_id else person for person in self.added_people]
        return updated

    def add_relationship(self, *, person_id: str, counterpart_kind: str, relation_type: str,
                         counterpart_id: str | None = None, counterpart_name: str | None = None,
                         co_resident: bool = False, home_place_id: str | None = None,
                         strength: float = .7, contact_frequency: str = "weekly",
                         description: str = "") -> dict[str, Any]:
        person_id = person_id.strip().upper()
        if person_id not in self.people:
            raise ValueError(f"Unknown person: {person_id}")
        kind, relation = counterpart_kind.strip().lower(), relation_type.strip().lower()
        if kind not in {"in_population", "external"}:
            raise ValueError("counterpart_kind must be in_population or external")
        allowed = {"spouse", "friend", "parent", "adult_child", "coworker", "extended_family"}
        if relation not in allowed or not 0 <= strength <= 1:
            raise ValueError("Invalid relationship type or strength")
        target_id = (counterpart_id or "").strip().upper()
        label = (counterpart_name or "").strip()
        if kind == "in_population":
            if target_id not in self.people or target_id == person_id:
                raise ValueError("Choose a different existing person_id")
            label = self.people[target_id].name
            relationship_id = f"REL_ADMIN_{stable_seed(person_id, target_id, relation) % 10**12:012d}"
            if any(item["relationship_id"] == relationship_id for item in self.admin_relationships):
                raise ValueError("This relationship already exists")
            if co_resident:
                shared_home = self.people[person_id].home_place_id
                self.person_place_overrides.setdefault(target_id, {})["home_place_id"] = shared_home
                self._replace_person(target_id, home_place_id=shared_home)
            resolved_home = self.people[target_id].home_place_id
        else:
            if not label:
                raise ValueError("External contacts require a name")
            target_id = f"EXT_ADMIN_{stable_seed(person_id, label, relation) % 10**12:012d}"
            relationship_id = f"REL_ADMIN_{stable_seed(person_id, target_id, relation) % 10**12:012d}"
            if any(item["relationship_id"] == relationship_id for item in self.admin_relationships):
                raise ValueError("This relationship already exists")
            resolved_home = self.people[person_id].home_place_id if co_resident else self._validated_place_id(home_place_id)
            if not resolved_home:
                raise ValueError("External non-resident contacts require a home place")
        record = {
            "relationship_id": relationship_id,
            "person_id": person_id, "counterpart_kind": kind, "counterpart_id": target_id,
            "counterpart_name": label, "relation_type": relation, "co_resident": bool(co_resident),
            "home_place_id": resolved_home, "strength": round(float(strength), 2),
            "contact_frequency": contact_frequency.strip()[:40], "description": description.strip()[:2000],
        }
        self.admin_relationships.append(record)
        self.save()
        return record

    def set_schedule_override(self, person_id: str, workdays: list[int], work_start: str,
                              work_end: str) -> dict[str, Any]:
        person_id = person_id.strip().upper()
        if person_id not in self.people or any(day not in range(7) for day in workdays):
            raise ValueError("Unknown person or invalid workdays")
        start = datetime.strptime(work_start, "%H:%M").time()
        end = datetime.strptime(work_end, "%H:%M").time()
        if end <= start:
            raise ValueError("work_end must be later than work_start")
        override = {"workdays": sorted(set(workdays)), "work_start": work_start, "work_end": work_end}
        self.schedule_overrides[person_id] = override
        self.save()
        return override

    def add_favorite_place(self, person_id: str, place_id: str, category: str,
                           label: str, weight: float) -> dict[str, Any]:
        person_id = person_id.strip().upper()
        if person_id not in self.people or not 0 < weight <= 1:
            raise ValueError("Unknown person or invalid preference weight")
        resolved = self._validated_place_id(place_id)
        place = self.place_provider.get(resolved) if self.place_provider and resolved else None
        if not place:
            raise ValueError("Unknown favorite place")
        record = {"person_id": person_id, "place_id": resolved, "category": category.strip().lower(),
                  "label": label.strip() or place.name, "weight": round(float(weight), 2)}
        self.favorite_places = [item for item in self.favorite_places
                                if not (item["person_id"] == person_id and item["place_id"] == resolved)]
        self.favorite_places.append(record)
        self.save()
        return record
