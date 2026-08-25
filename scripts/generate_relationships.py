"""Generate organizations, teams, and a deterministic sparse social graph."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

try:
    from scripts.generate_organizations import make_organizations, write_population_with_employers
except ModuleNotFoundError:  # Direct execution from scripts/
    from generate_organizations import make_organizations, write_population_with_employers


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


class GraphBuilder:
    def __init__(self, people: dict[str, dict], places: dict[str, dict], organizations: list[dict], memberships: list[dict], seed: int) -> None:
        self.people, self.places, self.seed = people, places, seed
        self.organizations = {row["organization_id"]: row for row in organizations}
        self.memberships = {row["person_id"]: row for row in memberships}
        self.rows: list[dict] = []
        self.keys: set[tuple[str, str, str]] = set()
        self.pair_kinds: dict[tuple[str, str], set[str]] = defaultdict(set)
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
        self.pair_kinds[pair_key(a, b)].add(kind)
        self.social[a].add(b); self.social[b].add(a)
        return True

    @staticmethod
    def _number(person: dict, key: str, default: float = .5) -> float:
        try:
            return float(person.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _person_intro(person: dict) -> str:
        name = person.get("姓名") or person.get("person_id", "该人物")
        age = person.get("年龄", "年龄未知")
        job = person.get("具体职位") or person.get("职业大类") or "职业未注明"
        style = person.get("communication_style") or "沟通方式自然"
        return f"{name}（{age}岁，{job}，沟通风格偏{style}）"

    def _personality_note(self, person: dict) -> str:
        traits = [
            (abs(self._number(person, "sociability") - .5), "外向，愿意主动维系联系" if self._number(person, "sociability") >= .5 else "偏安静，更重视熟悉的小圈子"),
            (abs(self._number(person, "routine_preference") - .5), "重视固定安排" if self._number(person, "routine_preference") >= .5 else "对临时变化接受度较高"),
            (abs(self._number(person, "family_orientation") - .5), "很重视家庭联系" if self._number(person, "family_orientation") >= .5 else "更强调各自独立的生活节奏"),
            (abs(self._number(person, "warmth") - .5), "表达关心比较直接" if self._number(person, "warmth") >= .5 else "通常以实际行动而非言语表达关心"),
            (abs(self._number(person, "spontaneity") - .5), "容易接受临时邀约" if self._number(person, "spontaneity") >= .5 else "更喜欢提前约定时间"),
        ]
        return max(traits, key=lambda item: item[0])[1]

    @staticmethod
    def _place_text(place: dict) -> str:
        name = place.get("name") or place.get("place_id") or "未命名地点"
        district = place.get("district") or "GTA"
        return f"{name}（{district}）"

    def _home(self, person: dict) -> dict:
        return self.places.get(person.get("home_place_id", ""), {"name": "未记录住所", "district": "GTA"})

    def _work(self, person: dict) -> dict:
        return self.places.get(person.get("work_place_id", ""), {"name": "未记录工作地点", "district": "GTA"})

    @staticmethod
    def _strength_note(strength: float) -> str:
        if strength >= .85:
            return "两人的关系很亲近，通常会优先回应对方的消息或邀约。"
        if strength >= .65:
            return "两人保持稳定联系，遇到重要事情时通常会互相帮忙。"
        if strength >= .45:
            return "两人会定期往来，但是否见面仍取决于各自的工作和时间安排。"
        return "目前的联系以具体事务或偶尔碰面为主，私下互动相对有限。"

    def relationship_context(self, row: dict) -> str:
        a_id, b_id = row["person_id_a"], row["person_id_b"]
        a, b = self.people[a_id], self.people[b_id]
        kind, source = row["relationship_type"], row["source"]
        rng = seeded_rng(self.seed, a_id, b_id, kind, "relationship_context")
        a_intro, b_intro = self._person_intro(a), self._person_intro(b)
        a_home, b_home = self._home(a), self._home(b)
        strength = float(row["strength"])
        dynamics = (
            f"性格上，{a.get('姓名', a_id)}{self._personality_note(a)}；"
            f"{b.get('姓名', b_id)}{self._personality_note(b)}。"
        )

        if kind == "spouse":
            routines = [
                "他们通常会在周末一起采购日用品，并提前协调下一周的工作安排。",
                "工作日晚上两人多半在家吃饭，周末偶尔会去附近餐厅或商场。",
                "两人会共同处理住房和生活账单，临时行程一般会先发消息确认。",
            ]
            detail = (
                f"{a_intro}与{b_intro}是夫妻或长期伴侣，共同居住在{self._place_text(a_home)}。"
                f"{rng.choice(routines)}"
            )
        elif kind == "parent_of":
            routines = [
                "两人通常在周日晚上通话，遇到家庭事务时会临时增加联系。",
                "他们大约每两周见一次面，常选择其中一方住所或附近餐厅。",
                "父母一方会关注成年子女的工作近况，但平时尊重彼此独立的生活安排。",
            ]
            detail = (
                f"{a_intro}是{b_intro}的父母一方。{a.get('姓名', a_id)}住在{self._place_text(a_home)}，"
                f"{b.get('姓名', b_id)}已成年并独立住在{self._place_text(b_home)}。{rng.choice(routines)}"
            )
        elif kind == "sibling":
            routines = [
                "两人会在家庭节日见面，平时主要用简短消息交换近况。",
                "他们偶尔约在两处住所之间吃饭，也会互相转达其他家人的消息。",
                "两人各有独立生活圈，但遇到搬家、维修或家庭事务时通常会互相帮忙。",
            ]
            detail = (
                f"{a_intro}与{b_intro}是成年兄弟姐妹，分别居住在{self._place_text(a_home)}和"
                f"{self._place_text(b_home)}。{rng.choice(routines)}"
            )
        elif kind == "extended_family":
            relation = rng.choice(["表亲或堂亲", "关系较近的成年亲属", "通过父母一代保持联系的亲属"])
            routines = [
                "他们通常在节假日或家庭聚会中见面，平时偶尔通过消息联系。",
                "两人不常临时拜访，但家里有重要事情时会主动询问并提供帮助。",
                "联系多由共同亲属发起，见面地点通常在其中一方住所附近。",
            ]
            detail = (
                f"{a_intro}与{b_intro}是{relation}，目前分别住在{self._place_text(a_home)}和"
                f"{self._place_text(b_home)}。{rng.choice(routines)}"
            )
        elif kind == "coworker":
            membership = self.memberships.get(a_id, {})
            org = self.organizations.get(membership.get("organization_id", ""), {})
            workplace = self._work(a)
            same_team = source == "shared_team"
            routines = [
                "他们常在午餐前后同步进度，有紧急任务时会直接给对方发消息。",
                "两人的工作有固定交接环节，通常会在下班前确认尚未完成的事项。",
                "他们偶尔会在工作地点附近买咖啡，并顺便讨论当天的任务。",
            ]
            team_text = "同一团队" if same_team else "同一组织的不同团队"
            detail = (
                f"{a_intro}与{b_intro}在{org.get('name', '未命名组织')}任职，工作地点是"
                f"{self._place_text(workplace)}，两人属于{team_text}，"
                f"职位分别是{a.get('具体职位', '未注明')}和{b.get('具体职位', '未注明')}。{rng.choice(routines)}"
            )
        elif kind in {"neighbor", "housemate"}:
            relation = "室友或同住者" if kind == "housemate" else "邻居"
            routines = [
                "两人见面时会简短聊天，也会在对方不在家时帮忙留意包裹。",
                "他们平时保持礼貌距离，但遇到停车、维修或社区通知时会互相提醒。",
                "两人偶尔在住宅附近碰面，熟悉彼此通常在家的大致时间。",
            ]
            detail = (
                f"{a_intro}与{b_intro}是{relation}，住址都绑定到{self._place_text(a_home)}。"
                f"{rng.choice(routines)}"
            )
        else:
            prior = sorted(self.pair_kinds.get(pair_key(a_id, b_id), set()) - {"friend"})
            prior_names = {"coworker": "工作往来", "neighbor": "邻里往来", "housemate": "共同居住经历",
                           "spouse": "伴侣关系", "sibling": "家庭关系", "extended_family": "亲属关系",
                           "parent_of": "亲子关系"}
            if source == "existing_contact" and prior:
                origin = f"两人在原有的{prior_names.get(prior[0], '社会往来')}中逐渐熟悉并成为朋友"
            elif source == "nearby_and_similar_age":
                origin = f"两人因年龄相近且生活区域接近，在{a_home.get('district', 'GTA')}的社区活动中认识"
            elif source == "similar_work_and_age":
                origin = "两人年龄与职业背景相近，通过一次行业或共同兴趣活动认识"
            else:
                origin = "两人处于相似生活阶段，经共同认识的人介绍后成为朋友"
            routines = [
                "他们常约在两人工作地点之间喝咖啡，通常会提前一两天确认时间。",
                "两人偶尔在周末一起吃饭或逛商场，临时取消时会主动说明。",
                "他们主要通过消息保持联系，大约每月安排一次线下见面。",
                "天气合适时两人会选择公园散步，忙碌时则改为短时间喝咖啡。",
            ]
            detail = (
                f"{a_intro}住在{self._place_text(a_home)}，{b_intro}住在{self._place_text(b_home)}；"
                f"{origin}。{rng.choice(routines)}"
            )
        return f"{detail}{dynamics}{self._strength_note(strength)}"

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
        for index, row in enumerate(ordered, 1):
            row["relationship_id"] = f"REL{index:07d}"
            row["relationship_context"] = self.relationship_context(row)
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
    all_places = {row["place_id"]: row for row in load_rows(args.places)}
    places = {place_id: all_places[place_id] for place_id in used}
    organizations, memberships = make_organizations(people, places, all_places)
    places.update({row["place_id"]: all_places[row["place_id"]] for row in organizations})
    graph = GraphBuilder(people, places, organizations, memberships, args.seed)
    family_people = graph.family(args.family_coverage)
    graph.coworkers(); graph.neighbors(); graph.friends(args.friend_degree)
    relationships = graph.finalized()
    write_rows(args.organizations, ["organization_id", "name", "organization_type", "place_id", "district",
        "member_count", "team_count", "employee_capacity", "name_source", "is_real_name", "match_confidence",
        "max_match_distance_m", "work_place_count", "source", "source_id", "source_url", "description"], organizations)
    write_rows(args.memberships, ["person_id", "organization_id", "team_id", "member_role", "work_place_id",
                                      "match_distance_m", "match_confidence"], memberships)
    write_rows(args.relationships, ["relationship_id", "person_id_a", "person_id_b", "relationship_type", "directed", "strength", "source", "description", "relationship_context"], relationships)
    write_population_with_employers(args.population, population_rows, memberships)
    print(json.dumps({"organizations": len(organizations), "memberships": len(memberships), "relationships": len(relationships),
                      "family_people": len(family_people), "family_coverage": len(family_people) / len(people),
                      "types": Counter(row["relationship_type"] for row in relationships)}, ensure_ascii=False, default=dict))


if __name__ == "__main__":
    main()
