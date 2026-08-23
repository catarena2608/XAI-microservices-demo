"""Dựng lại đoạn prompt từ file snapshot JSON đã lưu.

Vì sao cần: đánh giá XAI phải chạy lại được mà không đụng tới cluster. Mỗi lần sửa
prompt hay đổi model mà phải tiêm lỗi lại thì mất 30 phút cho một lượt, và tệ hơn là
mỗi lượt lại ra một trạng thái hệ thống hơi khác nên không so sánh được với lượt trước.

Giữ nguyên đầu vào, chỉ đổi prompt — đó là cách duy nhất để biết prompt mới tốt hơn
prompt cũ hay chỉ là gặp may.

Cách làm: dựng lại các object nhẹ có đúng những thuộc tính mà `serialize.py` cần,
rồi gọi lại chính các hàm đó. Không chép lại logic sinh text, vì hai bản chép sẽ
lệch nhau ngay lần sửa đầu tiên.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src_thesis.graph import serialize
from src_thesis.graph.logical_graph import load_logical_topology

RUNS_DIR = Path(__file__).resolve().parents[2] / "data" / "runs"


def _findings(items: list[dict]) -> list[SimpleNamespace]:
    return [SimpleNamespace(**f) for f in items]


def _rebuild_diff(d: dict) -> SimpleNamespace:
    diff = SimpleNamespace(
        missing_edges=_findings(d.get("missing_edges", [])),
        unexpected_edges=_findings(d.get("unexpected_edges", [])),
        error_edges=_findings(d.get("error_edges", [])),
        slow_edges=_findings(d.get("slow_edges", [])),
        silent_services=d.get("silent_services", []),
        throughput_ratio=d.get("throughput_ratio"),
    )
    diff.is_clean = lambda: not (
        diff.missing_edges or diff.error_edges or diff.slow_edges
    )
    return diff


def _rebuild_graph(d: dict) -> SimpleNamespace:
    edges = {}
    for e in d.get("edges", []):
        edges[(e["source"], e["target"])] = SimpleNamespace(
            calls=e["calls"], errors=e["errors"],
            error_rate=e["error_rate"], avg_ms=e["avg_ms"], max_ms=e["max_ms"],
            how=e.get("how", ""),
        )
    return SimpleNamespace(edges=edges, nodes=set(d.get("nodes", [])))


def rebuild_prompt_text(snapshot_dict: dict, include_topology: bool = True) -> str:
    """Dựng lại y hệt đoạn text mà `SystemSnapshot.to_prompt_text()` đã sinh ra."""
    diff = _rebuild_diff(snapshot_dict.get("diff", {}))
    graph = _rebuild_graph(snapshot_dict.get("runtime_graph", {}))
    red = {k: SimpleNamespace(**v) for k, v in snapshot_dict.get("red", {}).items()}
    resources = {
        k: SimpleNamespace(**v) for k, v in snapshot_dict.get("resources", {}).items()
    }
    # File snapshot cu duoc ghi truoc khi them truong age_s va last_restart_age_s.
    # Dat gia tri mac dinh de van cham diem lai duoc, thay vi vut bo du lieu cu.
    pod_defaults = {"age_s": None, "last_restart_age_s": None, "reason": "",
                    "restarts": 0, "ready": True, "phase": "Running",
                    "deployment": "", "name": ""}
    pods = [SimpleNamespace(**{**pod_defaults, **p})
            for p in snapshot_dict.get("pods", [])]
    cpu = snapshot_dict.get("cpu", {})

    slow = {f.source for f in diff.slow_edges} | {f.target for f in diff.slow_edges}
    topo = load_logical_topology()

    parts = [
        serialize.describe_diff(diff),
        "",
        serialize.describe_red_metrics(red),
        "",
        serialize.describe_cpu(cpu, slow),
        "",
        serialize.describe_runtime_graph(graph),
        "",
        serialize.describe_pods(pods, expected=serialize.expected_deployments(topo)),
        "",
        serialize.describe_resources(resources),
    ]
    if include_topology:
        parts = [serialize.describe_topology(topo), ""] + parts
    return "\n".join(parts)


def load_cases(runs_dir: Path = RUNS_DIR) -> list[dict]:
    """Ghép mỗi snapshot "sau khi tiêm" với file ground truth tương ứng.

    Ghép theo thời gian: đáp án đúng của một snapshot là file ground truth được ghi
    GẦN NHẤT TRƯỚC nó. Cách này đúng vì quy trình luôn là tiêm lỗi rồi mới chụp ảnh,
    và mỗi lần chỉ có một lỗi đang hoạt động.

    Trả về danh sách dict {scenario, snapshot, ground_truth, prompt_text}.
    """
    snaps: list[tuple[float, str, dict]] = []
    truths: list[tuple[float, dict]] = []

    for path in sorted(runs_dir.glob("*.json")):
        if path.name == "active_fault.json":
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if "groundtruth" in path.name:
            truths.append((float(d.get("injected_at", 0)), d))
        elif d.get("label", "").endswith("-sau"):
            snaps.append((float(d.get("taken_at", 0)), d["label"], d))

    truths.sort(key=lambda t: t[0])
    cases: list[dict] = []
    for taken_at, label, snap in sorted(snaps, key=lambda s: s[0]):
        prior = [t for t in truths if t[0] <= taken_at]
        if not prior:
            continue
        gt = prior[-1][1]
        cases.append({
            "scenario": label.replace("-sau", ""),
            "snapshot": snap,
            "ground_truth": gt,
            "prompt_text": rebuild_prompt_text(snap),
        })
    return cases
