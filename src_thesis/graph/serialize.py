"""Biến graph, diff và metric thành đoạn văn bản cho LLM đọc.

Viết bằng tiếng Anh vì đây là phần đi thẳng vào prompt: model hiểu tốt hơn và tốn
ít token hơn tiếng Việt. Phần tiếng Việt chỉ dành cho người đọc báo cáo.

Nguyên tắc viết: ngắn, có số, không tính từ. Mỗi dòng thừa đều là tiền API.
"""

from __future__ import annotations

from src_thesis.graph.diff import GraphDiff
from src_thesis.graph.logical_graph import LogicalTopology
from src_thesis.graph.model import ServiceGraph


def describe_topology(topo: LogicalTopology) -> str:
    """Mô tả hệ thống ở trạng thái thiết kế. Phần này không đổi giữa các ca."""
    lines = ["SYSTEM DESIGN (expected topology):"]
    for src in sorted(topo.graph.nodes):
        targets = topo.graph.successors(src)
        if targets:
            lines.append(f"  {src} -> {', '.join(targets)}")
    lines.append("")
    lines.append("OBSERVABILITY LIMITS (important when reading the data below):")
    untraced = sorted(n for n, t in topo.traced.items() if not t)
    lines.append(
        f"  These services emit NO traces of their own: {', '.join(untraced)}."
    )
    lines.append(
        "  Their latency and error rate are measured indirectly from the caller side, "
        "so the numbers include network time and are slightly higher than reality."
    )
    lines.append(
        "  redis-cart is completely invisible: no data at all does NOT mean it is down."
    )
    lines.append(f"  Critical business path: {' -> '.join(topo.critical_path)}")
    return "\n".join(lines)


def describe_runtime_graph(graph: ServiceGraph, max_edges: int = 40) -> str:
    """Mô tả quan hệ gọi nhau quan sát được, kèm số liệu từng cạnh."""
    lines = ["OBSERVED CALL GRAPH (last observation window):"]
    edges = sorted(graph.edges.items(), key=lambda kv: -kv[1].calls)[:max_edges]
    for (s, t), stat in edges:
        lines.append(
            f"  {s} -> {t}: {stat.calls} calls, "
            f"{stat.error_rate * 100:.1f}% errors, "
            f"avg {stat.avg_ms}ms, max {stat.max_ms}ms"
        )
    if not edges:
        lines.append("  (no calls observed)")
    return "\n".join(lines)


def describe_red_metrics(red: dict, max_rows: int = 20) -> str:
    """Mô tả RED metrics từng service."""
    lines = ["SERVICE METRICS (rate / errors / latency):"]
    rows = sorted(red.values(), key=lambda r: -r.request_rate)[:max_rows]
    for r in rows:
        p95 = "n/a" if r.p95_ms != r.p95_ms else f"{r.p95_ms}ms"
        note = "" if r.source == "server" else " [measured from caller side]"
        lines.append(
            f"  {r.service}: {r.request_rate:.2f} req/s, "
            f"{r.error_rate * 100:.1f}% errors, p95 {p95}{note}"
        )
    if not rows:
        lines.append("  (no metrics)")
    return "\n".join(lines)


def describe_resources(resources: dict, top: int = 8) -> str:
    lines = ["POD RESOURCES (top consumers):"]
    rows = sorted(resources.values(), key=lambda r: -r.memory_bytes)[:top]
    for r in rows:
        lines.append(
            f"  {r.pod}: cpu {r.cpu_cores:.3f} cores, "
            f"mem {r.memory_bytes / 1024 / 1024:.0f}Mi"
        )
    return "\n".join(lines)


def describe_diff(diff: GraphDiff) -> str:
    """Phần lệch giữa thiết kế và thực tế. Thường là manh mối rõ nhất."""
    lines = ["DEVIATIONS FROM DESIGN (strongest signal, read this first):"]
    if diff.is_clean() and not diff.unexpected_edges and not diff.silent_services:
        lines.append("  none - the running system matches the design")
        return "\n".join(lines)

    def block(title: str, findings: list) -> None:
        if not findings:
            return
        lines.append(f"  {title}:")
        for f in findings:
            flag = " [ON CRITICAL PATH]" if f.on_critical_path else ""
            lines.append(f"    {f.source} -> {f.target}: {f.detail}{flag}")

    if diff.throughput_ratio is not None and diff.throughput_ratio < 0.5:
        lines.append(
            f"  WARNING: total call volume is only "
            f"{diff.throughput_ratio * 100:.0f}% of the healthy baseline. When throughput "
            f"collapses, edges disappear from the observation window even though they are "
            f"healthy. Treat MISSING calls below as weak evidence, not as separate faults."
        )
    block("MISSING calls (expected by design, not seen at runtime)", diff.missing_edges)
    block("FAILING calls", diff.error_edges)
    block("SLOW calls", diff.slow_edges)
    block("UNEXPECTED calls (not in design)", diff.unexpected_edges)
    if diff.silent_services:
        lines.append(
            f"  Services that should emit traces but sent nothing: "
            f"{', '.join(diff.silent_services)}"
        )
    return "\n".join(lines)


def describe_pods(pods: list, recent_restart_s: float = 600.0) -> str:
    """Chỉ liệt kê pod không bình thường. Pod khỏe mạnh không đáng tốn token.

    KHÔNG lọc theo `restarts` vì số đó cộng dồn cả những lần tắt mở cluster, gần như
    pod nào cũng khác 0. Chỉ quan tâm pod VỪA khởi động lại trong `recent_restart_s`
    giây gần đây — đó mới là dấu hiệu sự cố đang diễn ra.
    """
    bad = [
        p for p in pods
        if not p.ready
        or p.reason
        or (p.last_restart_age_s is not None and p.last_restart_age_s <= recent_restart_s)
        or (p.age_s is not None and p.age_s <= recent_restart_s)
    ]
    lines = ["POD HEALTH:"]
    if not bad:
        lines.append(f"  all {len(pods)} pods ready, no restarts")
        return "\n".join(lines)
    for p in bad:
        when = (f", restarted {p.last_restart_age_s:.0f}s ago"
                if p.last_restart_age_s is not None else "")
        if p.age_s is not None and p.age_s <= recent_restart_s:
            when += f", pod was RECREATED {p.age_s:.0f}s ago (previous pod is gone)"
        lines.append(
            f"  {p.name}: phase={p.phase}, ready={p.ready}, "
            f"reason={p.reason or 'n/a'}{when}"
        )
    return "\n".join(lines)
