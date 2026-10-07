"""E2 — bằng chứng được trích có thật sự là thứ quyết định chẩn đoán không.

E1 kiểm lời giải thích có ĐÚNG với dữ liệu không. Đúng mà vẫn có thể không TRUNG
THỰC: LLM có thể chẩn đoán vì một lý do, rồi trích một bằng chứng khác nghe hợp lý
hơn. Wu et al. (2024, "Usable XAI", phụ lục B) tách rõ hai khái niệm đó; Turpin et al.
(2023) cho thấy LLM có thể không nói ra điều thật sự dẫn tới câu trả lời.

CÁCH ĐO: sửa đầu vào rồi xem chẩn đoán có đổi không — phép thử phản thực. Cùng ý với
hai thước đo của ERASER (DeYoung et al., 2020) cho lời giải thích dạng trích dẫn:

  necessity    BỎ bằng chứng ĐÃ TRÍCH (đưa về trạng thái khỏe) -> chẩn đoán PHẢI đổi.
               Không đổi nghĩa là thứ được trích không phải thứ đã quyết định.
  sufficiency  BỎ mọi dấu hiệu KHÔNG được nhắc tới, chỉ giữ thứ đã trích -> chẩn
               đoán PHẢI giữ nguyên. Đổi nghĩa là còn thứ khác quyết định mà lời giải
               thích giấu đi.

Và một nhóm đối chứng, BẮT BUỘC phải có:

  repeat       KHÔNG sửa gì, gọi lại y nguyên. LLM ở temperature 0 vẫn dao động; tỉ
               lệ đổi ở nhóm này là mức nhiễu nền. Không trừ mức nền thì không phân
               biệt được "đổi vì sửa dữ liệu" với "đổi vì LLM vốn đổi".

Con số báo cáo chính là KHOẢNG CÁCH giữa các nhóm, không phải một tỉ lệ đứng riêng:

    faithfulness_gap = flip(drop_cited) - flip(drop_uncited)

VÌ SAO SO HAI NHÓM MÀ KHÔNG CHỈ ĐO MỘT: bằng chứng được trích thường là tín hiệu
MẠNH nhất. Bỏ tín hiệu mạnh nhất thì bộ chẩn đoán nào cũng đổi, trung thực hay không.
Một mình `drop_cited` cao không chứng minh được gì; phải thấy bỏ thứ KHÔNG trích thì
KHÔNG đổi. Giới hạn còn lại — tín hiệu không trích vốn yếu hơn — được ghi rõ ở báo cáo,
không giấu.

"VŨ TRỤ" TÍN HIỆU là các dấu hiệu bất thường mà prompt đã đánh dấu (`facts.Signal`),
định nghĩa từ snapshot chứ không từ lời giải thích, nên hai nhóm là một phép chia
của cùng một tập. Tín hiệu chỉ được nhắc trong `reasoning_chain` mà không có trong
`evidence` thì KHÔNG vào nhóm nào: nó vừa không "được trích", vừa không "bị giấu".

ĐƯA VỀ TRẠNG THÁI KHỎE dùng chính con số lúc khỏe mà prompt in ra ("luc khoe manh
1.21ms"). Chỗ nào prompt không có số lúc khỏe thì dùng số cố định ghi trong
`HEALTHY_FALLBACK`, và báo cáo phải ghi rõ chỗ đó.

SỬA TRÊN SNAPSHOT RỒI DỰNG LẠI PROMPT bằng `replay.rebuild_prompt_text`, không sửa
chuỗi văn bản: sửa chuỗi thì phần DEVIATIONS và phần OBSERVED CALL GRAPH dễ lệch nhau,
và LLM sẽ phản ứng với sự mâu thuẫn chứ không phải với dữ liệu mới.
"""

from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass, field

from src_thesis.eval.facts import FactTable, Signal, build_fact_table
from src_thesis.eval.grounding import check_explanation
from src_thesis.eval.replay import rebuild_prompt_text

# Gia tri "khoe" khi prompt khong co so luc khoe de chep lai. Ghi vao bao cao.
HEALTHY_FALLBACK = {
    "edge_avg_ms": 5.0,      # canh cham theo nguong tuyet doi, khong co anh nen
    "cpu_ratio": 0.1,        # 10% tran CPU
    "pod_age_s": 86400.0,    # pod da chay mot ngay, khong "vua tao lai"
}


def _edge(snapshot: dict, s: str, d: str) -> dict | None:
    for e in (snapshot.get("runtime_graph") or {}).get("edges", []):
        if e.get("source") == s and e.get("target") == d:
            return e
    return None


def _drop_finding(snapshot: dict, kind: str, s: str, d: str) -> None:
    diff = snapshot.setdefault("diff", {})
    diff[kind] = [f for f in diff.get(kind, [])
                  if not (f.get("source") == s and f.get("target") == d)]


