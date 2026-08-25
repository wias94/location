"""Build stable employer organizations from cached OpenStreetMap places.

Organization names are resolved once during data preparation. Runtime location
requests only read the resulting CSV files and never call an external service.
"""
from __future__ import annotations

import csv
import hashlib
import math
import random
import re
from collections import defaultdict
from pathlib import Path

try:
    from scripts.assign_places import JOB_CATEGORIES, WORK_CATEGORIES
except ModuleNotFoundError:  # Direct execution from scripts/
    from assign_places import JOB_CATEGORIES, WORK_CATEGORIES


EARTH_RADIUS_M = 6_371_008.8
GRID_DEGREES = .002
PLACEHOLDER_PREFIX = "OSM "
ADDRESS_LABEL = re.compile(r"^\d+[A-Za-z]?(?:[-/]\d+)?\s+\S+")
ORGANIZATION_CATEGORIES = {
    "office", "commercial", "industrial", "restaurant", "cafe", "bar",
    "retail", "hotel", "supermarket", "gym", "university", "college",
}
MATCH_RADIUS_M = {"industrial": 120, "commercial": 100, "office": 80}


def seeded_rng(*parts: object) -> random.Random:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def is_verified_osm_name(place: dict[str, str]) -> bool:
    """True when OSM supplied a name rather than our generated fallback label."""
    name = (place.get("name") or "").strip()
    if not name or name.startswith(PLACEHOLDER_PREFIX):
        return False
    # The place extractor uses a street address as a fallback when name=* is
    # absent. Keep the useful label, but do not claim it is a company name.
    if ADDRESS_LABEL.match(name) and place.get("category") in {"residential", "commercial", "industrial", "office"}:
        return False
    return True


def distance_m(a: dict[str, str], b: dict[str, str]) -> float:
    lat1, lng1, lat2, lng2 = map(float, (a["lat"], a["lng"], b["lat"], b["lng"]))
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    value = (math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) *
             math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def osm_url(place: dict[str, str]) -> str:
    osm_id = place.get("osm_id", "")
    kind = {"N": "node", "W": "way", "R": "relation"}.get(osm_id[:1])
    return f"https://www.openstreetmap.org/{kind}/{osm_id[1:]}" if kind and osm_id[1:].isdigit() else ""


class NamedPlaceIndex:
    """Small spatial index over named organization-like OSM places."""

    def __init__(self, places: dict[str, dict[str, str]]) -> None:
        self.grid: dict[tuple[int, int], list[dict[str, str]]] = defaultdict(list)
        for place in places.values():
            if place.get("category") not in ORGANIZATION_CATEGORIES or not is_verified_osm_name(place):
                continue
            self.grid[self._cell(place)].append(place)

    @staticmethod
    def _cell(place: dict[str, str]) -> tuple[int, int]:
        return math.floor(float(place["lat"]) / GRID_DEGREES), math.floor(float(place["lng"]) / GRID_DEGREES)

    def candidates(self, workplace: dict[str, str], person: dict[str, str]) -> list[tuple[float, dict[str, str]]]:
        if workplace.get("category") == "residential":
            return []
        allowed = set(JOB_CATEGORIES.get(person.get("具体职位", ""),
                                         WORK_CATEGORIES.get(person.get("occupation_code", ""), ())))
        if not allowed:
            allowed.add(workplace.get("category", ""))
        radius = MATCH_RADIUS_M.get(workplace.get("category", ""), 60)
        row, column = self._cell(workplace)
        matches = []
        for row_delta in range(-2, 3):
            for column_delta in range(-2, 3):
                for candidate in self.grid.get((row + row_delta, column + column_delta), ()):
                    if candidate["place_id"] == workplace["place_id"] or candidate.get("category") not in allowed:
                        continue
                    separation = distance_m(workplace, candidate)
                    if separation <= radius:
                        matches.append((separation, candidate))
        return sorted(matches, key=lambda item: (item[0], item[1]["place_id"]))


def _nearby_match(index: NamedPlaceIndex, workplace: dict[str, str], person: dict[str, str]) -> tuple[dict[str, str] | None, float]:
    matches = index.candidates(workplace, person)
    if not matches:
        return None, 0
    nearest = matches[0][0]
    # Several real tenants may occupy one commercial building. Distribute the
    # simulated workers deterministically among similarly close candidates.
    plausible = [item for item in matches[:8] if item[0] <= nearest + 20]
    separation, candidate = seeded_rng(person["person_id"], workplace["place_id"], "employer").choice(plausible)
    return candidate, separation


def _organization_id(key: str, resolved: bool) -> str:
    if key.startswith("PL_"):
        return f"ORG_{key[3:]}" if resolved else f"ORG_UNRES_{key[3:]}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:12].upper()
    return f"ORG_{digest}"


