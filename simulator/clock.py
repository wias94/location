from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class SimulationClock:
    simulation_anchor: datetime
    real_anchor: datetime
    speed: float = 1.0
    paused: bool = False

    def now(self, real_now: datetime | None = None) -> datetime:
        if self.paused:
            return self.simulation_anchor
        current = real_now or utc_now()
        elapsed = (current - self.real_anchor).total_seconds() * self.speed
        return self.simulation_anchor + timedelta(seconds=elapsed)

    def pause(self, real_now: datetime | None = None) -> None:
        if not self.paused:
            self.simulation_anchor = self.now(real_now)
            self.real_anchor = real_now or utc_now()
            self.paused = True

    def resume(self, real_now: datetime | None = None) -> None:
        if self.paused:
            self.real_anchor = real_now or utc_now()
            self.paused = False

    def seek(self, simulation_time: datetime, real_now: datetime | None = None) -> None:
        self.simulation_anchor = simulation_time
        self.real_anchor = real_now or utc_now()

    def set_speed(self, speed: float, real_now: datetime | None = None) -> None:
        if not 0 <= speed <= 86_400:
            raise ValueError("speed must be between 0 and 86400")
        current = self.now(real_now)
        self.simulation_anchor = current
        self.real_anchor = real_now or utc_now()
        self.speed = speed
        self.paused = speed == 0

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["simulation_anchor"] = self.simulation_anchor.isoformat()
        data["real_anchor"] = self.real_anchor.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SimulationClock":
        return cls(datetime.fromisoformat(str(data["simulation_anchor"])), datetime.fromisoformat(str(data["real_anchor"])),
                   float(data.get("speed", 1)), bool(data.get("paused", False)))
