from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Protocol

from .models import ExternalContact, Occupation, Person, Place
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


class CsvPlaceProvider(InMemoryPlaceProvider):
    INDEXED_CATEGORIES = {"restaurant", "cafe", "bar", "cinema", "retail", "supermarket", "gym", "park",
                          "hospital", "pharmacy", "school", "childcare", "kindergarten", "university", "college", "hotel"}
    GRID_DEGREES = .02

    def __init__(self) -> None:
        super().__init__()
        self._spatial: dict[str, dict[tuple[int, int], list[Place]]] = defaultdict(lambda: defaultdict(list))

    @classmethod
    def _cell(cls, lat: float, lng: float) -> tuple[int, int]:
        return math.floor(lat / cls.GRID_DEGREES), math.floor(lng / cls.GRID_DEGREES)

    def put(self, place: Place) -> None:
        is_new = place.place_id not in self._places
        super().put(place)
        if is_new and place.category in self.INDEXED_CATEGORIES:
            self._spatial[place.category][self._cell(place.lat, place.lng)].append(place)

    def nearby(self, category: str, origin: Place, radius_km: float) -> list[Place]:
        lat_cells = math.ceil((radius_km / 111) / self.GRID_DEGREES)
        lng_cells = math.ceil((radius_km / (111 * math.cos(math.radians(origin.lat)))) / self.GRID_DEGREES)
        row, column = self._cell(origin.lat, origin.lng)
        candidates = []
        for y in range(row - lat_cells, row + lat_cells + 1):
            for x in range(column - lng_cells, column + lng_cells + 1):
                candidates.extend(self._spatial.get(category, {}).get((y, x), ()))
        return [place for place in candidates if _distance_km(origin, place) <= radius_km]

    @classmethod
    def from_file(cls, path: str | Path) -> "CsvPlaceProvider":
        provider = cls()
        with Path(path).open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                provider.put(Place(
                    row["place_id"], row["name"], row["category"], float(row["lat"]), float(row["lng"]),
                    source="openstreetmap", source_id=row.get("osm_id") or None,
                ))
        return provider


