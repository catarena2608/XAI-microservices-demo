"""Bộ chẩn đoán bằng luật viết tay — mốc để so với LLM.

VÌ SAO CẦN: phần "How to read the data" của prompt (prompt_templates.py) đã viết sẵn
gần như toàn bộ tri thức chẩn đoán dưới dạng luật. Câu hỏi công bằng phải đặt ra:
LLM có làm được gì hơn chính những luật đó không? Không có mốc này thì độ chính xác
của LLM không nói lên được điều gì — có thể 100% đúng chỉ vì luật đã viết sẵn đáp án.

File này chạy ĐÚNG các luật đó bằng code, trên ĐÚNG bảng sự kiện mà LLM đọc
(`facts.py`). Không đọc biến môi trường, không đọc gì ngoài snapshot.

HAI CÁCH DÙNG:

1. So độ chính xác: luật và LLM chẩn đoán cùng một bộ snapshot có đáp án.
2. Kiểm chính bộ chấm E1: lời giải thích do luật sinh ra trích số TỪ bảng sự kiện,
   nên E1 phải chấm nó 2/2 và 100% grounded. Ra khác thì bộ chấm có lỗi, không phải
   luật có lỗi — đây là phép thử ngược cho `grounding.py`.

ĐIỀU KHÔNG ĐƯỢC NÓI: luật đúng bao nhiêu ca thì không có nghĩa LLM "thừa". Luật chỉ
phủ những mẫu đã gặp; giá trị của LLM, nếu có, nằm ở ca lạ và ở lời giải thích bằng
lời. Mốc này cho biết LLM hơn hay kém luật TRÊN BỘ DỮ LIỆU NÀY, không hơn.

`confidence` của luật là nhãn cố định theo luật đã khớp, KHÔNG phải xác suất đã hiệu
chỉnh. Không dùng nó để so với confidence của LLM.
"""

from __future__ import annotations

from src_thesis.eval.facts import (
    CPU_ALERT_RATIO,
    FactTable,
    build_fact_table,
)
from src_thesis.graph.diff import SLOW_ABSOLUTE_MS
from src_thesis.graph.logical_graph import load_logical_topology
from src_thesis.xai.schema import Explanation

# "Mot nguoi goi cham toi NHIEU dich" — prompt noi sau dich; o day lay tu ba tro len
# de khong bo sot ca chi co ba bon canh tren cua so quan sat.
RADIATING_MIN_CALLEES = 3
# Cung ten voi luat "Slow edges CONVERGING on one service" cua prompt.
CONVERGING_MIN_CALLERS = 2


def _fmt_slow(t: FactTable, s: str, d: str) -> str:
    key = f"{s}->{d}"
    avg = t.get(key, ["avg_ms"])
    base = t.get(key, ["base_avg_ms"])
    ratio = t.get(key, ["slow_ratio"])
    txt = f"{s} -> {d}: avg {avg[0].value:g}ms" if avg else f"{s} -> {d}: slow"
    if base and ratio:
        txt += f" vs healthy {base[0].value:g}ms ({ratio[0].value:g}x slower)"
    return txt


def _fmt_error(t: FactTable, s: str, d: str) -> str:
    key = f"{s}->{d}"
    pct, err, calls = (t.get(key, [k]) for k in ("error_pct", "errors", "calls"))
    if pct and err and calls:
        return (f"{s} -> {d}: {pct[0].value:.1f}% errors "
                f"({err[0].value:g}/{calls[0].value:g} calls)")
    return f"{s} -> {d}: failing calls"


def _upstream(t: FactTable, root: str) -> list[str]:
    """Các service bị lan tới: ai gọi vào root qua một cạnh lỗi hoặc chậm, đi ngược lên."""
    bad = t.slow_edges | t.error_edges
    seen, todo = {root}, [root]
    while todo:
        cur = todo.pop()
        for s, d in bad:
            if d == cur and s not in seen:
                seen.add(s)
                todo.append(s)
    seen.discard(root)
    return sorted(seen)


def _follow_down(edges: set[tuple[str, str]], start: str, t: FactTable,
                 metric: str) -> tuple[str, list[str]]:
    """Đi xuống theo cạnh xấu cho tới service không còn cạnh xấu đi ra.

    Luật "Latency propagates upward exactly like errors do" của prompt: service vừa
    chậm vừa có cạnh đi ra chậm là đang CHUYỂN TIẾP độ trễ, không tự sinh ra nó.
    """
    path, cur = [start], start
    while True:
        outs = [(s, d) for s, d in edges if s == cur and d not in path]
        if not outs:
            return cur, path

        def score(e):
            f = t.get(f"{e[0]}->{e[1]}", [metric])
            return f[0].value if f else 0.0

        cur = max(outs, key=score)[1]
        path.append(cur)


