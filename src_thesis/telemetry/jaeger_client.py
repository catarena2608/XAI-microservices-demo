"""Lấy trace từ Jaeger và chuẩn hóa thành danh sách span dễ xử lý.

Vì sao cần trace khi đã có metric: metric cho biết service nào chậm, còn trace cho
biết ai gọi ai. Không có quan hệ gọi nhau thì không dựng được graph, mà graph mới là
thứ XAI dùng để lần ra đường lan truyền lỗi.

API dùng: GET /api/traces?service=...&start=...&end=...&limit=...
Mốc thời gian của Jaeger tính bằng MICRO giây, không phải mili giây — sai chỗ này
thì luôn trả về rỗng mà không báo lỗi gì.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError

# Cong 30686 la NodePort cua Service `jaeger-external`, xem infra/jaeger-all-in-one.yaml.
# KHONG phai 16686. Ly do giong prometheus_client.py: k3s mo NodePort thang tren node,
# con kind thi phai bac cau qua Docker. Quay ve kind thi doi lai thanh 16686.
DEFAULT_URL = "http://localhost:30686"


@dataclass
class Span:
    """Một span đã chuẩn hóa. Chỉ giữ trường nào thật sự dùng tới."""

    trace_id: str
    span_id: str
    parent_id: str | None
    service: str            # service đã ghi ra span này
    operation: str          # tên thao tác, ví dụ hipstershop.CartService/GetCart
    kind: str               # "client", "server", "internal"...
    duration_us: int
    start_us: int
    is_error: bool
    server_address: str | None
    server_port: int | None

    def to_dict(self) -> dict:
        return asdict(self)


class JaegerClient:
    def __init__(self, base_url: str = DEFAULT_URL, timeout: int = 20,
                 retries: int = 3, retry_gap_s: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Jaeger all-in-one giu trace trong RAM va tung bi OOMKilled giua chung, khi do
        # moi request dang bay nhan `RemoteDisconnected` va lam hong ca luot thi nghiem.
        # Pod tu song lai sau vai giay nen thu lai la qua duoc. Rat can cho phase 6:
        # mot cu chop nhu vay khong duoc phep giet luot chay dai 7 tieng.
        self.retries = retries
        self.retry_gap_s = retry_gap_s

    def _get(self, path: str, params: dict | None = None) -> dict:
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                r = requests.get(f"{self.base_url}{path}", params=params,
                                 timeout=self.timeout)
                r.raise_for_status()
                return r.json()
            except RequestsConnectionError as e:
                last = e
                if attempt < self.retries:
                    print(f"  [jaeger] mat ket noi, thu lai {attempt}/{self.retries - 1} "
                          f"sau {self.retry_gap_s}s...")
                    time.sleep(self.retry_gap_s)
        raise RuntimeError(
            f"khong ket noi duoc Jaeger sau {self.retries} lan thu. "
            f"Kiem tra: kubectl get pod -l app=jaeger"
        ) from last

    def services(self) -> list[str]:
        """Danh sách service mà Jaeger từng nhận được span."""
        return sorted(self._get("/api/services").get("data") or [])

    def recent_spans(
        self,
        service: str = "frontend",
        lookback_seconds: int = 300,
        limit: int = 100,
    ) -> list[Span]:
        """Lấy span của các trace gần đây bắt đầu từ `service`.

        Mặc định lấy từ `frontend` vì mọi request của người dùng đều vào qua đó,
        nên một lần gọi là gom được gần hết quan hệ trong hệ thống.
        """
        end_us = int(time.time() * 1_000_000)
        start_us = end_us - lookback_seconds * 1_000_000
        body = self._get("/api/traces", {
            "service": service,
            "start": start_us,
            "end": end_us,
            "limit": limit,
        })
        traces = body.get("data") or []
        spans: list[Span] = []
        for tr in traces:
            spans.extend(self._parse_trace(tr))
        return spans

    def recent_spans_all(
        self,
        lookback_seconds: int = 300,
        limit_per_service: int = 60,
        skip: tuple[str, ...] = ("jaeger-all-in-one",),
    ) -> list[Span]:
        """Gom span từ MỌI service, không chỉ từ frontend.

        Bắt buộc phải làm vậy, không phải cho chắc ăn. Lý do cụ thể: trong
        `src/checkoutservice/main.go`, lệnh gọi `currencyservice` truyền
        `context.TODO()` thay vì `ctx`, làm đứt ngữ cảnh trace. Span đó không nối
        vào trace của đơn hàng mà thành một trace mồ côi đứng riêng, nên lấy trace
        theo đường vào từ frontend sẽ không bao giờ thấy cạnh
        checkoutservice -> currencyservice.

        Trùng lặp là chuyện đương nhiên vì một trace xuất hiện dưới nhiều service,
        nên phải khử trùng theo cặp (trace_id, span_id).
        """
        seen: set[tuple[str, str]] = set()
        merged: list[Span] = []
        for svc in self.services():
            if svc in skip:
                continue
            for sp in self.recent_spans(svc, lookback_seconds, limit_per_service):
                key = (sp.trace_id, sp.span_id)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(sp)
        return merged

    # ------------------------------------------------------------------
    # Nội bộ
    # ------------------------------------------------------------------

    def _parse_trace(self, trace: dict) -> list[Span]:
        # Jaeger trả tên service gián tiếp: span chỉ có processID, phải tra sang
        # bảng `processes` mới ra tên. Đây là chỗ hay nhầm nhất khi đọc API này.
        processes = {
            pid: p.get("serviceName", "") for pid, p in (trace.get("processes") or {}).items()
        }
        out: list[Span] = []
        for s in trace.get("spans") or []:
            tags = {t.get("key"): t.get("value") for t in (s.get("tags") or [])}
            parent = None
            for ref in s.get("references") or []:
                if ref.get("refType") == "CHILD_OF":
                    parent = ref.get("spanID")
                    break
            port = tags.get("server.port")
            try:
                port = int(port) if port is not None else None
            except (TypeError, ValueError):
                port = None

            out.append(
                Span(
                    trace_id=s.get("traceID", ""),
                    span_id=s.get("spanID", ""),
                    parent_id=parent,
                    service=processes.get(s.get("processID", ""), ""),
                    operation=s.get("operationName", ""),
                    kind=str(tags.get("span.kind", "")),
                    duration_us=int(s.get("duration", 0)),
                    start_us=int(s.get("startTime", 0)),
                    is_error=bool(tags.get("error")) or
                             str(tags.get("otel.status_code", "")).upper() == "ERROR",
                    server_address=tags.get("server.address"),
                    server_port=port,
                )
            )
        return out
