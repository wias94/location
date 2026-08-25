from __future__ import annotations

import heapq
import json
import math
import pickle
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path
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


class RoadNetworkRouteProvider:
    """A* routing on a locally generated OSM road graph."""

    GRID_DEGREES = .01

    def __init__(self, path: str | Path, max_expansions: int = 500_000) -> None:
        # Only load road_network.pkl generated locally by scripts/build_road_network.py.
        with Path(path).open("rb") as handle:
            data = pickle.load(handle)
        if data.get("version") != 1:
            raise ValueError("Unsupported road network version")
        self.coords: dict[int, tuple[float, float]] = data["coords"]
        self.adjacency: dict[int, list[tuple[int, float, float]]] = data["adjacency"]
        self.max_expansions = max_expansions
        self.grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        for node_id, (lat, lng) in self.coords.items():
            self.grid[self._cell(lat, lng)].append(node_id)
        self.fallback = StraightLineRouteProvider()

    @classmethod
    def _cell(cls, lat: float, lng: float) -> tuple[int, int]:
        return math.floor(lat / cls.GRID_DEGREES), math.floor(lng / cls.GRID_DEGREES)

    def _nearest(self, place: Place) -> int | None:
        row, column = self._cell(place.lat, place.lng)
        for radius in range(6):
            candidates = []
            for y in range(row - radius, row + radius + 1):
                for x in range(column - radius, column + radius + 1):
                    if radius == 0 or abs(y - row) == radius or abs(x - column) == radius:
                        candidates.extend(self.grid.get((y, x), ()))
            if candidates:
                return min(candidates, key=lambda node: _point_distance_m((place.lat, place.lng), self.coords[node]))
        return None

    def route(self, origin: Place, destination: Place, travel_mode: str = "car") -> Route:
        if travel_mode != "car":
            return self.fallback.route(origin, destination, travel_mode)
        start, goal = self._nearest(origin), self._nearest(destination)
        if start is None or goal is None:
            return self.fallback.route(origin, destination, travel_mode)
        if start == goal:
            return self._route_result(origin, destination, [start], 0, 0, travel_mode)
        queue = [(self._heuristic(start, goal), 0.0, start)]
        costs = {start: 0.0}; distances = {start: 0.0}; previous: dict[int, int] = {}
        visited, found = 0, False
        while queue and visited < self.max_expansions:
            _, cost, node = heapq.heappop(queue)
            if cost != costs.get(node): continue
            visited += 1
            if node == goal:
                found = True; break
            for neighbor, meters, seconds in self.adjacency.get(node, ()):
                candidate = cost + seconds
                if candidate < costs.get(neighbor, math.inf):
                    costs[neighbor] = candidate; distances[neighbor] = distances[node] + meters; previous[neighbor] = node
                    heapq.heappush(queue, (candidate + self._heuristic(neighbor, goal), candidate, neighbor))
        if not found:
            return self.fallback.route(origin, destination, travel_mode)
        path, node = [goal], goal
        while node != start:
            node = previous[node]; path.append(node)
        path.reverse()
        return self._route_result(origin, destination, path, distances[goal], costs[goal], travel_mode)

    def estimate(self, origin: Place, destination: Place, travel_mode: str = "car") -> Route:
        """Cheap schedule-time estimate; geometry is materialized before/while the trip is active."""
        direct = haversine_m(origin, destination)
        distance = direct * 1.25
        speed = {"walk": 1.4, "bike": 4.2, "car": 8.5}.get(travel_mode, 8.5)
        route_id = f"ROUTE_{stable_seed(origin.place_id, destination.place_id, travel_mode) % 10**12:012d}"
        return Route(route_id, origin.place_id, destination.place_id, distance, max(60, round(distance / speed)),
                     ((origin.lat, origin.lng), (destination.lat, destination.lng)), travel_mode)

    def _heuristic(self, node: int, goal: int) -> float:
        # Weighted A*: 80 km/h is a practical GTA upper-average speed. This
        # strongly reduces expansions while still favoring fast arterial roads.
        return _point_distance_m(self.coords[node], self.coords[goal]) / (80 / 3.6)

    def _route_result(self, origin: Place, destination: Place, path: list[int], road_m: float, road_s: float, mode: str) -> Route:
        geometry = [(origin.lat, origin.lng)] + [self.coords[node] for node in path] + [(destination.lat, destination.lng)]
        geometry = [point for index, point in enumerate(geometry) if index == 0 or point != geometry[index - 1]]
        connector_m = _point_distance_m(geometry[0], self.coords[path[0]]) + _point_distance_m(self.coords[path[-1]], geometry[-1])
        distance = road_m + connector_m; duration = max(60, round(road_s + connector_m / 8.5))
        route_id = f"ROUTE_{stable_seed(origin.place_id, destination.place_id, mode) % 10**12:012d}"
        return Route(route_id, origin.place_id, destination.place_id, distance, duration, tuple(geometry), mode)


