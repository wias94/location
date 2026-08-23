from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"


class Family(StrEnum):
    SINGLE_NO_KIDS = "single_no_kids"
    ADULT_CHILDREN = "adult_children"
    MINOR_CHILDREN = "minor_children"


class Occupation(StrEnum):
    OFFICE = "office_worker"
    FREELANCER = "freelancer"
    SERVICE = "service_worker"
    MANUAL = "manual_worker"
    STUDENT = "university_student"


@dataclass(frozen=True, slots=True)
class Person:
    person_id: str
    name: str
    gender: Gender
    age: int
    age_group: str
    family: Family
    occupation: Occupation
    job_title: str
    hukou_type: str
    hukou_province: str
    home_place_id: str | None = None
    work_place_id: str | None = None
    school_place_id: str | None = None


@dataclass(frozen=True, slots=True)
class Place:
    place_id: str
    name: str
    category: str
    lat: float
    lng: float
    address: str = ""
    source: str = "mock"
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class Route:
    route_id: str
    origin_place_id: str
    destination_place_id: str
    distance_m: float
    duration_s: int
    geometry: tuple[tuple[float, float], ...]
    travel_mode: str = "car"


@dataclass(frozen=True, slots=True)
class DailyEvent:
    event_id: str
    person_id: str
    start_time: datetime
    end_time: datetime
    event_type: str
    origin_place_id: str
    destination_place_id: str
    route_id: str | None = None
    status: str = "stationary"

    @property
    def moving(self) -> bool:
        return self.route_id is not None


MovementEvent = DailyEvent


@dataclass(frozen=True, slots=True)
class BehaviorTemplate:
    template_id: str
    tags: dict[str, str]
    fixed_skeleton: tuple[str, ...]
    time_rules: dict[str, Any] = field(default_factory=dict)
    midday_events: tuple[dict[str, Any], ...] = ()
    evening_events: tuple[dict[str, Any], ...] = ()
