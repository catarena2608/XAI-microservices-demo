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

import yaml

from src_thesis.faults.injectors import (
    ACTIVE_FAULT_FILE,
    FaultInjector,
    load_active_fault,
    load_active_faults,
)
from src_thesis.k8s_client import K8sClient
from src_thesis.telemetry.snapshot import take_snapshot

SCENARIOS = Path(__file__).resolve().parents[1] / "src_thesis" / "faults" / "scenarios.yaml"


def load_scenarios() -> dict:
    data = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["scenarios"]}


def apply_one(inj: FaultInjector, fault: str, target: str, params: dict):
    if fault == "F1":
        return inj.inject_latency(target, params.get("extra_latency", "6s"))
    if fault == "F2":
        return inj.inject_crash(target)
    if fault == "F3":
        return inj.inject_pod_kill(target)
    if fault == "F4":
        return inj.inject_cpu_throttle(target, params.get("cpu", "10m"))
    raise ValueError(f"khong biet loai loi {fault}")


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


def wait_for_clean_baseline(sid: str, max_tries: int = 6, gap_s: int = 60):
    """Chup anh nen, lap lai cho toi khi diff sach.

    VI SAO CAN: cua so quan sat la 5 phut. Vua hoan tac kich ban truoc xong ma tiem
    ngay kich ban moi thi anh nen van con du am loi cu, va moi so lieu do duoc sau do
    deu lan lon hai lan tiem. Day la cai bay de mac nhat khi chay nhieu kich ban lien tiep.

    Cho toi da 6 phut. Van khong sach thi dung han, vi loi do la loi that chua sua.
    """
    for i in range(1, max_tries + 1):
        print(f"Chup anh NEN (lan {i}/{max_tries})...")
        snap = take_snapshot(label=f"{sid}-truoc")
        path = snap.save()
        if snap.diff.is_clean():
            print(f"  anh nen SACH: {path.name}")
            return snap
        print(f"  chua sach, con lech: {len(snap.diff.error_edges)} canh loi, "
              f"{len(snap.diff.slow_edges)} canh cham, "
              f"{len(snap.diff.missing_edges)} canh thieu")
        for f in (snap.diff.error_edges + snap.diff.slow_edges)[:3]:
            print(f"    {f.source} -> {f.target}: {f.detail}")
        if i < max_tries:
            print(f"  cho {gap_s}s roi thu lai...")
            time.sleep(gap_s)

    print("")
    print("DUNG LAI: he thong chua tro ve trang thai sach sau 6 phut cho.")
    print("Day khong phai du am cua kich ban truoc ma la loi that chua duoc sua.")
    print("Kiem tra: kubectl get pods  va  python scripts/smoke_snapshot.py")
    return None


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
        before = wait_for_clean_baseline(sid)
        if before is None:
            return 1

    print(f"\nTiem {sid}: {s['fault']} vao {s.get('target')}")
    if s["fault"] == "combined":
        for step in s["steps"]:
            f = apply_one(inj, step["fault"], step["target"], step.get("params") or {})
            print(f"  da tiem {f.ground_truth.fault_id}")
    else:
        f = apply_one(inj, s["fault"], s["target"], s.get("params") or {})
        gt = f.ground_truth
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
