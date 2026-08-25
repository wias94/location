import unittest
import pickle
import tempfile
import csv
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from simulator.behavior import ScheduleEngine
from simulator.config import BehaviorConfig
from simulator.models import DailyEvent, ExternalContact, Family, Occupation, Place, SocialIntent
from simulator.places import CsvPlaceProvider, PlaceResolver
from simulator.population import load_population
from simulator.routes import RoadNetworkRouteProvider, RouteCache, StraightLineRouteProvider, route_provider_for_mode
from simulator.social import SocialCoordinator
from simulator.world import WorldEngine
from scripts.generate_organizations import make_organizations
from scripts.generate_relationships import GraphBuilder

DATA = Path(__file__).parents[1] / "data" / "gta_synthetic_population_10000.csv"
RUNTIME_DATA = Path(__file__).parents[1] / "data" / "gta_population_with_places.csv"


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

    def test_personality_profiles_load_and_affect_behavior_weights(self):
        profiled = load_population(RUNTIME_DATA)
        person = profiled[0]
        self.assertTrue(person.personality_summary)
        self.assertTrue(person.employer_id)
        self.assertTrue(all(0 <= getattr(person, key) <= 1 for key in (
            "sociability", "routine_preference", "spontaneity", "travel_tolerance",
            "nightlife_preference", "activity_budget", "family_orientation", "warmth",
            "directness", "patience")))
        quiet = replace(person, sociability=.1)
        social = replace(person, sociability=.9)
        self.assertGreater(ScheduleEngine._personality_weight(social, "friend_visit"),
                           ScheduleEngine._personality_weight(quiet, "friend_visit"))
        with RUNTIME_DATA.open(encoding="utf-8-sig", newline="") as handle:
            self.assertEqual(list(csv.DictReader(handle).fieldnames or [])[-1], "personality_summary")

    def test_organizations_use_cached_real_osm_names(self):
        people = {
            "A": {"person_id": "A", "occupation_code": "office_worker", "具体职位": "软件工程师",
                  "work_place_id": "WORK"},
            "B": {"person_id": "B", "occupation_code": "freelancer", "具体职位": "摄影师",
                  "work_place_id": "HOME_WORK"},
        }
        work = {"place_id": "WORK", "name": "OSM commercial W1", "category": "commercial",
                "lat": "43.8000", "lng": "-79.3000", "district": "Scarborough", "osm_id": "W1",
                "capacity_weight": "100"}
        home_work = {"place_id": "HOME_WORK", "name": "12 Test Road", "category": "residential",
                     "lat": "43.8100", "lng": "-79.3100", "district": "Scarborough", "osm_id": "W2",
                     "capacity_weight": "2"}
        real = {"place_id": "REAL", "name": "Real Toronto Software", "category": "office",
                "lat": "43.8001", "lng": "-79.3001", "district": "Scarborough", "osm_id": "N3",
                "capacity_weight": "40"}
        places = {row["place_id"]: row for row in (work, home_work)}
        all_places = {row["place_id"]: row for row in (work, home_work, real)}
        organizations, memberships = make_organizations(people, places, all_places)
        by_person = {row["person_id"]: row for row in memberships}
        by_id = {row["organization_id"]: row for row in organizations}
        self.assertEqual(by_id[by_person["A"]["organization_id"]]["name"], "Real Toronto Software")
        self.assertEqual(by_id[by_person["A"]["organization_id"]]["name_source"], "osm_nearby_name")
        self.assertEqual(by_id[by_person["B"]["organization_id"]]["is_real_name"], "false")
        self.assertTrue(by_id[by_person["B"]["organization_id"]]["name"].startswith("Unidentified"))

    def test_relationship_context_combines_people_place_and_personality(self):
        people = {
            "A": {"person_id": "A", "姓名": "甲", "年龄": "35", "具体职位": "工程师", "职业大类": "上班族",
                  "communication_style": "直接", "sociability": ".8", "routine_preference": ".7",
                  "family_orientation": ".4", "warmth": ".6", "spontaneity": ".3",
                  "home_place_id": "HOME", "work_place_id": "WORK"},
            "B": {"person_id": "B", "姓名": "乙", "年龄": "37", "具体职位": "设计师", "职业大类": "上班族",
                  "communication_style": "温和", "sociability": ".4", "routine_preference": ".5",
                  "family_orientation": ".7", "warmth": ".8", "spontaneity": ".6",
                  "home_place_id": "HOME", "work_place_id": "WORK"},
        }
        places = {
            "HOME": {"place_id": "HOME", "name": "测试公寓", "district": "Markham", "subtype": "apartments"},
            "WORK": {"place_id": "WORK", "name": "测试办公楼", "district": "Toronto", "category": "office"},
        }
        organizations = [{"organization_id": "ORG", "name": "测试公司", "place_id": "WORK"}]
        memberships = [{"person_id": pid, "organization_id": "ORG", "team_id": "TEAM", "member_role": people[pid]["具体职位"]}
                       for pid in people]
        graph = GraphBuilder(people, places, organizations, memberships, 42)
        graph.add("A", "B", "coworker", .75, "shared_team", "简短说明")
        context = graph.finalized()[0]["relationship_context"]
        self.assertTrue(all(value in context for value in ("甲", "乙", "工程师", "设计师", "测试办公楼", "测试公司")))
        self.assertGreaterEqual(len(context), 120)

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

    def test_places_are_in_the_greater_toronto_region(self):
        world = WorldEngine()
        world.generate_population_period(self.people[:250], date(2026, 8, 24), 1)
        places = world.schedule.places.provider.all().values()
        self.assertTrue(all(42.9 <= place.lat <= 44.5 and -80.7 <= place.lng <= -78.2 for place in places))

    def test_activity_uses_real_nearby_osm_poi(self):
        provider = CsvPlaceProvider()
        origin = Place("HOME", "Home", "residential", 43.8, -79.3, source="openstreetmap")
        restaurant = Place("REST", "Real restaurant", "restaurant", 43.801, -79.301, source="openstreetmap")
        provider.put(origin); provider.put(restaurant)
        result = PlaceResolver(provider).resolve_place("RESTAURANT", self.people[0], origin, datetime(2026, 8, 24, 12))
        self.assertEqual(result.place_id, "REST")

    def test_friend_visit_uses_relationship_home(self):
        first = replace(self.people[0], home_place_id="HOME_A")
        friend = replace(self.people[1], home_place_id="HOME_B")
        provider = CsvPlaceProvider()
        provider.put(Place("HOME_A", "A", "residential", 43.8, -79.3, source="openstreetmap"))
        provider.put(Place("HOME_B", "B", "residential", 43.81, -79.31, source="openstreetmap"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "relationships.csv"
            path.write_text("person_id_a,person_id_b,relationship_type\n" + f"{first.person_id},{friend.person_id},friend\n", encoding="utf-8")
            resolver = PlaceResolver(provider, people={first.person_id: first, friend.person_id: friend}, relationships_path=path)
            result = resolver.resolve_place("FRIEND_HOME", first, provider.get("HOME_A"), datetime(2026, 8, 24, 18))
        self.assertEqual(result.place_id, "HOME_B")

    def test_local_road_network_materializes_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roads.pkl"
            path.write_bytes(pickle.dumps({"version": 1, "coords": {1: (43.8, -79.3), 2: (43.8, -79.29), 3: (43.81, -79.29)},
                                           "adjacency": {1: [(2, 800.0, 60.0)], 2: [(1, 800.0, 60.0), (3, 1110.0, 80.0)], 3: [(2, 1110.0, 80.0)]}}))
            cache = RouteCache(RoadNetworkRouteProvider(path))
            route = cache.get_or_create(Place("A", "A", "home", 43.8, -79.3), Place("B", "B", "office", 43.81, -79.29))
            self.assertEqual(len(route.geometry), 2)  # cheap schedule-time estimate
            actual = cache.get(route.route_id)
            self.assertGreater(len(actual.geometry), 2)

    def test_straight_routing_is_default_without_loading_road_graph(self):
        self.assertIsNone(route_provider_for_mode("straight", Path("data/road_network.pkl")))
        cache = RouteCache(route_provider_for_mode("straight", Path("data/road_network.pkl")))
        self.assertIsInstance(cache.provider, StraightLineRouteProvider)
        with self.assertRaises(ValueError):
            route_provider_for_mode("unknown", None)

    def test_friend_visit_creates_synchronized_events(self):
        first = replace(self.people[0], home_place_id="HOME_A")
        friend = replace(self.people[1], home_place_id="HOME_B")
        provider = CsvPlaceProvider()
        provider.put(Place("HOME_A", "A", "residential", 43.80, -79.30))
        provider.put(Place("HOME_B", "B", "residential", 43.81, -79.31))
        resolver = PlaceResolver(provider, people={first.person_id: first, friend.person_id: friend})
        resolver.relationships[first.person_id]["friend"].append(friend.person_id)
        resolver.relationships[friend.person_id]["friend"].append(first.person_id)
        start, end = datetime(2026, 8, 24), datetime(2026, 8, 25)
        schedules = {
            first.person_id: [DailyEvent("A0", first.person_id, start, end, "stay_home", "HOME_A", "HOME_A")],
            friend.person_id: [DailyEvent("B0", friend.person_id, start, end, "stay_home", "HOME_B", "HOME_B")],
        }
        intent = SocialIntent(first.person_id, "2026-08-24", "friend_visit", "FRIEND_HOME",
                              start + timedelta(hours=18), start + timedelta(hours=23), 90)
        config = BehaviorConfig(friend_accept_probability=1, friend_out_probability=0,
                                social_cancellation_probability=0)
        result = SocialCoordinator(resolver, RouteCache(), config).coordinate(
            schedules, {first.person_id: first, friend.person_id: friend}, [intent])
        self.assertEqual(len(result), 1)
        shared = [[event for event in schedules[pid] if event.social_event_id and not event.moving]
                  for pid in (first.person_id, friend.person_id)]
        self.assertEqual(shared[0][0].social_event_id, shared[1][0].social_event_id)
        self.assertEqual((shared[0][0].start_time, shared[0][0].end_time, shared[0][0].destination_place_id),
                         (shared[1][0].start_time, shared[1][0].end_time, shared[1][0].destination_place_id))

    def test_external_parent_is_not_added_to_population(self):
        person = replace(self.people[0], home_place_id="HOME_A")
        provider = CsvPlaceProvider()
        provider.put(Place("HOME_A", "A", "residential", 43.80, -79.30))
        provider.put(Place("PARENT_HOME", "Parent", "residential", 43.82, -79.32))
        resolver = PlaceResolver(provider, people={person.person_id: person})
        resolver.external_contacts[person.person_id]["parent"].append(
            ExternalContact("EXT1", person.person_id, "parent", "样本外父母", "PARENT_HOME")
        )
        start, end = datetime(2026, 8, 24), datetime(2026, 8, 25)
        schedules = {person.person_id: [DailyEvent("A0", person.person_id, start, end,
                                                   "stay_home", "HOME_A", "HOME_A")]}
        intent = SocialIntent(person.person_id, "2026-08-24", "visit_parent", "PARENT_HOME",
                              start + timedelta(hours=18), start + timedelta(hours=23), 90)
        config = BehaviorConfig(external_contact_accept_probability=1, social_cancellation_probability=0)
        result = SocialCoordinator(resolver, RouteCache(), config).coordinate(
            schedules, {person.person_id: person}, [intent])
        self.assertEqual(result[0].external_contact_id, "EXT1")
        self.assertEqual(result[0].participant_ids, (person.person_id,))
        self.assertNotIn("EXT1", {person.person_id: person})


if __name__ == "__main__":
    unittest.main()
