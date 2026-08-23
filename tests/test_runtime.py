import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from simulator.clock import SimulationClock
from simulator.config import BehaviorConfig
from simulator.service import Interaction, JsonStateStore


class RuntimeTests(unittest.TestCase):
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
        self.assertEqual(BehaviorConfig.from_dict(config.to_dict()).evening_weight_multiplier["date"], .5)
        with self.assertRaises(ValueError):
            BehaviorConfig.from_dict({"weekday_work_probability": {"office_worker": 2}})

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


if __name__ == "__main__":
    unittest.main()
