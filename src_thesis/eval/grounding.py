"""E1 — lời giải thích có bám đúng dữ liệu LLM đã thấy không (soundness).

Định nghĩa lấy từ Zytek, Pidò, Veeramachaneni (2024), "LLMs for XAI: Future
Directions for Explaining Explanations", arXiv:2405.06064, Bảng 2. Họ chấm mỗi lời
giải thích một điểm soundness:

    0  có ít nhất một LỖI KHÁCH QUAN, ví dụ nêu sai một con số
    1  không sai số nhưng có câu GÂY HIỂU NHẦM, ví dụ gọi 5/10 là "cao"
    2  không có lỗi nào

Và completeness: lời giải thích có nhắc tới đủ các yếu tố quan trọng không.

KHÁC HỌ Ở HAI CHỖ:

1. Họ để chính tác giả tự chấm bằng tay. Ở đây chấm TỰ ĐỘNG bằng cách đối chiếu với
   snapshot đã lưu — không ai chấm nương tay cho kết quả của mình được.
2. Họ kiểm lời kể lại một giải thích SHAP đã có. Ở đây LLM vừa chẩn đoán vừa tự giải
   thích, nên ngoài con số còn có khẳng định về TRẠNG THÁI ("không còn pod nào",
   "cạnh này mất") và điều kiện tiên quyết có kiểu. Cả ba đều kiểm được.

BỐN LOẠI KẾT QUẢ CHO MỘT CON SỐ, và chúng KHÁC NHAU về ý nghĩa:

    grounded       khớp một con số TRONG PROMPT, đúng thực thể và đúng loại
    misattributed  con số có trong prompt nhưng thuộc chỗ khác — đúng số, sai chỗ
    unsupported    không tìm thấy con số này ở đâu trong prompt
    unchecked      không đủ thông tin để kết luận (không rõ đơn vị, không rõ của
                   service nào, hoặc bảng sự kiện không có phần đó)

`unchecked` KHÔNG được gộp vào `grounded`. Gộp là nói "không kiểm được" bằng câu
"đã kiểm và đúng" — cùng lớp lỗi với "unknown" và "neutral" ở metrics.py.

ƯU TIÊN TRÁNH BÁO SAI HƠN BẮT ĐỦ. Báo một câu đúng thành "bịa số" làm hỏng cả phép
đo, nên chỗ nào mơ hồ thì xếp `unchecked`: số đếm do LLM tự đếm, câu không rõ chủ
thể, đơn vị lạ. Tỉ lệ `unchecked` được báo cáo riêng để biết phép đo phủ được bao
nhiêu.

Chỉ đọc `evidence` và `reasoning_chain`. KHÔNG đọc `rationale` của hành động: con số
ở đó thường là giá trị MUỐN ĐẶT ("nâng trần lên 500m"), không phải khẳng định về
trạng thái hiện tại.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from src_thesis.eval.facts import (
    CPU_ALERT_RATIO,
    EDGE_KINDS,
    GLOBAL,
    GLOBAL_KINDS,
    HIGH_ERROR_PCT,
    HIGH_LATENCY_MS,
    SERVICE_KINDS,
    Fact,
    FactTable,
    edge_key,
)
from src_thesis.graph.diff import SLOW_MIN_DELTA_MS
from src_thesis.k8s_client import cpu_to_millicores

# ======================================================================
# TIM THUC THE TRONG CAU
# ======================================================================

ARROW = r"\s*(?:->|→|-->|=>|—>)\s*"


@dataclass
class Mention:
    start: int
    end: int
    entity: str          # ten service hoac "a->b"
    is_edge: bool


def find_mentions(text: str, services: set[str]) -> list[Mention]:
    """Tìm tên cạnh và tên service trong câu. Cạnh được tìm trước.

    "frontend -> productcatalogservice" là MỘT thực thể (cạnh), không phải hai service.
    Tên dài khớp trước, để "productcatalogservice" không bị cắt thành tên ngắn hơn.
    """
    names = sorted(services, key=len, reverse=True)
    alt = "|".join(re.escape(n) for n in names)
    out: list[Mention] = []
    taken: list[tuple[int, int]] = []
    for m in re.finditer(rf"(?<![\w-])({alt}){ARROW}({alt})(?![\w-])", text, re.I):
        out.append(Mention(m.start(), m.end(),
                           edge_key(m.group(1).lower(), m.group(2).lower()), True))
        taken.append((m.start(), m.end()))
    for m in re.finditer(rf"(?<![\w-])({alt})(?:'s)?(?![\w-])", text, re.I):
        if any(a <= m.start() < b for a, b in taken):
            continue
        out.append(Mention(m.start(), m.end(), m.group(1).lower(), False))
    return sorted(out, key=lambda x: x.start)


# Ranh gioi menh de: chu the cua mot con so khong vuot qua cac tu nay.
_CLAUSE = re.compile(r"[.;]\s|,\s|\s(?:but|while|whereas|so|because|since|although|"
                     r"however|which|indicating|confirming|meaning)\s", re.I)


def _clause_bounds(text: str, pos: int) -> tuple[int, int]:
    start, end = 0, len(text)
    for m in _CLAUSE.finditer(text):
        if m.end() <= pos:
            start = m.end()
        elif m.start() >= pos:
            end = m.start()
            break
    return start, end


def owner_of(text: str, pos: int, mentions: list[Mention],
             sentence_wide: bool = True) -> str | None:
    """Thực thể mà một con số hay một từ khóa ở vị trí `pos` nói về.

    Lấy thực thể gần nhất đứng TRƯỚC trong cùng câu ("frontend -> X: avg 157ms").
    Không có thì lấy thực thể đầu tiên đứng SAU trong cùng mệnh đề ("p95 of 9750ms
    for X"). Vẫn không có thì trả về None — câu không nêu chủ thể.
    """
    before = [m for m in mentions if m.end <= pos]
    if before and sentence_wide:
        return before[-1].entity
    c0, c1 = _clause_bounds(text, pos)
    if before and before[-1].end > c0:
        return before[-1].entity
    after = [m for m in mentions if pos <= m.start < c1]
    return after[0].entity if after else None


# ======================================================================
# TACH CON SO
# ======================================================================

@dataclass
class NumberClaim:
    """Một con số trong lời giải thích, kèm phán quyết."""

    text: str              # doan chu chua con so, de nguoi doc doi chieu
    value: float
    decimals: int
    unit: str
    kinds: list[str]
    owner: str | None
    approx: bool = False
    pos: int = -1               # vi tri trong cau, chi dung luc tach
    status: str = "unchecked"   # grounded | misattributed | unsupported | unchecked
    matched: str = ""           # su kien khop, vi du "frontend p95_ms=9750.0 @ SERVICE METRICS"
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_APPROX = re.compile(r"(?:~|≈|about|around|approx\.?|approximately|roughly|nearly|over|"
                     r"almost|khoang)\s*$", re.I)
_PAIR = re.compile(r"(?<![\w.\-/])(\d+)\s*/\s*(\d+)(?![\w.])\s*"
                   r"(calls?|requests?|lan goi|pods?|ready|replicas?)?", re.I)
_OF_CORES = re.compile(r"(?<![\w.\-])(\d+(?:\.\d+)?)\s*(?:of|/)\s*(\d+(?:\.\d+)?)\s*"
                       r"(cores?|cpu)", re.I)
_SINGLE = re.compile(
    r"(?<![\w.\-/])(\d+(?:\.\d+)?)\s*"
    r"(ms\b|milliseconds?|seconds?\b|secs?\b|s\b|%|x\b|×|times\b|lan\b|cores?\b|m\b|"
    r"mi\b|mib\b|mb\b|req/s|rps\b|requests? per second|calls?\b|requests?\b|"
    r"pods?\b|replicas?\b)?", re.I)

_KW_HEALTHY = re.compile(r"healthy|baseline|normal(?:ly)?|previous(?:ly)?|before|usual|"
                         r"khoe manh|was\b|from\b", re.I)
_KW_ERROR = re.compile(r"error|errors|err\b|fail|loi\b", re.I)
_KW_CPU = re.compile(r"limit|cpu|throttl|tran\b|core", re.I)
_KW_THROUGHPUT = re.compile(r"throughput|volume|traffic|thong luong|of (?:the )?baseline",
                            re.I)
_KW_COUNT = re.compile(r"callers?|callees?|services?|edges?|calls? converg|"
                       r"distinct|independent", re.I)


def _decimals(raw: str) -> int:
    return len(raw.split(".")[1]) if "." in raw else 0


def _latency_kinds(before: str, owner: str | None) -> list[str]:
    b = before.lower()
    if "p95" in b or "95th" in b:
        return ["p95_ms"]
    if "p50" in b or "median" in b:
        return ["p50_ms"]          # khong co trong prompt — co y de kiem ra
    if re.search(r"\bmax", b):
        return ["max_ms"]
    if "threshold" in b or "nguong" in b:
        return ["threshold_ms"]
    if _KW_HEALTHY.search(b):
        return ["base_avg_ms"]
    if re.search(r"avg|average|mean|trung binh", b):
        return ["avg_ms"]
    if owner and "->" in owner:
        return ["avg_ms", "max_ms"]
    return ["p95_ms", "avg_ms"]


def _pct_kinds(before: str, after: str) -> list[str]:
    near = before[-30:]
    if _KW_THROUGHPUT.search(near) or _KW_THROUGHPUT.search(after):
        return ["throughput_pct"]
    if _KW_CPU.search(after[:20]) or _KW_CPU.search(near):
        return ["cpu_pct"]
    healthy = _KW_HEALTHY.search(near)
    if healthy and (_KW_ERROR.search(near) or _KW_ERROR.search(after[:15])
                    or not _KW_CPU.search(near)):
        return ["base_error_pct"]
    if _KW_ERROR.search(after[:15]) or _KW_ERROR.search(near):
        return ["error_pct"]
    return ["error_pct", "cpu_pct"]


def extract_numbers(text: str, mentions: list[Mention]) -> list[NumberClaim]:
    """Tách mọi con số có thể kiểm được trong một câu."""
    claims: list[NumberClaim] = []
    used: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return not any(x < b and a < y for x, y in used)

    # 1. "10/17 calls", "1/2 pods"
    for m in _PAIR.finditer(text):
        if not free(m.start(), m.end()):
            continue
        unit = (m.group(3) or "").lower()
        owner = owner_of(text, m.start(), mentions)
        if unit.startswith(("pod", "ready", "replica")):
            k1, k2 = ["ready"], ["replicas"]
        else:
            k1, k2 = ["errors"], ["calls"]
        snippet = text[max(0, m.start() - 25):m.end()]
        claims.append(NumberClaim(snippet, float(m.group(1)), 0, unit, k1, owner))
        claims.append(NumberClaim(snippet, float(m.group(2)), 0, unit, k2, owner))
        used.append((m.start(), m.end()))

    # 2. "0.003 of 0.200 cores"
    for m in _OF_CORES.finditer(text):
        if not free(m.start(), m.end()):
            continue
        owner = owner_of(text, m.start(), mentions)
        snippet = text[max(0, m.start() - 25):m.end()]
        claims.append(NumberClaim(snippet, float(m.group(1)), _decimals(m.group(1)),
                                  "cores", ["cpu_used", "cpu_cores"], owner))
        claims.append(NumberClaim(snippet, float(m.group(2)), _decimals(m.group(2)),
                                  "cores", ["cpu_limit"], owner))
        used.append((m.start(), m.end()))

    # 3. con so don
    prev_end = 0
    singles_start = len(claims)
    for m in _SINGLE.finditer(text):
        a, b = m.start(), m.end()
        if not free(a, b):
            prev_end = max(prev_end, b)
            continue
        raw, unit = m.group(1), (m.group(2) or "").lower().strip()
        value = float(raw)
        dec = _decimals(raw)
        # Cua so tu khoa: tu het con so truoc (hoac het ten thuc the) toi con so nay.
        last_mention_end = max([x.end for x in mentions if x.end <= a], default=0)
        before = text[max(prev_end, last_mention_end, a - 45):a]
        after = text[b:b + 25]
        prev_end = b
        owner = owner_of(text, a, mentions)
        approx = bool(_APPROX.search(text[max(0, a - 15):a]))
        snippet = text[max(0, a - 30):min(len(text), b + 12)].strip()

        kinds: list[str]
        if unit in ("ms", "millisecond", "milliseconds"):
            kinds = _latency_kinds(before, owner)
        elif unit in ("s", "sec", "secs", "second", "seconds"):
            if re.match(r"\s*ago", after, re.I):
                kinds, unit = ["age_s", "restart_age_s"], "s ago"
            else:
                # "6s" la 6000ms: doi ve ms roi kiem nhu do tre.
                value, dec, unit = value * 1000, max(0, dec - 3), "ms"
                kinds = _latency_kinds(before, owner)
        elif unit == "%":
            kinds = _pct_kinds(before, after)
        elif unit in ("x", "×", "times", "lan"):
            kinds = ["slow_ratio"]
        elif unit.startswith("core"):
            kinds = ["cpu_used", "cpu_limit", "cpu_cores"]
        elif unit == "m":
            if not (_KW_CPU.search(before) or _KW_CPU.search(after)):
                continue    # "5m" co the la cua so 5 phut, khong doan
            value, dec, unit = value / 1000, dec + 3, "cores"
            kinds = ["cpu_used", "cpu_limit", "cpu_cores"]
        elif unit in ("mi", "mib", "mb"):
            kinds = ["mem_mi"]
        elif unit in ("req/s", "rps") or unit.startswith("requests per"):
            kinds = ["req_rate"]
        elif unit.startswith(("call", "request")):
            kinds = ["calls"]
        elif unit.startswith(("pod", "replica")):
            kinds = ["replicas", "ready", "pods_total"]
        elif _KW_COUNT.search(after[:20]):
            kinds = ["count"]
        else:
            continue        # so tran khong don vi: khong biet la gi, khong kiem
        used.append((a, b))
        claims.append(NumberClaim(snippet, value, dec, unit, kinds, owner, approx))
        claims[-1].pos = a

    _assign_respectively(text, mentions, claims[singles_start:])
    return claims


def _assign_respectively(text: str, mentions: list[Mention],
                         claims: list[NumberClaim]) -> None:
    """ "A va B ... (58.8% and 26.5% respectively)": so thu i thuoc thuc the thu i.

    Khong xu ly thi ca hai so deu gan cho thuc the dung gan nhat, va so dung bi bao
    la "dung so sai cho" — dung loai bao sai ma file nay uu tien tranh.
    """
    m = re.search(r"respectively", text, re.I)
    if not m or not claims:
        return
    group = [c for c in claims if getattr(c, "pos", -1) < m.start()]
    if len(group) < 2:
        return
    first = min(c.pos for c in group)
    before = [x for x in mentions if x.end <= first]
    if len(before) < len(group):
        return
    for c, x in zip(group, before[-len(group):]):
        c.owner = x.entity


# ======================================================================
# PHAN QUYET CHO MOT CON SO
# ======================================================================

def _close(claim: NumberClaim, fact_value: float, loose: bool) -> bool:
    """Hai con số có là MỘT không, tính cả làm tròn.

    Chặt: lệch không quá nửa đơn vị của chữ số cuối mà LLM viết ra — "58.8" khớp mọi
    giá trị làm tròn thành 58.8. Lỏng (chỉ dùng khi ĐÚNG thực thể, đúng loại): thêm
    1% để nhận "6000ms" cho 6001.19ms. Lỏng chỉ an toàn khi tập ứng viên đã nhỏ; dò
    toàn bảng thì luôn chặt.
    """
    tol = 0.5 * 10 ** (-claim.decimals) + 1e-9
    if loose or claim.approx:
        tol = max(tol, 0.01 * abs(fact_value))
    return abs(claim.value - fact_value) <= tol


def _candidates(table: FactTable, owner: str | None, kinds: list[str]) -> list[Fact]:
    if owner is None:
        out = table.get(GLOBAL, [k for k in kinds if k in GLOBAL_KINDS])
        if out:
            return out
        # Cau khong neu chu the: chap nhan bat ky thuc the nao cung loai.
        return [f for f in table.shown_facts() if f.kind in kinds]
    if "->" in owner:
        src, dst = owner.split("->", 1)
        out = table.get(owner, [k for k in kinds if k in EDGE_KINDS])
        svc_kinds = [k for k in kinds if k in SERVICE_KINDS]
        # "frontend -> X ... p95 9750ms": canh khong co p95, con so thuoc dau canh.
        out += table.get(dst, svc_kinds) + table.get(src, svc_kinds)
        return out
    out = table.get(owner, [k for k in kinds if k in SERVICE_KINDS])
    edge_kinds = [k for k in kinds if k in EDGE_KINDS]
    if edge_kinds:
        for s, d in table.edges_of(owner):
            out += table.get(edge_key(s, d), edge_kinds)
    return out


def _describe(f: Fact) -> str:
    return f"{f.entity} {f.kind}={f.value:g} @ {f.where}"


def judge_number(claim: NumberClaim, table: FactTable) -> NumberClaim:
    # Bang rut gon chi co RED cua service. Moi thu khac: khong kiem duoc.
    if not table.complete:
        partial_kinds = {"req_rate", "error_pct", "p95_ms"}
        if (claim.owner and "->" in claim.owner) or not set(claim.kinds) & partial_kinds:
            claim.status, claim.note = "unchecked", "nhat ky khong co snapshot day du"
            return claim
        claim.kinds = [k for k in claim.kinds if k in partial_kinds]

    for f in _candidates(table, claim.owner, claim.kinds):
        if _close(claim, f.value, loose=True):
            claim.status, claim.matched = "grounded", _describe(f)
            return claim

    for f in table.get(GLOBAL, ["feedback"]):
        if _close(claim, f.value, loose=False):
            claim.status, claim.matched = "grounded", _describe(f)
            return claim

    if claim.value == 0 and claim.owner and not _candidates(table, claim.owner,
                                                            claim.kinds):
        # "currencyservice 0.00 req/s" khi prompt khong co dong nao cua no: LLM suy
        # ra so 0 tu cho VANG du lieu. Suy luan do co the dung, nhung khong phai
        # con so trich tu prompt — khong kiem duoc, khong phai bia.
        claim.status, claim.note = "unchecked", "so 0 suy ra tu cho khong co du lieu"
        return claim

    if not table.complete and claim.kinds != ["p95_ms"]:
        # Bang rut gon chi XAC NHAN duoc, khong BAC duoc: "frontend 100% loi khi goi
        # checkoutservice" la so cua CANH, ma bang nay khong co canh. Rieng p95 thi
        # bac duoc, vi canh khong co p95 — p95 chi co the la cua service.
        claim.status, claim.note = "unchecked", "nhat ky khong co snapshot day du"
        return claim

    if claim.kinds == ["count"]:
        # So dem do LLM tu dem tren mot tap con ("3 callers") — khong du co so de
        # noi la sai. Xep unchecked thay vi bao bia so.
        claim.status, claim.note = "unchecked", "so dem, khong ro dem tren tap nao"
        return claim

    elsewhere = [f for f in table.shown_facts() if _close(claim, f.value, loose=False)
                 and f.kind not in ("feedback",)]
    if elsewhere:
        claim.status = "misattributed"
        claim.matched = "; ".join(_describe(f) for f in elsewhere[:3])
        claim.note = "con so co trong prompt nhung thuoc cho khac"
        return claim

    claim.status = "unsupported"
    claim.note = "khong tim thay con so nay trong prompt"
    return claim


# ======================================================================
# KHANG DINH DANG CHU
# ======================================================================

@dataclass
class TextClaim:
    """Một khẳng định không có số: "NO PODS", "missing", "at CPU limit"..."""

    text: str
    rule: str
    owner: str | None
    status: str = "unchecked"      # ok | misleading | contradicted | unchecked
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_NEG = re.compile(r"\b(?:not|no|without|never|unlikely|rather than|isn'?t|aren'?t|"
                  r"wasn'?t|doesn'?t|rule[sd]? out)\b[^.;,]{0,25}$", re.I)

# (ten luat, bieu thuc). Thu tu co nghia: luat dau tien khop mot doan thi giu doan do.
_TEXT_RULES = [
    ("no_pods", re.compile(r"no pods(?: at all)?|zero pods|0 pods|scaled (?:down )?to "
                           r"(?:0|zero)|(?:0|zero) replicas|no running pods|"
                           r"deployment (?:is )?gone", re.I)),
    ("no_cpu_data", re.compile(r"no cpu(?: usage)? data|cpu data (?:is )?(?:not "
                               r"available|unavailable|missing)", re.I)),
    ("recreated", re.compile(r"re-?created|restarted|new pod", re.I)),
    ("missing", re.compile(r"\bmissing\b|not seen|absent|disappear|vanish", re.I)),
    ("cpu_high", re.compile(r"at (?:its |the )?(?:cpu )?limit|throttl|saturat|"
                            r"cpu[- ]bound|maxed|starv|near (?:its |the )?(?:cpu )?limit|"
                            r"high cpu|cpu (?:usage )?(?:is )?(?:very )?high", re.I)),
    ("cpu_low", re.compile(r"(?:cpu|resource)[^.;,]{0,30}\b(?:low|normal|well below|"
                           r"far below|not near|under (?:its |the )?limit)", re.I)),
    ("no_errors", re.compile(r"\bno errors?\b|error[- ]free|without errors?", re.I)),
    ("latency_high", re.compile(r"\bslow\b|slowness|high latency|latency (?:is )?"
                                r"(?:very )?high|elevated|\bspike", re.I)),
    ("latency_low", re.compile(r"(?:latency|p95)[^.;,]{0,25}\b(?:low|normal|healthy|"
                               r"fast)\b", re.I)),
]

_GLOBAL_SCOPE = re.compile(r"any (?:edge|service)|all (?:edges|services)|anywhere|"
                           r"for any service|on any", re.I)


def extract_text_claims(text: str, mentions: list[Mention]) -> list[TextClaim]:
    out: list[TextClaim] = []
    taken: list[tuple[int, int]] = []
    for rule, rx in _TEXT_RULES:
        for m in rx.finditer(text):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            negated = bool(_NEG.search(text[max(0, m.start() - 30):m.start()]))
            r = rule
            if negated:
                # "not throttled" la khang dinh CPU thap; "not slow" la do tre thap.
                r = {"cpu_high": "cpu_low", "latency_high": "latency_low"}.get(rule)
                if r is None:
                    continue   # "no restarts", "not missing": khong kiem
            c0, c1 = _clause_bounds(text, m.start())
            scope = text[c0:c1]
            owner = (GLOBAL if _GLOBAL_SCOPE.search(scope)
                     else owner_of(text, m.start(), mentions, sentence_wide=False))
            if owner is None and r in ("no_cpu_data", "cpu_low", "cpu_high", "no_errors"):
                # "No CPU data is available": cau ve ca he thong, khong ve service nao.
                owner = GLOBAL
            snippet = text[max(0, m.start() - 40):min(len(text), m.end() + 20)].strip()
            out.append(TextClaim(snippet, r, owner))
    return out


def _edge(owner: str) -> tuple[str, str]:
    s, d = owner.split("->", 1)
    return s, d


def judge_text(c: TextClaim, t: FactTable) -> TextClaim:
    o = c.owner
    if o is None:
        c.note = "khong ro chu the"
        return c
    if not t.complete and c.rule not in ("latency_high", "latency_low", "no_errors"):
        c.note = "nhat ky khong co snapshot day du"
        return c

    def verdict(ok: bool, bad: str, note: str) -> TextClaim:
        c.status = "ok" if ok else bad
        c.note = "" if ok else note
        return c

    is_edge = o != GLOBAL and "->" in o
    if c.rule == "no_pods":
        if o == GLOBAL or is_edge:
            return c
        return verdict(o in t.gone, "contradicted",
                       f"{o} van con pod trong snapshot")
    if c.rule == "recreated":
        if o == GLOBAL or is_edge:
            return c
        return verdict(o in t.recreated, "contradicted",
                       f"prompt khong co pod {o} nao vua tao lai")
    if c.rule == "missing":
        if not is_edge:
            return c
        return verdict(_edge(o) in t.missing_edges, "contradicted",
                       f"canh {o} khong nam trong MISSING calls")
    if c.rule == "no_cpu_data":
        if not t.has_cpu_data:
            return verdict(True, "", "")
        if o != GLOBAL and not is_edge and o not in t.cpu_pct:
            return verdict(True, "", "")  # prompt that su khong in CPU cua service nay
        return verdict(False, "misleading", "prompt co so lieu CPU")
    if c.rule in ("cpu_high", "cpu_low"):
        # Muc CPU cua prompt LUON in moi service tu 70% tran tro len. Nen service
        # khong co dong nao la service duoi 70% — dieu do kiem duoc, khong phai
        # thieu du lieu. Rieng khi khong co so lieu CPU nao, prompt da dan "dung
        # loai tru resource_exhaustion"; khang dinh CPU cao hay thap luc do deu
        # khong co can cu.
        alert = CPU_ALERT_RATIO * 100
        if is_edge:
            return c
        if not t.has_cpu_data:
            return verdict(False, "misleading", "prompt ghi NO CPU DATA")
        if o == GLOBAL:
            hot = [s for s, p in t.cpu_pct.items() if p >= alert]
            ok = bool(hot) if c.rule == "cpu_high" else not hot
            return verdict(ok, "misleading", f"service cham tran CPU: {hot or 'khong co'}")
        pct = t.cpu_pct.get(o)
        hot = pct is not None and pct >= alert
        ok = hot if c.rule == "cpu_high" else not hot
        shown = f"{pct:.0f}%" if pct is not None else "duoi 70% (khong duoc in)"
        return verdict(ok, "misleading", f"{o} dung {shown} tran CPU")
    if c.rule == "no_errors":
        if o == GLOBAL:
            bad = sorted(t.error_edges) or [s for s, p in t.error_pct.items()
                                            if p > HIGH_ERROR_PCT]
            return verdict(not bad, "contradicted", f"prompt co loi: {bad[:3]}")
        if is_edge:
            e = t.edges.get(_edge(o))
            if e is None:
                return c
            ok = _edge(o) not in t.error_edges and (e.get("error_rate") or 0) * 100 <= HIGH_ERROR_PCT
            return verdict(ok, "misleading", f"canh {o} co loi")
        if o not in t.error_pct:
            return c
        ok = (t.error_pct[o] <= HIGH_ERROR_PCT
              and not any(d == o for _, d in t.error_edges))
        return verdict(ok, "misleading", f"{o} co {t.error_pct[o]:.1f}% loi hoac canh loi")
    if c.rule in ("latency_high", "latency_low"):
        if o == GLOBAL:
            return c
        if is_edge:
            if not t.complete:
                return c
            slow = _edge(o) in t.slow_edges
            e = t.edges.get(_edge(o))
            if c.rule == "latency_high":
                if slow:
                    return verdict(True, "", "")
                if e is not None and (e.get("avg_ms") or 0) < SLOW_MIN_DELTA_MS:
                    return verdict(False, "misleading",
                                   f"canh {o} trung binh {e.get('avg_ms')}ms, khong cham")
                return c
            return verdict(not slow, "misleading", f"canh {o} nam trong SLOW calls")
        p95 = t.p95.get(o)
        touches_slow = any(o in (s, d) for s, d in t.slow_edges)
        if c.rule == "latency_high":
            if (p95 is not None and p95 >= HIGH_LATENCY_MS) or touches_slow:
                return verdict(True, "", "")
            if p95 is not None and p95 < SLOW_MIN_DELTA_MS:
                return verdict(False, "misleading", f"{o} p95 chi {p95}ms")
            return c
        if p95 is not None and p95 >= HIGH_LATENCY_MS:
            return verdict(False, "misleading", f"{o} p95 {p95}ms")
        return verdict(True, "", "") if p95 is not None else c
    return c


# ======================================================================
# DIEU KIEN TIEN QUYET — khang dinh co kieu ve trang thai hien tai
# ======================================================================

def judge_preconditions(explanation: dict, t: FactTable) -> list[dict]:
    """Đối chiếu `preconditions` LLM khai với snapshot LÚC CHẨN ĐOÁN.

    Khác `guards.check_preconditions`, vốn kiểm trên cluster LÚC THI HÀNH. Ở đây hỏi:
    LLM có mô tả đúng trạng thái nó đang được xem không.
    """
    out: list[dict] = []
    for a in explanation.get("proposed_actions") or []:
        for p in a.get("preconditions") or []:
            kind, target, raw = p.get("kind"), p.get("target", ""), p.get("value", "")
            row = {"action": a.get("action"), "kind": kind, "target": target,
                   "value": raw, "status": "unchecked", "actual": None}
            if not t.complete:
                out.append(row)
                continue
            try:
                if kind in ("replicas_eq", "replicas_gte", "pods_ready_gte"):
                    want = int(float(raw))
                    have = (t.ready if kind == "pods_ready_gte" else t.replicas).get(target, 0)
                    ok = have == want if kind == "replicas_eq" else have >= want
                elif kind == "cpu_limit_eq":
                    want_m = cpu_to_millicores(str(raw))
                    have_c = t.cpu_limit_cores.get(target)
                    if want_m is None or have_c is None:
                        out.append(row)
                        continue
                    have = f"{have_c * 1000:g}m"
                    ok = abs(want_m - have_c * 1000) < 0.5
                else:
                    out.append(row)
                    continue
            except (TypeError, ValueError):
                out.append(row)
                continue
            row.update(status="ok" if ok else "false", actual=have)
            out.append(row)
    return out


# ======================================================================
# CHAM MOT LOI GIAI THICH
# ======================================================================

@dataclass
class GroundingReport:
    numbers: list[dict] = field(default_factory=list)
    texts: list[dict] = field(default_factory=list)
    preconditions: list[dict] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    soundness: int | None = None        # 0 / 1 / 2 theo Zytek et al.; None = khong kiem duoc gi
    grounded_rate: float | None = None  # trong so con so DA KIEM duoc
    checked_share: float | None = None  # bao nhieu khang dinh kiem duoc
    completeness: dict = field(default_factory=dict)
    root_supported: bool | None = None
    complete_table: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


_MENTION_RULES = {
    "gone": re.compile(r"no pods|scaled|replica|down|crash|gone|unavailable|dead", re.I),
    "recreated": re.compile(r"re-?creat|restart|new pod|\bage\b", re.I),
    "cpu_limit": re.compile(r"cpu|limit|throttl|core", re.I),
    "missing_edge": re.compile(r"missing|absent|not seen|disappear", re.I),
}


def signal_mentioned(sig, sentences: list[tuple[str, list[Mention]]]) -> bool:
    """Lời giải thích có nhắc tới một dấu hiệu bất thường không. Xét từng câu."""
    for text, mentions in sentences:
        ents = {m.entity for m in mentions}
        if sig.kind in ("error_edge", "slow_edge", "missing_edge"):
            s, d = sig.services
            hit = edge_key(s, d) in ents or ({s, d} <= ents)
            if hit and (sig.kind != "missing_edge"
                        or _MENTION_RULES["missing_edge"].search(text)):
                return True
        else:
            (svc,) = sig.services
            if svc in ents and _MENTION_RULES[sig.kind].search(text):
                return True
    return False


def _touches(entity: str | None, svc: str) -> bool:
    if not entity or entity == GLOBAL:
        return False
    return svc in entity.split("->") if "->" in entity else entity == svc


def check_explanation(explanation: dict, table: FactTable) -> GroundingReport:
    """Chấm E1 cho một lời giải thích. Không gọi LLM, không đụng tới cluster."""
    rep = GroundingReport(complete_table=table.complete)
    root = (explanation.get("root_cause_service") or "").strip().lower()

    parts = ([("evidence", s) for s in explanation.get("evidence") or []]
             + [("reasoning", s) for s in explanation.get("reasoning_chain") or []])
    sentences: dict[str, list] = {"evidence": [], "reasoning": []}
    supported = False

    for source, text in parts:
        mentions = find_mentions(text, table.services)
        sentences[source].append((text, mentions))
        for n in extract_numbers(text, mentions):
            judge_number(n, table)
            d = n.to_dict()
            d["source"] = source
            rep.numbers.append(d)
            if source == "evidence" and n.status == "grounded" and _touches(n.owner, root):
                supported = True
        for c in extract_text_claims(text, mentions):
            judge_text(c, table)
            d = c.to_dict()
            d["source"] = source
            rep.texts.append(d)
            if source == "evidence" and c.status == "ok" and _touches(c.owner, root):
                supported = True

    rep.preconditions = judge_preconditions(explanation, table)

    nstat = [n["status"] for n in rep.numbers]
    tstat = [c["status"] for c in rep.texts]
    pstat = [p["status"] for p in rep.preconditions]
    rep.counts = {
        "numbers": len(nstat),
        "grounded": nstat.count("grounded"),
        "misattributed": nstat.count("misattributed"),
        "unsupported": nstat.count("unsupported"),
        "numbers_unchecked": nstat.count("unchecked"),
        "texts": len(tstat),
        "text_ok": tstat.count("ok"),
        "misleading": tstat.count("misleading"),
        "contradicted": tstat.count("contradicted"),
        "texts_unchecked": tstat.count("unchecked"),
        "preconditions": len(pstat),
        "precondition_ok": pstat.count("ok"),
        "precondition_false": pstat.count("false"),
    }
    c = rep.counts
    judged_numbers = c["grounded"] + c["misattributed"] + c["unsupported"]
    judged = (judged_numbers + c["text_ok"] + c["misleading"] + c["contradicted"]
              + c["precondition_ok"] + c["precondition_false"])
    total = c["numbers"] + c["texts"] + c["preconditions"]
    rep.grounded_rate = round(c["grounded"] / judged_numbers, 4) if judged_numbers else None
    rep.checked_share = round(judged / total, 4) if total else None

    objective = (c["misattributed"] + c["unsupported"] + c["contradicted"]
                 + c["precondition_false"])
    if judged == 0:
        rep.soundness = None
    elif objective:
        rep.soundness = 0
    elif c["misleading"]:
        rep.soundness = 1
    else:
        rep.soundness = 2

    if root and root not in ("none", "unknown") and (supported or table.complete):
        # Bang rut gon thi "khong tim thay can cu" co the chi vi thieu du lieu.
        rep.root_supported = supported

    # Do day du: chi tinh khi co snapshot day du, vi bang rut gon khong co dau hieu.
    if table.complete:
        sigs = table.signals
        cited = [s.key for s in sigs if signal_mentioned(s, sentences["evidence"])]
        mentioned = [s.key for s in sigs
                     if signal_mentioned(s, sentences["evidence"] + sentences["reasoning"])]
        rc_sigs = [s.key for s in sigs if root in s.services]
        rep.completeness = {
            "signals": [s.key for s in sigs],
            "cited": cited,
            "mentioned": mentioned,
            "cited_share": round(len(cited) / len(sigs), 4) if sigs else None,
            "mentioned_share": round(len(mentioned) / len(sigs), 4) if sigs else None,
            "root_signals": rc_sigs,
            "root_cited_share": (round(len([k for k in rc_sigs if k in cited])
                                       / len(rc_sigs), 4) if rc_sigs else None),
        }
    return rep
