"""Build a compact car-routing graph from the local OSM PBF extract."""
from __future__ import annotations

import argparse
import math
import pickle
import re
from collections import defaultdict
from pathlib import Path

import osmium

SPEEDS_KMH = {"motorway": 100, "motorway_link": 60, "trunk": 80, "trunk_link": 50,
              "primary": 60, "primary_link": 40, "secondary": 50, "secondary_link": 35,
              "tertiary": 40, "tertiary_link": 30, "residential": 30, "unclassified": 35,
              "service": 20, "living_street": 10}


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[0] + b[0]) / 2)
    return math.hypot((a[0] - b[0]) * 111_000, (a[1] - b[1]) * 111_000 * math.cos(lat))


def speed_kmh(tags, highway: str) -> float:
    value = tags.get("maxspeed", "")
    match = re.search(r"\d+(?:\.\d+)?", value)
    if match:
        speed = float(match.group())
        if "mph" in value.lower(): speed *= 1.60934
        return min(130, max(5, speed))
    return SPEEDS_KMH[highway]


class RoadHandler(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.coords: dict[int, tuple[float, float]] = {}
        self.adjacency: dict[int, list[tuple[int, float, float]]] = defaultdict(list)
        self.parent: dict[int, int] = {}
        self.component_size: dict[int, int] = {}
        self.ways = 0

    def find(self, node: int) -> int:
        root = node
        while self.parent[root] != root: root = self.parent[root]
        while self.parent[node] != node:
            next_node = self.parent[node]; self.parent[node] = root; node = next_node
        return root

    def union(self, a: int, b: int) -> None:
        for node in (a, b):
            if node not in self.parent: self.parent[node] = node; self.component_size[node] = 1
        left, right = self.find(a), self.find(b)
        if left == right: return
        if self.component_size[left] < self.component_size[right]: left, right = right, left
        self.parent[right] = left; self.component_size[left] += self.component_size.pop(right)

    def way(self, way) -> None:
        highway = way.tags.get("highway")
        if highway not in SPEEDS_KMH or way.tags.get("access") in {"no", "private"}:
            return
        nodes = [(node.ref, (node.lat, node.lon)) for node in way.nodes if node.location.valid()]
        if len(nodes) < 2: return
        self.ways += 1
        speed_mps = speed_kmh(way.tags, highway) / 3.6
        oneway = way.tags.get("oneway") in {"yes", "true", "1"} or way.tags.get("junction") == "roundabout"
        reverse = way.tags.get("oneway") == "-1"
        for (a_id, a), (b_id, b) in zip(nodes, nodes[1:]):
            self.coords[a_id] = a; self.coords[b_id] = b
            self.union(a_id, b_id)
            meters = distance_m(a, b); seconds = max(.1, meters / speed_mps)
            if reverse:
                self.adjacency[b_id].append((a_id, meters, seconds))
            else:
                self.adjacency[a_id].append((b_id, meters, seconds))
                if not oneway: self.adjacency[b_id].append((a_id, meters, seconds))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pbf", type=Path, default=Path("data/gta-mobility.osm.pbf"))
    parser.add_argument("--output", type=Path, default=Path("data/road_network.pkl"))
    args = parser.parse_args()
    handler = RoadHandler(); handler.apply_file(str(args.pbf), locations=True, idx="flex_mem")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    largest_root = max(handler.component_size, key=handler.component_size.get)
    keep = {node for node in handler.coords if handler.find(node) == largest_root}
    coords = {node: point for node, point in handler.coords.items() if node in keep}
    adjacency = {node: [edge for edge in edges if edge[0] in keep]
                 for node, edges in handler.adjacency.items() if node in keep}
    # This pickle is an internal generated artifact; never replace it with an untrusted file.
    with args.output.open("wb") as handle:
        pickle.dump({"version": 1, "coords": coords, "adjacency": adjacency}, handle, pickle.HIGHEST_PROTOCOL)
    print({"ways": handler.ways, "all_nodes": len(handler.coords), "largest_component_nodes": len(coords),
           "directed_edges": sum(map(len, adjacency.values())), "output": str(args.output)})


if __name__ == "__main__":
    main()
