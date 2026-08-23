import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from simulator.behavior import ScheduleEngine
from simulator.models import Family, Occupation
from simulator.population import load_population
from simulator.world import WorldEngine

DATA = Path(__file__).parents[1] / "data" / "shanghai_synthetic_population_10000.csv"


class SimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.people = load_population(DATA)

    def test_same_seed_is_identical_and_dates_vary(self):
        engine = ScheduleEngine()
        person = next(p for p in self.people if p.occupation == Occupation.OFFICE)
        first = engine.generate_day(person, date(2026, 8, 24))
        self.assertEqual(first, engine.generate_day(person, date(2026, 8, 24)))
        self.assertNotEqual([(e.start_time.time(), e.event_type) for e in first],
                            [(e.start_time.time(), e.event_type) for e in engine.generate_day(person, date(2026, 8, 25))])

    def test_occupation_work_patterns(self):
        engine = ScheduleEngine()
        office = [p for p in self.people if p.occupation == Occupation.OFFICE][:200]
        self.assertGreater(sum(any(e.event_type == "work" for e in engine.generate_day(p, date(2026, 8, 24))) for p in office), 175)
        service = [p for p in self.people if p.occupation == Occupation.SERVICE][:500]
        monday = sum(any(e.event_type == "work" for e in engine.generate_day(p, date(2026, 8, 24))) for p in service)
        saturday = sum(any(e.event_type == "work" for e in engine.generate_day(p, date(2026, 8, 29))) for p in service)
        self.assertGreater(saturday, monday)

    def test_minor_children_can_have_both_events(self):
        engine = ScheduleEngine()
        people = [p for p in self.people if p.family == Family.MINOR_CHILDREN][:100]
        kinds = {e.event_type for p in people for e in engine.generate_day(p, date(2026, 8, 24))}
        self.assertTrue({"child_dropoff", "child_pickup"}.issubset(kinds))

    def test_integrity_and_no_overlap(self):
        world = WorldEngine()
        schedules = world.generate_population_period(self.people[:100], date(2026, 8, 24), 2)
        places, routes = world.schedule.places.provider.all(), world.schedule.routes.all()
        for events in schedules.values():
            for left, right in zip(events, events[1:]):
                self.assertLessEqual(left.end_time, right.start_time)
            for event in events:
                self.assertIn(event.origin_place_id, places)
                self.assertIn(event.destination_place_id, places)
                if event.route_id:
                    self.assertIn(event.route_id, routes)

    def test_stationary_and_moving_location(self):
        world = WorldEngine()
        person = next(p for p in self.people if p.occupation == Occupation.OFFICE)
        world.generate_population_period([person], date(2026, 8, 24), 1)
        stationary = next(e for e in world.events[person.person_id] if not e.moving)
        self.assertIsNotNone(world.get_location(person.person_id, stationary.start_time + timedelta(seconds=1))["place_id"])
        moving = next(e for e in world.events[person.person_id] if e.moving)
        location = world.get_location(person.person_id, moving.start_time + (moving.end_time - moving.start_time) / 2)
        route = world.schedule.routes.get(moving.route_id or "")
        self.assertAlmostEqual(location["lat"], (route.geometry[0][0] + route.geometry[-1][0]) / 2)
        self.assertIsNone(location["place_id"])

    def test_world_has_10000_people(self):
        world = WorldEngine()
        world.generate_population_period(self.people, date(2026, 8, 24), 1)
        self.assertEqual(len(world.get_world(datetime(2026, 8, 24, 14, 32))["people"]), 10_000)


if __name__ == "__main__":
    unittest.main()
