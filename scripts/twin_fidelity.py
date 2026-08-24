"""Do TWIN FIDELITY — twin du doan dung ket qua production bao nhieu phan tram.

  python scripts/twin_fidelity.py --list
  python scripts/twin_fidelity.py --scenarios S4
  python scripts/twin_fidelity.py --scenarios S1,S4,S5
  python scripts/twin_fidelity.py --dry-run          # in ke hoach, khong dung toi cluster

Day la chi so 7 muc 8 KLTN.md. No tra loi cau hoi: co dang tin twin khong? Neu twin
noi mot hanh dong "tot len" ma production lai "xau di" thi ca kien truc twin-verified
sup do, vi agent se tin nham.

VI SAO PHAI THU CA HANH DONG SAI:
Neu chi thu hanh dong DUNG thi fidelity luon ra 100% mot cach vo nghia — hanh dong
dung chinh la phep nghich dao cua loi, ca hai moi truong deu khoi. Phep do chi co y
nghia khi twin phai PHAN BIET duoc hanh dong tot voi hanh dong vo ich. Vi vay moi
kich ban thu hai hanh dong:

  - hanh dong DUNG  : nam trong correct_actions cua file dap an
  - hanh dong SAI   : hop ly ve mat truc giac nhung khong sua duoc nguyen nhan

Fidelity = so lan twin va production ra CUNG mot phan quyet, chia cho tong so lan thu.

THOI GIAN: moi lan thu mat khoang 11 phut (cho 330s sau khi tiem, 300s sau khi chay
hanh dong). Moi kich ban co 2 hanh dong x 2 moi truong = 4 lan thu, cong thoi gian
dung va xoa twin, khoang 50 phut. Chay ca 3 kich ban la gan 2 tieng ruoi. Tinh vao
lich, dung de sat han.
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Console Windows mac dinh dung bang ma cp1252, in tieng Viet se vo va script chet.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src_thesis.agent.twin_manager import TwinManager
from src_thesis.agent.verifier import TwinVerifier, Verdict
from src_thesis.faults.injectors import FaultInjector
from src_thesis.k8s_client import K8sClient
from src_thesis.telemetry.prometheus_client import PrometheusClient

RESULTS_DIR = Path(__file__).resolve().parents[1] / "data" / "fidelity"

WAIT_AFTER_FAULT = 330      # nhu scenarios.yaml
WAIT_AFTER_ACTION = 300     # day mot cua so quan sat


@dataclass
class Trial:
    """Mot lan thu: mot kich ban, mot hanh dong, tren mot moi truong."""

    scenario: str
    action: str
    action_kind: str          # "dung" hoac "sai"
    environment: str          # "twin" hoac "production"
    verdict: str = ""
    reason: str = ""
    detail: dict = field(default_factory=dict)


# Ba kich ban co the do fidelity. S2 va S3 bi loai co chu dich:
#   S2 ha so ban sao ve 0 -> hanh dong dung la scale_up, hanh dong sai nao cung ra
#      "khong doi" vi service van chet, phep do khong phan biet duoc gi.
#   S3 xoa pod -> Kubernetes tu tao lai truoc khi do xong, khong con gi de sua.
SCENARIOS = {
    "S1": {
        "target": "productcatalogservice",
        "fault": "latency",
        "params": {"extra_latency": "6s"},
        "correct": ("rollback", "go bo bien EXTRA_LATENCY, tra service ve nhu cu"),
        "wrong": ("scale_up", "them mot ban sao — khong go duoc do tre chen vao "
                              "moi lan goi, nen khong sua duoc gi"),
    },
    "S4": {
        "target": "frontend",
        "fault": "cpu",
        "params": {"cpu": "10m"},
        "correct": ("adjust_resources", "tra tran CPU ve muc cu"),
        "wrong": ("restart_pod", "pod moi van mang dung tran CPU cu, khoi dong lai "
                                 "khong doi duoc gi"),
    },
    "S5": {
        "target": "productcatalogservice",
        "fault": "cpu",
        "params": {"cpu": "10m"},
        "correct": ("adjust_resources", "tra tran CPU ve muc cu"),
        "wrong": ("restart_pod", "pod moi van mang dung tran CPU cu"),
    },
}


class Runner:
    """Chay mot lan thu tren mot namespace bat ky."""

    def __init__(self, namespace: str, verifier: TwinVerifier):
        self.namespace = namespace
        self.k8s = K8sClient(namespace=namespace)
        self.injector = FaultInjector(k8s=self.k8s, namespace=namespace)
        self.verifier = verifier

    # ------------------------------------------------------------------

    def inject(self, spec: dict):
        target = spec["target"]
        if spec["fault"] == "latency":
            return self.injector.inject_latency(target, **spec["params"])
        if spec["fault"] == "cpu":
            return self.injector.inject_cpu_throttle(target, **spec["params"])
        raise ValueError(f"khong biet loai loi {spec['fault']}")

    def apply_action(self, action: str, spec: dict, fault) -> None:
        """Thi hanh mot hanh dong len namespace nay.

        Cac hanh dong deu di qua k8s_client, dung nhung ham da duoc kiem chung o
        phase 2. Khong viet duong tat rieng cho thi nghiem nay: duong tat se lech
        voi thu ma agent that su lam o phase 5, va con so fidelity se khong con noi
        ve he thong that.
        """
        target = spec["target"]
        if action == "rollback":
            self.k8s.unset_env(target, "EXTRA_LATENCY", namespace=self.namespace)
        elif action == "adjust_resources":
            args = fault.undo_args
            self.k8s.restore_cpu(target, args.get("old_cpu"),
                                 args.get("old_cpu_request"),
                                 namespace=self.namespace)
        elif action == "scale_up":
            current = self.k8s.get_replicas(target, namespace=self.namespace) or 1
            self.k8s.scale_deployment(target, current + 1, namespace=self.namespace)
        elif action == "restart_pod":
            self.k8s.restart_deployment(target, namespace=self.namespace)
        else:
            raise ValueError(f"khong biet hanh dong {action}")
        self.k8s.wait_ready(target, timeout=180, namespace=self.namespace)

    def undo_action(self, action: str, spec: dict) -> None:
        """Tra lai nhung gi hanh dong da doi, TRUOC khi hoan tac loi.

        Chi scale_up can hoan tac rieng. rollback va adjust_resources chinh la phep
        hoan tac loi nen khong phai lam gi them; restart_pod khong doi cau hinh.
        """
        if action == "scale_up":
            self.k8s.scale_deployment(spec["target"], 1, namespace=self.namespace)
            self.k8s.wait_ready(spec["target"], timeout=180, namespace=self.namespace)


def wait(seconds: int, label: str) -> None:
    print(f"    cho {seconds}s ({label})...", flush=True)
    remaining = seconds
    while remaining > 0:
        time.sleep(min(30, remaining))
        remaining -= 30
        if remaining > 0:
            print(f"      con {remaining}s", flush=True)


def run_trial(runner: Runner, sid: str, spec: dict, action: str,
              kind: str, environment: str) -> Trial:
    """Tiem loi, cho, chay hanh dong, cho, do, phan quyet, don sach."""
    print(f"\n  --- {sid} / {environment} / hanh dong {kind}: {action} ---", flush=True)
    fault = runner.inject(spec)
    try:
        wait(WAIT_AFTER_FAULT, "trieu chung on dinh")
        before = runner.verifier.measure()

        runner.apply_action(action, spec, fault)
        wait(WAIT_AFTER_ACTION, "day mot cua so quan sat")
        after = runner.verifier.measure()

        v: Verdict = runner.verifier.compare(before, after)
        print(f"    {v.describe()}", flush=True)
        return Trial(scenario=sid, action=action, action_kind=kind,
                     environment=environment, verdict=v.verdict,
                     reason=v.reason, detail=v.to_dict())
    finally:
        # Don sach DU CO LOI GIUA CHUNG. Bai hoc dat nhat cua phase 2: ba lan hong
        # ham hoan tac deu co chung dac diem nguy hiem la he thong VAN HONG trong
        # khi cong cu bao thanh cong.
        try:
            runner.undo_action(action, spec)
        finally:
            fault.revert(runner.k8s)


def main() -> int:
    ap = argparse.ArgumentParser(description="Do twin fidelity")
    ap.add_argument("--scenarios", default="S4",
                    help="danh sach cach nhau bang dau phay, vi du S1,S4,S5")
    ap.add_argument("--list", action="store_true", help="liet ke kich ban")
    ap.add_argument("--dry-run", action="store_true",
                    help="in ke hoach va thoi gian du kien, khong dung toi cluster")
    ap.add_argument("--load-seconds", type=int, default=330,
                    help="cho bo sinh tai trong twin am len bao nhieu giay")
    args = ap.parse_args()

    if args.list:
        for sid, spec in SCENARIOS.items():
            print(f"{sid}: {spec['fault']} vao {spec['target']}")
            print(f"   dung: {spec['correct'][0]:18s} {spec['correct'][1]}")
            print(f"   sai : {spec['wrong'][0]:18s} {spec['wrong'][1]}")
        return 0

    chosen = [s.strip().upper() for s in args.scenarios.split(",") if s.strip()]
    unknown = [s for s in chosen if s not in SCENARIOS]
    if unknown:
        print(f"khong biet kich ban: {', '.join(unknown)}. "
              f"Chon trong: {', '.join(SCENARIOS)}")
        return 1

    per_trial_min = (WAIT_AFTER_FAULT + WAIT_AFTER_ACTION) / 60 + 3
    total_min = len(chosen) * 4 * per_trial_min + len(chosen) * 6
    print(f"Kich ban: {', '.join(chosen)}")
    print(f"Moi kich ban 2 hanh dong x 2 moi truong = 4 lan thu")
    print(f"Uoc tinh: {total_min:.0f} phut")
    if args.dry_run:
        print("\n(dry-run, khong dung toi cluster)")
        return 0

    prom = PrometheusClient()
    tm = TwinManager()
    trials: list[Trial] = []

    # ------------------------------------------------------------------
    # PHAN 1 — chay tren TWIN
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PHAN 1: TWIN")
    print("=" * 70)
    print("  dung twin...", flush=True)
    st = tm.create_twin()
    print(f"  {st.describe()}", flush=True)
    tm.load_state()

    twin_verifier = TwinVerifier(prom=prom, namespace="twin")
    twin_runner = Runner("twin", twin_verifier)

    try:
        # Bo sinh tai chay TRONG namespace twin nen tu chay lien tuc, khong phai
        # bom tay qua port-forward nua. Chi phai cho no am len du mot cua so quan
        # sat truoc khi do lan dau, neu khong thi so lieu con lan luc twin chua co
        # luu luong.
        print(f"  cho {args.load_seconds}s cho bo sinh tai trong twin am len...",
              flush=True)
        wait(args.load_seconds, "bo sinh tai am len")
        warm = twin_verifier.measure()
        if not warm:
            print("KHONG DO DUOC GI TRONG TWIN. Kiem tra bo sinh tai:")
            print("  kubectl logs -n twin -l app=loadgenerator --tail=30")
            return 1
        print(f"  twin co luu luong tren {len(warm)} service, "
              f"frontend {warm.get('frontend', {}).get('request_rate', 0):.2f} req/s",
              flush=True)

        for sid in chosen:
            spec = SCENARIOS[sid]
            for kind, (action, _) in (("dung", spec["correct"]),
                                      ("sai", spec["wrong"])):
                trials.append(run_trial(twin_runner, sid, spec, action,
                                        kind, "twin"))
    finally:
        print("\n  xoa twin...", flush=True)
        tm.destroy_twin()
        print("  da xoa.", flush=True)

    # ------------------------------------------------------------------
    # PHAN 2 — chay tren PRODUCTION
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PHAN 2: PRODUCTION")
    print("=" * 70)
    # prefix="" vi ten service cua production khong mang tien to twin-.
    prod_verifier = TwinVerifier(prom=prom, namespace="default", prefix="")
    prod_runner = Runner("default", prod_verifier)

    for sid in chosen:
        spec = SCENARIOS[sid]
        for kind, (action, _) in (("dung", spec["correct"]),
                                  ("sai", spec["wrong"])):
            trials.append(run_trial(prod_runner, sid, spec, action,
                                    kind, "production"))

    # ------------------------------------------------------------------
    # SO SANH
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("TWIN FIDELITY")
    print("=" * 70)
    index = {(t.scenario, t.action, t.environment): t for t in trials}
    matches, total = 0, 0
    for sid in chosen:
        spec = SCENARIOS[sid]
        for kind, (action, _) in (("dung", spec["correct"]),
                                  ("sai", spec["wrong"])):
            tw = index.get((sid, action, "twin"))
            pr = index.get((sid, action, "production"))
            if not tw or not pr:
                continue
            total += 1
            same = tw.verdict == pr.verdict
            matches += 1 if same else 0
            print(f"  {sid} {kind:5s} {action:18s} twin={tw.verdict:10s} "
                  f"production={pr.verdict:10s} {'KHOP' if same else 'LECH'}")

    fidelity = matches / total if total else 0.0
    print(f"\n  TWIN FIDELITY: {fidelity * 100:.1f}%  ({matches}/{total} lan khop)")
    if fidelity < 1.0:
        print("  Fidelity duoi 100% la KET QUA NGHIEN CUU, khong phai that bai.")
        print("  Bao cao trung thuc con so nay va giai thich cho lech (muc 10 KLTN.md).")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_fidelity.json"
    out.write_text(json.dumps({
        "scenarios": chosen,
        "fidelity": fidelity,
        "matches": matches,
        "total": total,
        "trials": [t.__dict__ for t in trials],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nda ghi: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
