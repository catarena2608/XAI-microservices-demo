"""Đọc sơ đồ thiết kế từ data/logical_topology.yaml thành ServiceGraph."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src_thesis.graph.model import ServiceGraph

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "logical_topology.yaml"


@dataclass
class LogicalTopology:
    """Sơ đồ thiết kế cùng phần chú giải đi kèm."""

    graph: ServiceGraph
    # Cạnh có thật nhưng telemetry không nhìn thấy được. diff.py phải bỏ qua chúng,
    # nếu không sẽ báo nhầm là service đã chết.
    invisible_edges: set[tuple[str, str]] = field(default_factory=set)
    traced: dict[str, bool] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    languages: dict[str, str] = field(default_factory=dict)
    critical_path: list[str] = field(default_factory=list)

    def observable_edges(self) -> set[tuple[str, str]]:
        """Các cạnh đáng lẽ phải nhìn thấy trong trace nếu hệ thống khỏe mạnh."""
        return self.graph.edge_set() - self.invisible_edges


def load_logical_topology(path: str | Path = DEFAULT_PATH) -> LogicalTopology:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    graph = ServiceGraph(kind="logical")
    topo = LogicalTopology(graph=graph)

    for name, spec in (data.get("services") or {}).items():
        graph.add_node(name)
        topo.traced[name] = bool(spec.get("traced", False))
        topo.roles[name] = str(spec.get("role", ""))
        topo.languages[name] = str(spec.get("language", ""))

        for call in spec.get("calls") or []:
            # Cho phép viết gọn "- productcatalogservice" hoặc viết đủ
            # "- {target: redis-cart, observable: false}".
            if isinstance(call, str):
                target, observable = call, True
            else:
                target = call.get("target", "")
                observable = bool(call.get("observable", True))
            if not target:
                continue
            graph.add_edge(name, target, how="logical")
            if not observable:
                topo.invisible_edges.add((name, target))

    topo.critical_path = list(data.get("critical_path") or [])
    return topo
