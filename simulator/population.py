from __future__ import annotations

import csv
import random
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import Family, Gender, Occupation, Person
from .randomness import stable_seed

GENDER_MAP = {"男": Gender.MALE, "女": Gender.FEMALE, "male": Gender.MALE, "female": Gender.FEMALE}
FAMILY_MAP = {
    "无需要照顾的孩子": Family.SINGLE_NO_KIDS,
    "有成年孩子": Family.ADULT_CHILDREN,
    "有未成年孩子": Family.MINOR_CHILDREN,
    **{value.value: value for value in Family},
}


def _blank(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _trait(row: dict[str, str], key: str) -> float:
    value = float(row.get(key) or .5)
    if not 0 <= value <= 1:
        raise ValueError(f"{key} must be between 0 and 1")
    return value


def load_population(path: str | Path) -> list[Person]:
    people: list[Person] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            people.append(Person(
                person_id=row["person_id"].strip(), name=row["姓名"].strip(),
                gender=GENDER_MAP[row["性别"].strip()], age=int(row["年龄"]),
                age_group=row["年龄段"].strip(), family=FAMILY_MAP[row["家庭状态"].strip()],
                occupation=Occupation(row["occupation_code"].strip()),
                job_title=row["具体职位"].strip(), hukou_type=(row.get("户口类型") or "").strip(),
                hukou_province=(row.get("户口省份") or "").strip(), home_place_id=_blank(row.get("home_place_id")),
                work_place_id=_blank(row.get("work_place_id")), school_place_id=_blank(row.get("school_place_id")),
                employer_id=_blank(row.get("employer_id")),
                sociability=_trait(row, "sociability"), routine_preference=_trait(row, "routine_preference"),
                spontaneity=_trait(row, "spontaneity"), travel_tolerance=_trait(row, "travel_tolerance"),
                nightlife_preference=_trait(row, "nightlife_preference"), activity_budget=_trait(row, "activity_budget"),
                family_orientation=_trait(row, "family_orientation"), warmth=_trait(row, "warmth"),
                directness=_trait(row, "directness"), patience=_trait(row, "patience"),
                communication_style=(row.get("communication_style") or "均衡自然").strip(),
                personality_summary=(row.get("personality_summary") or "").strip(),
                company_name=(row.get("company_name") or "").strip(),
            ))
    return people


def person_to_dict(person: Person) -> dict[str, Any]:
    """Return a JSON-safe representation used by the persistent admin state."""
    return asdict(person)


def person_from_dict(data: dict[str, Any]) -> Person:
    """Restore a person created through the admin API."""
    values = dict(data)
    values["gender"] = Gender(values["gender"])
    values["family"] = Family(values["family"])
    values["occupation"] = Occupation(values["occupation"])
    return Person(**values)


def age_group_for(age: int) -> str:
    if age < 20:
        return "18-19"
    lower = min(80, age // 5 * 5)
    return "80+" if lower == 80 else f"{lower}-{lower + 4}"


def summarize_personality(traits: dict[str, float], style: str) -> str:
    sociability = traits["sociability"]
    routine = traits["routine_preference"]
    spontaneity = traits["spontaneity"]
    social = ("性格较为外向，通常愿意主动联系熟人并参加共同活动" if sociability >= .67 else
              "性格偏安静，更喜欢小范围交往和熟悉的人" if sociability <= .36 else
              "社交态度适中，既愿意参加活动，也需要独处时间")
    rhythm = ("日常节奏规律，倾向提前安排" if routine >= .67 else
              "行动比较随性，容易接受临时邀约" if spontaneity >= .67 else
              "通常会做基本安排，但也愿意临时调整")
    mobility = ("对较远的出行接受度较高" if traits["travel_tolerance"] >= .68 else
                "更偏好住处或工作地点附近的活动" if traits["travel_tolerance"] <= .34 else
                "对出行距离没有明显偏好")
    priorities = "重视家庭联系" if traits["family_orientation"] >= .68 else "生活取向相对均衡"
    return f"{social}。{rhythm}；{mobility}。交流方式{style}，{priorities}。"


def generated_personality(person_id: str, age: int, family: Family,
                          occupation: Occupation) -> dict[str, Any]:
    """Create a stable varied profile for a manually added person."""
    rng = random.Random(stable_seed(person_id, "admin_personality", base_seed=20260824))

    def trait(adjustment: float = 0) -> float:
        return round(min(.98, max(.02, rng.betavariate(2.6, 2.6) + adjustment)), 2)

    sociability = trait()
    routine = trait({Occupation.OFFICE: .08, Occupation.MANUAL: .06, Occupation.SERVICE: .01,
                     Occupation.STUDENT: -.06, Occupation.FREELANCER: -.13}[occupation]
                    + max(-.06, min(.08, (age - 35) / 300)))
    spontaneity = round(min(.98, max(.02, .45 * trait() + .55 * (1 - routine))), 2)
    traits = {
        "sociability": sociability,
        "routine_preference": routine,
        "spontaneity": spontaneity,
        "travel_tolerance": trait(.05 if age < 35 else -.03 if age > 60 else 0),
        "nightlife_preference": trait(.12 if age < 30 else -.12 if age > 55 else 0),
        "activity_budget": trait(),
        "family_orientation": trait(.14 if family != Family.SINGLE_NO_KIDS else -.03),
        "warmth": trait(),
        "directness": trait(),
        "patience": trait(),
    }
    if traits["directness"] >= .67 and traits["warmth"] >= .58:
        style = "坦率热情"
    elif traits["directness"] >= .68:
        style = "直接简洁"
    elif traits["warmth"] >= .68:
        style = "温和体贴"
    elif traits["patience"] >= .68:
        style = "沉稳耐心"
    elif sociability >= .68:
        style = "健谈外向"
    else:
        style = "克制务实"
    return {**traits, "communication_style": style,
            "personality_summary": summarize_personality(traits, style)}
