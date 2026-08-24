"""Download real OpenStreetMap places for Markham and Scarborough.

Produces data/places.csv. Uses Nominatim only to resolve administrative
boundaries and Overpass for the actual buildings and POIs. Responses are
cached per area and category so an interrupted download can resume.
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS_ENDPOINTS = (
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
)
USER_AGENT = "gta-synthetic-mobility/1.0 (local research project)"
AREAS = {
    "Brampton": "Brampton, Peel Region, Ontario, Canada",
    "Vaughan": "Vaughan, York Region, Ontario, Canada",
    "Richmond Hill": "Richmond Hill, York Region, Ontario, Canada",
    "Markham": "Markham, York Region, Ontario, Canada",
    "North York": "North York, Toronto, Ontario, Canada",
    "Scarborough": "Scarborough, Toronto, Ontario, Canada",
    "Old Toronto": "Old Toronto, Toronto, Ontario, Canada",
}
HOME_AREAS = {"Markham", "Scarborough"}

QUERY_BATCHES = {
    "work": (
        'nwr[building~"office|commercial|warehouse|industrial"](area.a);'
        'nwr[landuse~"commercial|industrial"](area.a);nwr[office](area.a);'
        'nwr[tourism~"hotel|motel|hostel"](area.a);'
    ),
    "amenity": (
        'nwr[amenity~"school|kindergarten|childcare|university|college|restaurant|fast_food|food_court|cafe|bar|pub|nightclub|hospital|clinic|doctors|pharmacy|cinema"](area.a);'
    ),
    "shop": 'nwr[shop](area.a);',
    "leisure": 'nwr[leisure~"fitness_centre|sports_centre|park"](area.a);',
    "home": (
        'nwr[building~"apartments|residential|dormitory"](area.a);'
        'nwr[landuse="residential"][name](area.a);'
    ),
}


def request_json(url: str, data: bytes | None = None) -> object:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=35) as response:
        return json.load(response)


def resolve_relation(query: str) -> int:
    params = urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 5})
    results = request_json(f"{NOMINATIM}?{params}")
    for result in results:
        if result.get("osm_type") == "relation":
            return int(result["osm_id"])
    raise RuntimeError(f"No OSM boundary relation found for {query}")


def overpass_elements(relation_id: int, statements: str) -> list[dict]:
    area_id = 3_600_000_000 + relation_id
    query = f"""[out:json][timeout:60];
