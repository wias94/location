from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class BehaviorConfig:
    service_work_probability: dict[int, float] = field(default_factory=lambda: {
        0: .60, 1: .60, 2: .65, 3: .70, 4: .80, 5: .92, 6: .88,
    })
    weekday_work_probability: dict[str, float] = field(default_factory=lambda: {
        "office_worker": .96, "manual_worker": .90, "university_student": .92, "freelancer": .78,
    })
    weekend_work_probability: dict[str, float] = field(default_factory=lambda: {
        "office_worker": .08, "manual_worker": .35, "university_student": .18, "freelancer": .50,
    })
    evening_weight_multiplier: dict[str, float] = field(default_factory=dict)
    social_enabled: bool = True
    non_workday_social_probability: float = .32
    date_accept_probability: float = .82
    friend_accept_probability: float = .72
    family_accept_probability: float = .86
    external_contact_accept_probability: float = .78
    friend_out_probability: float = .35
    social_cancellation_probability: float = .04
    social_time_step_minutes: int = 15
    social_daily_limit: int = 1

    def validate(self) -> None:
        for mapping in (self.service_work_probability, self.weekday_work_probability, self.weekend_work_probability):
            for key, value in mapping.items():
                if not 0 <= float(value) <= 1:
                    raise ValueError(f"Probability {key} must be between 0 and 1")
        for key, value in self.evening_weight_multiplier.items():
            if not 0 <= float(value) <= 10:
                raise ValueError(f"Evening multiplier {key} must be between 0 and 10")
        for key in ("non_workday_social_probability", "date_accept_probability", "friend_accept_probability",
                    "family_accept_probability", "external_contact_accept_probability", "friend_out_probability",
                    "social_cancellation_probability"):
            value = float(getattr(self, key))
            if not 0 <= value <= 1:
                raise ValueError(f"{key} must be between 0 and 1")
        if not 5 <= int(self.social_time_step_minutes) <= 60:
            raise ValueError("social_time_step_minutes must be between 5 and 60")
        if not 1 <= int(self.social_daily_limit) <= 3:
            raise ValueError("social_daily_limit must be between 1 and 3")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "BehaviorConfig":
        if not data:
            return cls()
        defaults = cls()
        service = {**defaults.service_work_probability, **{int(k): float(v) for k, v in data.get("service_work_probability", {}).items()}}
        weekday = {**defaults.weekday_work_probability, **{str(k): float(v) for k, v in data.get("weekday_work_probability", {}).items()}}
        weekend = {**defaults.weekend_work_probability, **{str(k): float(v) for k, v in data.get("weekend_work_probability", {}).items()}}
        result = cls(
            service_work_probability=service,
            weekday_work_probability=weekday,
            weekend_work_probability=weekend,
            evening_weight_multiplier={str(k): float(v) for k, v in data.get("evening_weight_multiplier", {}).items()},
            social_enabled=bool(data.get("social_enabled", defaults.social_enabled)),
            non_workday_social_probability=float(data.get("non_workday_social_probability", defaults.non_workday_social_probability)),
            date_accept_probability=float(data.get("date_accept_probability", defaults.date_accept_probability)),
            friend_accept_probability=float(data.get("friend_accept_probability", defaults.friend_accept_probability)),
            family_accept_probability=float(data.get("family_accept_probability", defaults.family_accept_probability)),
            external_contact_accept_probability=float(data.get("external_contact_accept_probability", defaults.external_contact_accept_probability)),
            friend_out_probability=float(data.get("friend_out_probability", defaults.friend_out_probability)),
            social_cancellation_probability=float(data.get("social_cancellation_probability", defaults.social_cancellation_probability)),
            social_time_step_minutes=int(data.get("social_time_step_minutes", defaults.social_time_step_minutes)),
            social_daily_limit=int(data.get("social_daily_limit", defaults.social_daily_limit)),
        )
        result.validate()
        return result
