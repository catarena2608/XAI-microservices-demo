"""Bộ sinh tải nhẹ cho Digital Twin, chạy từ Windows qua port-forward.

VÌ SAO KHÔNG DÙNG LOADGENERATOR GỐC: nó là một Deployment chạy Locust bên trong
cluster, tốn thêm khoảng 50 MiB và một pod nữa. Mục 2 KLTN.md đã chốt RAM là nút
thắt lớn nhất, mà twin chỉ cần đủ tải để sinh ra trace, không cần mô phỏng nghìn
người dùng.

VÌ SAO PHẢI PORT-FORWARD: kind không thêm được cổng sau khi tạo cluster, 5 cổng đã
cố định từ đầu và không còn cổng trống cho frontend của twin. `kubectl port-forward`
mở đường hầm từ Windows vào Service trong cluster, không cần đụng tới cấu hình kind.

TỈ LỆ TÁC VỤ GIỮ ĐÚNG NHƯ BẢN CHÍNH (`infra/loadgenerator-locustfile.yaml`):
index 1, setCurrency 2, browseProduct 10, addToCart 2, viewCart 3, checkout 1.
Đây là điều kiện bắt buộc để so sánh twin với production: hai bên phải chịu cùng
một hình dạng tải, nếu không thì chênh lệch đo được không biết là do hành động hay
do tải khác nhau.

Số thẻ dùng chung một số VISA hợp lệ cố định, cùng lý do đã ghi ở bản chính: số thẻ
ngẫu nhiên đôi khi rơi vào dải Visa Electron bị paymentservice từ chối, sinh ra
1 đến 9% đơn hàng lỗi ngay cả khi hệ thống hoàn toàn khỏe.
"""

from __future__ import annotations

import random
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

TWIN_NAMESPACE = "twin"

# Cổng phía Windows cho đường hầm. Chọn 18080 để không đụng 8080 của production.
LOCAL_PORT = 18080

VALID_VISA_CARD = "4432801561520454"

PRODUCTS = [
    "0PUK6V6EV0", "1YMWWN1N4O", "2ZYFJ3GM2N", "66VCHSJNUP", "6E92ZMYYFZ",
    "9SIQT8TOJO", "L9ECAV7KIM", "LS4PSXUNUM", "OLJCESPC7Z",
]

CURRENCIES = ["EUR", "USD", "JPY", "CAD", "GBP", "TRY"]


@dataclass
class LoadStats:
    """Kết quả một đợt sinh tải. Đây là số liệu THÔ phía người gọi.

    Không dùng con số này để kết luận hành động tốt hay xấu — việc đó là của
    `verifier.py`, nó đọc RED metrics từ Prometheus. Con số ở đây chỉ để biết bộ
    sinh tải có thực sự chạm được vào twin hay không.
    """

    requests: int = 0
    errors: int = 0
    checkouts: int = 0
    checkout_errors: int = 0
    duration_s: float = 0.0
    status_counts: dict[int, int] = field(default_factory=dict)

    @property
    def error_rate(self) -> float:
        return self.errors / self.requests if self.requests else 0.0

    def describe(self) -> str:
        return (f"{self.requests} request trong {self.duration_s:.0f}s, "
                f"loi {self.error_rate * 100:.1f}%, "
                f"dat hang {self.checkouts} lan (loi {self.checkout_errors})")


