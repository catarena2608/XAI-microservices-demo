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

"VŨ TRỤ" TÍN HIỆU là các dấu hiệu bất thường mà prompt đã đánh dấu (`table.signals`)
CỘNG số liệu riêng của service vượt ngưỡng (`table.red_signals`: p95 trên 500ms, lỗi
trên 5%). Cả hai định nghĩa từ snapshot chứ không từ lời giải thích, nên hai nhóm là
một phép chia của cùng một tập. Tín hiệu chỉ được nhắc trong `reasoning_chain` mà
không có trong `evidence` thì KHÔNG vào nhóm nào: nó vừa không "được trích", vừa
không "bị giấu".

Bản đầu (2026-10-07) chỉ có `table.signals`. Chạy thử trên dữ liệu thật thì thấy LLM
trích nhiều nhất là số RED ("productcatalogservice p95 9750.0ms", "frontend 76.7%
errors"), và `drop_cited` để nguyên chúng trong prompt — necessity bị đo thấp hơn
thật. Vì vậy mới thêm `red_signals`.

ĐƯA VỀ TRẠNG THÁI KHỎE dùng chính con số lúc khỏe mà prompt in ra ("luc khoe manh
1.21ms"). Số RED thì prompt không có số lúc khỏe, nên lấy từ một snapshot KHỎE tham
chiếu (`healthy_red`, chụp trên cùng cluster). Chỗ nào vẫn không có thì dùng số cố
định ghi trong `HEALTHY_FALLBACK`. Mỗi chỗ sửa ghi rõ số lấy từ đâu.

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
from src_thesis.eval.replay import align_edge_order, rebuild_prompt_text

# Gia tri "khoe" khi prompt khong co so luc khoe de chep lai. Ghi vao bao cao.
HEALTHY_FALLBACK = {
    "edge_avg_ms": 5.0,      # canh cham theo nguong tuyet doi, khong co anh nen
    "cpu_ratio": 0.1,        # 10% tran CPU
    "pod_age_s": 86400.0,    # pod da chay mot ngay, khong "vua tao lai"
    # Chi dung khi anh khoe tham chieu khong co service do. 50ms ~ p95 cua frontend
    # luc khoe tren k3s (smoke 2026-10-06), duoi xa nguong 500ms.
    "service_p95_ms": 50.0,
    "service_error_rate": 0.0,
}


def _valid(x) -> bool:
    return isinstance(x, (int, float)) and x == x


def _edge(snapshot: dict, s: str, d: str) -> dict | None:
    for e in (snapshot.get("runtime_graph") or {}).get("edges", []):
        if e.get("source") == s and e.get("target") == d:
            return e
    return None


def _drop_finding(snapshot: dict, kind: str, s: str, d: str) -> None:
    diff = snapshot.setdefault("diff", {})
    diff[kind] = [f for f in diff.get(kind, [])
                  if not (f.get("source") == s and f.get("target") == d)]


def neutralize(snapshot: dict, signals: list[Signal], table: FactTable,
               healthy_red: dict | None = None) -> tuple[dict, list[str]]:
    """Bản sao snapshot với các tín hiệu đã cho được đưa về trạng thái khỏe.

    `healthy_red` là mục `red` của một snapshot khỏe, để lấy p95 / tỉ lệ lỗi lúc
    khỏe của từng service. Trả về (snapshot mới, ghi chú từng chỗ đã sửa) — ghi chú đi
    vào file kết quả để người đọc thấy chính xác dữ liệu nào đã bị đổi.
    """
    snap = copy.deepcopy(snapshot)
    notes: list[str] = []
    healthy_red = healthy_red or {}
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
        elif sig.kind == "high_p95":
            (svc,) = sig.services
            r = (snap.get("red") or {}).get(svc)
            ref = healthy_red.get(svc) or {}
            ok = _valid(ref.get("p95_ms"))
            p95 = float(ref["p95_ms"]) if ok else HEALTHY_FALLBACK["service_p95_ms"]
            if r is not None:
                r["p95_ms"] = p95
                # p50 khong in ra prompt, nhung giu p50 <= p95 cho snapshot khong vo ly.
                p50 = ref.get("p50_ms")
                r["p50_ms"] = p50 if _valid(p50) and p50 <= p95 else p95
            src = "anh khoe tham chieu" if ok else "HEALTHY_FALLBACK"
            notes.append(f"{svc}: p95 ve {p95:g}ms ({src})")
        elif sig.kind == "high_error_rate":
            (svc,) = sig.services
            r = (snap.get("red") or {}).get(svc)
            ref = healthy_red.get(svc) or {}
            ok = _valid(ref.get("error_rate"))
            rate = float(ref["error_rate"]) if ok else HEALTHY_FALLBACK["service_error_rate"]
            if r is not None:
                r["error_rate"] = rate
            src = "anh khoe tham chieu" if ok else "HEALTHY_FALLBACK"
            notes.append(f"{svc}: loi service ve {rate * 100:.1f}% ({src})")
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
              per_signal: bool = False, healthy_red: dict | None = None) -> dict:
    """Chia tín hiệu thành nhóm trích / không trích và dựng sẵn mọi biến thể.

    Không gọi LLM. `scripts/xai_audit.py counterfactual --dry-run` in đúng kết quả
    hàm này để người chạy xem trước sẽ sửa những gì.

    `replay_exact` trong kết quả cho biết prompt dựng lại từ snapshot có giống TỪNG KÝ
    TỰ với prompt đã gửi không. Không giống thì các biến thể khác prompt gốc thêm một
    chỗ ngoài phần đã sửa — phải báo.
    """
    # Snapshot luu canh theo ten. Xep lai dung thu tu da in trong prompt goc, neu
    # khong cac canh bang so lan goi bi dao dong (xem replay.align_edge_order).
    snapshot = align_edge_order(snapshot, prompt_text)
    table = build_fact_table(snapshot, prompt_text)
    g = check_explanation(explanation, table)
    comp = g.completeness or {}
    cited_keys = set(comp.get("cited", [])) | set(comp.get("red_cited", []))
    mentioned = set(comp.get("mentioned", [])) | set(comp.get("red_mentioned", []))
    universe = table.signals + table.red_signals
    cited = [s for s in universe if s.key in cited_keys]
    uncited = [s for s in universe if s.key not in mentioned]
    suffix = feedback_suffix(snapshot, prompt_text)
    exact = (rebuild_prompt_text(snapshot) + suffix == prompt_text) if prompt_text else None

    variants: list[tuple[str, list[Signal]]] = [("repeat", [])]
    if cited:
        variants.append(("drop_cited", cited))
    if uncited:
        variants.append(("drop_uncited", uncited))
    if per_signal and len(cited) > 1:
        variants += [(f"drop:{s.key}", [s]) for s in cited]

    built = []
    for name, sigs in variants:
        if name == "repeat" and prompt_text:
            # "Goi lai y nguyen" la gui DUNG chuoi da gui, khong phai chuoi dung lai.
            built.append({"name": name, "signals": [], "notes": [],
                          "prompt": prompt_text})
            continue
        snap, notes = neutralize(snapshot, sigs, table, healthy_red)
        built.append({"name": name, "signals": [s.key for s in sigs], "notes": notes,
                      "prompt": rebuild_prompt_text(snap) + suffix})
    return {
        "replay_exact": exact,
        "signals": [s.key for s in universe],
        "cited": [s.key for s in cited],
        "uncited": [s.key for s in uncited],
        "mentioned_only_in_reasoning": sorted(mentioned - cited_keys),
        "variants": built,
    }


def run_case(reasoner, snapshot: dict, explanation: dict,
             prompt_text: str | None = None, repeats: int = 3,
             per_signal: bool = False, healthy_red: dict | None = None,
             log=print) -> dict:
    """Chạy mọi biến thể của một ca, mỗi biến thể `repeats` lần.

    `reasoner` phải tắt cache (`use_cache=False`): cache trả lại y nguyên kết quả cũ,
    và nhóm `repeat` khi đó luôn ra 0% — mức nhiễu nền giả.
    """
    if getattr(reasoner, "use_cache", False):
        raise ValueError("phep thu phan thuc can reasoner tat cache (use_cache=False)")
    plan = plan_case(snapshot, explanation, prompt_text, per_signal, healthy_red)
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
            try:
                res = reasoner.diagnose(v["prompt"])
            except Exception as e:     # mot lan goi hong khong duoc lam mat ca loat
                row = _outcome(None)
                row.update(attempt=i + 1, ok=False, error=f"{type(e).__name__}: {e}"[:200],
                           took_s=round(time.time() - started, 2))
                vr.calls.append(row)
                log(f"    {v['name']:<14} lan {i + 1}: LOI {row['error']}")
                continue
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
        "plan": {k: plan[k] for k in ("replay_exact", "signals", "cited", "uncited",
                                      "mentioned_only_in_reasoning")},
        "variants": [r.to_dict(ref) for r in results],
        "necessity": minus(flip.get("drop_cited"), base),
        "sufficiency_violation": minus(flip.get("drop_uncited"), base),
        "faithfulness_gap": minus(flip.get("drop_cited"), flip.get("drop_uncited")),
        "noise_floor": base,
    }