class PlaceResolver:
    """Bind fixed places and resolve activities to real nearby OSM POIs."""

    GTA_CENTRES = (
        (43.6532, -79.3832),  # Toronto
        (43.5890, -79.6441),  # Mississauga
        (43.7315, -79.7624),  # Brampton
        (43.8561, -79.3370),  # Markham
        (43.8372, -79.5083),  # Vaughan
        (43.8828, -79.4403),  # Richmond Hill
        (43.4675, -79.6877),  # Oakville
        (43.8384, -79.0868),  # Pickering
        (43.8975, -78.9429),  # Ajax
        (43.5183, -79.8774),  # Milton
        (43.8975, -78.9429),  # Whitby/Ajax corridor
    )

    DEST_CATEGORIES = {
        "RESTAURANT_NEAR_WORK": "restaurant", "RESTAURANT": "restaurant",
        "CAFE_OR_COWORKING": "cafe", "DATE_POI": "restaurant", "FRIEND_HOME": "friend_home",
        "FRIEND_HOME_OR_DORM": "friend_home", "OTHER_POI": "other",
        "SHOP_OR_SERVICE_POI": "retail", "FAMILY_RESTAURANT": "restaurant",
        "CHILD_ACTIVITY_POI": "other", "LIBRARY_OR_CAFE": "cafe",
        "RESTAURANT_NEAR_CAMPUS": "restaurant", "CAMPUS_CANTEEN": "restaurant",
        "SCHOOL_OR_CHILDCARE": "school",
    }

    DEST_CATEGORY_CHOICES = {
        "DATE_POI": (("restaurant", 40), ("cafe", 15), ("cinema", 15), ("bar", 10), ("park", 10), ("retail", 10)),
        "OTHER_POI": (("park", 35), ("retail", 30), ("cafe", 20), ("gym", 15)),
        "SHOP_OR_SERVICE_POI": (("retail", 70), ("supermarket", 20), ("pharmacy", 10)),
        "CHILD_ACTIVITY_POI": (("park", 60), ("gym", 25), ("retail", 15)),
        "LIBRARY_OR_CAFE": (("cafe", 80), ("park", 20)),
    }

    def __init__(self, provider: PlaceProvider | None = None, seed: int = 20260819,
                 people: dict[str, Person] | None = None, relationships_path: str | Path | None = None,
                 external_contacts_path: str | Path | None = None) -> None:
        self.provider = provider or InMemoryPlaceProvider()
        self.seed = seed
        self.people = people or {}
        self.relationships: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        self.external_contacts: dict[str, dict[str, list[ExternalContact]]] = defaultdict(lambda: defaultdict(list))
        if relationships_path and Path(relationships_path).exists():
            with Path(relationships_path).open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    a, b, kind = row["person_id_a"], row["person_id_b"], row["relationship_type"]
                    self.relationships[a][kind].append(b)
                    self.relationships[b][kind].append(a)
                    if kind == "parent_of":
                        self.relationships[a]["adult_child"].append(b)
                        self.relationships[b]["parent"].append(a)
        if external_contacts_path and Path(external_contacts_path).exists():
            with Path(external_contacts_path).open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    contact = ExternalContact(
                        row["external_contact_id"], row["person_id"], row["relation_type"], row["label"],
                        row["home_place_id"], str(row.get("co_resident", "false")).lower() == "true",
                        row.get("availability_profile") or "evenings_and_weekends",
                    )
                    self.external_contacts[contact.person_id][contact.relation_type].append(contact)

    def _coordinates(self, key: str, origin: Place | None = None, radius_km: float = 12.0) -> tuple[float, float]:
        number = stable_seed(key, base_seed=self.seed)
        angle = (number % 360_000) / 1000 * math.pi / 180
        distance = 0.15 + ((number >> 20) % 10_000) / 10_000 * radius_km
        if origin:
            base_lat, base_lng = origin.lat, origin.lng
        else:
            base_lat, base_lng = self.GTA_CENTRES[number % len(self.GTA_CENTRES)]
            radius_km = min(radius_km, 8.0)
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
        bucket = getattr(timestamp, "date", lambda: "static")()
        if destination_type in {"FRIEND_HOME", "FRIEND_HOME_OR_DORM"}:
            friends = sorted(self.relationships.get(person.person_id, {}).get("friend", ()))
            if friends:
                friend_id = friends[stable_seed(person.person_id, bucket, destination_type, base_seed=self.seed) % len(friends)]
                friend = self.people.get(friend_id)
                if friend and friend.home_place_id:
                    return self.provider.get(friend.home_place_id)
        category = self._destination_category(destination_type, person.person_id, bucket)
        near = destination_type in {"RESTAURANT_NEAR_WORK", "RESTAURANT_NEAR_CAMPUS", "CAMPUS_CANTEEN"}
        travel_scale = .65 + .70 * person.travel_tolerance
        radius = .8 if near else 5.0 * travel_scale
        nearby = getattr(self.provider, "nearby", lambda *_: [])(category, current_place, radius)
        if not nearby and near:
            nearby = getattr(self.provider, "nearby", lambda *_: [])(category, current_place, 3.0)
        if not nearby:
            nearby = getattr(self.provider, "nearby", lambda *_: [])(category, current_place, 15.0 * travel_scale)
        if nearby:
            return nearby[stable_seed(person.person_id, bucket, destination_type, base_seed=self.seed) % len(nearby)]
        place_id = f"DYN_{category.upper()}_{stable_seed(person.person_id, bucket, destination_type, base_seed=self.seed) % 100000:05d}"
        return self._ensure(place_id, category, current_place, radius)

    def _destination_category(self, destination_type: str, person_id: str, bucket: object) -> str:
        choices = self.DEST_CATEGORY_CHOICES.get(destination_type)
        if not choices:
            return self.DEST_CATEGORIES.get(destination_type, "park")
        point = stable_seed(person_id, bucket, destination_type, "category", base_seed=self.seed) % sum(weight for _, weight in choices)
        for category, weight in choices:
            if point < weight:
                return category
            point -= weight
        return choices[-1][0]


def _distance_km(a: Place, b: Place) -> float:
    lat_scale = 111.0
    lng_scale = 111.0 * math.cos(math.radians((a.lat + b.lat) / 2))
    return math.hypot((a.lat - b.lat) * lat_scale, (a.lng - b.lng) * lng_scale)