def _latency_or_resource(t: FactTable, root: str) -> tuple[str, str]:
    """Phân biệt hai loại lỗi bằng đúng luật của prompt.

    CPU chạm trần -> resource_exhaustion. Không thì so p95 RIÊNG của service với độ
    trễ người gọi thấy: p95 riêng cũng cao -> chậm khi xử lý (latency); p95 riêng
    thấp -> request xếp hàng trước khi được CPU (resource_exhaustion).
    """
    pct = t.cpu_pct.get(root)
    if pct is not None and pct >= CPU_ALERT_RATIO * 100:
        return "resource_exhaustion", f"{root} is at {pct:.0f}% of its CPU limit"
    callers = [f.value for s, d in t.slow_edges if d == root
               for f in t.get(f"{s}->{d}", ["avg_ms"])]
    # Service khong phat trace thi "p95" cua no la so nguoi goi do, khong phai p95
    # rieng — so voi do tre nguoi goi thay la tu so voi chinh no.
    own = t.p95.get(root) if t.red_source.get(root) == "server" else None
    if own is not None and callers:
        if own >= 0.5 * min(callers):
            return "latency", (f"{root}'s own p95 {own:g}ms is as high as what its "
                               f"callers see, so it is slow while processing")
        return "resource_exhaustion", (f"{root}'s own p95 {own:g}ms is far below what "
                                       f"its callers see, so requests queue before CPU")
    return "latency", f"no CPU or own-latency evidence of starvation on {root}"


def _action(fault: str, root: str, t: FactTable) -> dict:
    """Một hành động theo loại lỗi, kèm điều kiện tiên quyết đọc từ chính snapshot."""
    pre: list[dict] = []
    if fault == "crash" and root in t.gone:
        name = "scale_up"
        params = [{"key": "replicas", "value": "1"}]
        pre = [{"kind": "replicas_eq", "target": root, "value": "0"}]
    elif fault in ("crash", "dependency_failure"):
        name, params = "restart_pod", []
        pre = [{"kind": "replicas_gte", "target": root, "value": "1"}]
    elif fault == "latency":
        name, params = "rollback", []
    elif fault == "resource_exhaustion":
        name, params = "adjust_resources", []
        lim = t.cpu_limit_cores.get(root)
        if lim is not None:
            pre = [{"kind": "cpu_limit_eq", "target": root, "value": f"{lim * 1000:g}m"}]
    else:
        name, params = "no_action", []
    risk = {"scale_up": "easy", "scale_down": "easy", "adjust_resources": "medium",
            "restart_pod": "hard", "rollback": "hard"}.get(name, "easy")
    return {"action": name, "target": root if name != "no_action" else root or "none",
            "params": params, "preconditions": pre, "risk_class": risk,
            "rationale": f"rule for fault type {fault}"}


