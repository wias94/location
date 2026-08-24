"""Assign shared real OSM homes, workplaces and schools to the population."""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import random
from collections import Counter, defaultdict
from pathlib import Path

WORK_CATEGORIES = {
    "office_worker": ("office", "commercial"),
    "service_worker": ("restaurant", "retail", "hotel", "supermarket", "gym"),
    "manual_worker": ("industrial", "commercial"),
    "freelancer": ("residential", "cafe", "office"),
    "university_student": ("university", "college"),
}

JOB_CATEGORIES = {
    "咖啡师": ("cafe",), "厨师": ("restaurant", "hotel"), "餐厅服务员": ("restaurant",),
    "酒店服务人员": ("hotel",), "酒店前台": ("hotel",), "健身教练": ("gym",),
    "美容师": ("retail",), "理发师": ("retail",), "零售店员": ("retail",),
    "收银员": ("retail", "supermarket"), "房产经纪": ("office", "commercial"),
    "仓库操作员": ("industrial",), "搬运工": ("industrial",), "设备操作员": ("industrial",),
    "配送员": ("industrial", "commercial"), "快递员": ("industrial", "commercial"),
    "卡车司机": ("industrial",), "汽车技师": ("industrial", "commercial"),
    "维修技师": ("industrial", "commercial"), "安装工": ("industrial", "commercial"),
    "电工": ("industrial", "commercial"), "焊工": ("industrial",), "建筑工人": ("industrial",),
    "私教": ("gym",), "摄影师": ("office", "commercial"),
}
HOME_DISTRICTS = {"Markham", "Scarborough"}
HOME_SUBTYPES = {"apartments", "residential", "dormitory", "house", "detached", "semidetached_house", "terrace"}


def rng_for(*parts: str) -> random.Random:
    return random.Random(int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:8], "big"))


class WeightedPool:
    def __init__(self, places: list[dict]) -> None:
        if not places:
            raise ValueError("Cannot create an empty place pool")
        self.places, self.cumulative, total = places, [], 0
        for place in places:
            total += max(1, int(place["capacity_weight"]))
            self.cumulative.append(total)
        self.total = total

    def choose(self, rng: random.Random) -> dict:
        return self.places[bisect.bisect_left(self.cumulative, rng.randint(1, self.total))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population", type=Path, default=Path("data/gta_synthetic_population_10000.csv"))
    parser.add_argument("--places", type=Path, default=Path("data/places.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/person_places.csv"))
    parser.add_argument("--bound-population", type=Path, default=Path("data/gta_population_with_places.csv"))
    args = parser.parse_args()
    with args.places.open(encoding="utf-8-sig", newline="") as f: places = list(csv.DictReader(f))
    by_category = defaultdict(list)
    for place in places: by_category[place["category"]].append(place)
    homes = [place for place in by_category["residential"]
             if place["district"] in HOME_DISTRICTS and place.get("subtype") in HOME_SUBTYPES]
    if not homes: raise RuntimeError("places.csv contains no residential places")
    home_pool = WeightedPool(homes)
    category_pools = {kind: WeightedPool(pool) for kind, pool in by_category.items() if pool}
    district_school_pools = {}
    for district in HOME_DISTRICTS:
        pool = [p for kind in ("school", "kindergarten", "childcare") for p in by_category[kind] if p["district"] == district]
        district_school_pools[district] = WeightedPool(pool)
    rows = []
    with args.population.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        population_fields = list(reader.fieldnames or [])
        people = list(reader)
        for person in people:
            pid, occupation = person["person_id"], person["occupation_code"]
            home = home_pool.choose(rng_for(pid, "HOME"))
            rows.append({"person_id": pid, "place_role": "HOME", "place_id": home["place_id"]})
            categories = JOB_CATEGORIES.get(person["具体职位"], WORK_CATEGORIES[occupation])
            if occupation == "freelancer" and rng_for(pid, "WORK_KIND").random() < .45:
                work = home
            else:
                pools = [category_pools[kind] for kind in categories if kind in category_pools]
                pool = pools[rng_for(pid, "WORK_POOL").randrange(len(pools))] if pools else None
                work = pool.choose(rng_for(pid, "WORK")) if pool else None
            if work:
                role = "UNIVERSITY" if occupation == "university_student" else "WORK"
                rows.append({"person_id": pid, "place_role": role, "place_id": work["place_id"]})
            if person["家庭状态"] == "有未成年孩子":
                school = district_school_pools[home["district"]].choose(rng_for(pid, "CHILD_SCHOOL"))
                rows.append({"person_id": pid, "place_role": "CHILD_SCHOOL", "place_id": school["place_id"]})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["person_id", "place_role", "place_id"]); writer.writeheader(); writer.writerows(rows)
    bindings = defaultdict(dict)
    for row in rows: bindings[row["person_id"]][row["place_role"]] = row["place_id"]
    for field in ("home_place_id", "work_place_id", "school_place_id"):
        if field not in population_fields: population_fields.append(field)
    with args.bound_population.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=population_fields); writer.writeheader()
        for person in people:
            assigned = bindings[person["person_id"]]
            person["home_place_id"] = assigned.get("HOME", "")
            person["work_place_id"] = assigned.get("WORK", assigned.get("UNIVERSITY", ""))
            person["school_place_id"] = assigned.get("CHILD_SCHOOL", assigned.get("UNIVERSITY", ""))
            writer.writerow(person)
    print(dict(Counter(row["place_role"] for row in rows)))


if __name__ == "__main__":
    main()
