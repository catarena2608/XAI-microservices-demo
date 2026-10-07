"""Lời giải thích có khớp với chính hành động nó đề xuất không.

E1 (`grounding.py`) hỏi: con số có đúng không. File này hỏi một câu khác: KẾT LUẬN
có đi theo LẬP LUẬN không. Hai câu độc lập với nhau — một lời giải thích có thể trích
đúng mọi con số rồi vẫn đề xuất hành động mà chính nó vừa bác bỏ.

Ca làm lộ ra yêu cầu này, lần chạy S1 trên cluster k3s mới ngày 2026-10-07:

    reasoning : "CPU usage for productcatalogservice is very low (1% of limit), so
                 resource exhaustion is unlikely; the fault is application latency."
    action    : adjust_resources — "Increasing CPU limit will allow
                 productcatalogservice to process requests faster"

Mọi con số trong lời giải thích đó đều đúng (E1 chấm 2/2), độ tin cậy tự khai 0.95,
và file đáp án của F1 còn chấm `adjust_resources` là hành động ĐÚNG. Không phép đo nào
có từ trước bắt được nó. Người vận hành đọc lời giải thích đó mà tin theo thì đang tin
một lập luận tự mâu thuẫn.

CHỈ XÉT HÀNH ĐỘNG ĐẦU TIÊN, vì agent chỉ thi hành hành động đó (react_loop._select).

BẢNG HÀNH ĐỘNG HỢP VỚI LOẠI LỖI dưới đây suy ra từ ĐỊNH NGHĨA mà chính prompt đưa
cho LLM (prompt_templates.py), không từ đáp án: "latency" nghĩa là service chậm khi
XỬ LÝ — own p95 cao; "resource_exhaustion" nghĩa là request XẾP HÀNG chờ CPU. Nên
nói "latency" rồi đi nâng trần CPU là trái định nghĩa của chính nó. Đáp án F1 dễ dãi
hơn, chấp nhận cả `adjust_resources`; độ lệch đó là có chủ ý: đáp án đo ĐÚNG/SAI so
với sự thật, file này đo KHỚP/KHÔNG KHỚP với lập luận.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from src_thesis.eval.grounding import find_mentions, owner_of

# Hanh dong hop ly cho tung loai loi, theo dinh nghia trong prompt.
ACTIONS_FOR_FAULT = {
    "crash": {"scale_up", "restart_pod", "rollback"},
    "latency": {"rollback", "restart_pod", "scale_up", "reroute_traffic"},
    "resource_exhaustion": {"adjust_resources", "scale_up"},
    "dependency_failure": {"restart_pod", "rollback", "scale_up", "reroute_traffic"},
    "pod_kill": {"no_action"},
    "unknown": {"no_action"},
}

# Cau BAC BO nguyen nhan tai nguyen. Ba cai bay da gap tren 158 loi giai thich that
# cua phase 3 va lan chay k3s, phai tranh ca ba:
#
#   "No CPU data is available, so resource exhaustion cannot be ruled out"
#       -> noi CHUA KIEM DUOC, khong phai da bac bo. Nen KHONG co chu "no" dung tran,
#          va "ruled out" ma dung sau "cannot be" thi khong tinh.
#   "it is not slow processing but requests queue before CPU"
#       -> chu "not" phu dinh "slow processing"; "queue" dung sau "but" la KHANG
#          DINH thieu CPU. Nen giua tu phu dinh va tu chi tai nguyen khong duoc co
#          "but", "however", dau phay.
#   "adservice's own CPU usage is low ... so adservice is a victim" (hanh dong nham
#   frontend) -> CPU thap cua MOT SERVICE KHAC khong bac bo viec nang CPU cho dich.
#          Nen cau "CPU thap" chi tinh khi no noi ve chinh service bi tac dong.
_GAP = r"(?:(?!\bbut\b|\bhowever\b|\byet\b)[^.;,]){0,40}?"
# "not just queuing" / "not only" la "khong CHI do", khong phai bac bo.
_NEGATED_RESOURCE = re.compile(
    r"\b(?:not(?!\s+(?:just|only|merely|simply)\b)|unlikely|rather than|instead of|"
    r"rules? out|ruled out|no sign of|"
    r"no evidence of|no indication of|isn'?t|aren'?t)\b" + _GAP
    + r"\b(?:resource|cpu|throttl|starv|queu)", re.I)
_RESOURCE_UNLIKELY = re.compile(
    r"\b(?:resource exhaustion|resource starvation|cpu (?:throttling|starvation|"
    r"pressure|saturation))\b[^.;,]{0,30}\b(?:is |seems |appears )?(?:unlikely|"
    r"ruled out|not the (?:cause|bottleneck|issue|problem))", re.I)
_CPU_LOW = [
    re.compile(r"\bcpu\b[^.;,]{0,30}\b(?:is |are )?(?:very |extremely )?low\b", re.I),
    re.compile(r"\bcpu\b[^.;,]{0,30}\bnot (?:near|close to|at) (?:its |the )?limit", re.I),
]
_NOT_RULED = re.compile(r"(?:cannot|can'?t|could not|couldn'?t|not) be\s+$", re.I)


# Hanh dong chi co nghia khi nguyen nhan LA thieu tai nguyen.
RESOURCE_ACTIONS = {"adjust_resources"}


@dataclass
class Violation:
    code: str
    severity: str      # "major" lam lap luan mau thuan; "minor" sai quy uoc dau ra
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConsistencyReport:
    consistent: bool
    violations: list[dict] = field(default_factory=list)
    action: str = ""
    target: str = ""
    root: str = ""
    fault_type: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _service_names() -> set[str]:
    from src_thesis.graph.logical_graph import load_logical_topology
    return set(load_logical_topology().graph.nodes)


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def rules_out_resources(texts: list[str], target: str = "",
                        services: set[str] | None = None) -> str | None:
    """Câu đầu tiên bác bỏ nguyên nhân thiếu tài nguyên của `target`, hoặc None."""
    names = services or set()
    for t in texts:
        mentions = find_mentions(t, names)
        for rx in (_NEGATED_RESOURCE, _RESOURCE_UNLIKELY, *_CPU_LOW):
            for m in rx.finditer(t):
                if "ruled out" in m.group(0).lower() and _NOT_RULED.search(
                        t[:m.start() + m.group(0).lower().index("ruled out")]):
                    continue
                # Bac bo cua AI? "adservice itself is not slow and has low CPU" noi
                # ve adservice, khong bac bo viec nang CPU cho frontend. Dung cung
                # cach xac dinh chu the voi E1; cau khong chu the ("the fault is
                # latency, not resource exhaustion") la noi ve ca chan doan.
                who = owner_of(t, m.start(), mentions, sentence_wide=False)
                if who in (None, target):
                    return t
    return None


def check_consistency(explanation: dict) -> ConsistencyReport:
    root = _norm(explanation.get("root_cause_service"))
    fault = _norm(explanation.get("fault_type"))
    actions = explanation.get("proposed_actions") or []
    top = actions[0] if actions else {}
    action = _norm(top.get("action")) or "no_action"
    target = _norm(top.get("target"))
    healthy = root in ("", "none")

    out: list[Violation] = []

    if healthy and action != "no_action":
        out.append(Violation("action_on_healthy", "major",
                             f"noi he thong khoe ma van de xuat {action}"))
    if not healthy and action == "no_action" and fault not in ("pod_kill", "unknown"):
        out.append(Violation("fault_but_no_action", "major",
                             f"chan doan {root} bi {fault} nhung khong lam gi"))
    if action != "no_action" and not healthy and target and target != root:
        out.append(Violation("target_not_root", "major",
                             f"nguyen nhan goc la {root} nhung hanh dong nham vao {target}"))
    allowed = ACTIONS_FOR_FAULT.get(fault)
    if (allowed is not None and action not in allowed and not healthy
            and action != "no_action"):   # no_action da co luat rieng o tren
        out.append(Violation("action_type_mismatch", "major",
                             f"{action} khong chua loai loi '{fault}' "
                             f"(hop ly: {', '.join(sorted(allowed))})"))
    if action in RESOURCE_ACTIONS:
        texts = (list(explanation.get("reasoning_chain") or [])
                 + list(explanation.get("evidence") or []))
        said = rules_out_resources(texts, target, _service_names())
        if said:
            out.append(Violation("text_rules_out_action", "major",
                                 f"de xuat {action} trong khi chinh loi giai thich "
                                 f"viet: \"{said[:160]}\""))
    if root and root in {_norm(s) for s in explanation.get("propagation_path") or []}:
        out.append(Violation("root_in_propagation", "minor",
                             "propagation_path co ca nguyen nhan goc"))

    return ConsistencyReport(
        consistent=not any(v.severity == "major" for v in out),
        violations=[v.to_dict() for v in out],
        action=action, target=target, root=root, fault_type=fault,
    )
