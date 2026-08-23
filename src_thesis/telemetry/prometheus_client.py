"""Lấy số liệu từ Prometheus bằng PromQL.

Hai nhóm số liệu:
  - RED metrics từng service (request rate, error rate, latency) — sinh từ trace
    qua connector spanmetrics, nên KHÔNG phải cắm thư viện đo vào 11 service.
  - Metric hạ tầng (CPU, RAM từng pod) và trạng thái deployment.

Tên metric đã kiểm chứng trên cluster ở bước 0.7:
    traces_span_metrics_calls_total                  (counter)
    traces_span_metrics_duration_milliseconds_bucket (histogram)

Nhãn `status_code` CHỈ có hai giá trị: STATUS_CODE_UNSET lúc bình thường và
STATUS_CODE_ERROR lúc lỗi. Không hề có STATUS_CODE_OK — nên tỉ lệ lỗi phải tính
bằng ERROR chia tổng, đừng lọc theo OK.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import requests

DEFAULT_URL = "http://localhost:9090"
CALLS = "traces_span_metrics_calls_total"
DURATION = "traces_span_metrics_duration_milliseconds_bucket"

# Loại hai loại span nhiễu ra khỏi mọi phép tính:
#   - grpc.health.v1.Health/Check: lệnh kiểm tra sức khỏe chạy vài giây một lần,
#     không phải lưu lượng nghiệp vụ. Để nguyên thì request rate bị thổi phồng.
#   - opentelemetry.proto...TraceService/Export: span do chính thư viện SDK sinh ra
#     khi gửi telemetry về collector. Để nguyên thì collector bị đếm thành một service.
# Hai điều dễ sai. Biểu thức của Prometheus luôn khớp TRỌN chuỗi nên phải bọc .* hai đầu.
# Và trong chuỗi nháy kép của PromQL, viết \. sẽ báo lỗi 400 vì đó không phải chuỗi
# thoát hợp lệ — nên ở đây để dấu chấm trần, nó khớp mọi ký tự, vẫn đúng mục đích.
NOISE = 'span_name!~".*grpc.health..*|.*opentelemetry.proto..*"'


@dataclass
class ServiceRED:
    """Ba chỉ số RED của một service trong khoảng thời gian đã chọn."""

    service: str
    request_rate: float     # số request mỗi giây
    error_rate: float       # tỉ lệ lỗi, 0..1
    p50_ms: float
    p95_ms: float
    source: str             # "server" nếu tự phát trace, "client" nếu đo gián tiếp

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PodResource:
    pod: str
    cpu_cores: float
    memory_bytes: float

    def to_dict(self) -> dict:
        return asdict(self)


class PrometheusClient:
    def __init__(self, base_url: str = DEFAULT_URL, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Gọi API thô
    # ------------------------------------------------------------------

    def query(self, promql: str) -> list[dict]:
        """Chạy một câu PromQL, trả về danh sách kết quả tại thời điểm hiện tại."""
        r = requests.get(
            f"{self.base_url}/api/v1/query",
            params={"query": promql},
            timeout=self.timeout,
        )
        r.raise_for_status()
        body = r.json()
        if body.get("status") != "success":
            raise RuntimeError(f"PromQL loi: {body.get('error')}")
        return body["data"]["result"]

    def _as_map(self, promql: str, label: str) -> dict[str, float]:
        """Chạy PromQL rồi gom thành {giá trị của nhãn: số}."""
        out: dict[str, float] = {}
        for row in self.query(promql):
            key = row["metric"].get(label)
            if key is None:
                continue
            try:
                out[key] = float(row["value"][1])
            except (TypeError, ValueError):
                continue
        return out

    # ------------------------------------------------------------------
    # RED metrics phía server — cho 7 service tự phát trace
    # ------------------------------------------------------------------

    def red_metrics(self, window: str = "5m") -> dict[str, ServiceRED]:
        """RED của các service tự phát span server.

        `window` là bề rộng cửa sổ nhìn lại, ví dụ "5m" là 5 phút gần nhất.
        Cửa sổ hẹp thì nhạy với sự cố nhưng nhiễu; 5 phút là mức cân bằng,
        và phải rộng hơn chu kỳ lấy metric 15 giây ít nhất vài lần.
        """
        kind = f'span_kind="SPAN_KIND_SERVER",{NOISE}'
        rate = self._as_map(
            f'sum by (service_name) (rate({CALLS}{{{kind}}}[{window}]))',
            "service_name",
        )
        errors = self._as_map(
            f'sum by (service_name) '
            f'(rate({CALLS}{{{kind},status_code="STATUS_CODE_ERROR"}}[{window}]))',
            "service_name",
        )
        p50 = self._quantile(0.50, kind, window, "service_name")
        p95 = self._quantile(0.95, kind, window, "service_name")

        out: dict[str, ServiceRED] = {}
        for svc, r in rate.items():
            err = errors.get(svc, 0.0)
            out[svc] = ServiceRED(
                service=svc,
                request_rate=round(r, 4),
                error_rate=round(err / r, 4) if r > 0 else 0.0,
                p50_ms=round(p50.get(svc, float("nan")), 2),
                p95_ms=round(p95.get(svc, float("nan")), 2),
                source="server",
            )
        return out

    # ------------------------------------------------------------------
    # RED metrics phía client — vớt lại cartservice, shippingservice, adservice
    # ------------------------------------------------------------------

    def red_metrics_observed(
        self,
        endpoint_map: dict[tuple[str, int], str],
        window: str = "5m",
    ) -> dict[str, ServiceRED]:
        """RED của service ĐÍCH, nhìn từ phía người gọi.

        Ba service `cartservice`, `shippingservice`, `adservice` không có
        OpenTelemetry nên không tự báo cáo được. Nhưng người gọi chúng có ghi span
        client, nên vẫn đo được độ trễ và lỗi — chỉ khác là con số này bao gồm cả
        thời gian đi trên mạng, hơi cao hơn số thật một chút. Ghi rõ điều này trong
        báo cáo, đừng trộn lẫn với số đo phía server.

        `endpoint_map` lấy từ K8sClient.service_endpoint_map(), phải dựng lại mỗi
        lần chụp snapshot vì ClusterIP thay đổi.
        """
        from src_thesis.naming import resolve_target

        kind = f'span_kind="SPAN_KIND_CLIENT",{NOISE}'
        by = "(service_name, server_address, server_port, span_name)"

        rate_rows = self.query(f"sum by {by} (rate({CALLS}{{{kind}}}[{window}]))")
        err_rows = self.query(
            f'sum by {by} (rate({CALLS}{{{kind},status_code="STATUS_CODE_ERROR"}}[{window}]))'
        )
        p95_rows = self.query(
            f"histogram_quantile(0.95, sum by (server_address, server_port, span_name, le) "
            f"(rate({DURATION}{{{kind}}}[{window}])))"
        )

        def target_of(metric: dict) -> str | None:
            name, _ = resolve_target(
                endpoint_map,
                metric.get("server_address"),
                metric.get("server_port"),
                metric.get("span_name"),
            )
            return name

        rates: dict[str, float] = {}
        errs: dict[str, float] = {}
        p95s: dict[str, list[float]] = {}

        for row in rate_rows:
            t = target_of(row["metric"])
            if t:
                rates[t] = rates.get(t, 0.0) + float(row["value"][1])
        for row in err_rows:
            t = target_of(row["metric"])
            if t:
                errs[t] = errs.get(t, 0.0) + float(row["value"][1])
        for row in p95_rows:
            t = target_of(row["metric"])
            v = float(row["value"][1])
            if t and v == v:  # loại NaN
                p95s.setdefault(t, []).append(v)

        out: dict[str, ServiceRED] = {}
        for svc, r in rates.items():
            e = errs.get(svc, 0.0)
            vals = p95s.get(svc, [])
            out[svc] = ServiceRED(
                service=svc,
                request_rate=round(r, 4),
                error_rate=round(e / r, 4) if r > 0 else 0.0,
                p50_ms=float("nan"),
                p95_ms=round(max(vals), 2) if vals else float("nan"),
                source="client",
            )
        return out

    def red_metrics_all(
        self,
        endpoint_map: dict[tuple[str, int], str],
        window: str = "5m",
    ) -> dict[str, ServiceRED]:
        """Gộp hai nguồn. Số đo phía server luôn thắng vì chính xác hơn."""
        merged = dict(self.red_metrics_observed(endpoint_map, window))
        merged.update(self.red_metrics(window))
        return merged

    # ------------------------------------------------------------------
    # Metric hạ tầng
    # ------------------------------------------------------------------

    def pod_resources(self, namespace: str = "default") -> dict[str, PodResource]:
        """CPU (lõi) và RAM (byte) từng pod."""
        cpu = self._as_map(
            f'sum by (pod) (rate(container_cpu_usage_seconds_total'
            f'{{namespace="{namespace}",container!=""}}[5m]))',
            "pod",
        )
        mem = self._as_map(
            f'sum by (pod) (container_memory_working_set_bytes'
            f'{{namespace="{namespace}",container!=""}})',
            "pod",
        )
        pods = set(cpu) | set(mem)
        return {
            p: PodResource(pod=p, cpu_cores=round(cpu.get(p, 0.0), 4),
                           memory_bytes=mem.get(p, 0.0))
            for p in sorted(pods)
        }

    def deployment_availability(self, namespace: str = "default") -> dict[str, dict]:
        """Số bản chạy mong muốn và số đang sẵn sàng của từng deployment.

        Đây là cách phân biệt "service không có lưu lượng" với "service đã chết" —
        bài học rút ra ở bước 0.6, xem docs/thesis-notes.md.
        """
        want = self._as_map(
            f'kube_deployment_spec_replicas{{namespace="{namespace}"}}', "deployment"
        )
        have = self._as_map(
            f'kube_deployment_status_replicas_available{{namespace="{namespace}"}}',
            "deployment",
        )
        return {
            d: {"desired": int(want.get(d, 0)), "available": int(have.get(d, 0))}
            for d in sorted(set(want) | set(have))
        }

    # ------------------------------------------------------------------
    # Nội bộ
    # ------------------------------------------------------------------

    def _quantile(self, q: float, kind_filter: str, window: str,
                  label: str) -> dict[str, float]:
        promql = (
            f"histogram_quantile({q}, sum by ({label}, le) "
            f"(rate({DURATION}{{{kind_filter}}}[{window}])))"
        )
        return self._as_map(promql, label)