area({area_id})->.a;
({statements});
out center tags;"""
    payload = urllib.parse.urlencode({"data": query}).encode()
    errors = []
    for delay in (0,):
        if delay:
            time.sleep(delay)
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                return request_json(endpoint, payload)["elements"]
            except Exception as error:
                errors.append(f"{endpoint}: {error}")
                time.sleep(3)
    raise RuntimeError("All Overpass endpoints failed:\n" + "\n".join(errors))


def category(tags: dict[str, str]) -> str | None:
    amenity, building, landuse = tags.get("amenity"), tags.get("building"), tags.get("landuse")
    shop, leisure, tourism, office = tags.get("shop"), tags.get("leisure"), tags.get("tourism"), tags.get("office")
    if amenity in {"school", "kindergarten", "childcare", "university", "college"}: return amenity
    if amenity in {"restaurant", "fast_food", "food_court"}: return "restaurant"
    if amenity == "cafe": return "cafe"
    if amenity in {"bar", "pub", "nightclub"}: return "bar"
    if amenity in {"hospital", "clinic", "doctors"}: return "hospital"
    if amenity == "pharmacy": return "pharmacy"
    if amenity == "cinema": return "cinema"
    if tourism in {"hotel", "motel", "hostel"}: return "hotel"
    if leisure in {"fitness_centre", "sports_centre"}: return "gym"
    if leisure == "park": return "park"
    if shop == "supermarket": return "supermarket"
    if shop: return "retail"
    if office or building == "office": return "office"
    if building in {"warehouse", "industrial"} or landuse == "industrial": return "industrial"
    if building == "commercial" or landuse == "commercial": return "commercial"
    if building in {"apartments", "residential", "house", "detached", "terrace", "dormitory"} or landuse == "residential": return "residential"
    return None


def capacity_weight(kind: str, tags: dict[str, str]) -> int:
    levels = int(float(tags.get("building:levels", "0"))) if tags.get("building:levels", "").replace(".", "", 1).isdigit() else 0
    building = tags.get("building")
    if kind == "residential":
        if tags.get("landuse") == "residential": return 300
        if building == "apartments": return min(1000, 40 * max(1, levels))
        if building == "dormitory": return min(1000, 100 * max(1, levels))
        if building in {"house", "detached", "semidetached_house", "terrace"}: return max(1, 2 * max(1, levels))
        return min(1000, 15 * max(1, levels))
    base = {"residential": 30, "office": 80, "commercial": 60, "industrial": 70,
            "university": 200, "school": 80, "college": 120, "kindergarten": 30,
            "childcare": 25, "hotel": 40, "retail": 15, "supermarket": 35,
            "restaurant": 12, "cafe": 8, "gym": 20}.get(kind, 10)
    return min(1000, base * max(1, levels))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/places.csv"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/osm_cache"))
    parser.add_argument("--area", choices=tuple(AREAS), action="append", help="download only selected areas")
    parser.add_argument("--batch", choices=tuple(QUERY_BATCHES), action="append", help="download only selected batches")
    parser.add_argument("--cache-only", action="store_true", help="merge available caches without network downloads")
    parser.add_argument("--resolve-only", action="store_true", help="print resolved OSM relation IDs and exit")
    args = parser.parse_args()
    rows: dict[str, dict] = {}
    failures = []
    selected = args.area or list(AREAS)
    relations = {}
    if not args.cache_only:
        for district in selected:
            relations[district] = resolve_relation(AREAS[district])
            print(f"resolved {district}: relation {relations[district]}")
            time.sleep(1)
    if args.resolve_only:
        return
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    for district in selected:
        relation_id = relations.get(district)
        batches = args.batch or (["work", "amenity", "shop", "leisure"] + (["home"] if district in HOME_AREAS else []))
        batches = [batch for batch in batches if batch != "home" or district in HOME_AREAS]
        elements = []
        for batch in batches:
            cache_path = args.cache_dir / f"{district.lower().replace(' ', '_')}_{batch}.json"
            if cache_path.exists():
                batch_elements = json.loads(cache_path.read_text(encoding="utf-8"))
                print(f"cached {district}/{batch}: {len(batch_elements)}")
            else:
                if args.cache_only:
                    failures.append(f"{district}/{batch}")
                    continue
                try:
                    batch_elements = overpass_elements(relation_id, QUERY_BATCHES[batch])
                except RuntimeError as error:
                    failures.append(f"{district}/{batch}")
                    print(f"skipped {district}/{batch}: {str(error).splitlines()[1]}")
                    continue
                else:
                    cache_path.write_text(json.dumps(batch_elements, ensure_ascii=False), encoding="utf-8")
                    print(f"downloaded {district}/{batch}: {len(batch_elements)}")
                    time.sleep(8)
            elements.extend(batch_elements)
        for item in elements:
            tags = item.get("tags", {})
            kind = category(tags)
            point = item.get("center", item)
            if not kind or "lat" not in point or "lon" not in point:
                continue
            osm_key = f"{item['type'][0].upper()}{item['id']}"
            rows[osm_key] = {"place_id": f"PL_{osm_key}", "name": tags.get("name") or tags.get("addr:housename") or f"OSM {kind} {osm_key}",
                "category": kind, "lat": point["lat"], "lng": point["lon"], "district": district,
                "osm_id": osm_key, "capacity_weight": capacity_weight(kind, tags)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["place_id", "name", "category", "lat", "lng", "district", "osm_id", "capacity_weight"])
        writer.writeheader(); writer.writerows(sorted(rows.values(), key=lambda row: row["place_id"]))
    print(json.dumps({"places": len(rows), "output": str(args.output), "incomplete_batches": failures}, ensure_ascii=False))


if __name__ == "__main__":
    main()
