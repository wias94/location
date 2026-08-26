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
    employer_id: str | None = None
    sociability: float = .5
    routine_preference: float = .5
    spontaneity: float = .5
    travel_tolerance: float = .5
    nightlife_preference: float = .5
    activity_budget: float = .5
    family_orientation: float = .5
    warmth: float = .5
    directness: float = .5
    patience: float = .5
    communication_style: str = "均衡自然"
    personality_summary: str = ""
    company_name: str = ""
    background: str = ""
    interests: str = ""
    goals: str = ""
    dialogue_notes: str = ""


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
    social_event_id: str | None = None
    counterparty_id: str | None = None

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


@dataclass(frozen=True, slots=True)
class ExternalContact:
    external_contact_id: str
    person_id: str
    relation_type: str
    label: str
    home_place_id: str
    co_resident: bool = False
    availability_profile: str = "evenings_and_weekends"


@dataclass(frozen=True, slots=True)
class SocialIntent:
    person_id: str
    day: str
    event_type: str
    destination_type: str
    earliest: datetime
    latest_end: datetime
    duration_minutes: int


@dataclass(frozen=True, slots=True)
class SocialEvent:
    social_event_id: str
    event_type: str
    start_time: datetime
    end_time: datetime
    place_id: str
    participant_ids: tuple[str, ...]
    external_contact_id: str | None = None