def make_organizations(people: dict[str, dict[str, str]], places: dict[str, dict[str, str]],
                       all_places: dict[str, dict[str, str]] | None = None) -> tuple[list[dict], list[dict]]:
    """Create organizations and memberships, using verified OSM names when possible."""
    all_places = all_places or places
    named_index = NamedPlaceIndex(all_places)
    assignments: dict[str, list[dict]] = defaultdict(list)
    metadata: dict[str, dict] = {}

    for person in people.values():
        workplace = places[person["work_place_id"]]
        if is_verified_osm_name(workplace):
            resolved_place, separation, name_source = workplace, 0.0, "osm_name"
        else:
            resolved_place, separation = _nearby_match(named_index, workplace, person)
            name_source = "osm_nearby_name" if resolved_place else "unresolved_osm"
        key = resolved_place["place_id"] if resolved_place else workplace["place_id"]
        resolved = resolved_place is not None
        group_key = f"resolved:{key}" if resolved else f"unresolved:{key}"
        assignments[group_key].append({"person": person, "workplace": workplace,
                                       "resolved_place": resolved_place, "distance": separation,
                                       "name_source": name_source})
        if group_key not in metadata or name_source == "osm_name":
            metadata[group_key] = {"key": key, "resolved": resolved, "name_source": name_source}

    organizations, memberships = [], []
    for group_key in sorted(assignments):
        assigned = assignments[group_key]
        meta = metadata[group_key]
        resolved_place = assigned[0]["resolved_place"]
        source_place = resolved_place or assigned[0]["workplace"]
        resolved = bool(meta["resolved"])
        org_id = _organization_id(meta["key"], resolved)
        members = [item["person"] for item in assigned]
        org_type = "university" if all(p["occupation_code"] == "university_student" for p in members) else source_place["category"]
        if resolved:
            name = source_place["name"]
            max_resolved_distance = max(item["distance"] for item in assigned)
            confidence = "verified" if max_resolved_distance == 0 else (
                "high" if max_resolved_distance <= 25 else "medium")
            description = (f"OpenStreetMap name cached during data preparation: {name}. "
                           "No external company lookup occurs during runtime.")
        else:
            label = source_place["name"] if not source_place["name"].startswith(PLACEHOLDER_PREFIX) else source_place["osm_id"]
            name = f"Unidentified {org_type.title()} at {label}"
            confidence = "unresolved"
            description = ("OSM records the workplace location and category but no verified organization name; "
                           "the explicit placeholder is retained instead of inventing a company.")
        team_size = 24 if org_type == "university" else (10 if org_type in {"office", "commercial", "industrial"} else 8)
        ordered = sorted(assigned, key=lambda item: item["person"]["person_id"])
        seeded_rng(org_id, "teams").shuffle(ordered)
        for offset, item in enumerate(ordered):
            person = item["person"]
            member_confidence = ("verified" if item["name_source"] == "osm_name" else
                                 ("high" if item["distance"] <= 25 else "medium")) if resolved else "unresolved"
            memberships.append({"person_id": person["person_id"], "organization_id": org_id,
                                "team_id": f"{org_id}_T{offset // team_size + 1:03d}",
                                "member_role": person["具体职位"], "work_place_id": item["workplace"]["place_id"],
                                "match_distance_m": f"{item['distance']:.1f}" if item["resolved_place"] and item["distance"] else "0.0",
                                "match_confidence": member_confidence})
        work_place_ids = sorted({item["workplace"]["place_id"] for item in assigned})
        max_distance = max(item["distance"] for item in assigned)
        organizations.append({"organization_id": org_id, "name": name, "organization_type": org_type,
            "place_id": source_place["place_id"], "district": source_place["district"],
            "member_count": len(members), "team_count": math.ceil(len(members) / team_size),
            "employee_capacity": source_place.get("capacity_weight", ""), "name_source": meta["name_source"],
            "is_real_name": str(resolved).lower(), "match_confidence": confidence,
            "max_match_distance_m": f"{max_distance:.1f}", "work_place_count": len(work_place_ids),
            "source": "OpenStreetMap", "source_id": source_place.get("osm_id", ""),
            "source_url": osm_url(source_place), "description": description})
    return organizations, sorted(memberships, key=lambda row: row["person_id"])


def write_population_with_employers(path: Path, rows: list[dict[str, str]], memberships: list[dict]) -> None:
    """Atomically add the stable employer_id mapping to the runtime population CSV."""
    employers = {row["person_id"]: row["organization_id"] for row in memberships}
    fields = list(rows[0]) if rows else []
    if "employer_id" not in fields:
        position = fields.index("personality_summary") if "personality_summary" in fields else len(fields)
        fields.insert(position, "employer_id")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for original in rows:
            row = dict(original)
            row["employer_id"] = employers.get(row["person_id"], "")
            writer.writerow(row)
    temporary.replace(path)