class PortForward:
    """Đường hầm từ Windows vào Service của twin, dùng theo kiểu `with`.

    Tự đóng tiến trình `kubectl port-forward` khi ra khỏi khối `with`, kể cả khi có
    lỗi. Quên đóng thì tiến trình sống mãi và giữ cổng, lần chạy sau sẽ báo cổng bận
    mà không rõ vì sao.
    """

    def __init__(self, service: str = "frontend", namespace: str = TWIN_NAMESPACE,
                 local_port: int = LOCAL_PORT, remote_port: int = 80,
                 startup_timeout: int = 30):
        self.service = service
        self.namespace = namespace
        self.local_port = local_port
        self.remote_port = remote_port
        self.startup_timeout = startup_timeout
        self.proc: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://localhost:{self.local_port}"

    def __enter__(self) -> "PortForward":
        self.proc = subprocess.Popen(
            ["kubectl", "port-forward", "-n", self.namespace,
             f"svc/{self.service}", f"{self.local_port}:{self.remote_port}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace",
        )
        # Chờ tới khi gọi thật được, chứ không chờ một khoảng thời gian cố định.
        # port-forward in ra "Forwarding from..." trước khi thực sự sẵn sàng nhận
        # kết nối, nên bám vào dòng log đó là bám nhầm.
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                out = self.proc.stdout.read() if self.proc.stdout else ""
                raise RuntimeError(f"port-forward chet ngay: {out[:300]}")
            try:
                urllib.request.urlopen(self.base_url + "/", timeout=3).read(1)
                return self
            except (urllib.error.HTTPError,):
                return self          # co phan hoi HTTP la du, ma loi cung tinh
            except Exception:
                time.sleep(1)
        self.close()
        raise TimeoutError(
            f"khong ket noi duoc toi {self.base_url} sau {self.startup_timeout}s. "
            f"Kiem tra twin da san sang chua: kubectl get pods -n {self.namespace}"
        )

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


class TwinLoadGenerator:
    """Sinh tải vào twin trong một khoảng thời gian định trước."""

    def __init__(self, base_url: str, users: int = 10, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        # 10 người dùng ảo, ĐÚNG BẰNG production (biến USERS của loadgenerator).
        #
        # Ban đầu tớ đặt 3 với lý lẽ "đủ để mọi cạnh có lưu lượng mà không làm twin
        # nghẹt". Lý lẽ đó sai, và đo fidelity mới lộ ra: twin chạy 0.67 req/s trong
        # khi production chạy 2.93 req/s. Hai hậu quả:
        #
        #   1. Kịch bản S1 chèn độ trễ 6 giây làm lưu lượng twin sụp xuống dưới
        #      ngưỡng tối thiểu, verifier không còn đủ mẫu để kết luận gì.
        #   2. Twin phản ứng khác production với cùng một sự cố, và chênh lệch đó
        #      đến từ TẢI chứ không từ bản chất twin — tức là đo nhầm thứ cần đo.
        #
        # So sánh hai môi trường chịu tải khác nhau là so nhầm ngay từ đầu. Tải phải
        # khớp theo cấu hình, không phải theo cảm giác "đủ dùng".
        self.users = users
        self.timeout = timeout
        self._stats = LoadStats()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------

    def _record(self, status: int, is_checkout: bool = False) -> None:
        with self._lock:
            self._stats.requests += 1
            self._stats.status_counts[status] = (
                self._stats.status_counts.get(status, 0) + 1
            )
            failed = status >= 400 or status == 0
            if failed:
                self._stats.errors += 1
            if is_checkout:
                self._stats.checkouts += 1
                if failed:
                    self._stats.checkout_errors += 1

    def _call(self, path: str, data: dict | None = None,
              is_checkout: bool = False) -> None:
        url = self.base_url + path
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        try:
            with urllib.request.urlopen(url, data=body, timeout=self.timeout) as r:
                r.read()
                self._record(r.status, is_checkout)
        except urllib.error.HTTPError as e:
            self._record(e.code, is_checkout)
        except Exception:
            # Ket noi dut hoac qua han deu tinh la loi, ma khong lam chet vong lap.
            self._record(0, is_checkout)

    # ------------------------------------------------------------------
    # Cac tac vu, giu dung ten va hanh vi cua ban chinh
    # ------------------------------------------------------------------

    def _index(self) -> None:
        self._call("/")

    def _set_currency(self) -> None:
        self._call("/setCurrency", {"currency_code": random.choice(CURRENCIES)})

    def _browse_product(self) -> None:
        self._call("/product/" + random.choice(PRODUCTS))

    def _view_cart(self) -> None:
        self._call("/cart")

    def _add_to_cart(self) -> None:
        product = random.choice(PRODUCTS)
        self._call("/product/" + product)
        self._call("/cart", {"product_id": product,
                             "quantity": random.randint(1, 10)})

    def _checkout(self) -> None:
        self._add_to_cart()
        year = time.gmtime().tm_year + 1
        self._call("/cart/checkout", {
            "email": "twin@example.com",
            "street_address": "1600 Amphitheatre Parkway",
            "zip_code": "94043",
            "city": "Mountain View",
            "state": "CA",
            "country": "United States",
            "credit_card_number": VALID_VISA_CARD,
            "credit_card_expiration_month": random.randint(1, 12),
            "credit_card_expiration_year": random.randint(year, year + 20),
            "credit_card_cvv": f"{random.randint(100, 999)}",
        }, is_checkout=True)

    def _pick_task(self):
        # Đúng tỉ lệ của bản chính. Tổng trọng số 19.
        roll = random.randint(1, 19)
        if roll <= 1:
            return self._index
        if roll <= 3:
            return self._set_currency
        if roll <= 13:
            return self._browse_product
        if roll <= 15:
            return self._add_to_cart
        if roll <= 18:
            return self._view_cart
        return self._checkout

    # ------------------------------------------------------------------

    def _worker(self, stop_at: float) -> None:
        while time.time() < stop_at:
            try:
                self._pick_task()()
            except Exception:
                pass
            # ĐÚNG BẰNG bản chính: locust dùng between(1, 10). Trước đây tớ rút
            # xuống 0.5 đến 3 giây để bù cho việc chỉ có 3 người dùng — cách bù đó
            # làm hình dạng tải khác hẳn production, mà giống nhau về hình dạng tải
            # chính là điều kiện để con số fidelity có nghĩa.
            time.sleep(random.uniform(1.0, 10.0))

    def run(self, duration_s: int = 60) -> LoadStats:
        """Chạy `users` luồng song song trong `duration_s` giây."""
        self._stats = LoadStats()
        started = time.time()
        stop_at = started + duration_s
        threads = [threading.Thread(target=self._worker, args=(stop_at,), daemon=True)
                   for _ in range(self.users)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=duration_s + self.timeout + 10)
        self._stats.duration_s = time.time() - started
        return self._stats


def warm_twin(duration_s: int = 60, users: int = 10) -> LoadStats:
    """Mở đường hầm, bơm tải vào twin, đóng đường hầm. Dùng cho trường hợp đơn giản."""
    with PortForward() as pf:
        return TwinLoadGenerator(pf.base_url, users=users).run(duration_s)
