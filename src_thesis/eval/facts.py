"""Bảng sự kiện: mọi con số và trạng thái mà LLM ĐÃ NHÌN THẤY khi chẩn đoán.

Dùng chung cho ba phần đánh giá XAI:

  - E1, độ bám dữ liệu (`grounding.py`): đối chiếu từng con số trong lời giải thích
    với bảng này.
  - E2, phép thử phản thực (`counterfactual.py`): biết tín hiệu nào đang bất thường
    để sửa nó đi.
  - Bộ chẩn đoán bằng luật (`rule_baseline.py`): đọc đúng nguồn mà LLM đọc.

DỰNG TỪ SNAPSHOT, NHƯNG CHỈ GIỮ NHỮNG GÌ CÓ TRONG PROMPT. Snapshot chứa nhiều hơn
prompt: CPU của mọi pod trong khi prompt chỉ in service đáng ngờ, RAM của mọi pod
trong khi prompt chỉ in 8 pod, tuổi của mọi pod trong khi prompt chỉ in pod bất
thường. Một con số đúng với hệ thống mà LLM không được xem thì không thể là căn cứ
của lời giải thích — LLM trích trúng nó chỉ có thể là do trùng hợp. Nên mỗi sự kiện
mang cờ `shown`, và E1 chỉ chấp nhận sự kiện có `shown`.

Cờ `shown` xét bằng cách dò DÒNG tương ứng trong chính đoạn prompt, chứ không chép
lại luật chọn dòng của `serialize.py` — chép lại thì hai bản lệch nhau ngay lần sửa
đầu tiên (cùng lý do với `replay.py`).

Mỗi sự kiện ghi kèm `where`: nó nằm ở mục nào của prompt, để báo cáo chỉ được tận
chỗ mà con số được lấy ra.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src_thesis.eval.replay import rebuild_prompt_text
from src_thesis.graph.diff import (
    ERROR_RATE_THRESHOLD,
    SLOW_ABSOLUTE_MS,
    THROUGHPUT_COLLAPSE_RATIO,
)
from src_thesis.graph.logical_graph import load_logical_topology
from src_thesis.graph.serialize import INFRA_PODS, expected_deployments

# Hai nguong lay DUNG gia tri mac dinh cua serialize.py, de "bat thuong" o day
# trung voi "bat thuong" ma prompt da danh dau cho LLM:
#   describe_pods(recent_restart_s=600)  -> pod "vua tao lai"
#   describe_cpu(ratio_alert=0.7)        -> "<-- AT LIMIT"
RECENT_RESTART_S = 600.0
CPU_ALERT_RATIO = 0.7

GLOBAL = "*"   # thuc the "ca he thong", vi du thong luong so voi luc khoe

# Loai su kien. Ten ngan vi xuat hien trong file ket qua hang tram lan.
EDGE_KINDS = (
    "calls", "errors", "error_pct", "avg_ms", "max_ms",
    "base_avg_ms",       # do tre trung binh luc khoe manh, lay tu phan DEVIATIONS
    "slow_ratio",        # cham gap bao nhieu lan
    "base_error_pct",    # ti le loi luc khoe manh
    "threshold_ms",      # nguong tuyet doi 500ms khi khong co anh nen
)
SERVICE_KINDS = (
    "req_rate", "error_pct", "p95_ms",
    "cpu_used", "cpu_limit", "cpu_pct",     # muc CPU USAGE vs LIMIT
    "cpu_cores", "mem_mi",                  # muc POD RESOURCES
    "age_s", "restart_age_s",               # muc POD HEALTH
    "slow_callers_n", "error_callers_n",    # dem tu phan DEVIATIONS
    "slow_callees_n", "error_callees_n",
)
GLOBAL_KINDS = (
    "throughput_pct", "pods_total",
    "slow_edges_n", "error_edges_n", "missing_edges_n",
    "feedback",          # so trong phan hoi cua vong truoc, cung nam trong prompt
)


def edge_key(source: str, target: str) -> str:
    return f"{source}->{target}"


def service_of_pod(pod: str) -> str:
    """Bo hai doan hash cuoi cua ten pod, giong `serialize.describe_cpu`."""
    return pod.rsplit("-", 2)[0]


@dataclass(frozen=True)
class Fact:
    """Một con số cụ thể nằm trong prompt."""

    entity: str      # ten service, "a->b" cho canh, hoac "*" cho ca he thong
    kind: str
    value: float
    where: str       # muc cua prompt chua con so
    shown: bool = True


@dataclass(frozen=True)
class Signal:
    """Một dấu hiệu bất thường mà chính hệ thống đã đánh dấu trong prompt.

    Đây là "vũ trụ" chung để đo độ đầy đủ (E1) và để chia nhóm trích/không trích
    cho phép thử phản thực (E2). Định nghĩa từ snapshot, KHÔNG từ lời giải thích,
    nên hai nhóm của E2 là một phép chia của cùng một tập.
    """

    key: str                     # vi du "slow:frontend->productcatalogservice"
    kind: str                    # slow_edge | error_edge | gone | recreated | cpu_limit
    services: tuple[str, ...]    # (nguon, dich) voi canh, (service,) voi service
    detail: str


@dataclass
class FactTable:
    """Mọi thứ LLM đã thấy, đã sắp theo thực thể để tra nhanh."""

    facts: list[Fact] = field(default_factory=list)
    services: set[str] = field(default_factory=set)
    # False khi chi dung duoc tu bang RED rut gon (nhat ky agent cu, chua luu
    # snapshot). Luc do moi khang dinh ve canh, CPU, pod deu khong kiem duoc.
    complete: bool = True

    # Trang thai, cho cac khang dinh dang chu ("NO PODS", "AT LIMIT", "missing")
    gone: set[str] = field(default_factory=set)
    recreated: set[str] = field(default_factory=set)
    edges: dict[tuple[str, str], dict] = field(default_factory=dict)
    slow_edges: set[tuple[str, str]] = field(default_factory=set)
    error_edges: set[tuple[str, str]] = field(default_factory=set)
    missing_edges: set[tuple[str, str]] = field(default_factory=set)
    throughput_collapsed: bool = False
    has_cpu_data: bool = False
    cpu_pct: dict[str, float] = field(default_factory=dict)
    p95: dict[str, float] = field(default_factory=dict)
    error_pct: dict[str, float] = field(default_factory=dict)
    replicas: dict[str, int] = field(default_factory=dict)
    ready: dict[str, int] = field(default_factory=dict)
    cpu_limit_cores: dict[str, float] = field(default_factory=dict)
    signals: list[Signal] = field(default_factory=list)

    _index: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------

    def add(self, entity: str, kind: str, value, where: str, shown: bool = True) -> None:
        if value is None:
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if v != v:          # NaN: "n/a" trong prompt, khong phai mot con so
            return
        f = Fact(entity, kind, v, where, shown)
        self.facts.append(f)
        self._index.setdefault((entity, kind), []).append(f)

    def get(self, entity: str, kinds) -> list[Fact]:
        out: list[Fact] = []
        for k in kinds:
            out.extend(f for f in self._index.get((entity, k), []) if f.shown)
        return out

    def shown_facts(self) -> list[Fact]:
        return [f for f in self.facts if f.shown]

    def edges_of(self, service: str) -> list[tuple[str, str]]:
        """Các cạnh chạm tới service, cạnh đi VÀO xếp trước (người gọi đo nó)."""
        into = [e for e in self.edges if e[1] == service]
        out = [e for e in self.edges if e[0] == service]
        return into + out


# ======================================================================
# DUNG BANG
# ======================================================================

_SLOW_BASE = re.compile(
    r"trung binh ([\d.]+)ms, luc khoe manh ([\d.]+)ms \(cham gap ([\d.]+) lan\)")
_SLOW_ABS = re.compile(r"trung binh ([\d.]+)ms, vuot nguong ([\d.]+)ms")
_ERR = re.compile(r"ti le loi ([\d.]+)% \((\d+)/(\d+) lan goi\)"
                  r"(?:, luc khoe manh ([\d.]+)%)?")
_NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def _section_lines(prompt: str, title: str) -> list[str]:
    """Các dòng thuộc một mục của prompt. Mục kết thúc ở dòng trống."""
    lines = prompt.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if line.startswith(title):
            inside = True
            continue
        if inside:
            if not line.strip():
                break
            out.append(line)
    return out


def build_fact_table(snapshot: dict, prompt_text: str | None = None) -> FactTable:
    """Dựng bảng sự kiện từ snapshot đầy đủ.

    `prompt_text` là chuỗi ĐÃ GỬI cho LLM, kể cả phần phản hồi của vòng trước. Không
    truyền thì dựng lại từ snapshot — đúng y chuỗi gốc khi không có phản hồi.
    """
    snapshot_text = rebuild_prompt_text(snapshot)
    prompt = prompt_text if prompt_text else snapshot_text
    t = FactTable()

    topo = load_logical_topology()
    t.services |= set(topo.graph.nodes)

    # --- muc OBSERVED CALL GRAPH ---
    graph_lines = _section_lines(prompt, "OBSERVED CALL GRAPH")
    for e in (snapshot.get("runtime_graph") or {}).get("edges", []):
        s, d = e.get("source", ""), e.get("target", "")
        if not s or not d:
            continue
        t.services |= {s, d}
        t.edges[(s, d)] = e
        key = edge_key(s, d)
        shown = any(line.startswith(f"  {s} -> {d}: ") for line in graph_lines)
        where = "OBSERVED CALL GRAPH"
        t.add(key, "calls", e.get("calls"), where, shown)
        t.add(key, "errors", e.get("errors"), where, shown)
        t.add(key, "error_pct", (e.get("error_rate") or 0.0) * 100, where, shown)
        t.add(key, "avg_ms", e.get("avg_ms"), where, shown)
        t.add(key, "max_ms", e.get("max_ms"), where, shown)

    # --- muc DEVIATIONS: luon in day du ---
    diff = snapshot.get("diff") or {}
    where = "DEVIATIONS"
    for f in diff.get("slow_edges", []):
        s, d, detail = f["source"], f["target"], f.get("detail", "")
        t.slow_edges.add((s, d))
        key = edge_key(s, d)
        m = _SLOW_BASE.search(detail)
        if m:
            t.add(key, "avg_ms", m.group(1), where)
            t.add(key, "base_avg_ms", m.group(2), where)
            t.add(key, "slow_ratio", m.group(3), where)
        m = _SLOW_ABS.search(detail)
        if m:
            t.add(key, "avg_ms", m.group(1), where)
            t.add(key, "threshold_ms", m.group(2), where)
    for f in diff.get("error_edges", []):
        s, d, detail = f["source"], f["target"], f.get("detail", "")
        t.error_edges.add((s, d))
        key = edge_key(s, d)
        m = _ERR.search(detail)
        if m:
            t.add(key, "error_pct", m.group(1), where)
            t.add(key, "errors", m.group(2), where)
            t.add(key, "calls", m.group(3), where)
            if m.group(4) is not None:
                t.add(key, "base_error_pct", m.group(4), where)
    for f in diff.get("missing_edges", []):
        t.missing_edges.add((f["source"], f["target"]))

    ratio = diff.get("throughput_ratio")
    if ratio is not None:
        t.throughput_collapsed = ratio < THROUGHPUT_COLLAPSE_RATIO
        # Prompt chi in con so nay trong dong CANH BAO, tuc khi thong luong da sup.
        t.add(GLOBAL, "throughput_pct", ratio * 100, "DEVIATIONS (WARNING)",
              shown=t.throughput_collapsed)

    t.add(GLOBAL, "slow_edges_n", len(t.slow_edges), where)
    t.add(GLOBAL, "error_edges_n", len(t.error_edges), where)
    t.add(GLOBAL, "missing_edges_n", len(t.missing_edges), where)
    for svc in t.services:
        t.add(svc, "slow_callers_n",
              len({s for s, d in t.slow_edges if d == svc}), where)
        t.add(svc, "error_callers_n",
              len({s for s, d in t.error_edges if d == svc}), where)
        t.add(svc, "slow_callees_n",
              len({d for s, d in t.slow_edges if s == svc}), where)
        t.add(svc, "error_callees_n",
              len({d for s, d in t.error_edges if s == svc}), where)

    # --- muc SERVICE METRICS ---
    red_lines = _section_lines(prompt, "SERVICE METRICS")
    for name, r in (snapshot.get("red") or {}).items():
        t.services.add(name)
        shown = any(line.startswith(f"  {name}: ") for line in red_lines)
        where = "SERVICE METRICS"
        t.add(name, "req_rate", r.get("request_rate"), where, shown)
        t.add(name, "error_pct", (r.get("error_rate") or 0.0) * 100, where, shown)
        t.add(name, "p95_ms", r.get("p95_ms"), where, shown)
        if shown:
            p = r.get("p95_ms")
            if p is not None and p == p:
                t.p95[name] = float(p)
            t.error_pct[name] = (r.get("error_rate") or 0.0) * 100

    # --- muc CPU USAGE vs LIMIT ---
    cpu_lines = _section_lines(prompt, "CPU USAGE vs LIMIT")
    cpu = snapshot.get("cpu") or {}
    t.has_cpu_data = bool(cpu)
    for pod, v in cpu.items():
        svc = service_of_pod(pod)
        shown = any(line.startswith(f"  {svc}: using") for line in cpu_lines)
        where = "CPU USAGE vs LIMIT"
        t.add(svc, "cpu_used", v.get("used_cores"), where, shown)
        t.add(svc, "cpu_limit", v.get("limit_cores"), where, shown)
        r = v.get("ratio")
        if r is not None:
            t.add(svc, "cpu_pct", r * 100, where, shown)
            if shown:
                t.cpu_pct[svc] = r * 100
        lim = v.get("limit_cores")
        if lim is not None:
            # Tran CPU dung de kiem dieu kien tien quyet cpu_limit_eq. Day la
            # khang dinh ve TRANG THAI, nen xet ca dong khong in ra.
            t.cpu_limit_cores[svc] = float(lim)

    # --- muc POD RESOURCES ---
    res_lines = _section_lines(prompt, "POD RESOURCES")
    for pod, v in (snapshot.get("resources") or {}).items():
        svc = service_of_pod(pod)
        shown = any(line.startswith(f"  {pod}: cpu") for line in res_lines)
        where = "POD RESOURCES"
        t.add(svc, "cpu_cores", v.get("cpu_cores"), where, shown)
        mem = v.get("memory_bytes")
        if mem is not None:
            t.add(svc, "mem_mi", mem / 1024 / 1024, where, shown)

    # --- muc POD HEALTH ---
    pod_lines = _section_lines(prompt, "POD HEALTH")
    pods = [p for p in (snapshot.get("pods") or [])
            if not str(p.get("name", "")).startswith(INFRA_PODS)]
    for p in pods:
        dep = p.get("deployment", "")
        if not dep:
            continue
        t.replicas[dep] = t.replicas.get(dep, 0) + 1
        t.ready[dep] = t.ready.get(dep, 0) + (1 if p.get("ready") else 0)
        shown = any(line.startswith(f"  {p.get('name')}: phase=") for line in pod_lines)
        where = "POD HEALTH"
        age, rst = p.get("age_s"), p.get("last_restart_age_s")
        t.add(dep, "age_s", age, where, shown)
        t.add(dep, "restart_age_s", rst, where, shown)
        if shown and ((age is not None and age <= RECENT_RESTART_S)
                      or (rst is not None and rst <= RECENT_RESTART_S)):
            t.recreated.add(dep)
    running = set(t.replicas)
    t.gone = {d for d in expected_deployments(topo) if d not in running}
    m = re.search(r"(?:all|the other) (\d+) pods", "\n".join(pod_lines))
    if m:
        t.add(GLOBAL, "pods_total", m.group(1), "POD HEALTH")

    # --- phan hoi cua vong truoc: cung la thu LLM da doc ---
    if prompt_text and prompt_text.startswith(snapshot_text):
        for n in _NUM.findall(prompt_text[len(snapshot_text):]):
            t.add(GLOBAL, "feedback", n, "PREVIOUS ATTEMPT")

    t.signals = _signals(t)
    return t


def build_partial_table(red: dict) -> FactTable:
    """Bảng sự kiện khi chỉ còn bảng RED rút gọn của nhật ký agent.

    Nhật ký ghi TRƯỚC khi agent lưu snapshot (trước bước A, 2026-10-07) chỉ giữ ba
    con số mỗi service. Dựng bảng từ đó thì kiểm được khẳng định về p95, tỉ lệ lỗi,
    lưu lượng của từng service; mọi khẳng định về cạnh, CPU, pod là "không kiểm được".
    """
    t = FactTable(complete=False)
    t.services |= set(load_logical_topology().graph.nodes)
    for name, r in (red or {}).items():
        t.services.add(name)
        where = "SERVICE METRICS (bang rut gon)"
        t.add(name, "req_rate", r.get("request_rate"), where)
        t.add(name, "error_pct", (r.get("error_rate") or 0.0) * 100, where)
        t.add(name, "p95_ms", r.get("p95_ms"), where)
        p = r.get("p95_ms")
        if p is not None and p == p:
            t.p95[name] = float(p)
        t.error_pct[name] = (r.get("error_rate") or 0.0) * 100
    return t


def _signals(t: FactTable) -> list[Signal]:
    """Các dấu hiệu bất thường mà prompt đã đánh dấu sẵn cho LLM.

    Cạnh MẤT chỉ tính khi thông lượng chưa sụp: lúc đã sụp, prompt tự ghi chúng là
    KÉM TIN CẬY, và đòi lời giải thích nhắc tới chúng là đòi sai.
    """
    out: list[Signal] = []
    for s, d in sorted(t.error_edges):
        out.append(Signal(f"error:{s}->{d}", "error_edge", (s, d),
                          f"{s} -> {d} loi"))
    for s, d in sorted(t.slow_edges):
        out.append(Signal(f"slow:{s}->{d}", "slow_edge", (s, d),
                          f"{s} -> {d} cham"))
    if not t.throughput_collapsed:
        for s, d in sorted(t.missing_edges):
            out.append(Signal(f"missing:{s}->{d}", "missing_edge", (s, d),
                              f"{s} -> {d} mat"))
    for svc in sorted(t.gone):
        out.append(Signal(f"gone:{svc}", "gone", (svc,), f"{svc} khong con pod nao"))
    for svc in sorted(t.recreated):
        out.append(Signal(f"recreated:{svc}", "recreated", (svc,),
                          f"{svc} vua tao lai pod"))
    for svc, pct in sorted(t.cpu_pct.items()):
        if pct >= CPU_ALERT_RATIO * 100:
            out.append(Signal(f"cpu:{svc}", "cpu_limit", (svc,),
                              f"{svc} cham tran CPU {pct:.0f}%"))
    return out


# Nguong cho cac khang dinh dang chu ve do tre va loi. Lay tu diff.py de "cao" o day
# trung voi "bat thuong" cua chinh he thong, khong tu dat nguong moi.
HIGH_LATENCY_MS = SLOW_ABSOLUTE_MS
HIGH_ERROR_PCT = ERROR_RATE_THRESHOLD * 100
