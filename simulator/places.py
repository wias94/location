from __future__ import annotations

import math
from typing import Protocol

from .models import Occupation, Person, Place
from .randomness import stable_seed


class PlaceProvider(Protocol):
    def get(self, place_id: str) -> Place: ...
    def put(self, place: Place) -> None: ...
    def all(self) -> dict[str, Place]: ...


class InMemoryPlaceProvider:
    def __init__(self) -> None:
        self._places: dict[str, Place] = {}

    def get(self, place_id: str) -> Place:
        return self._places[place_id]

    def put(self, place: Place) -> None:
        self._places[place.place_id] = place

    def all(self) -> dict[str, Place]:
        return dict(self._places)


class PlaceResolver:
    """Deterministic mock binding centered on Shanghai; replace provider for real OSM places."""

    DEST_CATEGORIES = {
        "RESTAURANT_NEAR_WORK": "restaurant", "RESTAURANT": "restaurant",
        "CAFE_OR_COWORKING": "cafe", "DATE_POI": "cinema", "FRIEND_HOME": "friend_home",
        "FRIEND_HOME_OR_DORM": "friend_home", "OTHER_POI": "other",
        "SHOP_OR_SERVICE_POI": "retail", "FAMILY_RESTAURANT": "restaurant",
        "CHILD_ACTIVITY_POI": "other", "LIBRARY_OR_CAFE": "cafe",
        "RESTAURANT_NEAR_CAMPUS": "restaurant", "CAMPUS_CANTEEN": "restaurant",
        "SCHOOL_OR_CHILDCARE": "school",
    }

    def __init__(self, provider: PlaceProvider | None = None, seed: int = 20260819) -> None:
        self.provider = provider or InMemoryPlaceProvider()
        self.seed = seed

    def _coordinates(self, key: str, origin: Place | None = None, radius_km: float = 12.0) -> tuple[float, float]:
        number = stable_seed(key, base_seed=self.seed)
        angle = (number % 360_000) / 1000 * math.pi / 180
        distance = 0.15 + ((number >> 20) % 10_000) / 10_000 * radius_km
        base_lat, base_lng = (origin.lat, origin.lng) if origin else (31.2304, 121.4737)
        return base_lat + distance / 111 * math.cos(angle), base_lng + distance / (111 * math.cos(math.radians(base_lat))) * math.sin(angle)

    def _ensure(self, place_id: str, category: str, origin: Place | None = None, radius_km: float = 12.0) -> Place:
        try:
            return self.provider.get(place_id)
        except KeyError:
            lat, lng = self._coordinates(place_id, origin, radius_km)
            place = Place(place_id, f"Synthetic {category} {place_id}", category, lat, lng)
            self.provider.put(place)
            return place

    def bind_person(self, person: Person) -> dict[str, Place]:
        home = self._ensure(person.home_place_id or f"HOME_{person.person_id}", "home")
        work_category = "university" if person.occupation == Occupation.STUDENT else ("worksite" if person.occupation == Occupation.MANUAL else "company")
        work_id = person.school_place_id if person.occupation == Occupation.STUDENT else person.work_place_id
        work = self._ensure(work_id or f"WORK_{person.person_id}", work_category, home, 18)
        result = {"HOME": home, "HOME_OR_DORM": home, "WORK": work, "WORKSITE": work, "CAMPUS": work}
        if person.family.value == "minor_children":
            result["SCHOOL_OR_CHILDCARE"] = self._ensure(person.school_place_id or f"SCHOOL_{person.person_id}", "school", home, 2.5)
        return result

    def resolve_place(self, destination_type: str, person: Person, current_place: Place, timestamp: object = None) -> Place:
        fixed = self.bind_person(person)
        if destination_type in fixed:
            return fixed[destination_type]
        category = self.DEST_CATEGORIES.get(destination_type, "other")
        near = destination_type in {"RESTAURANT_NEAR_WORK", "RESTAURANT_NEAR_CAMPUS", "CAMPUS_CANTEEN"}
        bucket = getattr(timestamp, "date", lambda: "static")()
        place_id = f"DYN_{category.upper()}_{stable_seed(person.person_id, bucket, destination_type, base_seed=self.seed) % 100000:05d}"
        return self._ensure(place_id, category, current_place, 0.8 if near else 5.0)
