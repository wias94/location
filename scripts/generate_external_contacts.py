"""Create lightweight contacts for relatives/partners outside the 10,000-person sample."""
from __future__ import annotations

import argparse
import csv
import hashlib
import random
from collections import defaultdict
from pathlib import Path


def rng_for(*parts: object, seed: int) -> random.Random:
    digest = hashlib.sha256("|".join(map(str, (*parts, seed))).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population", type=Path, default=Path("data/gta_population_with_places.csv"))
    parser.add_argument("--places", type=Path, default=Path("data/places.csv"))
    parser.add_argument("--relationships", type=Path, default=Path("data/relationships.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/external_contacts.csv"))
    parser.add_argument("--seed", type=int, default=20260824)
    args = parser.parse_args()

    people = load_rows(args.population)
    homes = sorted({row["place_id"] for row in load_rows(args.places) if row["category"] == "residential"})
    if not homes:
        homes = sorted({row["home_place_id"] for row in people})
    in_sample: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in load_rows(args.relationships):
        a, b, kind = row["person_id_a"], row["person_id_b"], row["relationship_type"]
        if kind == "spouse":
            in_sample[a]["partner"].add(b); in_sample[b]["partner"].add(a)
        elif kind == "parent_of":
            in_sample[a]["adult_child"].add(b); in_sample[b]["parent"].add(a)

    rows: list[dict[str, object]] = []

    def other_home(person: dict[str, str], relation: str, index: int) -> str:
        own = person["home_place_id"]
        candidate = homes[rng_for(person["person_id"], relation, index, "home", seed=args.seed).randrange(len(homes))]
        if candidate == own and len(homes) > 1:
            candidate = homes[(homes.index(candidate) + 1) % len(homes)]
        return candidate

    def add(person: dict[str, str], relation: str, label: str, home: str, co_resident: bool,
            profile: str, description: str) -> None:
        index = len(rows) + 1
        rows.append({
            "external_contact_id": f"EXT{index:07d}", "person_id": person["person_id"],
            "relation_type": relation, "label": label, "home_place_id": home,
            "co_resident": str(co_resident).lower(), "availability_profile": profile,
            "description": description,
        })

    for person in sorted(people, key=lambda row: row["person_id"]):
        pid, age, family = person["person_id"], int(person["年龄"]), person["家庭状态"]
        rng = rng_for(pid, "external_contacts", seed=args.seed)
        if not in_sample[pid]["partner"]:
            partner_probability = .76 if family == "有未成年孩子" else (.66 if family == "有成年孩子" else .34)
            if rng.random() < partner_probability:
                co_resident_probability = .78 if family != "无需要照顾的孩子" else .48
                co_resident = rng.random() < co_resident_probability
                home = person["home_place_id"] if co_resident else other_home(person, "partner", 0)
                add(person, "partner", "样本外伴侣", home, co_resident, "evenings_and_weekends",
                    "此伴侣未进入一万人样本；只用于约会和家庭活动，不进行实时位置追踪。")

        if not in_sample[pid]["parent"] and rng.random() < (.86 if age <= 55 else .55):
            count = 2 if rng.random() < .32 else 1
            for index in range(count):
                label = "样本外母亲" if index == 0 and rng.random() < .5 else "样本外父亲"
                add(person, "parent", label, other_home(person, "parent", index), False,
                    "daytime_and_evenings", "父母未进入一万人样本，并且与成年子女分开居住。")

        if family == "有成年孩子" and not in_sample[pid]["adult_child"]:
            count = 2 if rng.random() < .28 else 1
            for index in range(count):
                add(person, "adult_child", f"样本外成年子女{index + 1}", other_home(person, "adult_child", index), False,
                    "evenings_and_weekends", "成年子女未进入一万人样本，并且已经独立居住。")

        if family == "有未成年孩子":
            count = 2 if rng.random() < .42 else 1
            for index in range(count):
                add(person, "minor_child", f"样本外未成年子女{index + 1}", person["home_place_id"], True,
                    "dependent", "未成年子女不属于成人模拟样本，与该人物共同居住。")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["external_contact_id", "person_id", "relation_type", "label", "home_place_id",
              "co_resident", "availability_profile", "description"]
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)
    counts = {kind: sum(row["relation_type"] == kind for row in rows)
              for kind in ("partner", "parent", "adult_child", "minor_child")}
    print({"external_contacts": len(rows), "types": counts})


if __name__ == "__main__":
    main()
