"""Kiem tra mot hanh dong co that su sua duoc loi, hay chi lam tot len TAM THOI.

  python scripts/transient_check.py                       # S4 + restart_pod
  python scripts/transient_check.py --scenario S1 --action rollback
  python scripts/transient_check.py --dry-run             # in ke hoach, khong dung cluster

VI SAO CAN SCRIPT NAY:

Do fidelity ngay 2026-08-29 cho ket qua kho hieu: `restart_pod` tren S4 duoc cham
`better` o CA HAI moi truong. Nhung S4 ha tran CPU cua frontend xuong 10m, ma tran
CPU nam trong spec cua Deployment — xoa pod thi pod moi sinh ra van bi bop dung 10m.
Nguyen nhan goc con nguyen, nen khong the "tot len" that su duoc.

Gia thuyet: cai tot len la do XOA TRANG THAI TICH LUY. Pod cu da chay duoi tai voi
10m CPU nen hang doi don u toi p95 14 giay. Pod moi bat dau tu hang doi rong. Cua so
5 phut chup dung doan hoi phuc tam thoi do va doc thanh "da sua".

CACH KIEM: do BA lan thay vi hai.

  T0  sau khi tiem loi, truoc hanh dong
  T1  sau hanh dong mot cua so   -> day la lan do ma verifier hien tai dung
  T2  sau hanh dong hai cua so   -> lan nay moi tra loi duoc cau hoi

Neu T1 tot len ma T2 tut ve nhu cu thi cai tot len la tam thoi, va verifier dang bi
lua. Neu ca T1 lan T2 deu tot len thi hanh dong that su co tac dung, va thu can xem
lai la NHAN `correct_actions` trong file dap an chu khong phai verifier.

QUAN TRONG: chay tren PRODUCTION, khong dung twin. Cau hoi o day la ve ban chat cua
hanh dong, khong phai ve do trung thuc cua twin — va bo twin di thi bot mot bien.
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Console Windows mac dinh dung bang ma cp1252, in tieng Viet se vo va script chet.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src_thesis.agent.actions import ActionExecutor
from src_thesis.agent.verifier import WINDOW_SECONDS, TwinVerifier
from src_thesis.eval.preflight import wait_for_clean_baseline
from src_thesis.faults.injectors import FaultInjector, load_active_faults
from src_thesis.faults.library import inject_scenario, load_scenarios, wait_seconds
from src_thesis.k8s_client import K8sClient
from src_thesis.xai.schema import ProposedAction

RESULTS_DIR = Path(__file__).resolve().parents[1] / "data" / "fidelity"


def countdown(seconds: int, label: str) -> None:
    print(f"  cho {seconds}s ({label})...", flush=True)
    for remain in range(seconds, 0, -60):
        time.sleep(min(60, remain))
        left = max(0, remain - 60)
        if left:
            print(f"    con {left}s", flush=True)


def revert_all(executor: ActionExecutor, action_result) -> None:
    """Don theo thu tu NGUOC chieu tac dong: go hanh dong truoc, roi go loi da tiem.

    Thu tu nay lay tu runner.py cua phase 6. Go loi truoc thi hanh dong cua agent con
    lai tren he thong va ca sau bat dau tu mot trang thai khac ca truoc.
    """
    if action_result is not None and action_result.applied:
        print("  go hanh dong...", flush=True)
        try:
            undo = executor.undo(action_result)
            print(f"    {undo.detail}")
        except Exception as e:
            print(f"    LOI khi go hanh dong: {e}")

    faults = load_active_faults()
    for active in reversed(faults):
        k8s = K8sClient(namespace=active.namespace)
        print(f"  hoan tac {active.ground_truth.fault_id}...", flush=True)
        try:
            active.revert(k8s)
            ok = k8s.wait_ready(active.ground_truth.target_service, timeout=180)
            print(f"    {active.ground_truth.target_service} san sang: {ok}")
        except Exception as e:
            print(f"    LOI khi hoan tac: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Kiem tra hanh dong co tot len ben khong")
    ap.add_argument("--scenario", default="S4", help="ma kich ban, vi du S4")
    ap.add_argument("--action", default="restart_pod", help="hanh dong can kiem")
    ap.add_argument("--target", default=None,
                    help="de trong thi lay target cua kich ban")
    ap.add_argument("--window", type=int, default=WINDOW_SECONDS,
                    help=f"do dai mot cua so, mac dinh {WINDOW_SECONDS}s")
    ap.add_argument("--dry-run", action="store_true",
                    help="in ke hoach roi thoat, khong dung toi cluster")
    args = ap.parse_args()

    scenarios = load_scenarios()
    if args.scenario not in scenarios:
        print(f"Khong co kich ban {args.scenario}. Chon trong: {', '.join(scenarios)}")
        return 1
    spec = scenarios[args.scenario]
    target = args.target or spec.get("target")
    if not target:
        print(f"Kich ban {args.scenario} khong co target don le, phai dat --target.")
        return 1

    wait_inject = wait_seconds(spec)
    total = wait_inject + args.window * 2
    print(f"Kich ban : {args.scenario}  ({spec['fault']} vao {target})")
    print(f"Hanh dong: {args.action} tren {target}")
    print(f"Ke hoach : tiem -> cho {wait_inject}s -> do T0 -> hanh dong")
    print(f"           -> cho {args.window}s -> do T1 -> cho {args.window}s -> do T2")
    print(f"Uoc tinh : {total // 60} phut do, cong thoi gian cho nen sach va hoan tac")
    if args.dry_run:
        return 0

    if load_active_faults():
        print("\nDang co loi chua hoan tac. Chay: python scripts/inject.py --revert")
        return 1

    verifier = TwinVerifier(namespace="default")
    executor = ActionExecutor(namespace="default")
    action_result = None
    record: dict = {"scenario": args.scenario, "action": args.action,
                    "target": target, "environment": "production",
                    "window_s": args.window, "started_at": time.time()}

    try:
        base = wait_for_clean_baseline(f"{args.scenario}-transient-nen")
        if base is None:
            print("Khong cho duoc nen sach. Dung.")
            return 1

        print(f"\nTiem {args.scenario}...", flush=True)
        inject_scenario(FaultInjector(), spec)
        countdown(wait_inject, "cho trieu chung on dinh")

        print("\n=== T0: do TRUOC hanh dong ===", flush=True)
        t0 = verifier.measure()

        print(f"\nThi hanh {args.action} tren {target}...", flush=True)
        action_result = executor.apply(ProposedAction(
            action=args.action, target=target, risk_class="hard",
            rationale="kiem tra hanh dong co tot len ben khong"))
        print(f"  {action_result.detail}")
        if not action_result.applied:
            print("  hanh dong KHONG thi hanh duoc, dung lai.")
            return 1

        countdown(args.window, "cua so thu nhat")
        print("\n=== T1: do sau MOT cua so ===", flush=True)
        t1 = verifier.measure()

        countdown(args.window, "cua so thu hai")
        print("\n=== T2: do sau HAI cua so ===", flush=True)
        t2 = verifier.measure()

        v01 = verifier.compare(t0, t1)
        v02 = verifier.compare(t0, t2)
        v12 = verifier.compare(t1, t2)

        print("\n" + "=" * 70)
        print("KET QUA")
        print("=" * 70)
        for name, v in (("T0 -> T1  (verifier hien tai dung lan nay)", v01),
                        ("T0 -> T2  (sau hai cua so)", v02),
                        ("T1 -> T2  (co tut lai khong)", v12)):
            print(f"  {name:44s} {v.verdict}")
            print(f"      {v.reason}")

        # Ket luan. Chi phat bieu duoc khi T1 that su tot len; neu T1 da khong tot
        # len thi khong co gi de goi la tam thoi ca.
        if v01.verdict != "better":
            verdict = "khong_ket_luan"
            note = (f"T0->T1 ra '{v01.verdict}' chu khong phai 'better', nen khong co "
                    f"cai tot len nao de xet la ben hay tam thoi. Co the moi truong "
                    f"lan nay khac lan do fidelity.")
        elif v02.verdict == "better":
            verdict = "ben"
            note = ("Tot len sau CA HAI cua so. Hanh dong that su co tac dung, "
                    "verifier khong bi lua. Thu can xem lai la nhan correct_actions "
                    "trong file dap an.")
        else:
            verdict = "tam_thoi"
            note = (f"Tot len o cua so dau ({v01.verdict}) roi mat o cua so sau "
                    f"({v02.verdict}). Cai tot len la TAM THOI — verifier do mot cua "
                    f"so nen bi lua. Phai do xa hon hoac do hai lan cach nhau.")
        print(f"\n  KET LUAN: {verdict}")
        print(f"  {note}")

        record.update({
            "verdict_t0_t1": v01.to_dict() if hasattr(v01, "to_dict") else v01.verdict,
            "verdict_t0_t2": v02.to_dict() if hasattr(v02, "to_dict") else v02.verdict,
            "verdict_t1_t2": v12.to_dict() if hasattr(v12, "to_dict") else v12.verdict,
            "conclusion": verdict, "note": note,
            "measurements": {"t0": t0, "t1": t1, "t2": t2},
            "action_result": action_result.to_dict(),
        })
        return 0

    finally:
        print("\n=== DON DEP ===", flush=True)
        revert_all(executor, action_result)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / (time.strftime("%Y%m%d-%H%M%S")
                             + f"_transient_{args.scenario}_{args.action}.json")
        out.write_text(json.dumps(record, indent=2, ensure_ascii=False,
                                  default=str), encoding="utf-8")
        print(f"da ghi: {out}")


if __name__ == "__main__":
    raise SystemExit(main())
