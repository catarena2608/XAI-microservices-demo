"""So lệch sơ đồ thiết kế với sơ đồ chạy thật.

Đây là tín hiệu quan trọng nhất đưa cho XAI (mục 7.1 KLTN.md). Bốn loại lệch, mỗi
loại ứng với một kiểu hỏng khác nhau:

  missing_edges   — thiết kế có, chạy thật không thấy. Dấu hiệu service chết hoặc
                    không gọi được. Đây là chữ ký của lỗi F2 và F3.
  unexpected_edges— chạy thật có, thiết kế không có. Hoặc gọi sai chỗ, hoặc sơ đồ
                    thiết kế viết thiếu. Đừng vội kết luận, kiểm tra lại YAML trước.
  error_edges     — cạnh vẫn có nhưng tỉ lệ lỗi vượt ngưỡng.
  slow_edges      — cạnh vẫn có nhưng chậm hơn hẳn. Chữ ký của lỗi F1 và F4.

`silent_services` tách riêng, vì "không có lưu lượng" khác hẳn "đã chết" — bài học
rút ra ở bước 0.6.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src_thesis.graph.logical_graph import LogicalTopology
from src_thesis.graph.model import ServiceGraph

# Ngưỡng mặc định. Đặt ở đây để phase 6 đổi một chỗ là đổi cả hệ thống.
ERROR_RATE_THRESHOLD = 0.05      # trên 5% số lần gọi bị lỗi

# Phải có ít nhất ngần này lần lỗi mới được coi là sự cố.
#
# Vì sao cần: Online Boutique có tỉ lệ lỗi NỀN tự nhiên trên luồng thanh toán.
# `loadgenerator` sinh số thẻ ngẫu nhiên bằng fake.credit_card_number(card_type="visa"),
# thỉnh thoảng rơi vào dải Visa Electron mà `paymentservice` từ chối. Đo thật:
# 0.2% trên cửa sổ 1 giờ, 0.4% trên 30 phút.
#
# Nhưng cửa sổ quan sát chỉ 5 phút, luồng đặt hàng chỉ khoảng 18 lần gọi, nên MỘT
# lỗi nền đã thành 5.6% và vượt ngưỡng. Đó là bẫy mẫu nhỏ chứ không phải sự cố.
# Yêu cầu 2 lỗi trở lên thì loại được nó: với tỉ lệ nền 0.3%, số lỗi kỳ vọng trong
# 5 phút chỉ khoảng 0.05, hai lỗi cùng lúc gần như chắc chắn là hỏng thật.
MIN_ERRORS = 2

# Khi có baseline: lỗi phải cao hơn mức nền ít nhất ngần này mới tính.
ERROR_MARGIN_OVER_BASELINE = 0.05

# Thông lượng còn dưới ngần này so với lúc khỏe mạnh thì coi là ĐÃ SỤP.
#
# Vì sao cần: lỗi độ trễ làm cả hệ thống chậm tới mức rất ít request hoàn tất trong
# cửa sổ 5 phút, nên nhiều cạnh biến mất khỏi graph dù chúng hoàn toàn khỏe mạnh.
# Đo thật ở kịch bản kép S6: 7 cạnh bị báo mất oan, trong đó có
# checkoutservice -> paymentservice nằm trên luồng nghiệp vụ chính.
#
# Đưa nguyên xi cho LLM thì nó báo bảy nguyên nhân gốc cho hai lỗi. Nên khi thông
# lượng đã sụp, `missing_edges` được đánh dấu là kém tin cậy thay vì bỏ hẳn —
# bỏ hẳn thì mất luôn trường hợp service chết thật.
THROUGHPUT_COLLAPSE_RATIO = 0.5
SLOW_ABSOLUTE_MS = 500.0         # chậm hơn nửa giây là bất thường với hệ này
SLOW_RATIO = 3.0                 # hoặc chậm gấp 3 lần so với lúc khỏe mạnh

# SÀN TUYỆT ĐỐI cho phép so theo tỉ lệ. Cạnh phải chậm thêm ÍT NHẤT chừng này mới
# được tính, dù tỉ lệ có lớn đến đâu.
#
# VÌ SAO CẦN: `SLOW_RATIO` thuần tương đối làm cạnh càng nhanh càng nhạy với nhiễu,
# vì mẫu số càng nhỏ. Ngày 2026-08-30, preflight của ca S2_direct trượt 5 trên 6 lượt
# chỉ vì `checkoutservice -> currencyservice` đo được 10–14ms so với nền 2.71ms — tức
# "chậm gấp 4.2 lần", nhưng chênh lệch thật là 8–11 mili giây. Cần lượt thứ 7 là cả
# ca hỏng, giữa một loạt chạy 30 tiếng.
#
# CHỌN SỐ NÀY THẾ NÀO: đối chiếu với dữ liệu kiểm chứng phase 2, KHÔNG phải với loạt
# phase 6 đang đo — chọn ngưỡng cho vừa số liệu mình sắp kết luận là tự lừa mình.
#
#   tin hieu THAT nho nhat trong 6 kich ban:  +82ms   (S5, recommendation->catalog)
#   nhieu QUAN SAT DUOC lon nhat:             +11.4ms (preflight S2, va "canh lech
#                                                      nhat 11.46 lan" luc so hai nen)
#
# 20ms nam giua, cach nhieu 2 lan va cach tin hieu that 4 lan. Moi cạnh cham cua ca 6
# kich ban da kiem chung deu vuot xa nguong nay, nen sàn nay khong bo sot ca nao.
SLOW_MIN_DELTA_MS = 20.0


@dataclass
class EdgeFinding:
    source: str
    target: str
    detail: str
    on_critical_path: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GraphDiff:
    missing_edges: list[EdgeFinding] = field(default_factory=list)
    unexpected_edges: list[EdgeFinding] = field(default_factory=list)
    error_edges: list[EdgeFinding] = field(default_factory=list)
    slow_edges: list[EdgeFinding] = field(default_factory=list)
    silent_services: list[str] = field(default_factory=list)
    # Tổng lưu lượng hiện tại so với lúc khỏe mạnh. None nếu không có baseline.
    # Dưới 0.5 nghĩa là thông lượng đã sụp quá nửa, và khi đó `missing_edges`
    # phần lớn là báo động giả — xem THROUGHPUT_COLLAPSE_RATIO.
    throughput_ratio: float | None = None

    def is_clean(self) -> bool:
        """Hệ thống khỏe mạnh thì hàm này phải trả True.

        Đây là cổng chặn của phase 1 trong KLTN-PLAN.md: nếu lúc bình thường mà diff
        đã báo đầy lỗi thì tín hiệu này vô dụng cho XAI, phải sửa trước khi đi tiếp.
        """
        return not (self.missing_edges or self.error_edges or self.slow_edges)

    def to_dict(self) -> dict:
        return {
            "missing_edges": [f.to_dict() for f in self.missing_edges],
            "unexpected_edges": [f.to_dict() for f in self.unexpected_edges],
            "error_edges": [f.to_dict() for f in self.error_edges],
            "slow_edges": [f.to_dict() for f in self.slow_edges],
            "silent_services": self.silent_services,
            "throughput_ratio": self.throughput_ratio,
        }


def diff_graphs(
    topo: LogicalTopology,
    runtime: ServiceGraph,
    baseline: ServiceGraph | None = None,
    *,
    error_threshold: float = ERROR_RATE_THRESHOLD,
    min_errors: int = MIN_ERRORS,
    slow_absolute_ms: float = SLOW_ABSOLUTE_MS,
    slow_ratio: float = SLOW_RATIO,
    slow_min_delta_ms: float = SLOW_MIN_DELTA_MS,
) -> GraphDiff:
    """So hai graph. `baseline` là graph lúc hệ thống khỏe mạnh, có thì tốt hơn.

    Không có baseline thì chỉ phát hiện được chậm theo ngưỡng tuyệt đối, dễ bỏ sót
    những service vốn rất nhanh mà bị chậm đi gấp mười lần nhưng vẫn dưới 500ms.
    """
    out = GraphDiff()
    critical = set(topo.critical_path)

    def on_path(a: str, b: str) -> bool:
        return a in critical and b in critical

    runtime_edges = runtime.edge_set()

    # Thông lượng hiện tại so với lúc khỏe mạnh
    collapsed = False
    if baseline is not None:
        base_calls = sum(st.calls for st in baseline.edges.values())
        now_calls = sum(st.calls for st in runtime.edges.values())
        if base_calls > 0:
            out.throughput_ratio = round(now_calls / base_calls, 3)
            collapsed = out.throughput_ratio < THROUGHPUT_COLLAPSE_RATIO

    # 1. Thiết kế có, chạy thật không thấy
    note = ""
    if collapsed:
        note = (f" (KEM TIN CAY: thong luong chi con "
                f"{out.throughput_ratio * 100:.0f}% so voi luc khoe manh, canh nay co the "
                f"vang mat vi qua it luu luong chu khong phai vi hong)")
    for (s, t) in sorted(topo.observable_edges()):
        if (s, t) not in runtime_edges:
            out.missing_edges.append(EdgeFinding(
                s, t, "co trong thiet ke nhung khong thay trong trace" + note,
                on_critical_path=on_path(s, t),
            ))

    # 2. Chạy thật có, thiết kế không có
    for (s, t) in sorted(runtime_edges - topo.graph.edge_set()):
        out.unexpected_edges.append(EdgeFinding(
            s, t, "xuat hien trong trace nhung khong co trong thiet ke",
            on_critical_path=on_path(s, t),
        ))

    # 3 và 4. Cạnh còn sống nhưng lỗi hoặc chậm
    for (s, t), stat in sorted(runtime.edges.items()):
        base = baseline.edges.get((s, t)) if baseline else None

        # Có baseline thì so với mức nền của chính cạnh đó, không có thì so ngưỡng cứng.
        limit = (base.error_rate + ERROR_MARGIN_OVER_BASELINE) if base else error_threshold
        if stat.errors >= min_errors and stat.error_rate > limit:
            extra = f", luc khoe manh {base.error_rate * 100:.1f}%" if base else ""
            out.error_edges.append(EdgeFinding(
                s, t,
                f"ti le loi {stat.error_rate * 100:.1f}% "
                f"({stat.errors}/{stat.calls} lan goi){extra}",
                on_critical_path=on_path(s, t),
            ))

        if (base and base.avg_ms > 0
                and stat.avg_ms > base.avg_ms * slow_ratio
                and stat.avg_ms - base.avg_ms >= slow_min_delta_ms):
            out.slow_edges.append(EdgeFinding(
                s, t,
                f"trung binh {stat.avg_ms}ms, luc khoe manh {base.avg_ms}ms "
                f"(cham gap {stat.avg_ms / base.avg_ms:.1f} lan)",
                on_critical_path=on_path(s, t),
            ))
        elif stat.avg_ms > slow_absolute_ms:
            out.slow_edges.append(EdgeFinding(
                s, t, f"trung binh {stat.avg_ms}ms, vuot nguong {slow_absolute_ms}ms",
                on_critical_path=on_path(s, t),
            ))

    # 5. Service có trong thiết kế, đáng lẽ phát trace, mà không thấy hoạt động gì
    for name, traced in sorted(topo.traced.items()):
        if not traced:
            continue
        seen = name in runtime.nodes
        has_traffic = any(s == name or t == name for (s, t) in runtime_edges)
        if not seen and not has_traffic:
            out.silent_services.append(name)

    return out