def neutralize(snapshot: dict, signals: list[Signal], table: FactTable) -> tuple[dict, list[str]]:
    """Bản sao snapshot với các tín hiệu đã cho được đưa về trạng thái khỏe.

    Trả về (snapshot mới, ghi chú từng chỗ đã sửa) — ghi chú đi vào file kết quả để
    người đọc thấy chính xác dữ liệu nào đã bị đổi.
    """
    snap = copy.deepcopy(snapshot)
    notes: list[str] = []
    for sig in signals:
        if sig.kind == "error_edge":
            s, d = sig.services
            _drop_finding(snap, "error_edges", s, d)
            e = _edge(snap, s, d)
            if e is not None:
                e["errors"], e["error_rate"] = 0, 0.0
            notes.append(f"{s} -> {d}: loi ve 0%")
        elif sig.kind == "slow_edge":
            s, d = sig.services
            _drop_finding(snap, "slow_edges", s, d)
            base = table.get(f"{s}->{d}", ["base_avg_ms"])
            avg = base[0].value if base else HEALTHY_FALLBACK["edge_avg_ms"]
            e = _edge(snap, s, d)
            if e is not None:
                calls = max(int(e.get("calls") or 1), 1)
                e["avg_ms"] = round(avg, 2)
                e["max_ms"] = round(min(float(e.get("max_ms") or avg), avg * 3), 2)
                e["total_us"] = int(avg * 1000 * calls)
                e["max_us"] = int(e["max_ms"] * 1000)
            src = "anh nen trong prompt" if base else "HEALTHY_FALLBACK"
            notes.append(f"{s} -> {d}: trung binh ve {avg:g}ms ({src})")
        elif sig.kind == "missing_edge":
            s, d = sig.services
            _drop_finding(snap, "missing_edges", s, d)
            notes.append(f"{s} -> {d}: bo khoi MISSING calls")
        elif sig.kind == "gone":
            (svc,) = sig.services
            snap.setdefault("pods", []).append({
                "name": f"{svc}-0000000000-cf000", "deployment": svc,
                "phase": "Running", "ready": True, "restarts": 0, "reason": "",
                "last_restart_age_s": None, "age_s": HEALTHY_FALLBACK["pod_age_s"],
            })
            notes.append(f"{svc}: them mot pod dang chay")
        elif sig.kind == "recreated":
            (svc,) = sig.services
            for p in snap.get("pods", []):
                if p.get("deployment") == svc:
                    p["age_s"] = HEALTHY_FALLBACK["pod_age_s"]
                    p["last_restart_age_s"] = None
            notes.append(f"{svc}: pod khong con 'vua tao lai'")
        elif sig.kind == "cpu_limit":
            (svc,) = sig.services
            for pod, v in (snap.get("cpu") or {}).items():
                if pod.rsplit("-", 2)[0] == svc and v.get("limit_cores"):
                    r = HEALTHY_FALLBACK["cpu_ratio"]
                    v["used_cores"] = round(v["limit_cores"] * r, 4)
                    v["ratio"] = r
            notes.append(f"{svc}: CPU ve {HEALTHY_FALLBACK['cpu_ratio'] * 100:.0f}% tran")
    return snap, notes


def feedback_suffix(snapshot: dict, prompt_text: str | None) -> str:
    """Phần phản hồi của vòng trước trong prompt, để gắn lại y nguyên sau khi sửa."""
    if not prompt_text:
        return ""
    base = rebuild_prompt_text(snapshot)
    return prompt_text[len(base):] if prompt_text.startswith(base) else ""


def _outcome(exp) -> dict:
    top = exp.top_action() if exp else None
    return {
        "root": (exp.root_cause_service.strip().lower() if exp else None),
        "fault": exp.fault_type if exp else None,
        "action": (top.action if top else "no_action") if exp else None,
        "target": (top.target.strip().lower() if top else "") if exp else None,
    }


@dataclass
class VariantResult:
    name: str                       # repeat | drop_cited | drop_uncited | drop:<key>
    signals: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    def rates(self, ref: dict) -> dict:
        ok = [c for c in self.calls if c.get("root") is not None]
        n = len(ok)

        def rate(key):
            return round(sum(c[key] != ref[key] for c in ok) / n, 4) if n else None

        return {"n": n, "failed": len(self.calls) - n,
                "flip_root": rate("root"), "flip_fault": rate("fault"),
                "flip_action": rate("action")}

    def to_dict(self, ref: dict) -> dict:
        d = asdict(self)
        d.update(self.rates(ref))
        return d


