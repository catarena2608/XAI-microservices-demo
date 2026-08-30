"""Kiem tra prometheus_client.py doc duoc so lieu that.

Chay: python scripts/smoke_telemetry.py
Yeu cau: cluster dang chay, localhost:30090 mo duoc (NodePort cua Prometheus).
"""

import sys
from pathlib import Path

# Console Windows mac dinh dung bang ma cp1252, in tieng Viet se vo va script chet.
# Dong nay ep dau ra sang UTF-8; errors="replace" de lo font thieu ky tu thi thay
# dau hoi cham chu khong dung chuong trinh.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src_thesis.k8s_client import K8sClient
from src_thesis.telemetry.prometheus_client import PrometheusClient


def main() -> int:
    k8s = K8sClient()
    prom = PrometheusClient()

    endpoint_map = k8s.service_endpoint_map()
    print(f"=== bang tra ClusterIP: {len(endpoint_map)} muc ===")

    print("\n=== RED phia server (service tu phat trace) ===")
    server = prom.red_metrics()
    for s in sorted(server.values(), key=lambda x: -x.request_rate):
        print(f"  {s.service:24s} rate={s.request_rate:7.2f}/s  "
              f"err={s.error_rate*100:5.1f}%  p50={s.p50_ms:8.1f}ms  p95={s.p95_ms:8.1f}ms")

    print("\n=== RED phia client (do gian tiep qua nguoi goi) ===")
    observed = prom.red_metrics_observed(endpoint_map)
    for s in sorted(observed.values(), key=lambda x: -x.request_rate):
        print(f"  {s.service:24s} rate={s.request_rate:7.2f}/s  "
              f"err={s.error_rate*100:5.1f}%  p95={s.p95_ms:8.1f}ms")

    blind = {"cartservice", "shippingservice", "adservice"}
    found = blind & set(observed)
    print(f"\n  service khong phat trace ma van do duoc: {sorted(found) or 'KHONG CO'}")

    print("\n=== Gop hai nguon ===")
    merged = prom.red_metrics_all(endpoint_map)
    for name, s in sorted(merged.items()):
        print(f"  {name:24s} nguon={s.source}")

    print("\n=== Tai nguyen tung pod (5 pod ton RAM nhat) ===")
    res = prom.pod_resources()
    for r in sorted(res.values(), key=lambda x: -x.memory_bytes)[:5]:
        print(f"  {r.pod:45s} cpu={r.cpu_cores:6.3f}  ram={r.memory_bytes/1024/1024:7.1f}Mi")

    print("\n=== Trang thai deployment ===")
    avail = prom.deployment_availability()
    bad = [d for d, v in avail.items() if v["available"] < v["desired"]]
    print(f"  tong {len(avail)} deployment, thieu ban chay: {bad or 'khong co'}")

    if not server:
        print("\nLOI: khong lay duoc RED phia server.")
        return 1
    print("\nTAT CA OK — prometheus_client.py doc duoc so lieu that.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
