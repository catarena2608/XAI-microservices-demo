"""Nạp lại ảnh nền — runtime graph của hệ thống lúc khỏe mạnh — từ file đã lưu.

VÌ SAO PHẢI CÓ FILE NÀY: `diff_graphs()` phát hiện cạnh chậm theo hai cách, và hai
cách đó cách nhau rất xa về độ nhạy.

    có ảnh nền     : chậm gấp `SLOW_RATIO` = 3 lần so với chính cạnh đó lúc khỏe
    không có nền   : chỉ bắt khi vượt `SLOW_ABSOLUTE_MS` = 500ms tuyệt đối

Số đo thật của ba kịch bản lỗi cho thấy ngưỡng tuyệt đối bỏ sót gần hết:

    S1  frontend -> productcatalogservice   157ms
    S4  frontend -> checkoutservice         284ms
    S5  frontend -> productcatalogservice   101ms

Cả ba đều dưới 500ms. Không có ảnh nền thì agent nhìn ba kịch bản này và kết luận
**hệ thống khỏe mạnh**, rồi dừng ngay ở vòng đầu. Chỉ S2 chạy được, vì service chết
sinh ra cạnh LỖI chứ không phải cạnh CHẬM, mà cạnh lỗi không cần nền để phát hiện.

Đây là kiểu hỏng im lặng nguy hiểm: agent không báo lỗi, không ném ngoại lệ, nó chỉ
nói rằng mọi thứ vẫn ổn trong khi hệ thống đang hỏng.

`scripts/inject.py` đã chụp và lưu ảnh nền sạch ở mỗi lần tiêm lỗi từ phase 2, nên
nguồn dữ liệu có sẵn — chỉ thiếu đường nạp lại.
"""

from __future__ import annotations

import json
from pathlib import Path

from src_thesis.graph.model import EdgeStat, ServiceGraph

RUNS_DIR = Path(__file__).resolve().parents[2] / "data" / "runs"

# Nhan cua snapshot duoc coi la anh nen. `inject.py` ghi "baseline" va
# "baseline-clean"; `smoke_snapshot.py` ghi "baseline".
BASELINE_LABELS = ("baseline", "baseline-clean")


def graph_from_dict(d: dict, kind: str = "runtime") -> ServiceGraph:
    """Dựng lại `ServiceGraph` từ phần `runtime_graph` của một snapshot đã lưu.

    Dựng lại `EdgeStat` thật chứ không dùng object giả, để mọi thuộc tính tính toán
    (`avg_ms`, `error_rate`) hoạt động đúng như lúc chụp.
    """
    g = ServiceGraph(kind=kind)
    for name in d.get("nodes", []):
        g.add_node(name)
    for e in d.get("edges", []):
        source, target = e.get("source"), e.get("target")
        if not source or not target:
            continue
        g.add_node(source)
        g.add_node(target)
        g.edges[(source, target)] = EdgeStat(
            calls=int(e.get("calls", 0)),
            errors=int(e.get("errors", 0)),
            total_us=int(e.get("total_us", 0)),
            max_us=int(e.get("max_us", 0)),
            how=e.get("how", "server_span"),
        )
    return g


def find_baseline_file(runs_dir: Path = RUNS_DIR) -> Path | None:
    """Tìm file ảnh nền mới nhất. Trả về None nếu chưa có cái nào.

    Lấy cái MỚI NHẤT vì cấu hình hệ thống có thể đã đổi giữa các phiên — ví dụ bản
    vá nới hạn thăm dò của `emailservice` làm số liệu nền khác hẳn trước đó. Ảnh nền
    cũ hơn thì so lệch ra kết quả sai lệch về phía báo động giả.
    """
    best: tuple[float, Path] | None = None
    for path in runs_dir.glob("*.json"):
        if path.name == "active_fault.json":
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if d.get("label") not in BASELINE_LABELS:
            continue
        taken = float(d.get("taken_at", 0))
        if best is None or taken > best[0]:
            best = (taken, path)
    return best[1] if best else None


def load_baseline_graph(runs_dir: Path = RUNS_DIR) -> tuple[ServiceGraph | None, str]:
    """Nạp ảnh nền mới nhất. Trả về (graph, mô tả nguồn).

    Trả về `(None, lý do)` khi không tìm được, để bên gọi **cảnh báo rõ ràng** thay
    vì âm thầm chạy với độ nhạy thấp. Chạy không có nền vẫn tốt hơn là không chạy,
    nhưng người dùng phải biết mình đang chạy ở chế độ nào.
    """
    path = find_baseline_file(runs_dir)
    if path is None:
        return None, (
            "khong tim thay anh nen nao trong data/runs/. Chay "
            "'python scripts/smoke_snapshot.py' luc he thong khoe manh de tao mot cai."
        )
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return None, f"khong doc duoc {path.name}: {e}"

    graph = graph_from_dict(d.get("runtime_graph", {}))
    if not graph.edges:
        return None, f"{path.name} khong co canh nao, khong dung lam nen duoc"
    return graph, f"{path.name} ({d.get('taken_at_human', '?')}, {len(graph.edges)} canh)"