def diagnose_by_rules(snapshot: dict) -> dict:
    """Chẩn đoán một snapshot bằng luật. Trả về dict đúng schema `Explanation`."""
    t = build_fact_table(snapshot)
    topo = load_logical_topology()
    critical = set(topo.critical_path)
    steps: list[str] = []
    evidence: list[str] = []

    def done(root: str, fault: str, conf: float, rule: str) -> dict:
        exp = {
            "root_cause_service": root,
            "fault_type": fault,
            "confidence": conf,
            "reasoning_chain": steps + [f"Rule applied: {rule}."],
            "propagation_path": _upstream(t, root) if root != "none" else [],
            "evidence": evidence or ["DEVIATIONS: none"],
            "proposed_actions": [_action(fault, root if root != "none" else "", t)],
        }
        return Explanation.model_validate(exp).model_dump()

    # R1. Deployment khong con pod nao — ket luan chac chan nhat
    if t.gone:
        root = sorted(t.gone, key=lambda s: (s not in critical, s))[0]
        evidence.append(f"{root}: NO PODS AT ALL")
        evidence += [_fmt_error(t, s, d) for s, d in sorted(t.error_edges) if d == root]
        steps.append(f"POD HEALTH shows {root} has no pods at all.")
        return done(root, "crash", 0.9, "deployment gone")

    # R2. Canh loi hoi tu: nhieu nguoi goi cung loi toi mot dich
    callers: dict[str, set] = {}
    for s, d in t.error_edges:
        callers.setdefault(d, set()).add(s)
    conv = [d for d, c in callers.items() if len(c) >= CONVERGING_MIN_CALLERS]
    if conv:
        top = max(conv, key=lambda d: (len(callers[d]), d in critical))
        root, path = _follow_down(t.error_edges, top, t, "error_pct")
        steps.append(f"Error edges converge on {top} from {len(callers[top])} "
                     f"distinct callers.")
        if root != top:
            steps.append(f"{top} has failing outbound calls; following them down to {root}.")
        evidence += [_fmt_error(t, s, d) for s, d in sorted(t.error_edges)
                     if d in path]
        return done(root, "crash", 0.9, "converging error edges")

    # R3. Mot nguoi goi cham toi nhieu dich, dich van nhanh -> nguoi goi nghet CPU
    callees: dict[str, set] = {}
    for s, d in t.slow_edges:
        callees.setdefault(s, set()).add(d)
    for caller, cs in sorted(callees.items(), key=lambda kv: -len(kv[1])):
        # "callees keep low p95 OF THEIR OWN": chi xet dich tu phat trace. Dich do
        # tu phia nguoi goi (cartservice...) mang ca do tre cua chinh nguoi goi dang
        # nghet, nen khong noi duoc gi ve ban than dich. Sua 2026-10-07: ban dau xet
        # ca nhung dich nay va bo sot frontend nghet CPU o mot ca S4 that.
        own = [d for d in cs if t.red_source.get(d) == "server"]
        slow_own = [d for d in own if t.p95.get(d, 0.0) >= SLOW_ABSOLUTE_MS]
        if len(cs) >= RADIATING_MIN_CALLEES and own and not slow_own:
            steps.append(f"{caller} is slow toward {len(cs)} distinct callees while "
                         f"those callees keep low p95 of their own.")
            evidence += [_fmt_slow(t, caller, d) for d in sorted(cs)]
            pct = t.cpu_pct.get(caller)
            if pct is not None:
                cpu = t.get(caller, ["cpu_used"]), t.get(caller, ["cpu_limit"])
                if cpu[0] and cpu[1]:
                    evidence.append(f"{caller}: using {cpu[0][0].value:.3f} of "
                                    f"{cpu[1][0].value:.3f} cores ({pct:.0f}% of limit)")
            return done(caller, "resource_exhaustion", 0.8, "radiating slow edges")

    # R4. Canh cham hoi tu
    slow_callers: dict[str, set] = {}
    for s, d in t.slow_edges:
        slow_callers.setdefault(d, set()).add(s)
    conv = [d for d, c in slow_callers.items() if len(c) >= CONVERGING_MIN_CALLERS]
    if conv:
        top = max(conv, key=lambda d: (len(slow_callers[d]), d in critical))
        root, path = _follow_down(t.slow_edges, top, t, "avg_ms")
        steps.append(f"Slow edges converge on {top} from {len(slow_callers[top])} "
                     f"distinct callers.")
        if root != top:
            steps.append(f"{top} has slow outbound calls; following them down to {root}.")
        fault, why = _latency_or_resource(t, root)
        steps.append(why + ".")
        evidence += [_fmt_slow(t, s, d) for s, d in sorted(t.slow_edges) if d in path]
        if root in t.p95:
            evidence.append(f"{root} p95 {t.p95[root]:g}ms")
        return done(root, fault, 0.8, "converging slow edges")

    # R5. Pod vua tao lai, khong co trieu chung manh nao khac -> pod_kill, khong lam gi
    # "No other strong symptom": khong canh loi, khong service nao cham tran CPU
    # (prompt tu danh dau "AT LIMIT"), toi da mot canh cham cham vao chinh service
    # do. Sua 2026-10-07: ban dau khong xet CPU, va goi mot ca S5 that — CPU 73%
    # tran — la pod_kill.
    strong = t.error_edges or t.gone or any(s.kind == "cpu_limit" for s in t.signals)
    if t.recreated and not strong:
        svc = sorted(t.recreated)[0]
        touching = [e for e in t.slow_edges if svc in e]
        if len(t.slow_edges) <= 1 and len(touching) == len(t.slow_edges):
            age = t.get(svc, ["age_s", "restart_age_s"])
            ages = sorted(f.value for f in age)
            evidence.append(f"{svc} pod was RECREATED {ages[0]:.0f}s ago" if ages
                            else f"{svc} pod was RECREATED")
            evidence += [_fmt_slow(t, s, d) for s, d in touching]
            steps.append(f"{svc} was recreated recently and no other strong symptom "
                         f"is present; Kubernetes already replaced it.")
            return done(svc, "pod_kill", 0.7, "recreated pod, no other symptom")

    # R6. Mot canh loi
    if t.error_edges:
        def err(e):
            f = t.get(f"{e[0]}->{e[1]}", ["error_pct"])
            return f[0].value if f else 0.0
        top = max(t.error_edges, key=err)
        root, path = _follow_down(t.error_edges, top[1], t, "error_pct")
        steps.append(f"Only isolated error edges; the worst points at {top[1]}.")
        evidence += [_fmt_error(t, s, d) for s, d in sorted(t.error_edges)
                     if d in path]
        return done(root, "crash", 0.6, "single error edge")

    # R7. Mot canh cham
    if t.slow_edges:
        def ratio(e):
            f = t.get(f"{e[0]}->{e[1]}", ["slow_ratio"])
            return f[0].value if f else 0.0
        top = max(t.slow_edges, key=ratio)
        root, path = _follow_down(t.slow_edges, top[1], t, "avg_ms")
        fault, why = _latency_or_resource(t, root)
        steps.append(f"Only isolated slow edges; the worst points at {top[1]}.")
        steps.append(why + ".")
        evidence += [_fmt_slow(t, s, d) for s, d in sorted(t.slow_edges) if d in path]
        return done(root, fault, 0.6, "single slow edge")

    # R8. Khong co gi bat thuong
    steps.append("No deviation from the design is reported.")
    return done("none", "unknown", 0.1, "healthy")
