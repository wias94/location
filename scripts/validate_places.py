"""Validate place coverage, assignment compatibility and concentration."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

try:
    from scripts.assign_places import HOME_DISTRICTS, JOB_CATEGORIES, WORK_CATEGORIES
except ModuleNotFoundError:
    from assign_places import HOME_DISTRICTS, JOB_CATEGORIES, WORK_CATEGORIES


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population", type=Path, default=Path("data/gta_synthetic_population_10000.csv"))
    parser.add_argument("--places", type=Path, default=Path("data/places.csv"))
    parser.add_argument("--bindings", type=Path, default=Path("data/person_places.csv"))
    args = parser.parse_args()
    with args.population.open(encoding="utf-8-sig", newline="") as f:
        people = {row["person_id"]: row for row in csv.DictReader(f)}
    with args.places.open(encoding="utf-8-sig", newline="") as f:
        places = {row["place_id"]: row for row in csv.DictReader(f)}
    roles = defaultdict(dict)
    occupancy = Counter()
    with args.bindings.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            roles[row["person_id"]][row["place_role"]] = row["place_id"]
            occupancy[(row["place_role"], row["place_id"])] += 1
    errors = []
    for pid, person in people.items():
        assigned = roles[pid]
        home = places.get(assigned.get("HOME", ""))
        work_role = "UNIVERSITY" if person["occupation_code"] == "university_student" else "WORK"
        work = places.get(assigned.get(work_role, ""))
        if not home or home["category"] != "residential" or home["district"] not in HOME_DISTRICTS:
            errors.append(f"{pid}: invalid HOME")
        if not work:
            errors.append(f"{pid}: missing {work_role}")
        else:
            allowed = set(JOB_CATEGORIES.get(person["具体职位"], WORK_CATEGORIES[person["occupation_code"]]))
            if person["occupation_code"] == "freelancer": allowed.add("residential")
            if work["category"] not in allowed:
                errors.append(f"{pid}: {person['具体职位']} assigned to {work['category']}")
        if person["家庭状态"] == "有未成年孩子":
            school = places.get(assigned.get("CHILD_SCHOOL", ""))
            if not school or school["category"] not in {"school", "kindergarten", "childcare"}:
                errors.append(f"{pid}: invalid CHILD_SCHOOL")
            elif home and school["district"] != home["district"]:
                errors.append(f"{pid}: child school outside home district")
    home_districts = Counter(places[roles[pid]["HOME"]]["district"] for pid in people if "HOME" in roles[pid])
    top_homes = [{"place_id": place_id, "people": count, "name": places[place_id]["name"]}
                 for (role, place_id), count in occupancy.most_common() if role == "HOME"][:10]
    result = {"valid": not errors, "people": len(people), "places": len(places),
              "home_districts": dict(home_districts), "unique_homes": sum(1 for role, _ in occupancy if role == "HOME"),
              "top_homes": top_homes, "errors": errors[:20], "error_count": len(errors)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
