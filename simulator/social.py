from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Iterable

from .config import BehaviorConfig
from .models import DailyEvent, ExternalContact, Person, Place, SocialEvent, SocialIntent
from .places import PlaceResolver
from .randomness import stable_seed
from .routes import RouteCache


class SocialCoordinator:
    """Turn individual social intentions into conflict-free shared events."""

    def __init__(self, places: PlaceResolver, routes: RouteCache, config: BehaviorConfig, seed: int = 20260819) -> None:
        self.places = places
        self.routes = routes
        self.config = config
        self.seed = seed

    def coordinate(self, schedules: dict[str, list[DailyEvent]], people: dict[str, Person],
                   intents: Iterable[SocialIntent]) -> list[SocialEvent]:
        if not self.config.social_enabled:
            return []
        counts: dict[tuple[str, str], int] = {}
        social_events: list[SocialEvent] = []
        ordered = sorted(intents, key=lambda item: stable_seed(item.day, item.person_id, item.event_type,
                                                               "social_order", base_seed=self.seed))
        for intent in ordered:
            key = (intent.person_id, intent.day)
            if counts.get(key, 0) >= self.config.social_daily_limit:
                continue
            if self._rng(intent.person_id, intent.day, intent.event_type, "cancel").random() < self.config.social_cancellation_probability:
                continue

            participant_id, external = self._counterparty(intent, counts)
            if participant_id is None and external is None:
                continue
            if participant_id:
                other_key = (participant_id, intent.day)
                if counts.get(other_key, 0) >= self.config.social_daily_limit:
                    continue
                acceptance = self._acceptance_probability(intent.event_type, people[participant_id])
                if self._rng(intent.person_id, participant_id, intent.day, intent.event_type, "accept").random() >= acceptance:
                    continue
            else:
                if self._rng(intent.person_id, external.external_contact_id, intent.day, intent.event_type,
                             "accept").random() >= self.config.external_contact_accept_probability:
                    continue

            planned = self._plan(intent, participant_id, external, schedules, people)
            if not planned:
                continue
            event, replacements = planned
            for person_id, replacement_events in replacements.items():
                schedules[person_id] = replacement_events
                counts[(person_id, intent.day)] = counts.get((person_id, intent.day), 0) + 1
            social_events.append(event)
        return sorted(social_events, key=lambda event: (event.start_time, event.social_event_id))

    def _rng(self, *parts: object) -> random.Random:
        return random.Random(stable_seed(*parts, base_seed=self.seed))

    def _acceptance_probability(self, event_type: str, person: Person) -> float:
        if event_type == "date":
            base = self.config.date_accept_probability
            trait = (person.sociability + person.nightlife_preference) / 2
        elif event_type in {"visit_parent", "visit_adult_child", "family_visit"}:
            base = self.config.family_accept_probability
            trait = person.family_orientation
        else:
            base = self.config.friend_accept_probability
            trait = person.sociability
        return min(1.0, base * (.65 + .70 * trait))

    def _counterparty(self, intent: SocialIntent, counts: dict[tuple[str, str], int]) -> tuple[str | None, ExternalContact | None]:
        relation, external_relation = {
            "date": ("spouse", "partner"),
            "friend_visit": ("friend", "friend"),
            "visit_parent": ("parent", "parent"),
            "visit_adult_child": ("adult_child", "adult_child"),
            "family_visit": ("extended_family", "parent"),
        }.get(intent.event_type, ("friend", "friend"))
        candidates = [person_id for person_id in sorted(self.places.relationships.get(intent.person_id, {}).get(relation, ()))
                      if counts.get((person_id, intent.day), 0) < self.config.social_daily_limit]
        if candidates:
            index = stable_seed(intent.person_id, intent.day, intent.event_type, "counterparty", base_seed=self.seed) % len(candidates)
            return candidates[index], None
        contacts = sorted(self.places.external_contacts.get(intent.person_id, {}).get(external_relation, ()),
                          key=lambda contact: contact.external_contact_id)
        if contacts:
            index = stable_seed(intent.person_id, intent.day, intent.event_type, "external", base_seed=self.seed) % len(contacts)
            return None, contacts[index]
        return None, None

    def _plan(self, intent: SocialIntent, participant_id: str | None, external: ExternalContact | None,
              schedules: dict[str, list[DailyEvent]], people: dict[str, Person]) -> tuple[SocialEvent, dict[str, list[DailyEvent]]] | None:
        initiator = people[intent.person_id]
        initiator_home = self.places.bind_person(initiator)["HOME"]
        other = people.get(participant_id) if participant_id else None
        other_home = self.places.bind_person(other)["HOME"] if other else None

        event_type = intent.event_type
        is_friend_outing = event_type == "friend_visit" and self._rng(
            intent.person_id, intent.day, "friend_outing").random() < self.config.friend_out_probability
        if event_type == "date":
            destination = self.places.resolve_place("DATE_POI", initiator, initiator_home, intent.earliest)
            public_type = "date"
        elif is_friend_outing:
            destination = self.places.resolve_place("CAFE_OR_COWORKING", initiator, initiator_home, intent.earliest)
            public_type = "friend_outing"
        elif event_type == "friend_visit":
            if other_home:
                destination = other_home
            elif external:
                destination = self.places.provider.get(external.home_place_id)
            else:
                return None
            public_type = "friend_visit"
        elif event_type in {"visit_parent", "visit_adult_child", "family_visit"}:
            if other_home:
                destination = other_home
            elif external:
                destination = self.places.provider.get(external.home_place_id)
            else:
                return None
            public_type = "family_visit"
        else:
            return None

        participants = [(initiator, initiator_home, False)]
        other_is_host = bool(other and destination.place_id == other_home.place_id)
        if other:
            participants.append((other, other_home, other_is_host))

        chosen = self._find_window(intent, participants, destination, schedules)
        if not chosen:
            return None
        meeting_start, meeting_end, home_events = chosen
        social_id = f"SOC_{stable_seed(intent.person_id, intent.day, public_type, participant_id or external.external_contact_id,
                                      base_seed=self.seed) % 10**15:015d}"
        replacements: dict[str, list[DailyEvent]] = {}
        for person, home, is_host in participants:
            counterparty = participant_id if person.person_id == intent.person_id else intent.person_id
            if external and person.person_id == intent.person_id:
                counterparty = external.external_contact_id
            person_event_type = "hosting_friend" if is_host and public_type == "friend_visit" else public_type
            replacements[person.person_id] = self._replace_home_interval(
                schedules[person.person_id], home_events[person.person_id], person, home, destination,
                meeting_start, meeting_end, person_event_type, social_id, counterparty,
            )
        social_event = SocialEvent(social_id, public_type, meeting_start, meeting_end, destination.place_id,
                                   tuple(person.person_id for person, _, _ in participants),
                                   external.external_contact_id if external else None)
        return social_event, replacements

    def _find_window(self, intent: SocialIntent, participants: list[tuple[Person, Place, bool]], destination: Place,
                     schedules: dict[str, list[DailyEvent]]) -> tuple[datetime, datetime, dict[str, DailyEvent]] | None:
        options: list[list[tuple[DailyEvent, int, int]]] = []
        for person, home, is_host in participants:
            outbound = 0 if is_host or home.place_id == destination.place_id else self.routes.get_or_create(home, destination).duration_s
            inbound = 0 if is_host or home.place_id == destination.place_id else self.routes.get_or_create(destination, home).duration_s
            intervals = [(event, outbound, inbound) for event in schedules[person.person_id]
                         if not event.moving and event.destination_place_id == home.place_id
                         and event.end_time > intent.earliest and event.start_time < intent.latest_end]
            if not intervals:
                return None
            options.append(intervals)

        # There are only one or two simulated participants in v1, so a small
        # Cartesian search is clearer and faster than a general interval solver.
        combinations = [(left,) for left in options[0]]
        if len(options) == 2:
            combinations = [(left, right) for left in options[0] for right in options[1]]
        step = self.config.social_time_step_minutes
        for combination in combinations:
            earliest = intent.earliest
            latest = intent.latest_end
            selected: dict[str, DailyEvent] = {}
            for (person, _, _), (home_event, outbound, inbound) in zip(participants, combination):
                earliest = max(earliest, home_event.start_time + timedelta(seconds=outbound))
                latest = min(latest, home_event.end_time - timedelta(seconds=inbound))
                selected[person.person_id] = home_event
            meeting_start = self._ceil_time(earliest, step)
            meeting_end = meeting_start + timedelta(minutes=intent.duration_minutes)
            if meeting_end <= latest:
                return meeting_start, meeting_end, selected
        return None

    @staticmethod
    def _ceil_time(value: datetime, minutes: int) -> datetime:
        base = value.replace(second=0, microsecond=0)
        remainder = base.minute % minutes
        if remainder or value.second or value.microsecond:
            base += timedelta(minutes=minutes - remainder if remainder else minutes)
        return base

    def _replace_home_interval(self, events: list[DailyEvent], home_event: DailyEvent, person: Person,
                               home: Place, destination: Place, meeting_start: datetime, meeting_end: datetime,
                               event_type: str, social_id: str, counterparty_id: str | None) -> list[DailyEvent]:
        outbound = None if home.place_id == destination.place_id else self.routes.get_or_create(home, destination)
        inbound = None if home.place_id == destination.place_id else self.routes.get_or_create(destination, home)
        depart = meeting_start - timedelta(seconds=outbound.duration_s if outbound else 0)
        return_home = meeting_end + timedelta(seconds=inbound.duration_s if inbound else 0)
        result = [event for event in events if event is not home_event]
        if home_event.start_time < depart:
            result.append(replace(home_event, end_time=depart))
        if outbound:
            result.append(self._event(person, depart, meeting_start, "social_commute", home, destination,
                                      outbound.route_id, "commuting", social_id, counterparty_id, "out"))
        result.append(self._event(person, meeting_start, meeting_end, event_type, destination, destination,
                                  None, "stationary", social_id, counterparty_id, "meet"))
        if inbound:
            result.append(self._event(person, meeting_end, return_home, "social_commute", destination, home,
                                      inbound.route_id, "commuting", social_id, counterparty_id, "return"))
        if return_home < home_event.end_time:
            result.append(replace(home_event, start_time=return_home))
        return sorted(result, key=lambda event: (event.start_time, event.end_time, event.event_id))

    def _event(self, person: Person, start: datetime, end: datetime, event_type: str, origin: Place,
               destination: Place, route_id: str | None, status: str, social_id: str,
               counterparty_id: str | None, phase: str) -> DailyEvent:
        event_id = f"EV_{stable_seed(person.person_id, social_id, phase, base_seed=self.seed) % 10**15:015d}"
        return DailyEvent(event_id, person.person_id, start, end, event_type, origin.place_id,
                          destination.place_id, route_id, status, social_id, counterparty_id)
