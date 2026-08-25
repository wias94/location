from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from .population import load_population
from .places import CsvPlaceProvider, PlaceResolver
from .behavior import ScheduleEngine
from .routes import RouteCache, route_provider_for_mode
from .world import WorldEngine

DEFAULT_POPULATION = Path(__file__).parents[1] / "data" / "gta_population_with_places.csv"
DEFAULT_PLACES = Path(__file__).parents[1] / "data" / "places.csv"
DEFAULT_RELATIONSHIPS = Path(__file__).parents[1] / "data" / "relationships.csv"
DEFAULT_EXTERNAL_CONTACTS = Path(__file__).parents[1] / "data" / "external_contacts.csv"
DEFAULT_ROAD_NETWORK = Path(__file__).parents[1] / "data" / "road_network.pkl"
DEFAULT_ROUTE_CACHE = Path(__file__).parents[1] / "work" / "routes.sqlite"
DEFAULT_ROUTING_MODE = os.getenv("ROUTING_MODE", "straight")


def world_engine(places_path: Path, people, relationships_path: Path, external_contacts_path: Path,
                 road_network_path: Path, route_cache_path: Path, routing_mode: str) -> WorldEngine:
    by_id = {person.person_id: person for person in people}
    provider = route_provider_for_mode(routing_mode, road_network_path)
    routes = RouteCache(provider, route_cache_path) if provider else RouteCache()
    return WorldEngine(ScheduleEngine(places=PlaceResolver(CsvPlaceProvider.from_file(places_path),
                                                           people=by_id, relationships_path=relationships_path,
                                                           external_contacts_path=external_contacts_path), routes=routes))


def main() -> None:
    parser = argparse.ArgumentParser(description="Greater Toronto Area synthetic mobility simulator")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--population", type=Path, default=DEFAULT_POPULATION)
    generate.add_argument("--places", type=Path, default=DEFAULT_PLACES)
    generate.add_argument("--relationships", type=Path, default=DEFAULT_RELATIONSHIPS)
    generate.add_argument("--external-contacts", type=Path, default=DEFAULT_EXTERNAL_CONTACTS)
    generate.add_argument("--road-network", type=Path, default=DEFAULT_ROAD_NETWORK)
    generate.add_argument("--route-cache", type=Path, default=DEFAULT_ROUTE_CACHE)
    generate.add_argument("--routing-mode", choices=("straight", "road"), default=DEFAULT_ROUTING_MODE)
    generate.add_argument("--start", type=date.fromisoformat, required=True)
    generate.add_argument("--days", type=int, default=1)
    generate.add_argument("--output", type=Path)
    world = commands.add_parser("world")
    world.add_argument("--population", type=Path, default=DEFAULT_POPULATION)
    world.add_argument("--places", type=Path, default=DEFAULT_PLACES)
    world.add_argument("--relationships", type=Path, default=DEFAULT_RELATIONSHIPS)
    world.add_argument("--external-contacts", type=Path, default=DEFAULT_EXTERNAL_CONTACTS)
    world.add_argument("--road-network", type=Path, default=DEFAULT_ROAD_NETWORK)
    world.add_argument("--route-cache", type=Path, default=DEFAULT_ROUTE_CACHE)
    world.add_argument("--routing-mode", choices=("straight", "road"), default=DEFAULT_ROUTING_MODE)
    world.add_argument("--time", type=datetime.fromisoformat, required=True)
    world.add_argument("--compact", action="store_true")
    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("--population", type=Path, default=DEFAULT_POPULATION)
    benchmark.add_argument("--places", type=Path, default=DEFAULT_PLACES)
    benchmark.add_argument("--relationships", type=Path, default=DEFAULT_RELATIONSHIPS)
    benchmark.add_argument("--external-contacts", type=Path, default=DEFAULT_EXTERNAL_CONTACTS)
    benchmark.add_argument("--road-network", type=Path, default=DEFAULT_ROAD_NETWORK)
    benchmark.add_argument("--route-cache", type=Path, default=DEFAULT_ROUTE_CACHE)
    benchmark.add_argument("--routing-mode", choices=("straight", "road"), default=DEFAULT_ROUTING_MODE)
    benchmark.add_argument("--time", type=datetime.fromisoformat, default=datetime.fromisoformat("2026-08-24T18:30:00"))
    args = parser.parse_args()

    people = load_population(args.population)
    engine = world_engine(args.places, people, args.relationships, args.external_contacts,
                          args.road_network, args.route_cache, args.routing_mode)
    start = args.start if args.command == "generate" else args.time.date()
    days = args.days if args.command == "generate" else 1
    before = time.perf_counter()
    schedules = engine.generate_population_period(people, start, days)
    generation_s = time.perf_counter() - before
    if args.command == "generate":
        summary = {"people": len(people), "days": days, "events": sum(map(len, schedules.values())),
                   "generation_seconds": round(generation_s, 3), "places": len(engine.schedule.places.provider.all()),
                   "routes": len(engine.schedule.routes.all()), "routing_mode": args.routing_mode}
        if args.output:
            with args.output.open("w", encoding="utf-8") as handle:
                for events in schedules.values():
                    for event in events:
                        row = asdict(event)
                        row["start_time"], row["end_time"] = event.start_time.isoformat(), event.end_time.isoformat()
                        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps(summary))
    elif args.command == "world":
        print(json.dumps(engine.get_world(args.time), ensure_ascii=False, separators=(",", ":") if args.compact else None))
    else:
        before = time.perf_counter()
        result = engine.get_world(args.time)
        elapsed = time.perf_counter() - before
        print(json.dumps({"people": len(result["people"]), "generation_seconds": round(generation_s, 3),
                          "get_world_seconds": round(elapsed, 6), "locations_per_second": round(len(people) / elapsed),
                          "routing_mode": args.routing_mode}))


if __name__ == "__main__":
    main()
