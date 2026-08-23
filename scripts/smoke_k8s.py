"""Kiểm tra k8s_client.py có thật sự điều khiển được cluster không.

Chạy: python scripts/smoke_k8s.py

Kịch bản: đọc trạng thái -> tắt cartservice -> xác nhận đã tắt -> bật lại ->
xác nhận đã sống. Đây chính là hành động `scale_up`/`scale_down` mà agent sẽ dùng
ở phase 5, nên chạy được script này nghĩa là đã có action đầu tiên.

Trong lúc cartservice tắt, trang giỏ hàng ở localhost:8080 sẽ báo lỗi. Đó là điều
mong đợi, script tự bật lại ở cuối.
"""

import sys
from pathlib import Path

# Cho phép `import src_thesis...` khi chạy script trực tiếp từ thư mục gốc repo.
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

TARGET = "cartservice"


def main() -> int:
    k8s = K8sClient(namespace="default")

    print("=== 1. Danh sach pod ===")
    pods = k8s.list_pods()
    for p in pods:
        co = "OK " if p.ready else "CHUA"
        print(f"  {co} {p.name:45s} {p.phase:10s} restart={p.restarts} {p.reason}")
    print(f"  tong: {len(pods)} pod")

    print("\n=== 2. Bang tra ClusterIP -> ten service ===")
    table = k8s.service_endpoint_map()
    for (ip, port), name in sorted(table.items(), key=lambda x: x[1]):
        print(f"  {ip:16s}:{port:<6d} -> {name}")
    print("  (day la bang ma phase 1 dung de doc server.address trong span client)")

    print("\n=== 3. Doc cau hinh hien tai ===")
    print(f"  replicas cua {TARGET}: {k8s.get_replicas(TARGET)}")
    print(f"  EXTRA_LATENCY cua productcatalogservice: "
          f"{k8s.get_env('productcatalogservice', 'EXTRA_LATENCY')}")
    print(f"  tran CPU cua {TARGET}: {k8s.get_cpu_limit(TARGET)}")

    print(f"\n=== 4. TAT {TARGET} (scale ve 0) ===")
    old = k8s.scale_deployment(TARGET, 0)
    print(f"  so replicas cu duoc luu lai de hoan tac: {old}")
    ok = k8s.wait_replicas(TARGET, 0, timeout=60)
    print(f"  da tat han: {ok}")
    if not ok:
        print("  LOI: qua 60 giay van chua tat, dung lai de khoi hong trang thai")
        return 1

    print(f"\n=== 5. BAT LAI {TARGET} (hoan tac) ===")
    k8s.scale_deployment(TARGET, old)
    ok = k8s.wait_replicas(TARGET, old, timeout=120)
    print(f"  da song lai voi {old} replicas: {ok}")
    if not ok:
        print(f"  LOI: chua song lai. Chay tay: kubectl scale deploy/{TARGET} --replicas={old}")
        return 1

    print("\n=== 6. Log 5 dong cuoi cua cartservice ===")
    for line in k8s.get_logs_of_deployment(TARGET, tail=5).splitlines():
        print(f"  {line}")

    print("\nTAT CA OK — k8s_client.py dieu khien duoc cluster.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