def plan_case(snapshot: dict, explanation: dict, prompt_text: str | None = None,
              per_signal: bool = False) -> dict:
    """Chia tín hiệu thành nhóm trích / không trích và dựng sẵn mọi biến thể.

    Không gọi LLM. `scripts/xai_audit.py counterfactual --dry-run` in đúng kết quả
    hàm này để người chạy xem trước sẽ sửa những gì.
    """
    table = build_fact_table(snapshot, prompt_text)
    g = check_explanation(explanation, table)
    comp = g.completeness or {}
    cited_keys = set(comp.get("cited", []))
    mentioned = set(comp.get("mentioned", []))
    cited = [s for s in table.signals if s.key in cited_keys]
    uncited = [s for s in table.signals if s.key not in mentioned]
    suffix = feedback_suffix(snapshot, prompt_text)

    variants: list[tuple[str, list[Signal]]] = [("repeat", [])]
    if cited:
        variants.append(("drop_cited", cited))
    if uncited:
        variants.append(("drop_uncited", uncited))
    if per_signal and len(cited) > 1:
        variants += [(f"drop:{s.key}", [s]) for s in cited]

    built = []
    for name, sigs in variants:
        snap, notes = neutralize(snapshot, sigs, table)
        built.append({"name": name, "signals": [s.key for s in sigs], "notes": notes,
                      "prompt": rebuild_prompt_text(snap) + suffix})
    return {
        "signals": [s.key for s in table.signals],
        "cited": [s.key for s in cited],
        "uncited": [s.key for s in uncited],
        "mentioned_only_in_reasoning": sorted(mentioned - cited_keys),
        "variants": built,
    }


def run_case(reasoner, snapshot: dict, explanation: dict,
             prompt_text: str | None = None, repeats: int = 3,
             per_signal: bool = False, log=print) -> dict:
    """Chạy mọi biến thể của một ca, mỗi biến thể `repeats` lần.

    `reasoner` phải tắt cache (`use_cache=False`): cache trả lại y nguyên kết quả cũ,
    và nhóm `repeat` khi đó luôn ra 0% — mức nhiễu nền giả.
    """
    if getattr(reasoner, "use_cache", False):
        raise ValueError("phep thu phan thuc can reasoner tat cache (use_cache=False)")
    plan = plan_case(snapshot, explanation, prompt_text, per_signal)
    ref = {
        "root": (explanation.get("root_cause_service") or "").strip().lower(),
        "fault": explanation.get("fault_type"),
        "action": ((explanation.get("proposed_actions") or [{}])[0].get("action")
                   or "no_action"),
    }
    results: list[VariantResult] = []
    for v in plan["variants"]:
        vr = VariantResult(v["name"], v["signals"], v["notes"])
        for i in range(repeats):
            started = time.time()
            res = reasoner.diagnose(v["prompt"])
            row = _outcome(res.explanation)
            row.update(attempt=i + 1, ok=res.ok, took_s=round(time.time() - started, 2),
                       input_tokens=res.input_tokens, output_tokens=res.output_tokens)
            if res.ok:
                row["evidence"] = res.explanation.evidence
            else:
                row["error"] = (res.errors[-1] if res.errors else "")[:200]
            vr.calls.append(row)
            log(f"    {v['name']:<14} lan {i + 1}: {row['root']} / {row['fault']} / "
                f"{row['action']}")
        results.append(vr)

    by = {r.name: r.rates(ref) for r in results}
    flip = {k: v.get("flip_root") for k, v in by.items()}
    base = flip.get("repeat")

    def minus(a, b):
        return round(a - b, 4) if a is not None and b is not None else None

    return {
        "reference": ref,
        "plan": {k: plan[k] for k in ("signals", "cited", "uncited",
                                      "mentioned_only_in_reasoning")},
        "variants": [r.to_dict(ref) for r in results],
        "necessity": minus(flip.get("drop_cited"), base),
        "sufficiency_violation": minus(flip.get("drop_uncited"), base),
        "faithfulness_gap": minus(flip.get("drop_cited"), flip.get("drop_uncited")),
        "noise_floor": base,
    }


def summarize(cases: list[dict]) -> dict:
    """Gộp nhiều ca. Tỉ lệ tính trên TỔNG số lần gọi, không lấy trung bình của tỉ lệ:
    ca có ít lần gọi thành công không được nặng ngang ca đủ lần."""
    agg: dict[str, list[int]] = {}
    for c in cases:
        ref = c["reference"]
        for v in c["variants"]:
            name = "drop_one" if v["name"].startswith("drop:") else v["name"]
            n, flips = agg.setdefault(name, [0, 0])
            ok = [x for x in v["calls"] if x.get("root") is not None]
            agg[name][0] += len(ok)
            agg[name][1] += sum(x["root"] != ref["root"] for x in ok)
    rates = {k: (round(f / n, 4) if n else None) for k, (n, f) in agg.items()}

    def minus(a, b):
        return round(a - b, 4) if a is not None and b is not None else None

    return {
        "cases": len(cases),
        "calls": {k: n for k, (n, _) in agg.items()},
        "flip_root": rates,
        "necessity": minus(rates.get("drop_cited"), rates.get("repeat")),
        "sufficiency_violation": minus(rates.get("drop_uncited"), rates.get("repeat")),
        "faithfulness_gap": minus(rates.get("drop_cited"), rates.get("drop_uncited")),
        "cases_without_cited_signal": sum(1 for c in cases if not c["plan"]["cited"]),
        "cases_without_uncited_signal": sum(1 for c in cases if not c["plan"]["uncited"]),
    }
