import hashlib
import random
from datetime import date


def stable_seed(*parts: object, base_seed: int = 20260819) -> int:
    raw = "|".join((str(base_seed), *(str(p) for p in parts))).encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def seeded_rng(person_id: str, day: date, event_type: str, base_seed: int = 20260819) -> random.Random:
    return random.Random(stable_seed(person_id, day.isoformat(), event_type, base_seed=base_seed))
