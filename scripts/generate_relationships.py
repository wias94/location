"""Generate organizations, teams, and a deterministic sparse social graph."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path


def seeded_rng(*parts: object) -> random.Random:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def make_organizations(people: dict[str, dict], places: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    occupants = defaultdict(list)
    for person in people.values():
        occupants[person["work_place_id"]].append(person)
    organizations, memberships = [], []
    team_members: dict[str, list[str]] = defaultdict(list)
    for index, place_id in enumerate(sorted(occupants), 1):
        place = places[place_id]
        members = occupants[place_id]
        org_id = f"ORG{index:05d}"
        org_type = "university" if all(p["occupation_code"] == "university_student" for p in members) else place["category"]
        team_size = 24 if org_type == "university" else (10 if org_type in {"office", "commercial", "industrial"} else 8)
        ordered = sorted(members, key=lambda p: p["person_id"])
        seeded_rng(org_id, "teams").shuffle(ordered)
        for offset, person in enumerate(ordered):
            team_id = f"{org_id}_T{offset // team_size + 1:03d}"
            team_members[team_id].append(person["person_id"])
            memberships.append({"person_id": person["person_id"], "organization_id": org_id,
                                "team_id": team_id, "member_role": person["具体职位"]})
        organizations.append({"organization_id": org_id,
            "name": f"Synthetic {org_type.title()} {index:05d} @ {place['name']}",
            "organization_type": org_type, "place_id": place_id, "district": place["district"],
            "member_count": len(members), "team_count": math.ceil(len(members) / team_size)})
    return organizations, memberships


class GraphBuilder:
    def __init__(self, people: dict[str, dict], places: dict[str, dict], organizations: list[dict], memberships: list[dict], seed: int) -> None:
        self.people, self.places, self.seed = people, places, seed
        self.organizations = {row["organization_id"]: row for row in organizations}
        self.memberships = {row["person_id"]: row for row in memberships}
        self.rows: list[dict] = []
        self.keys: set[tuple[str, str, str]] = set()
        self.social = defaultdict(set)

    def add(self, a: str, b: str, kind: str, strength: float, source: str, description: str, directed: bool = False) -> bool:
        if a == b:
            return False
        left, right = (a, b) if directed else pair_key(a, b)
        key = (left, right, kind)
        if key in self.keys:
            return False
        self.keys.add(key)
        self.rows.append({"person_id_a": left, "person_id_b": right, "relationship_type": kind,
                          "directed": str(directed).lower(), "strength": f"{strength:.2f}",
                          "source": source, "description": description})
        self.social[a].add(b); self.social[b].add(a)
        return True

    def family(self, coverage: float) -> set[str]:
        target = round(len(self.people) * coverage)
        target += target % 2
        covered: set[str] = set()
        family_pairs: set[tuple[str, str]] = set()
        homes = defaultdict(list)
        for person in self.people.values(): homes[person["home_place_id"]].append(person["person_id"])

        spouse_candidates = []
        for home_id, members in homes.items():
            if len(members) < 2: continue
            ordered = sorted(members); seeded_rng(self.seed, home_id, "spouse").shuffle(ordered)
            for i, a in enumerate(ordered):
                for b in ordered[i + 1:]:
                    if abs(int(self.people[a]["年龄"]) - int(self.people[b]["年龄"])) <= 15:
                        spouse_candidates.append((a, b))
        seeded_rng(self.seed, "spouse_candidates").shuffle(spouse_candidates)
        spouse_target = min(target // 8, len(spouse_candidates))
        spouses = 0
        for a, b in spouse_candidates:
            if spouses >= spouse_target or len(covered) >= target: break
            if a in covered or b in covered: continue
            home = self.places[self.people[a]["home_place_id"]]["name"]
            if self.add(a, b, "spouse", .96, "family_model", f"两人是共同居住在 {home} 的夫妻或长期伴侣。"):
                covered.update((a, b)); family_pairs.add(pair_key(a, b)); spouses += 1

        uncovered = set(self.people) - covered
        parents = [pid for pid in sorted(uncovered) if self.people[pid]["家庭状态"] == "有成年孩子"]
        seeded_rng(self.seed, "parents").shuffle(parents)
        parent_target = target // 6
        parent_edges = 0
        for parent in parents:
            if parent_edges >= parent_target or len(covered) >= target: break
            candidates = [pid for pid in sorted(uncovered) if pid != parent and
                          int(self.people[parent]["年龄"]) - int(self.people[pid]["年龄"]) >= 18 and
                          self.people[parent]["home_place_id"] != self.people[pid]["home_place_id"]]
            if not candidates: continue
            child = seeded_rng(self.seed, parent, "adult_child").choice(candidates)
            if self.add(parent, child, "parent_of", .90, "family_model", "前者是后者的父母；成年子女已经独立居住。", True):
                covered.update((parent, child)); uncovered.discard(parent); uncovered.discard(child)
                family_pairs.add(pair_key(parent, child)); parent_edges += 1

        by_surname = defaultdict(list)
        for pid in sorted(uncovered): by_surname[self.people[pid]["姓名"][:1]].append(pid)
        sibling_candidates = []
        for members in by_surname.values():
            ordered = sorted(members)
            for i, a in enumerate(ordered):
                for b in ordered[i + 1:]:
                    if abs(int(self.people[a]["年龄"]) - int(self.people[b]["年龄"])) <= 15 and self.people[a]["home_place_id"] != self.people[b]["home_place_id"]:
                        sibling_candidates.append((a, b))
        seeded_rng(self.seed, "siblings").shuffle(sibling_candidates)
        for a, b in sibling_candidates:
            if len(covered) >= target: break
            if a in covered or b in covered: continue
            if self.add(a, b, "sibling", .86, "family_model", "两人是已经各自独立居住的成年兄弟姐妹。"):
                covered.update((a, b)); uncovered.discard(a); uncovered.discard(b); family_pairs.add(pair_key(a, b))

        remaining = sorted(set(self.people) - covered)
        seeded_rng(self.seed, "extended_family").shuffle(remaining)
        for a, b in zip(remaining[::2], remaining[1::2]):
            if len(covered) >= target: break
            if self.add(a, b, "extended_family", .68, "family_model", "两人是生活在不同住所的成年亲属，其他家庭成员不一定在样本中。"):
                covered.update((a, b)); family_pairs.add(pair_key(a, b))
        return covered

    def coworkers(self) -> None:
        teams, org_teams = defaultdict(list), defaultdict(list)
        for pid, membership in self.memberships.items(): teams[membership["team_id"]].append(pid)
        for team_id in teams: org_teams[self.memberships[teams[team_id][0]]["organization_id"]].append(team_id)
        for team_id, members in teams.items():
            ordered = sorted(members); seeded_rng(self.seed, team_id).shuffle(ordered)
            org = self.organizations[self.memberships[ordered[0]]["organization_id"]]
            if len(ordered) <= 10:
                pairs = [(a, b) for i, a in enumerate(ordered) for b in ordered[i + 1:]]
            else:
                pairs = [(a, ordered[(i + step) % len(ordered)]) for i, a in enumerate(ordered) for step in range(1, 4)]
            for a, b in pairs:
                self.add(a, b, "coworker", seeded_rng(a, b, "coworker").uniform(.45, .82), "shared_team",
                         f"两人在 {org['name']} 的同一工作团队任职。")
        for org_id, team_ids in org_teams.items():
            if len(team_ids) < 2: continue
            ordered = sorted(team_ids)
            for left, right in zip(ordered, ordered[1:]):
                a = seeded_rng(org_id, left).choice(teams[left]); b = seeded_rng(org_id, right).choice(teams[right])
                self.add(a, b, "coworker", .38, "shared_organization", f"两人在 {self.organizations[org_id]['name']} 的不同团队工作。")

    def neighbors(self) -> None:
        homes = defaultdict(list)
        for pid, person in self.people.items(): homes[person["home_place_id"]].append(pid)
        for home_id, members in homes.items():
            if len(members) < 2: continue
            ordered = sorted(members); seeded_rng(self.seed, home_id, "neighbors").shuffle(ordered)
            place = self.places[home_id]
            kind = "housemate" if place.get("subtype") in {"house", "detached", "semidetached_house", "terrace"} else "neighbor"
            for i, a in enumerate(ordered):
                for step in range(1, min(3, len(ordered))):
                    b = ordered[(i + step) % len(ordered)]
                    if (*pair_key(a, b), "spouse") in self.keys:
                        continue
                    self.add(a, b, kind, seeded_rng(a, b, kind).uniform(.25, .62), "shared_home_location",
                             f"两人的住址都位于 {place['name']}；他们可能住在同一住宅或同一公寓建筑内。")

    def friends(self, average_degree: int) -> None:
        target_edges = len(self.people) * average_degree // 2
        friend_keys: set[tuple[str, str]] = set()
        friend_degrees = Counter()
        by_age_job, by_age_district, by_age = defaultdict(list), defaultdict(list), defaultdict(list)
        for pid, person in self.people.items():
            band = int(person["年龄"]) // 5
            district = self.places[person["home_place_id"]]["district"]
            by_age_job[(band, person["occupation_code"])].append(pid)
            by_age_district[(band, district)].append(pid); by_age[band].append(pid)
        ids = sorted(self.people); rng = seeded_rng(self.seed, "friends")
        attempts = 0
        while len(friend_keys) < target_edges and attempts < target_edges * 30:
            attempts += 1
            a = rng.choice(ids); person = self.people[a]; band = int(person["年龄"]) // 5
            roll = rng.random(); context = "similar_profile"
            if roll < .25 and self.social[a]:
                b = rng.choice(sorted(self.social[a])); context = "existing_contact"
            elif roll < .60:
                b = rng.choice(by_age_job[(band, person["occupation_code"])]); context = "similar_work_and_age"
            elif roll < .88:
                district = self.places[person["home_place_id"]]["district"]
                b = rng.choice(by_age_district[(band, district)]); context = "nearby_and_similar_age"
            else:
                b = rng.choice(by_age[band]); context = "similar_age"
            key = pair_key(a, b)
            if a == b or key in friend_keys: continue
            if friend_degrees[a] >= average_degree * 3 or friend_degrees[b] >= average_degree * 3: continue
            if context == "existing_contact": description = "两人在既有的工作、居住或社会往来中逐渐成为朋友。"
            elif context == "nearby_and_similar_age": description = "两人居住区域相近且处于相似生活阶段，平时保持朋友往来。"
            else: description = "两人年龄或职业背景相近，通过共同活动建立了朋友关系。"
            if self.add(a, b, "friend", seeded_rng(a, b, "friend").uniform(.42, .91), context, description):
                friend_keys.add(key)
                friend_degrees[a] += 1; friend_degrees[b] += 1

    def finalized(self) -> list[dict]:
        ordered = sorted(self.rows, key=lambda row: (row["relationship_type"], row["person_id_a"], row["person_id_b"]))
        for index, row in enumerate(ordered, 1): row["relationship_id"] = f"REL{index:07d}"
        return ordered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population", type=Path, default=Path("data/gta_population_with_places.csv"))
    parser.add_argument("--places", type=Path, default=Path("data/places.csv"))
    parser.add_argument("--family-coverage", type=float, default=.30)
    parser.add_argument("--friend-degree", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260824)
    parser.add_argument("--organizations", type=Path, default=Path("data/organizations.csv"))
    parser.add_argument("--memberships", type=Path, default=Path("data/person_organizations.csv"))
    parser.add_argument("--relationships", type=Path, default=Path("data/relationships.csv"))
    args = parser.parse_args()
    population_rows = load_rows(args.population); people = {row["person_id"]: row for row in population_rows}
    used = {row["home_place_id"] for row in population_rows} | {row["work_place_id"] for row in population_rows}
    places = {row["place_id"]: row for row in load_rows(args.places) if row["place_id"] in used}
    organizations, memberships = make_organizations(people, places)
    graph = GraphBuilder(people, places, organizations, memberships, args.seed)
    family_people = graph.family(args.family_coverage)
    graph.coworkers(); graph.neighbors(); graph.friends(args.friend_degree)
    relationships = graph.finalized()
    write_rows(args.organizations, ["organization_id", "name", "organization_type", "place_id", "district", "member_count", "team_count"], organizations)
    write_rows(args.memberships, ["person_id", "organization_id", "team_id", "member_role"], memberships)
    write_rows(args.relationships, ["relationship_id", "person_id_a", "person_id_b", "relationship_type", "directed", "strength", "source", "description"], relationships)
    print(json.dumps({"organizations": len(organizations), "memberships": len(memberships), "relationships": len(relationships),
                      "family_people": len(family_people), "family_coverage": len(family_people) / len(people),
                      "types": Counter(row["relationship_type"] for row in relationships)}, ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()
