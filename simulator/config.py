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

    def validate(self) -> None:
        for mapping in (self.service_work_probability, self.weekday_work_probability, self.weekend_work_probability):
            for key, value in mapping.items():
                if not 0 <= float(value) <= 1:
                    raise ValueError(f"Probability {key} must be between 0 and 1")
        for key, value in self.evening_weight_multiplier.items():
            if not 0 <= float(value) <= 10:
                raise ValueError(f"Evening multiplier {key} must be between 0 and 10")

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
        )
        result.validate()
        return result