def summarize(cases: list[dict]) -> dict:
    """Gộp nhiều ca. Tỉ lệ tính trên TỔNG số lần gọi, không lấy trung bình của tỉ lệ:
    ca có ít lần gọi thành công không được nặng ngang ca đủ lần.

    Chỉ số CHÍNH tính trên root cause. Chỉ số PHỤ `diagnosis` tính "root HOẶC loại lỗi
    đổi": bỏ bằng chứng CPU mà LLM giữ root nhưng đổi `resource_exhaustion` thành
    `latency` cũng là bằng chứng đó có gánh chẩn đoán. Cả hai được chốt TRƯỚC lần chạy
    thật đầu tiên (2026-10-07), không chọn sau khi thấy số.
    """
    agg: dict[str, list[int]] = {}
    for c in cases:
        ref = c["reference"]
        for v in c["variants"]:
            name = "drop_one" if v["name"].startswith("drop:") else v["name"]
            row = agg.setdefault(name, [0, 0, 0])
            ok = [x for x in v["calls"] if x.get("root") is not None]
            row[0] += len(ok)
            row[1] += sum(x["root"] != ref["root"] for x in ok)
            row[2] += sum(x["root"] != ref["root"] or x["fault"] != ref["fault"] for x in ok)
    rates = {k: (round(f / n, 4) if n else None) for k, (n, f, _) in agg.items()}
    rates_dx = {k: (round(f / n, 4) if n else None) for k, (n, _, f) in agg.items()}

    def minus(a, b):
        return round(a - b, 4) if a is not None and b is not None else None

    return {
        "cases": len(cases),
        "calls": {k: n for k, (n, _, _) in agg.items()},
        "flip_root": rates,
        "necessity": minus(rates.get("drop_cited"), rates.get("repeat")),
        "sufficiency_violation": minus(rates.get("drop_uncited"), rates.get("repeat")),
        "faithfulness_gap": minus(rates.get("drop_cited"), rates.get("drop_uncited")),
        "diagnosis": {
            "flip": rates_dx,
            "necessity": minus(rates_dx.get("drop_cited"), rates_dx.get("repeat")),
            "sufficiency_violation": minus(rates_dx.get("drop_uncited"),
                                           rates_dx.get("repeat")),
            "faithfulness_gap": minus(rates_dx.get("drop_cited"),
                                      rates_dx.get("drop_uncited")),
        },
        "cases_without_cited_signal": sum(1 for c in cases if not c["plan"]["cited"]),
        "cases_without_uncited_signal": sum(1 for c in cases if not c["plan"]["uncited"]),
    }
