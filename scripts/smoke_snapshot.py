"""Chup mot anh trang thai he thong, in ra text cho LLM va ghi file JSON.

Chay: python scripts/smoke_snapshot.py

Day la cong chan cua phase 1: chay tren he thong khoe manh thi phan DEVIATIONS
phai la "none". Neu luc binh thuong ma da bao day loi thi tin hieu nay vo dung
cho XAI, phai sua truoc khi sang phase 2.
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

from src_thesis.telemetry.snapshot import take_snapshot


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    print(f"Dang chup snapshot '{label}'...")
    snap = take_snapshot(label=label)

    print(f"\nspan lay duoc : {snap.span_count}")
    print(f"cach dung canh: {snap.edge_sources}")
    print(f"ma bam trang thai: {snap.fingerprint()}")

    print("\n" + "=" * 70)
    print("DOAN TEXT SE NHOI CHO LLM")
    print("=" * 70)
    text = snap.to_prompt_text()
    print(text)
    print("=" * 70)
    print(f"do dai: {len(text)} ky tu, uoc luong {len(text) // 4} token")

    path = snap.save()
    print(f"\nda ghi: {path}")

    if snap.diff.is_clean():
        print("\nCONG CHAN PHASE 1: DAT — he thong khoe manh, diff sach.")
        return 0
    print("\nCONG CHAN PHASE 1: CHUA DAT — diff bao lech khi he thong dang khoe manh.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
