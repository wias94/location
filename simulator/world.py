from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime
from typing import Iterable

from .behavior import ScheduleEngine
from .models import DailyEvent, Person, SocialEvent
from .social import SocialCoordinator


class WorldEngine:
    def __init__(self, schedule_engine: ScheduleEngine | None = None) -> None:
        self.schedule = schedule_engine or ScheduleEngine()
        self.people: dict[str, Person] = {}
        self.events: dict[str, list[DailyEvent]] = {}
        self.social_events: list[SocialEvent] = []
        self._starts: dict[str, list[datetime]] = {}

    def generate_population_period(self, people: Iterable[Person], start_date: date, days: int) -> dict[str, list[DailyEvent]]:
        self.people = {person.person_id: person for person in people}
        self.schedule.reset_social_intents()
        self.events = {pid: self.schedule.generate_period(person, start_date, days) for pid, person in self.people.items()}
        coordinator = SocialCoordinator(self.schedule.places, self.schedule.routes, self.schedule.config, self.schedule.seed)
        self.social_events = coordinator.coordinate(self.events, self.people, self.schedule.social_intents.values())
        self._starts = {pid: [event.start_time for event in events] for pid, events in self.events.items()}
        return self.events

    def _active_event(self, person_id: str, timestamp: datetime) -> DailyEvent:
        events = self.events[person_id]
        index = bisect_right(self._starts[person_id], timestamp) - 1
        if index < 0 or timestamp >= events[index].end_time:
            raise LookupError(f"No generated event for {person_id} at {timestamp.isoformat()}")
        return events[index]

    def get_location(self, person_id: str, timestamp: datetime) -> dict[str, object]:
        event = self._active_event(person_id, timestamp)
        if not event.moving:
            place = self.schedule.places.provider.get(event.destination_place_id)
            return {"person_id": person_id, "timestamp": timestamp.isoformat(), "lat": place.lat, "lng": place.lng,
                    "status": event.event_type, "place_id": place.place_id, "destination_place_id": place.place_id,
                    "social_event_id": event.social_event_id, "counterparty_id": event.counterparty_id}
        route = self.schedule.routes.get(event.route_id or "")
        total = (event.end_time - event.start_time).total_seconds()
        fraction = min(1.0, max(0.0, (timestamp - event.start_time).total_seconds() / total))
        lat, lng = interpolate(route.geometry, fraction)
        return {"person_id": person_id, "timestamp": timestamp.isoformat(), "lat": lat, "lng": lng,
                "status": "commuting", "place_id": None, "destination_place_id": event.destination_place_id,
                "social_event_id": event.social_event_id, "counterparty_id": event.counterparty_id}

    def get_world(self, timestamp: datetime) -> dict[str, object]:
        points = []
        for person_id in self.people:
            location = self.get_location(person_id, timestamp)
            points.append({"id": person_id, "lat": location["lat"], "lng": location["lng"], "status": location["status"]})
        return {"time": timestamp.isoformat(), "people": points}


def interpolate(geometry: tuple[tuple[float, float], ...], fraction: float) -> tuple[float, float]:
    if len(geometry) == 1:
        return geometry[0]
    scaled = fraction * (len(geometry) - 1)
    index = min(int(scaled), len(geometry) - 2)
    local = scaled - index
    a, b = geometry[index], geometry[index + 1]
    return a[0] + (b[0] - a[0]) * local, a[1] + (b[1] - a[1]) * local


def generate_population_period(people: Iterable[Person], start_date: date, days: int, engine: WorldEngine | None = None):
    world = engine or WorldEngine()
    return world.generate_population_period(people, start_date, days)


def get_location(engine: WorldEngine, person_id: str, timestamp: datetime) -> dict[str, object]:
    return engine.get_location(person_id, timestamp)


def get_world(engine: WorldEngine, timestamp: datetime) -> dict[str, object]:
    return engine.get_world(timestamp)
