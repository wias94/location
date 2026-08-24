"""Validate personality coverage, ranges, diversity, and merged-column ordering."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

try:
    from scripts.generate_personality_profiles import PROFILE_FIELDS, TRAIT_FIELDS
except ModuleNotFoundError:
    from generate_personality_profiles import PROFILE_FIELDS, TRAIT_FIELDS


def rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population", type=Path, default=Path("data/gta_population_with_places.csv"))
    parser.add_argument("--profiles", type=Path, default=Path("data/person_behavior_profiles.csv"))
    args = parser.parse_args()
    population_fields, population = rows(args.population)
    profile_fields, profiles = rows(args.profiles)
    errors: list[str] = []
    population_ids = {row["person_id"] for row in population}
    profile_ids = [row["person_id"] for row in profiles]
    if len(profile_ids) != len(set(profile_ids)):
        errors.append("duplicate person_id in profiles")
    if set(profile_ids) != population_ids:
        errors.append("profile IDs do not match population")
    if profile_fields != ["person_id", *PROFILE_FIELDS]:
        errors.append("unexpected profile field order")
    if population_fields[-1:] != ["personality_summary"]:
        errors.append("personality_summary is not the final population column")
    for row in profiles:
        for field in TRAIT_FIELDS:
            try:
                value = float(row[field])
            except ValueError:
                errors.append(f"{row['person_id']}: invalid {field}"); continue
            if not 0 <= value <= 1:
                errors.append(f"{row['person_id']}: {field} outside 0..1")
        if not 35 <= len(row["personality_summary"]) <= 220:
            errors.append(f"{row['person_id']}: invalid summary length")
    distinct_vectors = len({tuple(row[field] for field in TRAIT_FIELDS) for row in profiles})
    if distinct_vectors < len(profiles) * .95:
        errors.append("personality vectors are insufficiently diverse")
    means = {field: round(sum(float(row[field]) for row in profiles) / len(profiles), 3) for field in TRAIT_FIELDS}
    result = {"valid": not errors, "profiles": len(profiles), "distinct_vectors": distinct_vectors,
              "means": means, "errors": errors[:20], "error_count": len(errors)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
