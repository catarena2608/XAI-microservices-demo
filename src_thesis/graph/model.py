"""Kiểu dữ liệu graph dùng chung cho cả sơ đồ thiết kế lẫn sơ đồ chạy thật.

Dùng chung một kiểu là điều kiện để so lệch được hai bên (`diff.py`).
Graph ở đây là đồ thị có hướng: đỉnh là service, cạnh là "A có gọi B".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class EdgeStat:
    """Số liệu quan sát được trên một cạnh. Sơ đồ thiết kế để trống phần này."""

    calls: int = 0
    errors: int = 0
    total_us: int = 0        # tổng thời gian, để tính trung bình
    max_us: int = 0
    # Cạnh này dựng ra bằng cách nào — dùng để báo cáo độ tin cậy của graph:
    #   server_span  : có span server của bên bị gọi, chắc chắn nhất
    #   ip           : tra ClusterIP từ thuộc tính server.address
    #   grpc_name    : tách tên gRPC từ tên span, dùng cho span của Python/Node.js
    how: str = "server_span"

    @property
    def avg_ms(self) -> float:
        return round(self.total_us / self.calls / 1000, 2) if self.calls else 0.0

    @property
    def max_ms(self) -> float:
        return round(self.max_us / 1000, 2)

    @property
    def error_rate(self) -> float:
        return round(self.errors / self.calls, 4) if self.calls else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(avg_ms=self.avg_ms, max_ms=self.max_ms, error_rate=self.error_rate)
        return d


@dataclass
class ServiceGraph:
    """Đồ thị service. `kind` là "logical" (thiết kế) hoặc "runtime" (chạy thật)."""

    kind: str
    nodes: set[str] = field(default_factory=set)
    edges: dict[tuple[str, str], EdgeStat] = field(default_factory=dict)

    def add_node(self, name: str) -> None:
        if name:
            self.nodes.add(name)

    def add_edge(self, source: str, target: str, *, how: str = "server_span",
                 duration_us: int = 0, is_error: bool = False) -> None:
        """Thêm một lần gọi từ source sang target. Gọi nhiều lần thì cộng dồn."""
        if not source or not target or source == target:
            return
        self.add_node(source)
        self.add_node(target)
        key = (source, target)
        stat = self.edges.get(key)
        if stat is None:
            stat = EdgeStat(how=how)
            self.edges[key] = stat
        stat.calls += 1
        stat.errors += 1 if is_error else 0
        stat.total_us += duration_us
        stat.max_us = max(stat.max_us, duration_us)
        # Cách dựng chắc chắn hơn thì được ghi đè lên cách kém chắc chắn.
        rank = {"server_span": 3, "ip": 2, "grpc_name": 1}
        if rank.get(how, 0) > rank.get(stat.how, 0):
            stat.how = how

    def edge_set(self) -> set[tuple[str, str]]:
        return set(self.edges)

    def successors(self, node: str) -> list[str]:
        return sorted(t for (s, t) in self.edges if s == node)

    def predecessors(self, node: str) -> list[str]:
        return sorted(s for (s, t) in self.edges if t == node)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "nodes": sorted(self.nodes),
            "edges": [
                {"source": s, "target": t, **stat.to_dict()}
                for (s, t), stat in sorted(self.edges.items())
            ],
        }
