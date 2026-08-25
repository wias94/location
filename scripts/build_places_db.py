"""Build the read-only runtime SQLite place index from places.csv."""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sqlite3
from pathlib import Path


SCHEMA_VERSION = "2"
ACTIVITY_CATEGORIES = {
    "restaurant", "cafe", "bar", "cinema", "retail", "supermarket", "gym", "park",
    "hospital", "pharmacy", "school", "childcare", "kindergarten", "university", "college", "hotel",
}
GRID_DEGREES = .02


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_places_database(source: str | Path, output: str | Path) -> int:
    source_path, output_path = Path(source), Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()

    database = sqlite3.connect(temporary)
    count = 0
    try:
        database.executescript("""
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            PRAGMA temp_store=MEMORY;
            PRAGMA page_size=4096;
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            ) WITHOUT ROWID;
            CREATE TABLE places (
                id INTEGER PRIMARY KEY,
                place_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                osm_id TEXT
            );
            CREATE VIRTUAL TABLE place_rtree USING rtree(
                id,
                min_lat, max_lat,
                min_lng, max_lng
            );
            CREATE TABLE activity_places (
                place_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                osm_id TEXT,
                grid_y INTEGER NOT NULL,
                grid_x INTEGER NOT NULL
            ) WITHOUT ROWID;
        """)
        with source_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = csv.DictReader(handle)
            batch: list[tuple[int, str, str, str, float, float, str | None]] = []
            spatial: list[tuple[int, float, float, float, float]] = []
            activities: list[tuple[str, str, str, float, float, str | None, int, int]] = []
            for count, row in enumerate(rows, 1):
                lat, lng = float(row["lat"]), float(row["lng"])
                batch.append((count, row["place_id"], row["name"], row["category"], lat, lng,
                              row.get("osm_id") or None))
                spatial.append((count, lat, lat, lng, lng))
                if row["category"] in ACTIVITY_CATEGORIES:
                    activities.append((row["place_id"], row["name"], row["category"], lat, lng,
                                       row.get("osm_id") or None, int(lat // GRID_DEGREES), int(lng // GRID_DEGREES)))
                if len(batch) >= 10_000:
                    database.executemany("INSERT INTO places VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
                    database.executemany("INSERT INTO place_rtree VALUES (?, ?, ?, ?, ?)", spatial)
                    database.executemany("INSERT INTO activity_places VALUES (?, ?, ?, ?, ?, ?, ?, ?)", activities)
                    batch.clear(); spatial.clear(); activities.clear()
            if batch:
                database.executemany("INSERT INTO places VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
                database.executemany("INSERT INTO place_rtree VALUES (?, ?, ?, ?, ?)", spatial)
                database.executemany("INSERT INTO activity_places VALUES (?, ?, ?, ?, ?, ?, ?, ?)", activities)
        database.execute("CREATE INDEX activity_places_grid_idx ON activity_places(category, grid_y, grid_x)")
        database.executemany("INSERT INTO metadata VALUES (?, ?)", (
            ("schema_version", SCHEMA_VERSION),
            ("source_file", source_path.name),
            ("source_sha256", _sha256(source_path)),
            ("place_count", str(count)),
        ))
        database.commit()
        database.execute("PRAGMA optimize")
        database.execute("VACUUM")
    finally:
        database.close()
    os.replace(temporary, output_path)
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/places.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/places.sqlite"))
    args = parser.parse_args()
    count = build_places_database(args.input, args.output)
    print({"places": count, "output": str(args.output)})


if __name__ == "__main__":
    main()
