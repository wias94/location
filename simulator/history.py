"""Append-only, compressed history beside the persistent simulator state file."""
from __future__ import annotations

from contextlib import contextmanager
import gzip
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


class HistoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    simulation_time TEXT,
                    payload BLOB NOT NULL,
                    UNIQUE(kind, record_key)
                );
                CREATE INDEX IF NOT EXISTS records_time ON records(kind, recorded_at);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def encode(data):
        return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    def append(self, kind, key, data, simulation_time=None, recorded_at=None):
        now = recorded_at or datetime.now(timezone.utc)
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO records(kind,record_key,recorded_at,simulation_time,payload) VALUES(?,?,?,?,?)",
                       (kind, key, now.isoformat(), simulation_time, gzip.compress(self.encode(data))))

    def state(self, data):
        # Compare with the latest version, so A -> B -> A preserves all changes.
        raw = self.encode(data)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            last = db.execute("SELECT payload FROM records WHERE kind='state' ORDER BY id DESC LIMIT 1").fetchone()
            if last and gzip.decompress(last[0]) == raw:
                return
            now = datetime.now(timezone.utc).isoformat()
            db.execute("INSERT INTO records(kind,record_key,recorded_at,payload) VALUES('state',?,?,?)",
                       (now + ':' + hashlib.sha256(raw).hexdigest(), now, gzip.compress(raw)))

    def has(self, kind, key):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM records WHERE kind=? AND record_key=?", (kind, key)).fetchone() is not None

    def capture(self, service, now=None):
        now = now or datetime.now(timezone.utc)
        bucket = str(int(now.timestamp()) // 300)
        day = now.astimezone(ZoneInfo('America/Toronto')).date().isoformat()
        # Real time keys continue to work when the simulation is paused or seeks backwards.
        if not self.has('locations', bucket):
            target = service.clock.now()
            snapshot = service.snapshot(target)
            self.append('locations', bucket, snapshot, target.isoformat(), now)
        if not self.has('daily', day):
            from .population import person_to_dict
            with service._lock:
                data = {'people': [person_to_dict(p) for p in service.people_list],
                        'state': service.store.load(), 'status': service.status()}
            self.append('daily', day, data, service.clock.now().isoformat(), now)
