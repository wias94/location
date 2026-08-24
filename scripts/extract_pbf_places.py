"""Extract simulation-ready places from a local OpenStreetMap PBF file."""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import osmium

try:
    from scripts.build_gta_places import capacity_weight, category
except ModuleNotFoundError:  # Direct execution: python scripts/extract_pbf_places.py
    from build_gta_places import capacity_weight, category

CITY_CENTRES = {
    "Brampton": (43.7315, -79.7624),
    "Vaughan": (43.8372, -79.5083),
    "Richmond Hill": (43.8828, -79.4403),
    "Markham": (43.8561, -79.3370),
    "North York": (43.7615, -79.4111),
    "Scarborough": (43.7764, -79.2318),
    "Old Toronto": (43.6532, -79.3832),
}
RELEVANT_TAGS = ("building", "landuse", "office", "shop", "amenity", "tourism", "leisure")


def district_for(lat: float, lng: float, tags: dict[str, str]) -> str:
    labelled = " ".join(tags.get(key, "") for key in ("addr:city", "addr:suburb", "is_in:city"))
    for district in CITY_CENTRES:
        if district.lower() in labelled.lower():
            return district
    # Longitude distances shrink at this latitude; scale before comparing.
    return min(CITY_CENTRES, key=lambda name: (lat - CITY_CENTRES[name][0]) ** 2 +
               ((lng - CITY_CENTRES[name][1]) * math.cos(math.radians(lat))) ** 2)


def display_name(tags: dict[str, str], kind: str, osm_key: str) -> str:
    if tags.get("name"):
        return tags["name"]
    address = " ".join(filter(None, (tags.get("addr:housenumber"), tags.get("addr:street"))))
    return address or f"OSM {kind} {osm_key}"


class PlaceHandler(osmium.SimpleHandler):
    def __init__(self, writer: csv.DictWriter) -> None:
        super().__init__()
        self.writer = writer
        self.count = 0

    def emit(self, osm_key: str, tags: dict[str, str], lat: float, lng: float) -> None:
        kind = category(tags)
        if not kind:
            return
        self.writer.writerow({
            "place_id": f"PL_{osm_key}", "name": display_name(tags, kind, osm_key),
            "category": kind, "lat": f"{lat:.7f}", "lng": f"{lng:.7f}",
            "district": district_for(lat, lng, tags), "osm_id": osm_key,
            "capacity_weight": capacity_weight(kind, tags),
            "subtype": tags.get("building") or tags.get("landuse") or tags.get("amenity") or tags.get("shop") or "",
        })
        self.count += 1

    def node(self, node) -> None:
        if node.location.valid() and any(key in node.tags for key in RELEVANT_TAGS):
            self.emit(f"N{node.id}", dict(node.tags), node.location.lat, node.location.lon)

    def way(self, way) -> None:
        if not any(key in way.tags for key in RELEVANT_TAGS):
            return
        points = [(node.lat, node.lon) for node in way.nodes if node.location.valid()]
        if points:
            self.emit(f"W{way.id}", dict(way.tags),
                      sum(point[0] for point in points) / len(points),
                      sum(point[1] for point in points) / len(points))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pbf", type=Path, default=Path("data/gta-mobility.osm.pbf"))
    parser.add_argument("--output", type=Path, default=Path("data/places.csv"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["place_id", "name", "category", "subtype", "lat", "lng", "district", "osm_id", "capacity_weight"]
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        handler = PlaceHandler(writer)
        handler.apply_file(str(args.pbf), locations=True, idx="flex_mem")
    print({"places": handler.count, "output": str(args.output)})


if __name__ == "__main__":
    main()
