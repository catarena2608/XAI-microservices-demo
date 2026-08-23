"""Quy đổi tên: từ nhãn trong telemetry ra tên deployment trong Kubernetes.

Tồn tại vì mỗi ngôn ngữ đặt tên span một kiểu. Đây là các dạng THẬT quan sát được
trên cluster (bước 0.5), không phải suy đoán:

    hipstershop.CartService/GetCart              <- Go
    /hipstershop.EmailService/SendOrderConfirm   <- Python, có dấu / ở đầu
    grpc.hipstershop.CurrencyService/Convert     <- Node.js, có tiền tố grpc.
    GET, POST                                    <- span HTTP của frontend

Không chuẩn hóa thì runtime graph sẽ coi ba dạng trên là ba service khác nhau.
"""

from __future__ import annotations

# Tên gRPC trong protos/ ánh xạ sang tên deployment trong cluster.
# Đây là "quy tắc 2" ở mục 4 KLTN.md: đường dự phòng khi span không có server.address.
GRPC_TO_DEPLOYMENT: dict[str, str] = {
    "hipstershop.AdService": "adservice",
    "hipstershop.CartService": "cartservice",
    "hipstershop.CheckoutService": "checkoutservice",
    "hipstershop.CurrencyService": "currencyservice",
    "hipstershop.EmailService": "emailservice",
    "hipstershop.PaymentService": "paymentservice",
    "hipstershop.ProductCatalogService": "productcatalogservice",
    "hipstershop.RecommendationService": "recommendationservice",
    "hipstershop.ShippingService": "shippingservice",
}

# Bỏ qua khi dựng graph:
#   - health check chạy vài giây một lần, không phải quan hệ nghiệp vụ
#   - span do chính SDK sinh ra khi gửi telemetry về collector, là nhiễu tự thân
IGNORED_GRPC_SERVICES: set[str] = {
    "grpc.health.v1.Health",
    "opentelemetry.proto.collector.trace.v1.TraceService",
}


def grpc_service_from_span_name(span_name: str) -> str | None:
    """Rút tên gRPC service từ tên span. Trả None nếu span không phải gọi gRPC.

    >>> grpc_service_from_span_name("hipstershop.CartService/GetCart")
    'hipstershop.CartService'
    >>> grpc_service_from_span_name("/hipstershop.EmailService/SendOrderConfirmation")
    'hipstershop.EmailService'
    >>> grpc_service_from_span_name("grpc.hipstershop.CurrencyService/Convert")
    'hipstershop.CurrencyService'
    >>> grpc_service_from_span_name("GET") is None
    True
    """
    if not span_name or "/" not in span_name:
        return None
    name = span_name.lstrip("/")
    # Node.js gắn thêm tiền tố "grpc." — nhưng cẩn thận, có cả
    # "grpc.grpc.health.v1.Health/Check" nên phải bóc lặp lại.
    while name.startswith("grpc.") and not name.startswith("grpc.health."):
        name = name[len("grpc."):]
    return name.split("/", 1)[0] or None


def deployment_from_span_name(span_name: str) -> str | None:
    """Tên span -> tên deployment. Trả None nếu là health check hoặc span nội bộ."""
    grpc_name = grpc_service_from_span_name(span_name)
    if grpc_name is None or grpc_name in IGNORED_GRPC_SERVICES:
        return None
    return GRPC_TO_DEPLOYMENT.get(grpc_name)


def is_noise(span_name: str) -> bool:
    """Span này có nên bị loại khỏi graph và khỏi thống kê không."""
    grpc_name = grpc_service_from_span_name(span_name)
    return grpc_name in IGNORED_GRPC_SERVICES


def resolve_target(
    endpoint_map: dict[tuple[str, int], str],
    server_address: str | None,
    server_port: str | int | None,
    span_name: str | None,
) -> tuple[str | None, str]:
    """Xác định span client này đang gọi tới service nào.

    Trả về (tên_deployment, cách_tìm_ra). Phần thứ hai để ghi vào báo cáo:
    biết bao nhiêu phần trăm cạnh dựng được bằng cách nào.

    Thứ tự ưu tiên:
      1. Tra ClusterIP — chính xác tuyệt đối, nhưng chỉ span của Go mới có.
      2. Tra tên gRPC — dùng cho span của Python và Node.js.
    """
    if server_address and server_port:
        try:
            key = (str(server_address), int(server_port))
        except (TypeError, ValueError):
            key = None
        if key and key in endpoint_map:
            return endpoint_map[key], "ip"

    if span_name:
        name = deployment_from_span_name(span_name)
        if name:
            return name, "grpc_name"

    return None, "khong_xac_dinh"
