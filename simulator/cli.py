from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from .population import load_population
from .world import WorldEngine

DEFAULT_POPULATION = Path(__file__).parents[1] / "data" / "shanghai_synthetic_population_10000.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Shanghai synthetic mobility simulator")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--population", type=Path, default=DEFAULT_POPULATION)
    generate.add_argument("--start", type=date.fromisoformat, required=True)
    generate.add_argument("--days", type=int, default=7)
    generate.add_argument("--output", type=Path)
    world = commands.add_parser("world")
    world.add_argument("--population", type=Path, default=DEFAULT_POPULATION)
    world.add_argument("--time", type=datetime.fromisoformat, required=True)
    world.add_argument("--compact", action="store_true")
    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("--population", type=Path, default=DEFAULT_POPULATION)
    benchmark.add_argument("--time", type=datetime.fromisoformat, default=datetime.fromisoformat("2026-08-24T18:30:00"))
    args = parser.parse_args()

    people = load_population(args.population)
    engine = WorldEngine()
    start = args.start if args.command == "generate" else args.time.date()
    days = args.days if args.command == "generate" else 1
    before = time.perf_counter()
    schedules = engine.generate_population_period(people, start, days)
    generation_s = time.perf_counter() - before
    if args.command == "generate":
        summary = {"people": len(people), "days": days, "events": sum(map(len, schedules.values())),
                   "generation_seconds": round(generation_s, 3), "places": len(engine.schedule.places.provider.all()),
                   "routes": len(engine.schedule.routes.all())}
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
                          "get_world_seconds": round(elapsed, 6), "locations_per_second": round(len(people) / elapsed)}))


if __name__ == "__main__":
    main()
