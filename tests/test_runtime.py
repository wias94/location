import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from simulator.clock import SimulationClock
from simulator.config import BehaviorConfig
from simulator.models import Family, Gender, Occupation
from simulator.organizations import OrganizationDirectory
from simulator.service import Interaction, JsonStateStore, SimulatorService

ROOT = Path(__file__).parents[1]


class RuntimeTests(unittest.TestCase):
    def test_clock_defaults_to_real_time(self):
        real = datetime(2026, 8, 23, tzinfo=timezone.utc)
        clock = SimulationClock(datetime(2026, 8, 24), real)
        self.assertEqual(clock.speed, 1)
        self.assertEqual(clock.now(real + timedelta(minutes=1)), datetime(2026, 8, 24, 0, 1))

    def test_clock_speed_pause_resume_and_seek(self):
        real = datetime(2026, 8, 23, tzinfo=timezone.utc)
        clock = SimulationClock(datetime(2026, 8, 24), real, 60)
        self.assertEqual(clock.now(real + timedelta(seconds=1)), datetime(2026, 8, 24, 0, 1))
        clock.pause(real + timedelta(seconds=2))
        self.assertEqual(clock.now(real + timedelta(hours=1)), datetime(2026, 8, 24, 0, 2))
        clock.resume(real + timedelta(hours=1))
        self.assertEqual(clock.now(real + timedelta(hours=1, seconds=1)), datetime(2026, 8, 24, 0, 3))
        clock.seek(datetime(2027, 1, 1), real)
        self.assertEqual(clock.now(real), datetime(2027, 1, 1))

    def test_behavior_validation_and_round_trip(self):
        config = BehaviorConfig()
        config.evening_weight_multiplier["date"] = .5
        config.friend_out_probability = .45
        restored = BehaviorConfig.from_dict(config.to_dict())
        self.assertEqual(restored.evening_weight_multiplier["date"], .5)
        self.assertEqual(restored.friend_out_probability, .45)
        with self.assertRaises(ValueError):
            BehaviorConfig.from_dict({"weekday_work_probability": {"office_worker": 2}})
        with self.assertRaises(ValueError):
            BehaviorConfig.from_dict({"friend_accept_probability": 1.2})

    def test_json_state_store_is_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JsonStateStore(Path(directory) / "state.json")
            store.save({"version": 3})
            self.assertEqual(store.load(), {"version": 3})

    def test_interaction_active_window(self):
        start = datetime(2026, 8, 24, 9)
        interaction = Interaction("I1", "P00001", start, start + timedelta(hours=1), 31.2, 121.4, "meeting")
        self.assertTrue(interaction.active(start + timedelta(minutes=30)))
        self.assertFalse(interaction.active(start + timedelta(hours=1)))

    def test_static_organization_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            organizations = root / "organizations.csv"
            memberships = root / "memberships.csv"
            organizations.write_text("organization_id,name\nORG_1,Example Company\n", encoding="utf-8")
            memberships.write_text("person_id,organization_id\nP1,ORG_1\n", encoding="utf-8")
            directory_index = OrganizationDirectory(organizations, memberships)
            result = directory_index.for_person("P1")
            self.assertEqual(result["organization"]["name"], "Example Company")
            self.assertEqual(directory_index.search("example")[0]["organization_id"], "ORG_1")
            directory_index.add_person("P2", "ORG_CUSTOM_P2", "工程师", "Custom Company", "PLACE_2")
            self.assertEqual(directory_index.for_person("P2")["organization"]["name"], "Custom Company")

    def test_admin_created_person_is_live_and_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = ROOT / "data" / "gta_population_with_places.csv"
            population = root / "people.csv"
            with source.open(encoding="utf-8-sig", newline="") as source_file:
                reader = csv.DictReader(source_file)
                rows = [next(reader) for _ in range(10)]
                with population.open("w", encoding="utf-8", newline="") as target:
                    writer = csv.DictWriter(target, fieldnames=reader.fieldnames)
                    writer.writeheader(); writer.writerows(rows)
            state = root / "state.json"
            options = dict(population_path=population, state_path=state, days=1,
                           places_path=ROOT / "data" / "places.sqlite")
            service = SimulatorService(**options)
            service.start()
            result = service.add_person(person_id=None, name="测试人物", gender=Gender.FEMALE, age=31,
                                        family=Family.SINGLE_NO_KIDS, occupation=Occupation.OFFICE,
                                        job_title="软件工程师", personality_traits={"sociability": .91},
                                        communication_style="坦率热情")
            person_id = result["person"]["person_id"]
            self.assertEqual(result["population"], 11)
            self.assertEqual(service.location(person_id)["person_id"], person_id)
            self.assertEqual(result["places"]["home"]["source"], "openstreetmap")
            self.assertEqual(result["person"]["sociability"], .91)
            self.assertEqual(result["person"]["communication_style"], "坦率热情")
            service.close()

            restored = SimulatorService(**options)
            self.assertIn(person_id, restored.people)
            self.assertEqual(len(restored.added_people), 1)
            restored.close()


if __name__ == "__main__":
    unittest.main()
