from __future__ import annotations

import csv
from pathlib import Path

from .models import Family, Gender, Occupation, Person

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
                sociability=_trait(row, "sociability"), routine_preference=_trait(row, "routine_preference"),
                spontaneity=_trait(row, "spontaneity"), travel_tolerance=_trait(row, "travel_tolerance"),
                nightlife_preference=_trait(row, "nightlife_preference"), activity_budget=_trait(row, "activity_budget"),
                family_orientation=_trait(row, "family_orientation"), warmth=_trait(row, "warmth"),
                directness=_trait(row, "directness"), patience=_trait(row, "patience"),
                communication_style=(row.get("communication_style") or "均衡自然").strip(),
                personality_summary=(row.get("personality_summary") or "").strip(),
            ))
    return people
