from __future__ import annotations

from datetime import date, datetime, time, timedelta
from itertools import count

from scripts.person_behavior_templates import PERSON_TEMPLATES

from .models import BehaviorTemplate, DailyEvent, Family, Occupation, Person, Place
from .config import BehaviorConfig
from .places import PlaceResolver
from .randomness import seeded_rng, stable_seed
from .routes import RouteCache

SERVICE_WORK_PROBABILITY = {0: 0.60, 1: 0.60, 2: 0.65, 3: 0.70, 4: 0.80, 5: 0.92, 6: 0.88}


def behavior_template(person: Person) -> BehaviorTemplate:
    key = f"{person.gender.value}__{person.occupation.value}__{person.family.value}"
    raw = PERSON_TEMPLATES[key]
    return BehaviorTemplate(key, dict(raw["tags"]), tuple(raw["fixed_skeleton"]), dict(raw["time_rules"]), tuple(raw["midday_events"]), tuple(raw["evening_events"]))


class ScheduleEngine:
    def __init__(self, places: PlaceResolver | None = None, routes: RouteCache | None = None, seed: int = 20260819,
                 config: BehaviorConfig | None = None) -> None:
        self.places = places or PlaceResolver(seed=seed)
        self.routes = routes or RouteCache()
        self.seed = seed
        self.config = config or BehaviorConfig()

    def _works(self, person: Person, day: date) -> bool:
        rng = seeded_rng(person.person_id, day, "work_day", self.seed)
        if person.occupation == Occupation.SERVICE:
            probability = self.config.service_work_probability[day.weekday()]
        else:
            mapping = self.config.weekday_work_probability if day.weekday() < 5 else self.config.weekend_work_probability
            probability = mapping[person.occupation.value]
        return rng.random() < probability

    @staticmethod
    def _weighted(rng, choices: tuple[dict, ...]) -> dict:
        point = rng.random() * sum(item["probability"] for item in choices)
        for item in choices:
            point -= item["probability"]
            if point <= 0:
                return item
        return choices[-1]

    def generate_day(self, person: Person, day: date) -> list[DailyEvent]:
        bound = self.places.bind_person(person)
        home, work = bound["HOME"], bound["WORK"]
        midnight = datetime.combine(day, time.min)
        end_day = midnight + timedelta(days=1)
        if not self._works(person, day):
            return [self._event(person, day, 0, midnight, end_day, "stay_home", home, home)]

        template = behavior_template(person)
        timing_rng = seeded_rng(person.person_id, day, "timing", self.seed)
        if person.occupation == Occupation.SERVICE:
            starts = template.time_rules["shift_start_options"]
            chosen = self._weighted(timing_rng, tuple({"probability": x["weight"], **x} for x in starts))
            base_start = chosen["base"]
            start_jitter = template.time_rules["shift_start_jitter_min"]
            duration_rule = template.time_rules["work_duration_min"]
        elif person.occupation == Occupation.STUDENT:
            base_start = template.time_rules["first_class"]["base"]
            start_jitter = template.time_rules["first_class"]["jitter_min"]
            duration_rule = template.time_rules["campus_duration_min"]
        else:
            base_start = template.time_rules["work_start"]["base"]
            start_jitter = template.time_rules["work_start"]["jitter_min"]
            duration_rule = template.time_rules["work_duration_min"]
        hour, minute = map(int, base_start.split(":"))
        work_start = datetime.combine(day, time(hour, minute)) + timedelta(minutes=timing_rng.randint(-start_jitter, start_jitter))
        duration = duration_rule["base"] + timing_rng.randint(-duration_rule["jitter_min"], duration_rule["jitter_min"])
        work_end = min(work_start + timedelta(minutes=duration), end_day - timedelta(minutes=30))

        seq = count()
        events: list[DailyEvent] = []
        current_place, cursor = home, midnight
        child_rng = seeded_rng(person.person_id, day, "child_care", self.seed)
        child_trip = person.family == Family.MINOR_CHILDREN and child_rng.random() < 0.65
        school = bound.get("SCHOOL_OR_CHILDCARE")

        commute = self.routes.get_or_create(school if child_trip and school else home, work)
        if child_trip and school:
            home_school = self.routes.get_or_create(home, school)
            depart = work_start - timedelta(seconds=commute.duration_s + home_school.duration_s + 10 * 60)
            events.append(self._event(person, day, next(seq), cursor, depart, "stay_home", home, home))
            cursor = self._move(events, person, day, seq, depart, home, school, "child_dropoff")
            drop_end = cursor + timedelta(minutes=10)
            events.append(self._event(person, day, next(seq), cursor, drop_end, "child_dropoff", school, school))
            cursor, current_place = drop_end, school
        else:
            depart = work_start - timedelta(seconds=self.routes.get_or_create(home, work).duration_s)
            events.append(self._event(person, day, next(seq), cursor, depart, "stay_home", home, home))

        cursor = self._move(events, person, day, seq, cursor if child_trip else depart, current_place, work, "commute")
        current_place = work
        if cursor < work_start:
            events.append(self._event(person, day, next(seq), cursor, work_start, "at_work", work, work))
        work_type = "study" if person.occupation == Occupation.STUDENT else "work"
        lunch_rng = seeded_rng(person.person_id, day, "midday", self.seed)
        lunch = self._weighted(lunch_rng, template.midday_events)
        is_out = lunch["destination"] not in {"WORK", "WORKSITE", "CURRENT_PLACE", "CAMPUS"} and work_start < datetime.combine(day, time(13, 0)) < work_end
        if is_out:
            lunch_start = max(work_start + timedelta(hours=2), datetime.combine(day, time(11, 40)))
            events.append(self._event(person, day, next(seq), work_start, lunch_start, work_type, work, work))
            lunch_place = self.places.resolve_place(lunch["destination"], person, work, lunch_start)
            cursor = self._move(events, person, day, seq, lunch_start, work, lunch_place, "lunch_out")
            lunch_duration = lunch_rng.randint(*lunch["duration_min"])
            lunch_end = min(cursor + timedelta(minutes=lunch_duration), work_end - timedelta(minutes=5))
            events.append(self._event(person, day, next(seq), cursor, lunch_end, "lunch_out", lunch_place, lunch_place))
            cursor = self._move(events, person, day, seq, lunch_end, lunch_place, work, "commute")
            events.append(self._event(person, day, next(seq), cursor, work_end, work_type, work, work))
        else:
            events.append(self._event(person, day, next(seq), work_start, work_end, work_type, work, work))
        cursor = work_end

        if child_trip and school:
            cursor = self._move(events, person, day, seq, cursor, work, school, "child_pickup")
            pickup_end = min(cursor + timedelta(minutes=10), end_day)
            events.append(self._event(person, day, next(seq), cursor, pickup_end, "child_pickup", school, school))
            cursor = pickup_end
            current_place = school
        else:
            current_place = work

        evening_choices = tuple({**item, "probability": item["probability"] * self.config.evening_weight_multiplier.get(item["event"], 1.0)} for item in template.evening_events)
        if not any(item["probability"] > 0 for item in evening_choices):
            evening_choices = ({"event": "go_home", "probability": 1.0, "destination": "HOME"},)
        evening = self._weighted(seeded_rng(person.person_id, day, "evening", self.seed), evening_choices)
        if evening["destination"] not in {"HOME", "HOME_OR_DORM"} and "duration_min" in evening:
            visit = self.places.resolve_place(evening["destination"], person, current_place, cursor)
            cursor = self._move(events, person, day, seq, cursor, current_place, visit, evening["event"])
            visit_end = min(cursor + timedelta(minutes=seeded_rng(person.person_id, day, "evening_duration", self.seed).randint(*evening["duration_min"])), end_day - timedelta(minutes=5))
            if visit_end > cursor:
                events.append(self._event(person, day, next(seq), cursor, visit_end, evening["event"], visit, visit))
                cursor, current_place = visit_end, visit
        if current_place.place_id != home.place_id and cursor < end_day:
            cursor = self._move(events, person, day, seq, cursor, current_place, home, "commute", end_day)
        if cursor < end_day:
            events.append(self._event(person, day, next(seq), cursor, end_day, "stay_home", home, home))
        return [event for event in events if event.end_time > event.start_time]

    def _move(self, events, person, day, seq, start, origin, destination, event_type, cap=None):
        route = self.routes.get_or_create(origin, destination)
        end = start + timedelta(seconds=route.duration_s)
        if cap is not None:
            end = min(end, cap)
        events.append(self._event(person, day, next(seq), start, end, event_type, origin, destination, route.route_id, "commuting"))
        return end

    def _event(self, person, day, sequence, start, end, event_type, origin, destination, route_id=None, status="stationary"):
        event_id = f"EV_{stable_seed(person.person_id, day, sequence, event_type, base_seed=self.seed) % 10**15:015d}"
        return DailyEvent(event_id, person.person_id, start, end, event_type, origin.place_id, destination.place_id, route_id, status)

    def generate_period(self, person: Person, start_date: date, days: int) -> list[DailyEvent]:
        return [event for offset in range(days) for event in self.generate_day(person, start_date + timedelta(days=offset))]


def generate_day(person: Person, day: date, engine: ScheduleEngine | None = None) -> list[DailyEvent]:
    return (engine or ScheduleEngine()).generate_day(person, day)


def generate_period(person: Person, start_date: date, days: int, engine: ScheduleEngine | None = None) -> list[DailyEvent]:
    return (engine or ScheduleEngine()).generate_period(person, start_date, days)
