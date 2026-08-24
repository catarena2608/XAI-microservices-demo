"""Cham diem lai mot loat fidelity da chay, bang verifier hien tai.

  python scripts/rescore_fidelity.py                  # file moi nhat
  python scripts/rescore_fidelity.py <duong-dan.json>

VI SAO CAN: sua verifier xong thi cau hoi tu nhien la "con so cu sai vi thuoc do
hong, hay vi he thong that su nhu vay". Chay lai tren cluster mat hang gio. Nhung
file ket qua da luu du so lieu THO truoc va sau tung lan thu, nen cham lai duoc
ngay ma khong dung toi cluster.

Day cung la ly do `Verdict` luu ca `deltas` chu khong chi luu ket luan: ket luan
phu thuoc vao nguong, ma nguong con doi; so lieu tho thi khong doi.

CANH BAO KHI DOC KET QUA: cham lai chi sua duoc loi cua THUOC DO. No khong sua duoc
loi cua PHEP DO. Loat S4 dau tien chay twin voi 3 nguoi dung ao trong khi production
chay 10, nen so lieu twin cua loat do van khong dung de so sanh duoc, du cham lai
bang verifier nao. Phan twin phai chay lai tren cluster.
"""

import json
import sys
from pathlib import Path

# Console Windows mac dinh dung bang ma cp1252, in tieng Viet se vo va script chet.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src_thesis.agent.verifier import MIN_RATE_FOR_VERDICT, TwinVerifier

RESULTS_DIR = Path(__file__).resolve().parents[1] / "data" / "fidelity"


def rebuild(deltas: list[dict], side: str) -> dict[str, dict]:
    """Dung lai bang do tu cac delta da luu. `side` la "before" hoac "after"."""
    return {
        d["service"]: {
            "error_rate": d[f"error_{side}"],
            "p95_ms": d[f"p95_{side}"],
            "request_rate": d[f"rate_{side}"],
        }
        for d in deltas
    }


def main() -> int:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        files = sorted(RESULTS_DIR.glob("*_fidelity.json"))
        if not files:
            print("Khong tim thay file fidelity nao trong data/fidelity/")
            return 1
        path = files[-1]

    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"File: {path.name}")
    print(f"Nguong luu luong hien tai: {MIN_RATE_FOR_VERDICT} req/s")
    print("")

    v = TwinVerifier.__new__(TwinVerifier)   # chi dung compare(), khong can cluster
    rescored: dict[tuple, str] = {}

    print(f"{'kich ban':9s} {'moi truong':11s} {'hanh dong':18s} "
          f"{'cu':11s} {'moi':11s}")
    print("-" * 66)
    for t in data["trials"]:
        deltas = t.get("detail", {}).get("deltas", [])
        if not deltas:
            continue
        new = v.compare(rebuild(deltas, "before"), rebuild(deltas, "after"))
        rescored[(t["scenario"], t["action"], t["environment"])] = new.verdict
        mark = "" if new.verdict == t["verdict"] else "  <-- DOI"
        print(f"{t['scenario']:9s} {t['environment']:11s} {t['action']:18s} "
              f"{t['verdict']:11s} {new.verdict:11s}{mark}")

    print("")
    matches = total = 0
    for (sid, action, env) in list(rescored):
        if env != "twin":
            continue
        tw = rescored.get((sid, action, "twin"))
        pr = rescored.get((sid, action, "production"))
        if tw is None or pr is None:
            continue
        total += 1
        same = tw == pr
        matches += 1 if same else 0
        print(f"  {sid} {action:18s} twin={tw:11s} production={pr:11s} "
              f"{'KHOP' if same else 'LECH'}")

    if total:
        print(f"\n  FIDELITY SAU KHI CHAM LAI: {matches / total * 100:.1f}% "
              f"({matches}/{total})")
        print(f"  (con so cu: {data.get('fidelity', 0) * 100:.1f}%)")
    print("\nNho: cham lai chi sua duoc loi cua THUOC DO, khong sua duoc loi cua")
    print("PHEP DO. Neu loat cu chay twin voi tai khac production thi phan twin van")
    print("phai chay lai tren cluster.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
