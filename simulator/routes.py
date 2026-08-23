from __future__ import annotations

import math
from typing import Protocol

from .models import Place, Route
from .randomness import stable_seed


def haversine_m(a: Place, b: Place) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 12_742_000 * math.asin(math.sqrt(h))


class RouteProvider(Protocol):
    def route(self, origin: Place, destination: Place, travel_mode: str = "car") -> Route: ...


class StraightLineRouteProvider:
    def route(self, origin: Place, destination: Place, travel_mode: str = "car") -> Route:
        distance = haversine_m(origin, destination)
        speed = {"walk": 1.4, "bike": 4.2, "car": 8.5}.get(travel_mode, 8.5)
        route_id = f"ROUTE_{stable_seed(origin.place_id, destination.place_id, travel_mode) % 10**12:012d}"
        return Route(route_id, origin.place_id, destination.place_id, distance, max(60, round(distance / speed)), ((origin.lat, origin.lng), (destination.lat, destination.lng)), travel_mode)


class RouteCache:
    def __init__(self, provider: RouteProvider | None = None) -> None:
        self.provider = provider or StraightLineRouteProvider()
        self._routes: dict[tuple[str, str, str], Route] = {}
        self._by_id: dict[str, Route] = {}

    def get_or_create(self, origin: Place, destination: Place, travel_mode: str = "car") -> Route:
        key = (origin.place_id, destination.place_id, travel_mode)
        if key not in self._routes:
            route = self.provider.route(origin, destination, travel_mode)
            self._routes[key] = route
            self._by_id[route.route_id] = route
        return self._routes[key]

    def get(self, route_id: str) -> Route:
        return self._by_id[route_id]

    def all(self) -> dict[str, Route]:
        return dict(self._by_id)
