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

    def search(self, query: str, limit: int = 8) -> list[dict[str, str]]:
        needle = query.strip().casefold()
        if not needle:
            return []
        matches = [row for row in self.organizations if needle in row.get("name", "").casefold()]
        matches.sort(key=lambda row: (row.get("name", "").casefold() != needle,
                                      not row.get("name", "").casefold().startswith(needle),
                                      len(row.get("name", "")), row.get("organization_id", "")))
        return matches[:limit]

    def add_person(self, person_id: str, organization_id: str | None, member_role: str,
                   company_name: str = "", place_id: str | None = None) -> None:
        """Add an in-memory membership for an admin-created person.

        The person itself is persisted by SimulatorService and this membership is
        reconstructed on each start, so the immutable source CSV stays untouched.
        """
        if not organization_id or person_id in self.by_person:
            return
        if organization_id not in self.by_id:
            if not company_name.strip() or not place_id:
                return
            organization = {
                "organization_id": organization_id, "name": company_name.strip(),
                "organization_type": "custom", "place_id": place_id, "district": "",
                "member_count": "1", "team_count": "1", "employee_capacity": "1",
                "name_source": "admin", "is_real_name": "true", "match_confidence": "manual",
                "max_match_distance_m": "0", "work_place_count": "1", "source": "admin",
                "source_id": "", "source_url": "", "description": "Admin-created organization",
            }
            self.organizations.append(organization)
            self.by_id[organization_id] = organization
        membership = {"person_id": person_id, "organization_id": organization_id,
                      "team_id": "", "member_role": member_role}
        self.memberships.append(membership)
        self.by_person[person_id] = membership
        self.version = hashlib.sha256(f"{self.version}|{person_id}|{organization_id}".encode()).hexdigest()[:16]
