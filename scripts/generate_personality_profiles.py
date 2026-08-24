"""Generate deterministic continuous personality traits and Chinese prompt-ready summaries."""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import random
from pathlib import Path


TRAIT_FIELDS = [
    "sociability", "routine_preference", "spontaneity", "travel_tolerance",
    "nightlife_preference", "activity_budget", "family_orientation", "warmth",
    "directness", "patience",
]
PROFILE_FIELDS = [*TRAIT_FIELDS, "communication_style", "personality_summary"]


def rng_for(person_id: str, seed: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}|{person_id}|personality".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def clamp(value: float) -> float:
    return min(.98, max(.02, value))


def communication_style(traits: dict[str, float]) -> str:
    if traits["directness"] >= .67 and traits["warmth"] >= .58:
        return "坦率热情"
    if traits["directness"] >= .68:
        return "直接简洁"
    if traits["warmth"] >= .68:
        return "温和体贴"
    if traits["patience"] >= .68:
        return "沉稳耐心"
    if traits["sociability"] >= .68:
        return "健谈外向"
    return "克制务实"


def summary(traits: dict[str, float], style: str) -> str:
    social = ("性格较为外向，通常愿意主动联系熟人并参加共同活动" if traits["sociability"] >= .67 else
              "性格偏安静，更喜欢小范围交往和熟悉的人" if traits["sociability"] <= .36 else
              "社交态度适中，既愿意参加活动，也需要独处时间")
    if traits["routine_preference"] >= .67:
        rhythm = "日常节奏规律，倾向提前安排，不太喜欢计划被突然打乱"
    elif traits["spontaneity"] >= .67:
        rhythm = "行动比较随性，容易接受临时邀约，也愿意尝试计划外活动"
    else:
        rhythm = "通常会做基本安排，但遇到合适机会也愿意临时调整"
    if traits["travel_tolerance"] >= .68:
        mobility = "对较远的出行接受度较高"
    elif traits["travel_tolerance"] <= .34:
        mobility = "更偏好住处或工作地点附近的活动"
    else:
        mobility = "对出行距离没有明显偏好"
    priorities = []
    if traits["family_orientation"] >= .68:
        priorities.append("重视家庭联系")
    if traits["nightlife_preference"] >= .68:
        priorities.append("喜欢晚间外出")
    if traits["patience"] >= .70:
        priorities.append("处理分歧时较有耐心")
    ending = "，".join(priorities) if priorities else "生活取向相对均衡"
    return f"{social}。{rhythm}；{mobility}。交流方式{style}，{ending}。"


def make_profile(person: dict[str, str], seed: int) -> dict[str, object]:
    rng = rng_for(person["person_id"], seed)
    age = int(person["年龄"])
    occupation = person["occupation_code"]
    family = person["家庭状态"]
    base = lambda: rng.betavariate(2.6, 2.6)
    sociability = clamp(base())
    routine_adjustment = {"office_worker": .08, "manual_worker": .06, "service_worker": .01,
                          "university_student": -.06, "freelancer": -.13}[occupation]
    routine = clamp(base() + routine_adjustment + max(-.06, min(.08, (age - 35) / 300)))
    spontaneity = clamp(.42 * base() + .58 * (1 - routine) + rng.uniform(-.08, .08))
    travel = clamp(.65 * base() + .35 * sociability + (.05 if age < 35 else -.03 if age > 60 else 0))
    nightlife = clamp(.55 * base() + .35 * sociability + (.12 if age < 30 else -.12 if age > 55 else 0))
    budget = clamp(base())
    family_adjustment = .14 if family in {"有成年孩子", "有未成年孩子"} else -.03
    family_orientation = clamp(base() + family_adjustment)
    warmth, directness, patience = clamp(base()), clamp(base()), clamp(base())
    traits = {
        "sociability": sociability, "routine_preference": routine, "spontaneity": spontaneity,
        "travel_tolerance": travel, "nightlife_preference": nightlife, "activity_budget": budget,
        "family_orientation": family_orientation, "warmth": warmth, "directness": directness,
        "patience": patience,
    }
    rounded = {key: f"{value:.2f}" for key, value in traits.items()}
    style = communication_style(traits)
    return {"person_id": person["person_id"], **rounded, "communication_style": style,
            "personality_summary": summary(traits, style)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population", type=Path, default=Path("data/gta_population_with_places.csv"))
    parser.add_argument("--profiles", type=Path, default=Path("data/person_behavior_profiles.csv"))
    parser.add_argument("--merge-population", type=Path, default=Path("data/gta_population_with_places.csv"))
    parser.add_argument("--seed", type=int, default=20260824)
    args = parser.parse_args()

    with args.population.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        source_fields = list(reader.fieldnames or [])
        people = list(reader)
    profiles = [make_profile(person, args.seed) for person in people]
    by_id = {row["person_id"]: row for row in profiles}

    args.profiles.parent.mkdir(parents=True, exist_ok=True)
    with args.profiles.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["person_id", *PROFILE_FIELDS])
        writer.writeheader(); writer.writerows(profiles)

    base_fields = [field for field in source_fields if field not in PROFILE_FIELDS]
    merged_fields = [*base_fields, *PROFILE_FIELDS]
    temporary = args.merge_population.with_suffix(args.merge_population.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=merged_fields)
        writer.writeheader()
        for person in people:
            clean = {field: person.get(field, "") for field in base_fields}
            writer.writerow({**clean, **{field: by_id[person["person_id"]][field] for field in PROFILE_FIELDS}})
    os.replace(temporary, args.merge_population)
    print({"profiles": len(profiles), "fields": PROFILE_FIELDS,
           "average_sociability": round(sum(float(row["sociability"]) for row in profiles) / len(profiles), 3)})


if __name__ == "__main__":
    main()
