"""Chỉ số đánh giá, theo mục 8 KLTN.md.

Phase 3 chỉ dùng chỉ số 1 và 2 — chất lượng của XAI. Bốn chỉ số còn lại cần agent
nên để sang phase 5 và 6.

Nguyên tắc: mọi hàm ở đây nhận `Explanation` và `GroundTruth`, không đụng tới cluster.
Nhờ vậy chấm điểm lại được bất cứ lúc nào từ file JSON đã lưu, không phải chạy lại
thí nghiệm.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean, stdev


@dataclass
class CaseScore:
    """Điểm của một ca."""

    scenario: str
    root_cause_correct: bool
    propagation_jaccard: float
    action_correct: bool
    confidence: float
    fault_type_correct: bool
    predicted_root: str
    expected_root: str

    def to_dict(self) -> dict:
        return asdict(self)


def root_cause_correct(predicted: str, expected: str) -> bool:
    """Chỉ số 1 — có chỉ đúng service gây lỗi không.

    So khớp chính xác sau khi chuẩn hóa chữ hoa thường và khoảng trắng. Cố ý KHÔNG
    khớp gần đúng: "frontend" và "productcatalogservice" là hai đáp án khác nhau,
    chấm nới tay ở đây là tự thổi phồng kết quả của chính mình.
    """
    return predicted.strip().lower() == expected.strip().lower()


def propagation_accuracy(predicted: list[str], expected: list[str]) -> float:
    """Chỉ số 2 — độ trùng của đường lan truyền, tính bằng Jaccard.

    Jaccard = số phần tử chung chia cho số phần tử của hợp hai tập. Chọn Jaccard vì
    nó phạt cả hai kiểu sai: bỏ sót service bị ảnh hưởng, và kể thừa service không
    liên quan. Dùng tỉ lệ bao phủ đơn thuần thì model cứ liệt kê hết 11 service là
    đạt điểm tuyệt đối.

    Hai tập đều rỗng trả về 1.0: không có gì lan truyền và model cũng nói vậy.
    """
    p = {s.strip().lower() for s in predicted if s.strip()}
    e = {s.strip().lower() for s in expected if s.strip()}
    if not p and not e:
        return 1.0
    if not p or not e:
        return 0.0
    return round(len(p & e) / len(p | e), 4)


def action_correct(predicted_actions: list[str], correct_actions: list[str]) -> bool:
    """Hành động ưu tiên cao nhất có nằm trong danh sách đáp án đúng không.

    Chỉ xét hành động ĐẦU TIÊN, vì phase 5 agent cũng chỉ thực hiện cái đầu tiên.
    Xét cả danh sách thì model cứ đề xuất đủ bảy hành động là chắc chắn trúng.
    """
    if not predicted_actions:
        return "no_action" in correct_actions
    return predicted_actions[0].strip().lower() in {
        a.strip().lower() for a in correct_actions
    }


def score_case(explanation, ground_truth: dict, scenario: str = "") -> CaseScore:
    """Chấm một ca. `ground_truth` là dict đọc từ file trong data/runs/."""
    expected_root = ground_truth.get("target_service", "")
    actions = [a.action for a in explanation.proposed_actions]
    return CaseScore(
        scenario=scenario or ground_truth.get("fault_id", ""),
        root_cause_correct=root_cause_correct(explanation.root_cause_service,
                                              expected_root),
        propagation_jaccard=propagation_accuracy(
            explanation.propagation_path,
            ground_truth.get("expected_propagation", []),
        ),
        action_correct=action_correct(actions,
                                      ground_truth.get("correct_actions", [])),
        confidence=explanation.confidence,
        fault_type_correct=(
            explanation.fault_type == ground_truth.get("fault_type", "")
        ),
        predicted_root=explanation.root_cause_service,
        expected_root=expected_root,
    )


@dataclass
class Aggregate:
    """Tổng hợp nhiều lần chạy. Có độ lệch chuẩn vì LLM không ổn định."""

    n: int
    root_cause_accuracy: float
    root_cause_std: float
    propagation_mean: float
    propagation_std: float
    action_accuracy: float
    fault_type_accuracy: float
    mean_confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


def aggregate(scores: list[CaseScore]) -> Aggregate:
    """Gộp điểm nhiều lần chạy.

    Mục 8 KLTN.md bắt buộc mỗi kịch bản chạy tối thiểu 5 lần để có độ lệch chuẩn —
    LLM không ổn định, một lần chạy không có giá trị khoa học.
    """
    if not scores:
        return Aggregate(0, 0, 0, 0, 0, 0, 0, 0)

    rc = [1.0 if s.root_cause_correct else 0.0 for s in scores]
    pp = [s.propagation_jaccard for s in scores]

    def sd(xs: list[float]) -> float:
        return round(stdev(xs), 4) if len(xs) > 1 else 0.0

    return Aggregate(
        n=len(scores),
        root_cause_accuracy=round(mean(rc), 4),
        root_cause_std=sd(rc),
        propagation_mean=round(mean(pp), 4),
        propagation_std=sd(pp),
        action_accuracy=round(
            mean([1.0 if s.action_correct else 0.0 for s in scores]), 4),
        fault_type_accuracy=round(
            mean([1.0 if s.fault_type_correct else 0.0 for s in scores]), 4),
        mean_confidence=round(mean([s.confidence for s in scores]), 4),
    )
