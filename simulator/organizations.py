from __future__ import annotations

import csv
import hashlib
from pathlib import Path


def _rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class OrganizationDirectory:
    """In-memory static organization lookup; no runtime geocoding is performed."""

    def __init__(self, organizations_path: str | Path, memberships_path: str | Path) -> None:
        organizations_path, memberships_path = Path(organizations_path), Path(memberships_path)
        self.organizations = _rows(organizations_path)
        self.memberships = _rows(memberships_path)
        digest = hashlib.sha256(organizations_path.read_bytes() + memberships_path.read_bytes()).hexdigest()
        self.version = digest[:16]
        self.by_id = {row["organization_id"]: row for row in self.organizations}
        self.by_person = {row["person_id"]: row for row in self.memberships}

    def for_person(self, person_id: str) -> dict[str, object]:
        membership = self.by_person[person_id]
        return {"membership": membership, "organization": self.by_id[membership["organization_id"]]}

    def snapshot(self) -> dict[str, object]:
        return {"organizations": self.organizations, "memberships": self.memberships}
