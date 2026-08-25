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
    parser.add_argument("--places", type=Path, default=Path("data/places.csv"))
    parser.add_argument("--organizations", type=Path, default=Path("data/organizations.csv"))
    parser.add_argument("--memberships", type=Path, default=Path("data/person_organizations.csv"))
    parser.add_argument("--relationships", type=Path, default=Path("data/relationships.csv"))
    parser.add_argument("--family-coverage", type=float, default=.30)
    args = parser.parse_args()
    people = {row["person_id"]: row for row in read(args.population)}
    used_places = {row["home_place_id"] for row in people.values()} | {row["work_place_id"] for row in people.values()}
    places = {row["place_id"]: row for row in read(args.places) if row["place_id"] in used_places}
    organizations = {row["organization_id"]: row for row in read(args.organizations)}
    memberships = {row["person_id"]: row for row in read(args.memberships)}
    relationships = read(args.relationships)
    errors, keys, ids = [], set(), set()
    family_people, spouses = set(), Counter()
    degrees, type_counts = Counter(), Counter()
    if set(memberships) != set(people): errors.append("organization membership does not cover the population exactly")
    for person_id, membership in memberships.items():
        organization_id = membership["organization_id"]
        if organization_id not in organizations: errors.append(f"unknown organization {organization_id} for {person_id}")
        if people.get(person_id, {}).get("employer_id") != organization_id:
            errors.append(f"employer_id mismatch for {person_id}")
    if sum(int(row["member_count"]) for row in organizations.values()) != len(people):
        errors.append("organization member counts do not sum to population")
    for organization_id, organization in organizations.items():
        real_name = organization.get("is_real_name") == "true"
        if real_name and (organization["name"].startswith("Unidentified ") or not organization.get("source_url")):
            errors.append(f"invalid real-name source for {organization_id}")
        if not real_name and not organization["name"].startswith("Unidentified "):
            errors.append(f"unresolved organization lacks explicit label {organization_id}")
    for row in relationships:
        rid, a, b, kind = row["relationship_id"], row["person_id_a"], row["person_id_b"], row["relationship_type"]
        key = (a, b, kind)
        if rid in ids: errors.append(f"duplicate relationship id {rid}")
        if key in keys: errors.append(f"duplicate relationship edge {key}")
        ids.add(rid); keys.add(key); type_counts[kind] += 1
        if a == b or a not in people or b not in people: errors.append(f"invalid endpoints {rid}")
        if not row["description"].strip(): errors.append(f"missing description {rid}")
        context = row.get("relationship_context", "").strip()
        if len(context) < 120: errors.append(f"relationship context too short {rid}")
        if people[a]["姓名"] not in context or people[b]["姓名"] not in context:
            errors.append(f"relationship context lacks person names {rid}")
        relevant_place_ids = {people[a]["home_place_id"], people[b]["home_place_id"]}
        if kind == "coworker": relevant_place_ids.update((people[a]["work_place_id"], people[b]["work_place_id"]))
        relevant_names = {places[place_id]["name"] for place_id in relevant_place_ids if place_id in places}
        if relevant_names and not any(name in context for name in relevant_names):
            errors.append(f"relationship context lacks a relevant place {rid}")
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
    result = {"valid": not errors, "people": len(people), "organizations": len(organizations),
              "real_organization_names": sum(row.get("is_real_name") == "true" for row in organizations.values()),
              "relationships": len(relationships),
              "family_people": len(family_people), "family_coverage": len(family_people) / len(people),
              "types": dict(type_counts), "average_typed_degree": round(sum(degrees.values()) / len(people), 2),
              "max_typed_degree": max(degrees.values()), "isolated_people": len(people) - len(degrees),
              "errors": errors[:20], "error_count": len(errors)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors: raise SystemExit(1)


if __name__ == "__main__":
    main()
