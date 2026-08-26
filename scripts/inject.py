"""Tiem loi bang tay va hoan tac.

  python scripts/inject.py --list                liet ke kich ban
  python scripts/inject.py S2                    tiem kich ban S2
  python scripts/inject.py S2 --watch            tiem, cho, roi chup snapshot so sanh
  python scripts/inject.py --revert              hoan tac loi dang tiem
  python scripts/inject.py --status              xem dang co loi nao khong

LUON chay --revert truoc khi tat may hoac chuyen sang kich ban khac.
Trang thai duoc ghi o data/runs/active_fault.json nen hoan tac duoc ca sau khi
dong terminal hay khoi dong lai may.
"""

import argparse
import sys
import time
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

from src_thesis.eval.preflight import wait_for_clean_baseline
from src_thesis.faults.injectors import (
    ACTIVE_FAULT_FILE,
    FaultInjector,
    load_active_fault,
    load_active_faults,
)
from src_thesis.faults.library import inject_scenario, load_scenarios
from src_thesis.k8s_client import K8sClient
from src_thesis.telemetry.snapshot import take_snapshot

# Phan nap va tiem kich ban da chuyen sang `src_thesis/faults/library.py`, dung
# chung voi bo chay 75 ca cua phase 6. Hai duong chay phai tiem giong het nhau,
# neu khong thi so lieu phase 6 khong so duoc voi cac lan chay tay da ghi trong
# docs/thesis-notes.md.


def cmd_list() -> int:
    for sid, s in load_scenarios().items():
        target = s.get("target", "nhieu service")
        print(f"{sid}  {s['fault']:9s} {target:24s} cho {s['wait_after_inject_s']}s")
        print(f"    {' '.join(s['description'].split())}")
    return 0


def cmd_status() -> int:
    faults = load_active_faults()
    if not faults:
        print("Khong co loi nao dang tiem. He thong sach.")
        return 0
    print(f"DANG CO {len(faults)} LOI CHUA HOAN TAC:")
    for active in faults:
        gt = active.ground_truth
        age = time.time() - gt.injected_at
        print(f"  {gt.fault_id}")
        print(f"    service dich : {gt.target_service}")
        print(f"    loai         : {gt.fault_type}  params={gt.params}")
        print(f"    tiem cach day: {age / 60:.1f} phut")
    print("  hoan tac tat ca: python scripts/inject.py --revert")
    return 1


def cmd_revert() -> int:
    faults = load_active_faults()
    if not faults:
        print("Khong co gi de hoan tac.")
        return 0
    # Hoan tac theo thu tu NGUOC lai voi luc tiem, giong nhu go chong sach.
    problems = 0
    for active in reversed(faults):
        k8s = K8sClient(namespace=active.namespace)
        target = active.ground_truth.target_service
        print(f"Dang hoan tac {active.ground_truth.fault_id}...")
        try:
            active.revert(k8s)
        except Exception as e:
            print(f"  LOI khi hoan tac: {e}")
            print(f"  Trang thai van con trong {ACTIVE_FAULT_FILE.name}, thu lai duoc.")
            problems += 1
            continue
        ok = k8s.wait_ready(target, timeout=180)
        print(f"  {target} san sang tro lai: {ok}")
        if not ok:
            print("  CANH BAO: chua san sang. Kiem tra: kubectl get pods")
            problems += 1
    if problems:
        return 1
    print("Da hoan tac xong tat ca.")
    return 0


def cmd_inject(sid: str, watch: bool) -> int:
    scenarios = load_scenarios()
    if sid not in scenarios:
        print(f"Khong co kich ban {sid}. Chay --list de xem danh sach.")
        return 1
    if load_active_faults():
        print("Dang co loi khac chua hoan tac. Chay --revert truoc.")
        return cmd_status()

    s = scenarios[sid]
    inj = FaultInjector()

    before = None
    if watch:
        before = wait_for_clean_baseline(f"{sid}-truoc")
        if before is None:
            return 1

    print(f"\nTiem {sid}: {s['fault']} vao {s.get('target')}")
    faults = inject_scenario(inj, s)
    if len(faults) > 1:
        for f in faults:
            print(f"  da tiem {f.ground_truth.fault_id}")
    else:
        gt = faults[0].ground_truth
        print(f"  fault_id      : {gt.fault_id}")
        print(f"  lan truyen dk : {', '.join(gt.expected_propagation) or '(khong)'}")
        print(f"  hanh dong dung: {', '.join(gt.correct_actions)} ({gt.correct_action_class})")

    print(f"\nDa ghi trang thai cu vao {ACTIVE_FAULT_FILE.name}")
    print("Hoan tac bat cu luc nao: python scripts/inject.py --revert")

    if not watch:
        return 0

    wait = int(s["wait_after_inject_s"])
    print(f"\nCho {wait}s cho trieu chung on dinh...")
    for remain in range(wait, 0, -30):
        time.sleep(min(30, remain))
        print(f"  con {max(0, remain - 30)}s")

    print("\nChup snapshot SAU khi tiem...")
    after = take_snapshot(
        label=f"{sid}-sau",
        baseline=before.runtime_graph if before else None,
    )
    print(f"  da ghi: {after.save().name}")
    print("\n" + "=" * 70)
    print(after.to_prompt_text())
    print("=" * 70)
    print(f"\nTrieu chung mong doi theo scenarios.yaml:")
    print(f"  {' '.join(s['expected_symptom'].split())}")
    print("\nSo sanh phan DEVIATIONS o tren voi dong tren. Khop = injector dat.")
    print("Nho hoan tac: python scripts/inject.py --revert")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Tiem loi va hoan tac")
    ap.add_argument("scenario", nargs="?", help="ma kich ban, vi du S2")
    ap.add_argument("--list", action="store_true", help="liet ke kich ban")
    ap.add_argument("--revert", action="store_true", help="hoan tac loi dang tiem")
    ap.add_argument("--status", action="store_true", help="xem co loi nao dang tiem khong")
    ap.add_argument("--watch", action="store_true",
                    help="chup snapshot truoc va sau, cho san giua hai lan")
    args = ap.parse_args()

    if args.list:
        return cmd_list()
    if args.revert:
        return cmd_revert()
    if args.status:
        return cmd_status()
    if args.scenario:
        return cmd_inject(args.scenario, args.watch)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