def route_provider_for_mode(routing_mode: str, road_network_path: str | Path | None) -> RoadNetworkRouteProvider | None:
    """Select straight-line or retained OSM routing without loading unused road data."""
    mode = routing_mode.strip().lower()
    if mode not in {"straight", "road"}:
        raise ValueError("routing_mode must be 'straight' or 'road'")
    if mode == "road" and road_network_path and Path(road_network_path).exists():
        return RoadNetworkRouteProvider(road_network_path)
    return None


class RouteCache:
    def __init__(self, provider: RouteProvider | None = None, cache_path: str | Path | None = None) -> None:
        self.provider = provider or StraightLineRouteProvider()
        self._routes: dict[tuple[str, str, str], Route] = {}
        self._by_id: dict[str, Route] = {}
        self._endpoints: dict[str, tuple[Place, Place, str]] = {}
        self._estimated: set[str] = set()
        self._lock = threading.Lock()
        self._materialize_lock = threading.Lock()
        if cache_path:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        self._database = sqlite3.connect(cache_path, check_same_thread=False) if cache_path else None
        if self._database:
            self._database.execute("CREATE TABLE IF NOT EXISTS routes (origin TEXT, destination TEXT, mode TEXT, route_id TEXT, distance REAL, duration INTEGER, geometry TEXT, PRIMARY KEY(origin,destination,mode))")

    def get_or_create(self, origin: Place, destination: Place, travel_mode: str = "car") -> Route:
        key = (origin.place_id, destination.place_id, travel_mode)
        if key not in self._routes:
            route = self._load(key)
            estimated = False
            if route is None:
                estimator = getattr(self.provider, "estimate", None)
                route = estimator(origin, destination, travel_mode) if estimator else self.provider.route(origin, destination, travel_mode)
                estimated = estimator is not None
            self._routes[key] = route
            self._by_id[route.route_id] = route
            self._endpoints[route.route_id] = (origin, destination, travel_mode)
            if estimated:
                self._estimated.add(route.route_id)
            else:
                self._store(key, route)
        return self._routes[key]

    def _load(self, key: tuple[str, str, str]) -> Route | None:
        if not self._database: return None
        with self._lock:
            row = self._database.execute("SELECT route_id,distance,duration,geometry FROM routes WHERE origin=? AND destination=? AND mode=?", key).fetchone()
        if not row: return None
        return Route(row[0], key[0], key[1], float(row[1]), int(row[2]), tuple(tuple(point) for point in json.loads(row[3])), key[2])

    def _store(self, key: tuple[str, str, str], route: Route) -> None:
        if not self._database: return
        with self._lock:
            self._database.execute("INSERT OR IGNORE INTO routes VALUES (?,?,?,?,?,?,?)",
                                   (*key, route.route_id, route.distance_m, route.duration_s, json.dumps(route.geometry, separators=(",", ":"))))

    def flush(self) -> None:
        if self._database:
            with self._lock: self._database.commit()

    def close(self) -> None:
        if self._database:
            with self._materialize_lock:
                with self._lock:
                    self._database.commit(); self._database.close(); self._database = None

    def get(self, route_id: str) -> Route:
        if route_id in self._estimated:
            self.materialize(route_id)
        return self._by_id[route_id]

    def materialize(self, route_id: str) -> Route:
        with self._materialize_lock:
            if route_id not in self._estimated:
                return self._by_id[route_id]
            origin, destination, mode = self._endpoints[route_id]
            actual = self.provider.route(origin, destination, mode)
            key = (origin.place_id, destination.place_id, mode)
            self._routes[key] = actual; self._by_id[route_id] = actual
            self._estimated.discard(route_id); self._store(key, actual)
            return actual

    def is_materialized(self, route_id: str) -> bool:
        return route_id not in self._estimated

    def all(self) -> dict[str, Route]:
        return dict(self._by_id)


def _point_distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[0] + b[0]) / 2)
    return math.hypot((a[0] - b[0]) * 111_000, (a[1] - b[1]) * 111_000 * math.cos(lat))
