"""Validate generated organizations and sparse relationship edges."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

FAMILY_TYPES = {"spouse", "parent_of", "sibling", "extended_family"}


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population", type=Path, default=Path("data/gta_population_with_places.csv"))
    parser.add_argument("--memberships", type=Path, default=Path("data/person_organizations.csv"))
    parser.add_argument("--relationships", type=Path, default=Path("data/relationships.csv"))
    parser.add_argument("--family-coverage", type=float, default=.30)
    args = parser.parse_args()
    people = {row["person_id"]: row for row in read(args.population)}
    memberships = {row["person_id"]: row for row in read(args.memberships)}
    relationships = read(args.relationships)
    errors, keys, ids = [], set(), set()
    family_people, spouses = set(), Counter()
    degrees, type_counts = Counter(), Counter()
    for row in relationships:
        rid, a, b, kind = row["relationship_id"], row["person_id_a"], row["person_id_b"], row["relationship_type"]
        key = (a, b, kind)
        if rid in ids: errors.append(f"duplicate relationship id {rid}")
        if key in keys: errors.append(f"duplicate relationship edge {key}")
        ids.add(rid); keys.add(key); type_counts[kind] += 1
        if a == b or a not in people or b not in people: errors.append(f"invalid endpoints {rid}")
        if not row["description"].strip(): errors.append(f"missing description {rid}")
        degrees[a] += 1; degrees[b] += 1
        if kind in FAMILY_TYPES: family_people.update((a, b))
        if kind == "spouse":
            spouses[a] += 1; spouses[b] += 1
            if people[a]["home_place_id"] != people[b]["home_place_id"]: errors.append(f"spouses do not share HOME {rid}")
        elif kind == "parent_of":
            if int(people[a]["年龄"]) - int(people[b]["年龄"]) < 18: errors.append(f"invalid parent age gap {rid}")
            if people[a]["home_place_id"] == people[b]["home_place_id"]: errors.append(f"adult child shares HOME {rid}")
        elif kind == "sibling":
            if abs(int(people[a]["年龄"]) - int(people[b]["年龄"])) > 15: errors.append(f"invalid sibling age gap {rid}")
            if people[a]["home_place_id"] == people[b]["home_place_id"]: errors.append(f"adult siblings share HOME {rid}")
        elif kind == "coworker":
            if memberships[a]["organization_id"] != memberships[b]["organization_id"]: errors.append(f"coworkers differ in organization {rid}")
        elif kind in {"neighbor", "housemate"}:
            if people[a]["home_place_id"] != people[b]["home_place_id"]: errors.append(f"invalid shared-home relation {rid}")
    if any(count > 1 for count in spouses.values()): errors.append("a person has multiple spouse relationships")
    expected_family = round(len(people) * args.family_coverage)
    if len(family_people) != expected_family: errors.append(f"family coverage is {len(family_people)}, expected {expected_family}")
    result = {"valid": not errors, "people": len(people), "relationships": len(relationships),
              "family_people": len(family_people), "family_coverage": len(family_people) / len(people),
              "types": dict(type_counts), "average_typed_degree": round(sum(degrees.values()) / len(people), 2),
              "max_typed_degree": max(degrees.values()), "isolated_people": len(people) - len(degrees),
              "errors": errors[:20], "error_count": len(errors)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors: raise SystemExit(1)


if __name__ == "__main__":
    main()
