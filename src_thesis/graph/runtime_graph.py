"""Dựng sơ đồ CHẠY THẬT từ trace lấy về từ Jaeger.

Ba quy tắc dựng cạnh, xếp theo độ tin cậy giảm dần. Phải có đủ cả ba, vì không
quy tắc nào phủ hết hệ thống (lý do đầy đủ ở mục 4 KLTN.md):

  1. server_span — span client có span server làm con. Chắc chắn nhất vì bên bị gọi
     tự xưng tên. Chỉ áp dụng được cho 7 service có OpenTelemetry.
  2. ip — tra `server.address` + `server.port` vào bảng ClusterIP. Đây là đường duy
     nhất nhìn thấy `cartservice`, `shippingservice`, `adservice`.
  3. grpc_name — tách tên gRPC từ tên span. Dùng cho span của Python và Node.js,
     hai loại này không ghi `server.address`.
"""

from __future__ import annotations

from src_thesis.graph.model import ServiceGraph
from src_thesis.naming import is_noise, resolve_target
from src_thesis.telemetry.jaeger_client import Span


def build_runtime_graph(
    spans: list[Span],
    endpoint_map: dict[tuple[str, int], str],
) -> ServiceGraph:
    """Gộp danh sách span thành một đồ thị có hướng kèm số liệu từng cạnh."""
    graph = ServiceGraph(kind="runtime")

    by_id: dict[str, Span] = {s.span_id: s for s in spans}
    # Con của mỗi span, để tìm span server tương ứng với một span client.
    children: dict[str, list[Span]] = {}
    for s in spans:
        if s.parent_id:
            children.setdefault(s.parent_id, []).append(s)

    for s in spans:
        graph.add_node(s.service)

    for s in spans:
        if is_noise(s.operation):
            continue
        if s.kind != "client":
            # Span server không tự tạo cạnh. Cạnh luôn xuất phát từ phía người gọi,
            # nếu tính cả hai phía thì mỗi lần gọi bị đếm hai lần.
            continue

        source = s.service
        target = None
        how = ""

        # Quy tắc 1
        for c in children.get(s.span_id, []):
            if c.kind == "server" and c.service and c.service != source:
                target, how = c.service, "server_span"
                break

        # Quy tắc 2 và 3
        if target is None:
            target, how_found = resolve_target(
                endpoint_map, s.server_address, s.server_port, s.operation
            )
            how = "ip" if how_found == "ip" else "grpc_name"

        if target is None:
            continue

        graph.add_edge(
            source, target, how=how, duration_us=s.duration_us, is_error=s.is_error
        )

    # Span server mồ côi: bên bị gọi có ghi span nhưng span của người gọi không lấy
    # được (Jaeger giới hạn số trace). Vẫn đưa đỉnh vào graph để không kết luận nhầm
    # là service đã chết.
    for s in spans:
        if s.kind == "server" and s.parent_id and s.parent_id not in by_id:
            graph.add_node(s.service)

    return graph


def edge_source_summary(graph: ServiceGraph) -> dict[str, int]:
    """Đếm mỗi quy tắc dựng được bao nhiêu cạnh. Số này đưa vào báo cáo."""
    out: dict[str, int] = {}
    for stat in graph.edges.values():
        out[stat.how] = out.get(stat.how, 0) + 1
    return out
