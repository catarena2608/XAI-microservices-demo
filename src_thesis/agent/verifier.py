"""Đo twin trước và sau khi thử một hành động, rồi phán quyết tốt lên hay xấu đi.

Đây là mảnh ghép biến twin từ "bản sao chạy được" thành **sân tập có ích**: agent
thử hành động ở đây, verifier trả về `better` / `worse` / `no_change` kèm con số, và
chỉ khi `better` thì hành động mới được đưa lên production (mục 7.4 KLTN.md).

BA QUYẾT ĐỊNH THIẾT KẾ, đều rút từ những gì đã đo ở phase 2 và 3:

1. **Chỉ nhìn service trên luồng nghiệp vụ chính, không nhìn trung bình toàn hệ
   thống.** Trung bình bị `productcatalogservice` áp đảo vì nó có lưu lượng gấp
   nhiều lần các service khác — số đo thật ở S5: 13.56 req/s so với 0.11 req/s của
   `checkoutservice`. Một hành động làm hỏng hẳn luồng đặt hàng vẫn có thể làm trung
   bình đẹp lên.

2. **Phải có ngưỡng thay đổi tối thiểu.** Không có ngưỡng thì mọi phép đo đều ra
   `better` hoặc `worse` do nhiễu tự nhiên, và phán quyết trở nên vô nghĩa. Phase 2
   đo được p95 dao động vài phần trăm giữa hai lần chụp liên tiếp trên hệ thống
   hoàn toàn khỏe mạnh.

3. **Tỉ lệ lỗi được ưu tiên hơn độ trễ.** Một hành động làm hệ thống nhanh hơn
   nhưng lỗi nhiều hơn là hành động có hại. Chậm thì người dùng phải chờ; lỗi thì
   đơn hàng mất hẳn.

CẢNH BÁO ĐO ĐẠC: mọi phép đo phải chờ ít nhất một cửa sổ quan sát đầy sau khi thay
đổi. Bài học đắt nhất của phase 2 — chờ 180 giây với cửa sổ 300 giây thì số liệu
vẫn còn 120 giây của trạng thái cũ, và `currencyservice` đã tắt hẳn 3 phút vẫn hiện
"0.0% errors".
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from src_thesis.k8s_client import K8sClient
from src_thesis.telemetry.prometheus_client import PrometheusClient

# Tien to ten service cua twin trong trace, dat trong infra/twin/kustomization.yaml.
TWIN_PREFIX = "twin-"

# Service tren luong nghiep vu chinh. Phan quyet chi nhin nhung service nay.
CRITICAL_SERVICES = (
    "frontend",
    "productcatalogservice",
    "cartservice",
    "checkoutservice",
    "paymentservice",
)

# Nguong thay doi toi thieu. Duoi muc nay coi la khong doi.
MIN_ERROR_DELTA = 0.02      # 2 diem phan tram
MIN_LATENCY_RATIO = 0.15    # 15% thay doi p95

# Luu luong toi thieu de mot service duoc quyen bo phieu vao phan quyet.
#
# VI SAO CAN: do fidelity S4 lan dau ra ket qua sai vi ly do nay. `checkoutservice`
# va `paymentservice` chay 0.08 req/s, tuc khoang 24 request trong cua so 5 phut.
# p95 tinh tren 24 mau nhay loan, va nhieu do du suc lat phan quyet: production bao
# "vua nhanh len o frontend, cartservice vua cham di o checkoutservice, paymentservice"
# roi ket luan no_change — trong khi hanh dong vua thuc hien la GO HAN nguyen nhan.
#
# 0.3 req/s la khoang 90 request moi cua so, du de p95 on dinh o muc chap nhan duoc.
# Service duoi nguong nay khong bi coi la xau di, chi don gian la KHONG DU CO SO de
# ket luan — day la hai chuyen khac nhau va gop chung lai thi phan quyet sai.
MIN_RATE_FOR_VERDICT = 0.3

# Cua so quan sat. Phai cho DAY cua so nay sau moi thay doi truoc khi do.
WINDOW = "5m"
WINDOW_SECONDS = 300


@dataclass
class ServiceDelta:
    """Thay đổi của một service giữa hai lần đo."""

    service: str
    error_before: float
    error_after: float
    p95_before: float
    p95_after: float
    rate_before: float
    rate_after: float

    @property
    def error_delta(self) -> float:
        return self.error_after - self.error_before

    @property
    def p95_ratio(self) -> float:
        """Tỉ lệ thay đổi p95. Dương là chậm đi, âm là nhanh lên."""
        if self.p95_before <= 0:
            return 0.0
        return (self.p95_after - self.p95_before) / self.p95_before

    @property
    def mean_rate(self) -> float:
        """Lưu lượng trung bình giữa hai lần đo.

        Dùng trung bình chứ không dùng `rate_after`: khi hành động gỡ được nút thắt
        thì thông lượng bật lên, và lấy riêng con số sau sẽ thổi phồng trọng số của
        đúng service vừa được cứu.
        """
        return (self.rate_before + self.rate_after) / 2

    @property
    def wait_cost_delta(self) -> float:
        """Thay đổi tổng thời gian chờ, tính bằng ms trên mỗi giây.

        Âm là hệ thống bắt người dùng chờ ít đi. Cân theo lưu lượng để một service
        vốn đã nhanh và ít khách không có trọng số ngang một service đang nghẽn cổ
        chai — đây chính là chỗ quy tắc đếm đầu người sai.
        """
        return (self.p95_after - self.p95_before) * self.mean_rate

    @property
    def wait_cost_before(self) -> float:
        """Tổng thời gian chờ mỗi giây TRƯỚC hành động. Dùng làm mẫu số."""
        return self.p95_before * self.mean_rate

    def describe(self) -> str:
        return (f"{self.service}: loi {self.error_before * 100:.1f}% -> "
                f"{self.error_after * 100:.1f}%, "
                f"p95 {self.p95_before:.1f}ms -> {self.p95_after:.1f}ms "
                f"({self.p95_ratio * 100:+.0f}%)")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["error_delta"] = round(self.error_delta, 4)
        d["p95_ratio"] = round(self.p95_ratio, 4)
        return d


@dataclass
class Verdict:
    """Phán quyết cuối cùng về một hành động đã thử trên twin."""

    verdict: str                         # better | worse | no_change
    reason: str
    deltas: list[ServiceDelta] = field(default_factory=list)
    improved: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    measured_at: float = field(default_factory=time.time)

    @property
    def is_safe_to_promote(self) -> bool:
        """Có được phép đưa hành động này lên production không.

        `no_change` KHÔNG được coi là an toàn: hành động không cải thiện gì thì đưa
        lên production chỉ tổ thêm rủi ro mà không được gì. Đây chính là chỉ số
        "wasted action count" ở mục 8 KLTN.md.
        """
        return self.verdict == "better"

    def describe(self) -> str:
        lines = [f"PHAN QUYET: {self.verdict.upper()} — {self.reason}"]
        for d in self.deltas:
            lines.append("  " + d.describe())
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "improved": self.improved,
            "degraded": self.degraded,
            "measured_at": self.measured_at,
            "deltas": [d.to_dict() for d in self.deltas],
        }


class TwinVerifier:
    """Đo twin và phán quyết. Tạo một lần rồi dùng lại."""

    def __init__(self, prom: PrometheusClient | None = None,
                 k8s: K8sClient | None = None,
                 namespace: str = "twin",
                 prefix: str | None = None):
        self.prom = prom or PrometheusClient()
        self.k8s = k8s or K8sClient(namespace=namespace)
        self.namespace = namespace
        # Ten service trong trace cua twin mang tien to "twin-", cua production thi
        # khong. Cung mot lop nay do duoc ca hai ben — bat buoc phai vay, vi fidelity
        # la phep so sanh HAI BEN va so sanh bang hai bo code khac nhau thi khong
        # con biet chenh lech den tu he thong hay den tu code do.
        self.prefix = TWIN_PREFIX if prefix is None and namespace == "twin" else (
            prefix or "")

    # ------------------------------------------------------------------

    def measure(self, window: str = WINDOW) -> dict[str, dict]:
        """Đo RED của twin, trả về bảng đã bỏ tiền tố `twin-` khỏi tên.

        Bỏ tiền tố ngay tại đây để phần còn lại của code so sánh twin với
        production bằng cùng một bộ tên, không phải nhớ chuyển đổi ở mọi chỗ.
        """
        endpoint_map = self.k8s.service_endpoint_map(self.namespace)
        # Bang tra IP phai dung IP cua namespace twin: dai IP hoan toan khac
        # production, dung nham bang thi moi canh deu tra ve sai ten.
        raw = self.prom.red_metrics_all(endpoint_map, window, self.prefix)

        out: dict[str, dict] = {}
        for name, red in raw.items():
            if self.prefix:
                if not name.startswith(self.prefix):
                    continue
                key = name[len(self.prefix):]
            else:
                # Do production: bo cac ten mang tien to twin- de khong lan sang
                # so lieu cua twin neu twin dang chay.
                if name.startswith(TWIN_PREFIX):
                    continue
                key = name
            out[key] = {
                "request_rate": red.request_rate,
                "error_rate": red.error_rate,
                "p95_ms": red.p95_ms,
                "source": red.source,
            }
        return out

    def wait_full_window(self, seconds: int = WINDOW_SECONDS,
                         announce: bool = True) -> None:
        """Chờ đủ một cửa sổ quan sát trước khi đo.

        Bỏ qua bước này thì số liệu "sau" còn lẫn trạng thái "trước", và phán quyết
        sẽ sai theo hướng nói rằng hành động không có tác dụng gì.
        """
        if announce:
            print(f"  cho {seconds}s cho du mot cua so quan sat...", flush=True)
        time.sleep(seconds)

    # ------------------------------------------------------------------

    def compare(self, before: dict[str, dict], after: dict[str, dict],
                services: tuple[str, ...] = CRITICAL_SERVICES) -> Verdict:
        """So hai lần đo, trả phán quyết.

        Chỉ xét các service trong `services`. Service vắng mặt ở một trong hai lần
        đo thì bỏ qua, KHÔNG coi là xấu đi — vắng metric không đồng nghĩa đã chết,
        đó là bài học của bước 0.6.
        """
        deltas: list[ServiceDelta] = []
        improved: list[str] = []
        degraded: list[str] = []
        low_traffic: list[str] = []

        for svc in services:
            b, a = before.get(svc), after.get(svc)
            if not b or not a:
                continue
            d = ServiceDelta(
                service=svc,
                error_before=b["error_rate"], error_after=a["error_rate"],
                p95_before=b["p95_ms"], p95_after=a["p95_ms"],
                rate_before=b["request_rate"], rate_after=a["request_rate"],
            )
            deltas.append(d)

            # Qua it mau thi khong du co so ket luan. Van in ra de nguoi doc thay,
            # nhung khong cho bo phieu.
            if min(d.rate_before, d.rate_after) < MIN_RATE_FOR_VERDICT:
                low_traffic.append(svc)
                continue

            # Ti le loi xet truoc, va thang tuyet doi so voi do tre.
            if d.error_delta <= -MIN_ERROR_DELTA:
                improved.append(svc)
                continue
            if d.error_delta >= MIN_ERROR_DELTA:
                degraded.append(svc)
                continue
            if d.p95_ratio <= -MIN_LATENCY_RATIO:
                improved.append(svc)
            elif d.p95_ratio >= MIN_LATENCY_RATIO:
                degraded.append(svc)

        # TONG THOI GIAN CHO, thay cho phep dem dau nguoi.
        #
        # VI SAO: do fidelity S5 ngay 2026-08-29 lech vi ly do nay. `cartservice`
        # doi p95 tu 8.33ms len 20.50ms — 12 mili giay tren mot service von tra loi
        # trong mot chu so — nhung ti le la +146%, vuot xa MIN_LATENCY_RATIO, nen no
        # duoc ghi vao `degraded` voi TRONG SO NGANG frontend vua cai thien 2921ms.
        # Ket qua: phan quyet hoa, tra ve no_change cho mot hanh dong da go han nut
        # that. Nguong thuan tuong doi lam service cang nhanh cang nhay voi nhieu,
        # vi mau so cang nho.
        #
        # Cach sua: van dung 15% do, nhung ap len TONG thoi gian cho da can theo luu
        # luong, khong ap rieng tung service. Khong them hang so moi.
        #
        # Cung mot nguyen tac voi MIN_RATE_FOR_VERDICT o tren, chi la thap hon mot
        # tang: "khong du co so de ket luan" khac "khong co thay doi".
        voting = [d for d in deltas if d.service not in low_traffic]
        cost_delta = sum(d.wait_cost_delta for d in voting)
        cost_base = sum(d.wait_cost_before for d in voting)
        deadband = cost_base * MIN_LATENCY_RATIO
        small = abs(cost_delta) < deadband
        cost_note = (f"tong thoi gian cho doi {cost_delta:+.0f} ms/s "
                     f"tren nen {cost_base:.0f} ms/s")

        if not deltas:
            return Verdict(
                verdict="no_change",
                reason=("khong do duoc service nao tren luong nghiep vu chinh. "
                        "Kiem tra twin da co luu luong chua."),
            )

        if len(low_traffic) == len(deltas):
            return Verdict(
                verdict="no_change",
                reason=(f"moi service deu duoi {MIN_RATE_FOR_VERDICT} req/s "
                        f"({', '.join(low_traffic)}), khong du mau de ket luan"),
                deltas=deltas,
            )

        if degraded and not improved:
            if small:
                return Verdict(
                    "no_change",
                    f"cham di o {', '.join(degraded)} nhung {cost_note}, "
                    f"duoi 15% nen chua du de ket luan",
                    deltas, improved, degraded)
            return Verdict("worse", f"xau di o {', '.join(degraded)}, {cost_note}",
                           deltas, improved, degraded)
        if improved and not degraded:
            if small:
                return Verdict(
                    "no_change",
                    f"nhanh len o {', '.join(improved)} nhung {cost_note}, "
                    f"duoi 15% nen chua du de ket luan",
                    deltas, improved, degraded)
            return Verdict("better", f"tot len o {', '.join(improved)}, {cost_note}",
                           deltas, improved, degraded)
        if improved and degraded:
            # Vua tot vua xau: quyet dinh theo TI LE LOI, vi lam mat don hang nang
            # hon lam cham don hang. Chi khi ti le loi khong doi moi xet do tre.
            err_improved = [d.service for d in deltas
                            if d.error_delta <= -MIN_ERROR_DELTA]
            err_degraded = [d.service for d in deltas
                            if d.error_delta >= MIN_ERROR_DELTA]
            if err_degraded:
                return Verdict(
                    "worse",
                    f"co cho tot len nhung ti le loi tang o {', '.join(err_degraded)}, "
                    f"mat don hang nang hon cham don hang",
                    deltas, improved, degraded)
            if err_improved:
                return Verdict(
                    "better",
                    f"ti le loi giam o {', '.join(err_improved)}, du co cho cham di",
                    deltas, improved, degraded)
            # Vua tot vua xau, ti le loi khong doi -> can theo DO LON.
            if small:
                return Verdict(
                    "no_change",
                    f"vua nhanh len o {', '.join(improved)} vua cham di o "
                    f"{', '.join(degraded)}; {cost_note}, duoi 15% nen hoa",
                    deltas, improved, degraded)
            if cost_delta < 0:
                return Verdict(
                    "better",
                    f"nhanh len o {', '.join(improved)} thang phan cham di o "
                    f"{', '.join(degraded)}: {cost_note}",
                    deltas, improved, degraded)
            return Verdict(
                "worse",
                f"cham di o {', '.join(degraded)} thang phan nhanh len o "
                f"{', '.join(improved)}: {cost_note}",
                deltas, improved, degraded)

        return Verdict("no_change",
                       "moi thay doi deu duoi nguong nhieu tu nhien",
                       deltas, improved, degraded)

    # ------------------------------------------------------------------

    def verify_action(self, apply_action, wait_seconds: int = WINDOW_SECONDS,
                      announce: bool = True) -> Verdict:
        """Đo — chạy hành động — chờ đủ cửa sổ — đo lại — phán quyết.

        `apply_action` là một hàm không tham số, thực hiện hành động lên twin. Tách
        ra như vậy để verifier không cần biết hành động là gì, và phase 5 truyền vào
        được bất kỳ hành động nào.
        """
        if announce:
            print("  do twin TRUOC khi thu hanh dong...", flush=True)
        before = self.measure()

        apply_action()

        self.wait_full_window(wait_seconds, announce)

        if announce:
            print("  do twin SAU khi thu hanh dong...", flush=True)
        after = self.measure()

        return self.compare(before, after)
