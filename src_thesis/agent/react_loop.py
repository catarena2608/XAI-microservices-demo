"""Vòng lặp ReAct: nối XAI, hành động và Digital Twin thành một agent tự sửa lỗi.

Đây là mục 7.4 KLTN.md, và là chỗ cả đề tài hướng tới.

    Observe  -> chụp snapshot hệ thống
    Reason   -> LLM chẩn đoán, xuất JSON đã validate
    Select   -> lấy hành động ưu tiên cao nhất
    Precheck -> kiểm điều kiện tiên quyết trên production; sai thì không thử twin,
                không thi hành, vòng sau suy luận lại kèm giá trị thật
    rẽ nhánh theo risk_class:
        easy, medium -> Apply thẳng lên production
        hard         -> VerifyOnTwin: dựng twin, thử, đo
                        better -> Apply lên production
                        khác   -> quay lại Reason kèm kết quả twin làm phản hồi
    Apply    -> đối sánh trạng thái: cấu hình production đã đổi so với lúc kiểm chứng
                thì KHÔNG thi hành; kiểm lại điều kiện tiên quyết; qua hết thì đo
                production rồi mới thi hành
    (Precheck, đối sánh trạng thái và AutoUndo chỉ chạy khi bật cơ chế kiểm soát.)
    Watch    -> chờ một cửa sổ, đo production, so với số đo ngay trước khi áp
                tệ đi, mức medium hoặc hard -> AutoUndo: hoàn tác, chờ thêm một cửa sổ
    Observe lại -> khỏi thì dừng, chưa khỏi thì vòng tiếp, tối đa 3 vòng

BA CHẾ ĐỘ, để phase 6 so sánh (mục 8 KLTN.md):

    direct        bỏ qua twin, hành động nào cũng áp thẳng, không tự hoàn tác
                  — đây là ĐỐI CHỨNG
    twin_verified hành động `hard` phải qua twin, medium và hard tệ đi thì tự hoàn
                  tác — đây là đề tài này
    xai_only      chỉ chẩn đoán, không hành động — đo riêng chất lượng XAI

Chế độ `direct` cố ý làm liều: nó tồn tại để đo xem twin ngăn được bao nhiêu hành
động có hại. Không có nó thì con số "agent-có-twin an toàn hơn" không so với cái gì.

Cả hai chế độ đều qua node Watch, tức là đều đo trước và sau mỗi hành động. Bắt
buộc phải vậy: chỉ số harmful của phase 6 chấm bằng cặp số đo này, và hai chế độ
phải được chấm bằng cùng một thước. Chúng chỉ khác nhau ở chỗ có tự hoàn tác hay không.

VÌ SAO TRẦN 3 VÒNG: không có trần thì agent gặp lỗi nó không sửa được sẽ lặp vô hạn,
mỗi vòng tốn một lượt gọi LLM và ít nhất 5 phút chờ. Hết trần thì dừng và xuất báo
cáo "không tự sửa được" kèm lời giải thích — đó cũng là một kết quả hợp lệ, không
phải thất bại của chương trình.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from src_thesis.agent.actions import (
    ActionExecutor,
    ActionResult,
    needs_twin,
    risk_of,
    undo_if_worse,
)
from src_thesis.agent.guards import (
    capture_state,
    check_preconditions,
    describe_failed,
    diff_state,
    required_preconditions,
)
from src_thesis.agent.twin_manager import TwinManager
from src_thesis.agent.verifier import TwinVerifier, Verdict
from src_thesis.graph.baseline import load_baseline_graph
from src_thesis.graph.model import ServiceGraph
from src_thesis.k8s_client import K8sClient
from src_thesis.telemetry.prometheus_client import PrometheusClient
from src_thesis.telemetry.snapshot import take_snapshot
from src_thesis.xai.reasoner import PROMPT_VERSION, XaiReasoner
from src_thesis.xai.schema import Explanation, ProposedAction

RUNS_DIR = Path(__file__).resolve().parents[2] / "data" / "agent_runs"

MAX_ROUNDS = 3

Mode = Literal["direct", "twin_verified", "xai_only"]


def _append(left: list, right: list) -> list:
    """Gộp danh sách khi LangGraph hợp nhất trạng thái giữa các node."""
    return (left or []) + (right or [])


def compact_red(red: dict) -> dict:
    """Rút bảng RED xuống ba con số mỗi service để nhét vừa nhật ký vòng.

    Giữ `request_rate` chứ không chỉ giữ lỗi và độ trễ: thiếu nó thì không phân
    biệt được "service này không xấu đi" với "service này quá ít lưu lượng để nói
    gì" — đúng cái bẫy đã làm hỏng lần đo fidelity đầu tiên ở phase 4.

    Bỏ các tên mang tiền tố `twin-` để số liệu twin không lẫn vào production khi
    twin đang chạy. Đây là lỗi im lặng nhất của phase 4: hai nguồn trộn vào nhau
    mà con số vẫn ra đẹp.
    """
    out: dict = {}
    for name, v in (red or {}).items():
        if name.startswith("twin-"):
            continue
        out[name] = {
            "request_rate": v.get("request_rate", 0.0),
            "error_rate": v.get("error_rate", 0.0),
            "p95_ms": v.get("p95_ms", 0.0),
            "source": v.get("source", ""),
        }
    return out


@dataclass
class RoundLog:
    """Nhật ký một vòng. Đây là đơn vị nhỏ nhất mà phase 6 đọc lại được."""

    round_no: int
    snapshot_label: str = ""
    snapshot_fingerprint: str = ""
    # SNAPSHOT DAY DU va DUNG NGUYEN VAN prompt da gui LLM. Day la dau vao cua danh
    # gia XAI (src_thesis/eval/grounding.py, counterfactual.py): khong co chung thi
    # khong truy nguoc duoc moi con so trong `evidence` ve trang thai he thong luc
    # chan doan, va cung khong lam duoc phep thu phan thuc.
    #
    # Luu NGAY TRONG file nay, khong chi luu duong dan: data/runs/ nam ngoai git,
    # va snapshot cua phase 3 khong theo sang may khac chinh vi ly do do.
    #
    # `prompt_text` = doan snapshot dang chu + phan hoi cua vong truoc, tuc dung
    # chuoi da dua vao `XaiReasoner.diagnose()`. Doan snapshot dung lai duoc tu
    # `snapshot` bang `replay.rebuild_prompt_text()`; phan hoi thi khong, nen phai
    # luu ca chuoi.
    snapshot: dict = field(default_factory=dict)
    prompt_text: str = ""
    diff_summary: str = ""
    healthy: bool = False
    # Thoi diem CHUP, khac `started_at` o cho no la moc de tinh MTTR (chi so 3
    # muc 8): he thong duoc coi la hoi phuc tai thoi diem quan sat thay no sach,
    # khong phai tai thoi diem vong bat dau.
    observed_at: float = 0.0
    # Bang RED goc cua vong nay. PHAI luu, vi chi so 4 (harmful action) la phep so
    # RED truoc va sau moi hanh dong: `red` cua vong N la "truoc", `red` cua vong
    # N+1 la "sau" — agent da cho du mot cua so quan sat giua hai lan.
    #
    # Khong luu thi phase 6 phai chay lai ca thi nghiem moi cham diem duoc, trai
    # nguyen tac dau `src_thesis/eval/metrics.py`: cham diem lai tu file JSON.
    red: dict = field(default_factory=dict)
    # Phan biet BA truong hop, khong duoc gop: chua chan doan (he thong khoe nen
    # khong can), chan doan THAT BAI, va chan doan XONG. Gop lai thi log ghi
    # "XAI that bai" cho mot ca ma XAI chua he chay — doc lai se hieu nham hoan toan.
    reasoning_ran: bool = False
    explanation: dict | None = None
    reasoning_ok: bool = False
    reasoning_error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    chosen_action: dict | None = None
    risk_class: str = ""
    twin_verdict: dict | None = None
    twin_used: bool = False
    action_result: dict | None = None
    promoted: bool = False
    # Do production NGAY TRUOC va MOT CUA SO SAU hanh dong (node watch). Chi so
    # harmful cua phase 6 phai cham bang cap so nay. So voi `red` cua vong sau thi
    # sai khi hanh dong da bi tu hoan tac: vong sau do trang thai SAU hoan tac, nen
    # mot hanh dong co hai se trong nhu vo hai.
    prod_before: dict = field(default_factory=dict)
    prod_after: dict = field(default_factory=dict)
    prod_verdict: dict | None = None
    prod_error: str = ""
    auto_undo: dict | None = None       # ActionResult cua lan tu hoan tac, neu co
    auto_undone: bool = False
    # Doi sanh trang thai (src_thesis/agent/guards.py). `state_seen` la cau hinh luc
    # kiem chung: luc observe, hoac luc twin chep tu production neu di nhanh twin.
    state_seen: dict = field(default_factory=dict)
    drift_checked: bool = False
    drift: list = field(default_factory=list)   # khac nhau -> KHONG thi hanh
    # Dieu kien tien quyet: ket qua kiem cua lan gan nhat, ca dieu kien do code
    # quy dinh (source="code") lan do LLM khai (source="llm").
    preconditions: list = field(default_factory=list)
    blocked_by: str = ""                        # "precondition" | "drift" | ""
    skipped_reason: str = ""
    started_at: float = field(default_factory=time.time)
    took_s: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class AgentState(TypedDict, total=False):
    """Trạng thái chảy qua graph LangGraph."""

    run_id: str
    mode: str
    namespace: str
    round_no: int
    max_rounds: int

    snapshot: dict          # snapshot hien tai, dang dict
    prompt_text: str
    explanation: dict | None
    action: dict | None
    verdict: dict | None
    blocked: bool           # bi chan o precheck vi dieu kien tien quyet
    applied: bool           # hanh dong vua roi co doi production khong
    prod_verdict: str       # production te di / tot len sau mot cua so

    feedback: str           # ket qua twin lan truoc, nhoi lai vao prompt
    healthy: bool
    stop_reason: str
    rounds: Annotated[list, _append]


class ReactAgent:
    """Agent ReAct. Tạo một lần rồi chạy nhiều ca."""

    def __init__(
        self,
        mode: Mode = "twin_verified",
        namespace: str = "default",
        max_rounds: int = MAX_ROUNDS,
        reasoner: XaiReasoner | None = None,
        twin: TwinManager | None = None,
        settle_seconds: int = 300,
        dry_run: bool = False,
        baseline: ServiceGraph | None = None,
        guards: bool | None = None,
    ):
        self.mode = mode
        self.namespace = namespace
        self.max_rounds = max_rounds
        self.k8s = K8sClient(namespace=namespace)
        self.prom = PrometheusClient()
        self.executor = ActionExecutor(k8s=self.k8s, namespace=namespace)
        self.reasoner = reasoner or XaiReasoner()
        self.twin = twin or TwinManager()
        self.twin_verifier = TwinVerifier(prom=self.prom, namespace="twin")
        # Cung lop do voi twin, chi bo tien to "twin-": do production bang dung
        # thuoc da dung de phan quyet tren twin.
        self.prod_verifier = TwinVerifier(prom=self.prom, k8s=self.k8s,
                                          namespace=namespace, prefix="")

        # CO CHE KIEM SOAT (tu hoan tac). Mac dinh chi bat o `twin_verified`.
        # `direct` la doi chung "agent lam lieu": bat co che o do thi khong con tach
        # duoc phan an toan nao den tu twin, phan nao den tu co che. Truyen True hoac
        # False de chay them cau hinh khac.
        self.guards = (mode == "twin_verified") if guards is None else guards

        # ANH NEN — BAT BUOC de phat hien duoc kich ban cham.
        #
        # Khong co nen thi `diff_graphs` chi bat canh cham hon 500ms tuyet doi, ma so
        # do that cua S1, S4, S5 deu duoi 500ms (101-284ms). Agent se nhin ba kich
        # ban do va ket luan "he thong khoe manh" roi dung ngay vong dau — hong im
        # lang, khong bao loi gi.
        #
        # Xem chu thich day du o src_thesis/graph/baseline.py.
        if baseline is not None:
            self.baseline, self.baseline_source = baseline, "do ben goi truyen vao"
        else:
            self.baseline, self.baseline_source = load_baseline_graph()
        # Sau moi hanh dong phai cho DAY mot cua so quan sat roi moi do lai. Bai hoc
        # dat nhat cua phase 2: cho ngan hon cua so thi so lieu "sau" con lan trang
        # thai "truoc", va agent se ket luan nham rang hanh dong khong co tac dung.
        self.settle_seconds = settle_seconds
        # dry_run bo qua moi thao tac doi cluster. Dung de thu graph chay dung luong
        # ma khong dung toi he thong that.
        self.dry_run = dry_run
        self._round_log: RoundLog | None = None
        self.graph = self._build_graph()

    # ------------------------------------------------------------------
    # CAC NODE
    # ------------------------------------------------------------------

    def _observe(self, state: AgentState) -> AgentState:
        """Chụp trạng thái hệ thống. Vào vòng nào cũng chụp lại từ đầu."""
        rnd = state.get("round_no", 0) + 1
        self._round_log = RoundLog(round_no=rnd)

        snap = take_snapshot(label=f"agent-{state['run_id']}-r{rnd}",
                             namespace=self.namespace,
                             baseline=self.baseline)
        d = snap.to_dict()
        self._round_log.snapshot_label = d.get("label", "")
        self._round_log.snapshot_fingerprint = d.get("fingerprint", "")
        self._round_log.snapshot = d
        self._round_log.observed_at = d.get("taken_at", time.time())
        self._round_log.red = compact_red(d.get("red", {}))

        diff = d.get("diff", {})
        n_err = len(diff.get("error_edges", []))
        n_slow = len(diff.get("slow_edges", []))
        n_miss = len(diff.get("missing_edges", []))
        self._round_log.diff_summary = (
            f"{n_err} canh loi, {n_slow} canh cham, {n_miss} canh thieu")
        healthy = n_err == 0 and n_slow == 0 and n_miss == 0
        self._round_log.healthy = healthy
        if self.guards:
            # Cau hinh ma chan doan cua vong nay dua vao. Doi sanh lai ngay truoc
            # khi thi hanh.
            self._round_log.state_seen = self._capture_state()

        return {
            "round_no": rnd,
            "snapshot": d,
            "prompt_text": snap.to_prompt_text(),
            "healthy": healthy,
        }

    def _reason(self, state: AgentState) -> AgentState:
        """Gọi LLM chẩn đoán. Output luôn validate bằng Pydantic (mục 5 KLTN.md)."""
        prompt = state["prompt_text"]
        feedback = state.get("feedback", "")
        if feedback:
            # Nhoi ket qua twin cua vong truoc vao prompt. Day chinh la phan
            # "Observe" cua ReAct: agent hoc tu hau qua hanh dong vua roi.
            prompt = (prompt + "\n\nPREVIOUS ATTEMPT IN THIS INCIDENT:\n" + feedback
                      + "\n\nPropose a different action that addresses the same "
                        "root cause, or set root_cause_service to 'none' with "
                        "action no_action if the system has recovered.")

        res = self.reasoner.diagnose(prompt)
        log = self._round_log
        log.prompt_text = prompt
        log.reasoning_ran = True
        log.reasoning_ok = res.ok
        log.input_tokens = res.input_tokens
        log.output_tokens = res.output_tokens
        if not res.ok:
            log.reasoning_error = res.errors[-1][:300] if res.errors else "khong ro"
            return {"explanation": None}

        log.explanation = res.explanation.model_dump()
        return {"explanation": log.explanation}

    def _select(self, state: AgentState) -> AgentState:
        """Lấy hành động ưu tiên cao nhất và gắn mức rủi ro."""
        exp = state.get("explanation")
        if not exp:
            return {"action": None}
        actions = exp.get("proposed_actions") or []
        if not actions:
            return {"action": None}
        top = actions[0]
        self._round_log.chosen_action = top
        self._round_log.risk_class = risk_of(top.get("action", ""))
        return {"action": top}

    def _precheck(self, state: AgentState) -> AgentState:
        """Kiểm điều kiện tiên quyết trên production TRƯỚC khi dựng twin hay thi hành.

        Đặt trước twin là chủ ý: hành động bất khả thi bị chặn trong vài giây, thay
        vì phải dựng twin, chạy, đo xong mới biết.
        """
        action = state["action"]
        failed = self._check_preconditions(action)
        if not failed:
            return {"blocked": False}
        return {"blocked": True,
                "feedback": self._precondition_feedback(action, failed)}

    def _check_preconditions(self, action: dict) -> list[str]:
        """Kiểm điều kiện do code quy định và điều kiện LLM khai. Trả về các điều kiện sai.

        Không đọc được cluster thì coi như không đạt: không kiểm được thì không được
        coi là đã thỏa.
        """
        log = self._round_log
        conds = ([{**c, "source": "code"} for c in
                  required_preconditions(action.get("action", ""),
                                         action.get("target", ""))]
                 + [{**c, "source": "llm"} for c in action.get("preconditions") or []])
        try:
            log.preconditions = check_preconditions(self.k8s, conds, self.namespace)
        except Exception as e:
            log.preconditions = []
            failed = [f"khong doc duoc cluster de kiem dieu kien: {str(e)[:150]}"]
        else:
            failed = describe_failed(log.preconditions)
        if failed:
            log.blocked_by = "precondition"
            log.skipped_reason = "dieu kien tien quyet khong dat: " + "; ".join(failed)
        return failed

    @staticmethod
    def _precondition_feedback(action: dict, failed: list[str]) -> str:
        return (f"Action {action.get('action')} on {action.get('target')} was NOT "
                f"executed: precondition failed ({'; '.join(failed)}). Read the "
                f"snapshot again and propose an action whose preconditions hold.")

    def _verify_on_twin(self, state: AgentState) -> AgentState:
        """Dựng twin, nạp trạng thái production, thử hành động, đo, rồi xóa twin.

        Twin luôn bị xóa kể cả khi có lỗi giữa chừng — mục 2 KLTN.md cấm chạy twin
        song song với thí nghiệm production, và twin còn sống là còn ăn RAM.
        """
        action = ProposedAction(**state["action"])
        log = self._round_log
        log.twin_used = True

        if self.dry_run:
            v = Verdict("better", "dry_run: gia dinh twin xac nhan")
            log.twin_verdict = v.to_dict()
            return {"verdict": v.to_dict()}

        try:
            self.twin.create_twin()
            if self.guards:
                # Chup ngay truoc khi twin chep: phan quyet cua twin noi ve DUNG trang
                # thai nay, nen day moi la moc de doi sanh luc ap len production.
                log.state_seen = self._capture_state()
            self.twin.load_state(source_namespace=self.namespace)

            twin_exec = ActionExecutor(namespace="twin")
            # Cho bo sinh tai trong twin am len du mot cua so, neu khong thi phep do
            # "truoc" con lan luc twin chua co luu luong.
            time.sleep(self.settle_seconds)
            before = self.twin_verifier.measure()

            applied = twin_exec.apply(action)
            if not applied.ok:
                v = Verdict("no_change",
                            f"khong thi hanh duoc tren twin: {applied.detail}")
                log.twin_verdict = v.to_dict()
                return {"verdict": v.to_dict()}

            time.sleep(self.settle_seconds)
            after = self.twin_verifier.measure()
            v = self.twin_verifier.compare(before, after)
        except Exception as e:
            # Twin hong thi KHONG duoc coi la da xac nhan. Mac dinh an toan la
            # khong cho ap len production.
            v = Verdict("no_change", f"twin gap loi: {str(e)[:200]}")
        finally:
            try:
                self.twin.destroy_twin()
            except Exception:
                pass

        log.twin_verdict = v.to_dict()
        return {"verdict": v.to_dict()}

    def _apply(self, state: AgentState) -> AgentState:
        """Đo production rồi thi hành hành động. Chờ và đo lại là việc của Watch."""
        action = ProposedAction(**state["action"])
        log = self._round_log

        if self.dry_run:
            r = ActionResult(action=action.action, target=action.target,
                             namespace=self.namespace, applied=False, verified=True,
                             detail="dry_run: khong dung toi cluster")
        else:
            if self.guards and action.action != "no_action":
                # DOI SANH TRANG THAI: cau hinh production phai con dung nhu luc kiem
                # chung. Khac thi khong thi hanh, vong sau quan sat lai tu dau.
                now = self._capture_state()
                log.drift_checked = True
                log.drift = (diff_state(log.state_seen, now)
                             if log.state_seen and now
                             else ["khong doc duoc cau hinh production de doi sanh"])
                if log.drift:
                    shown = "; ".join(log.drift[:5])
                    log.blocked_by = "drift"
                    log.skipped_reason = f"production da doi tu luc kiem chung: {shown}"
                    return {"applied": False,
                            "feedback": (f"Action {action.action} on {action.target} "
                                         f"was NOT applied: production configuration "
                                         f"changed since it was checked ({shown}). "
                                         f"Diagnose again from the new snapshot.")}
                # Kiem lai dieu kien tien quyet: o nhanh twin da troi qua mot chu ky
                # twin, so pod san sang co the da khac luc precheck.
                failed = self._check_preconditions(state["action"])
                if failed:
                    return {"applied": False,
                            "feedback": self._precondition_feedback(state["action"],
                                                                    failed)}
            if action.action != "no_action":
                # Do NGAY truoc khi doi, khong dung `red` luc observe: o nhanh twin da
                # troi qua khoang 13 phut ke tu luc observe.
                log.prod_before = self._measure_prod()
            r = self.executor.apply(action)
        log.action_result = r.to_dict()
        log.promoted = r.ok

        if action.action == "no_action":
            return {"applied": False, "stop_reason": "agent chon khong lam gi"}
        if not r.applied:
            # Hanh dong that bai cung la mot ket qua, phai ghi lai va nhoi vao vong
            # sau — day chinh la "wasted action count" o muc 8 KLTN.md.
            return {"applied": False,
                    "feedback": f"Action {action.action} on {action.target} failed: "
                                f"{r.detail}"}
        # Da doi production thi phai qua Watch, ke ca khi kiem chung that bai (vi du
        # het gio cho rollout): thay doi van nam tren he thong va phai duoc do.
        note = "" if r.ok else f" Verification failed: {r.error}."
        return {"applied": True,
                "feedback": f"Action {action.action} on {action.target} was applied: "
                            f"{r.detail}.{note}"}

    def _capture_state(self) -> dict:
        """Chụp cấu hình production để đối sánh. Lỗi đọc thì trả về rỗng.

        Rỗng ở bất kỳ lần chụp nào đều làm `_apply` KHÔNG thi hành: không đọc được
        trạng thái thì không được coi là trạng thái không đổi.
        """
        try:
            return capture_state(self.k8s, self.namespace)
        except Exception:
            return {}

    def _measure_prod(self) -> dict:
        """Đo RED của production. Lỗi đo thì trả về rỗng và ghi lý do vào nhật ký vòng.

        Không đo được thì `compare()` ra `no_change`, tức là KHÔNG tự hoàn tác: không
        có số thì không được kết luận hành động đã làm hại.
        """
        try:
            return self.prod_verifier.measure()
        except Exception as e:
            self._round_log.prod_error = str(e)[:200]
            return {}

    def _watch(self, state: AgentState) -> AgentState:
        """Chờ đủ một cửa sổ, đo production lần nữa, so với số đo trước khi áp.

        Chạy ở mọi chế độ có hành động. Node này chỉ đo và ghi lại; tự hoàn tác hay
        không là việc của nhánh ngay sau nó.
        """
        log = self._round_log
        # Phai cho DAY mot cua so: cho ngan hon thi so "sau" con lan trang thai
        # "truoc" — bai hoc dat nhat cua phase 2.
        time.sleep(self.settle_seconds)
        log.prod_after = self._measure_prod()
        v = self.prod_verifier.compare(log.prod_before, log.prod_after)
        log.prod_verdict = v.to_dict()
        return {
            "prod_verdict": v.verdict,
            "feedback": (state.get("feedback", "")
                         + f" Measured on production {self.settle_seconds}s later: "
                           f"{v.verdict} — {v.reason}."),
        }

    def _auto_undo(self, state: AgentState) -> AgentState:
        """Hoàn tác hành động vừa làm production tệ đi.

        Hoàn tác xong thì chờ thêm một cửa sổ. Không chờ thì vòng sau chẩn đoán trên
        một cửa sổ còn lẫn khoảng thời gian tệ đi, và LLM sẽ đọc hậu quả của chính
        hành động vừa gỡ thành triệu chứng của lỗi gốc.
        """
        log = self._round_log
        act = state.get("action") or {}
        what = f"Action {act.get('action')} on {act.get('target')}"
        why = (log.prod_verdict or {}).get("reason", "")
        result = ActionResult(**{k: v for k, v in log.action_result.items()
                                 if k != "ok"})

        u = self.executor.undo(result)
        log.auto_undo = u.to_dict()
        log.auto_undone = u.ok
        if u.applied:
            time.sleep(self.settle_seconds)

        if u.ok:
            fb = (f"{what} made production WORSE ({why}) and was automatically "
                  f"undone. Do not propose this same action again.")
        elif result.undo_kind == "none":
            fb = (f"{what} made production WORSE ({why}). It cannot be undone "
                  f"automatically.")
        else:
            fb = (f"{what} made production WORSE ({why}). Automatic undo FAILED: "
                  f"{u.detail}.")
        return {"feedback": fb}

    def _reject(self, state: AgentState) -> AgentState:
        """Twin không xác nhận, không áp lên production."""
        v = state.get("verdict") or {}
        action = state.get("action") or {}
        log = self._round_log
        log.promoted = False
        log.skipped_reason = (
            f"twin phan quyet '{v.get('verdict')}': {v.get('reason', '')}")
        return {
            "feedback": (
                f"Action {action.get('action')} on {action.get('target')} was tested "
                f"on the digital twin and REJECTED. Twin verdict: "
                f"{v.get('verdict')} — {v.get('reason', '')}. "
                f"Do not propose this same action again.")
        }

    def _finish_round(self, state: AgentState) -> AgentState:
        """Đóng nhật ký vòng hiện tại."""
        log = self._round_log
        log.took_s = round(time.time() - log.started_at, 2)
        return {"rounds": [log.to_dict()]}

    # ------------------------------------------------------------------
    # CAC NHANH
    # ------------------------------------------------------------------

    def _after_observe(self, state: AgentState) -> str:
        if state.get("healthy"):
            return "done"
        if state.get("round_no", 1) > self.max_rounds:
            return "exhausted"
        return "reason"

    def _after_select(self, state: AgentState) -> str:
        exp = state.get("explanation")
        action = state.get("action")
        if not exp:
            return "failed"
        if not action:
            return "failed"
        if self.mode == "xai_only":
            return "observe_only"

        name = action.get("action", "")
        if name == "no_action":
            return "apply"
        if self.guards:
            return "precheck"
        return self._twin_or_apply(name)

    def _after_precheck(self, state: AgentState) -> str:
        if state.get("blocked"):
            return "blocked"
        return self._twin_or_apply((state.get("action") or {}).get("action", ""))

    def _twin_or_apply(self, name: str) -> str:
        if self.mode == "twin_verified" and needs_twin(name):
            return "twin"
        return "apply"

    def _after_twin(self, state: AgentState) -> str:
        v = state.get("verdict") or {}
        return "apply" if v.get("verdict") == "better" else "reject"

    def _after_apply(self, state: AgentState) -> str:
        return "watch" if state.get("applied") else "done"

    def _after_watch(self, state: AgentState) -> str:
        """Tệ đi thì tự hoàn tác — chỉ khi bật cơ chế, và chỉ với mức medium, hard.

        Mức easy cố ý không tự hoàn tác: đó là chỗ khác nhau giữa easy và medium.
        """
        action = (state.get("action") or {}).get("action", "")
        if (self.guards and state.get("prod_verdict") == "worse"
                and undo_if_worse(action)):
            return "undo"
        return "done"

    # ------------------------------------------------------------------

    def _build_graph(self):
        g = StateGraph(AgentState)
        g.add_node("observe", self._observe)
        g.add_node("reason", self._reason)
        g.add_node("select", self._select)
        g.add_node("precheck", self._precheck)
        g.add_node("twin", self._verify_on_twin)
        g.add_node("apply", self._apply)
        g.add_node("watch", self._watch)
        g.add_node("auto_undo", self._auto_undo)
        g.add_node("reject", self._reject)
        g.add_node("finish_round", self._finish_round)

        g.add_edge(START, "observe")
        g.add_conditional_edges("observe", self._after_observe, {
            "reason": "reason",
            "done": "finish_round",
            "exhausted": "finish_round",
        })
        g.add_edge("reason", "select")
        g.add_conditional_edges("select", self._after_select, {
            "precheck": "precheck",
            "twin": "twin",
            "apply": "apply",
            "reject": "reject",
            "failed": "finish_round",
            "observe_only": "finish_round",
        })
        g.add_conditional_edges("precheck", self._after_precheck, {
            "twin": "twin",
            "apply": "apply",
            "blocked": "finish_round",
        })
        g.add_conditional_edges("twin", self._after_twin, {
            "apply": "apply",
            "reject": "reject",
        })
        g.add_conditional_edges("apply", self._after_apply, {
            "watch": "watch",
            "done": "finish_round",
        })
        g.add_conditional_edges("watch", self._after_watch, {
            "undo": "auto_undo",
            "done": "finish_round",
        })
        g.add_edge("auto_undo", "finish_round")
        g.add_edge("reject", "finish_round")
        g.add_edge("finish_round", END)
        return g.compile()

    # ------------------------------------------------------------------
    # CHAY
    # ------------------------------------------------------------------

    def run(self, run_id: str | None = None, save: bool = True,
            on_round=None) -> dict:
        """Chạy trọn một ca, tối đa `max_rounds` vòng.

        LangGraph chạy MỘT vòng mỗi lần gọi `invoke`; vòng lặp bên ngoài ở đây quyết
        định có đi tiếp không. Cố ý tách như vậy: điều kiện dừng phụ thuộc vào việc
        đo lại hệ thống sau khi hành động, mà phép đo đó cần chờ đủ một cửa sổ quan
        sát — nhồi cả phần chờ vào trong graph làm nó khó đọc và khó thử.
        """
        run_id = run_id or uuid.uuid4().hex[:8]
        state: AgentState = {
            "run_id": run_id,
            "mode": self.mode,
            "namespace": self.namespace,
            "round_no": 0,
            "max_rounds": self.max_rounds,
            "feedback": "",
            "rounds": [],
        }
        started = time.time()
        stop_reason = ""

        for _ in range(self.max_rounds):
            state = {**state, **self.graph.invoke(state)}
            last = state["rounds"][-1] if state["rounds"] else {}

            # Bao ngay khi mot vong xong, khong doi ca ca chay het. Mot vong co the
            # mat 15 phut khi phai dung twin, va chay 15 phut ma khong in gi thi
            # khong phan biet duoc dang chay voi dang treo — dung bai hoc da tra gia
            # o phase 3 khi loat danh gia treo 16 phut trong im lang.
            if on_round is not None:
                try:
                    on_round(last)
                except Exception:
                    pass

            if state.get("healthy"):
                stop_reason = "he thong da khoe manh"
                break
            if last.get("reasoning_ran") and not last.get("reasoning_ok"):
                stop_reason = "XAI khong chan doan duoc"
                break
            if self.mode == "xai_only":
                stop_reason = "che do xai_only: chi chan doan, khong hanh dong"
                break
            if last.get("chosen_action", {}).get("action") == "no_action":
                stop_reason = "agent chon khong lam gi"
                break
        else:
            stop_reason = f"het tran {self.max_rounds} vong ma chua khoi"

        report = {
            "run_id": run_id,
            "mode": self.mode,
            "namespace": self.namespace,
            "started_at": started,
            "started_at_human": time.strftime("%Y-%m-%d %H:%M:%S",
                                              time.localtime(started)),
            "took_s": round(time.time() - started, 2),
            "rounds_used": len(state.get("rounds", [])),
            "max_rounds": self.max_rounds,
            # Ghi lai da chay voi anh nen nao. Doc lai mot ca cu ma khong biet no
            # dung nen nao thi khong giai thich duoc vi sao no phat hien hay bo sot.
            "baseline_source": self.baseline_source,
            "has_baseline": self.baseline is not None,
            # Phep thu phan thuc (src_thesis/eval/counterfactual.py) phai goi lai
            # DUNG model va DUNG ban prompt nay, khong thi doi ket qua la do doi model
            # chu khong phai do doi du lieu.
            "llm": {"provider": self.reasoner.provider.name,
                    "model": self.reasoner.model,
                    "prompt_version": PROMPT_VERSION},
            "healthy_at_end": bool(state.get("healthy")),
            "stop_reason": stop_reason,
            "total_input_tokens": sum(r.get("input_tokens", 0)
                                      for r in state.get("rounds", [])),
            "total_output_tokens": sum(r.get("output_tokens", 0)
                                       for r in state.get("rounds", [])),
            "actions_applied": sum(1 for r in state.get("rounds", [])
                                   if r.get("promoted")),
            "actions_rejected_by_twin": sum(1 for r in state.get("rounds", [])
                                            if r.get("twin_used")
                                            and not r.get("promoted")),
            "guards": self.guards,
            "actions_auto_undone": sum(1 for r in state.get("rounds", [])
                                       if r.get("auto_undone")),
            "blocked_by_precondition": sum(1 for r in state.get("rounds", [])
                                           if r.get("blocked_by") == "precondition"),
            "blocked_by_drift": sum(1 for r in state.get("rounds", [])
                                    if r.get("blocked_by") == "drift"),
            "rounds": state.get("rounds", []),
        }
        if save:
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            out = RUNS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_{self.mode}_{run_id}.json"
            out.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            report["saved_to"] = str(out)
        return report
