import gzip
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from threading import RLock

from simulator.history import HistoryStore


class HistoryTests(unittest.TestCase):
    def test_state_reversions_and_restart_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'history.sqlite'
            h = HistoryStore(path)
            for value in ['A', 'A', 'B', 'A']:
                h.state({'value': value})
            h = HistoryStore(path)
            h.state({'value': 'A'})
            with h.connect() as db:
                values = [json.loads(gzip.decompress(r[0]))['value'] for r in db.execute('SELECT payload FROM records ORDER BY id')]
                self.assertEqual(values, ['A', 'B', 'A'])

    def test_sampling_daily_timezone_restart_and_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            h = HistoryStore(Path(folder) / 'history.sqlite')
            now = datetime(2026, 9, 6, 3, 59, tzinfo=timezone.utc)
            service = SimpleNamespace(clock=SimpleNamespace(now=lambda: now),
                snapshot=Mock(return_value={'people': []}), people_list=[],
                _lock=RLock(), store=SimpleNamespace(load=lambda: {}), status=lambda: {})
            h.capture(service, now)
            h.capture(service, now)
            h = HistoryStore(h.path)
            h.capture(service, now)
            self.assertEqual(service.snapshot.call_count, 1)
            service.snapshot.side_effect = RuntimeError('unavailable')
            with self.assertRaises(RuntimeError):
                h.capture(service, now + timedelta(minutes=5))
            service.snapshot.side_effect = None
            h.capture(service, now + timedelta(minutes=5))
            with h.connect() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM records WHERE kind='locations'").fetchone()[0], 2)
                self.assertEqual([r[0] for r in db.execute("SELECT record_key FROM records WHERE kind='daily' ORDER BY record_key")], ['2026-09-05', '2026-09-06'])

if __name__ == '__main__':
    unittest.main()
