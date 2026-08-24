"""Cong cu dieu khien Digital Twin bang tay.

  python scripts/twin.py --status        xem twin dang the nao
  python scripts/twin.py --create        dung twin, cho toi khi san sang
  python scripts/twin.py --load-state    ap cau hinh production len twin
  python scripts/twin.py --destroy       xoa twin, tra RAM ve
  python scripts/twin.py --cycle 3       chay 3 vong dung-do-xoa lien tiep
  python scripts/twin.py --load 60       bom tai vao twin 60 giay qua port-forward
  python scripts/twin.py --measure       do RED cua twin ngay bay gio

`--cycle` chinh la CONG CHAN cua phase 4: phai chay du 3 vong lien tiep ma may
khong het RAM. Moi vong deu in RAM truoc va sau, de nhin ra ro ri neu co.
"""

import argparse
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

from src_thesis.agent.twin_manager import TwinManager, free_memory_mib
from src_thesis.agent.twin_loadgen import PortForward, TwinLoadGenerator
from src_thesis.agent.verifier import TwinVerifier


def show_memory(label: str) -> float:
    free = free_memory_mib()
    print(f"  RAM node con trong ({label}): {free:.0f} MiB")
    return free


def cmd_status(tm: TwinManager) -> int:
    print(tm.status().describe())
    show_memory("hien tai")
    return 0


def cmd_create(tm: TwinManager) -> int:
    before = show_memory("truoc khi dung")
    t0 = time.time()
    try:
        st = tm.create_twin()
    except (RuntimeError, TimeoutError) as e:
        print(f"KHONG DUNG DUOC: {e}")
        return 1
    print(f"  {st.describe()}")
    print(f"  dung xong sau {time.time() - t0:.0f}s")
    after = show_memory("sau khi dung")
    if before > 0 and after > 0:
        print(f"  twin an them: {before - after:.0f} MiB")
    return 0


def cmd_load_state(tm: TwinManager) -> int:
    applied = tm.load_state()
    if not applied:
        print("twin da khop voi production, khong phai doi gi.")
        return 0
    print("Da ap len twin:")
    for dep, change in sorted(applied.items()):
        for k, v in change.items():
            print(f"  {dep}: {k} = {v}")
    return 0


def cmd_destroy(tm: TwinManager) -> int:
    before = show_memory("truoc khi xoa")
    t0 = time.time()
    try:
        tm.destroy_twin()
    except (RuntimeError, TimeoutError) as e:
        print(f"KHONG XOA DUOC: {e}")
        return 1
    print(f"  xoa xong sau {time.time() - t0:.0f}s")
    after = show_memory("sau khi xoa")
    if before > 0 and after > 0:
        print(f"  tra lai: {after - before:.0f} MiB")
    return 0


def cmd_load(seconds: int, users: int) -> int:
    """Bom tai vao twin. Kiem tra duong ong tu Windows vao twin co thong khong."""
    st = TwinManager().status()
    if not st.all_ready:
        print(f"twin chua san sang: {st.describe()}")
        return 1
    try:
        with PortForward() as pf:
            print(f"  duong ham mo tai {pf.base_url}")
            stats = TwinLoadGenerator(pf.base_url, users=users).run(seconds)
    except (RuntimeError, TimeoutError) as e:
        print(f"KHONG BOM DUOC TAI: {e}")
        return 1
    print("  " + stats.describe())
    print(f"  ma trang thai: {dict(sorted(stats.status_counts.items()))}")
    if stats.requests == 0:
        print("KHONG CO REQUEST NAO DI QUA. Kiem tra frontend cua twin.")
        return 1
    # Ti le loi cao nghia la twin dung duoc nhung dang hong, khac han voi khong goi
    # duoc — phan biet hai truong hop nay de khoi di sua nham cho.
    if stats.error_rate > 0.5:
        print("CANH BAO: qua nua so request that bai. Twin dung duoc nhung dang hong.")
    return 0


def cmd_measure() -> int:
    """Do RED cua twin. Neu rong nghia la trace cua twin chua toi duoc collector."""
    red = TwinVerifier().measure()
    if not red:
        print("KHONG DO DUOC GI. Hai nguyen nhan thuong gap:")
        print("  1. Twin vua dung, chua du mot cua so quan sat 5 phut.")
        print("  2. COLLECTOR_SERVICE_ADDR khong tro dung ten day du qua namespace.")
        return 1
    for name in sorted(red):
        r = red[name]
        print(f"  {name:24s} {r['request_rate']:6.2f} req/s  "
              f"loi {r['error_rate'] * 100:5.1f}%  "
              f"p95 {r['p95_ms']:8.2f}ms  [{r['source']}]")
    return 0


def cmd_cycle(tm: TwinManager, times: int) -> int:
    """Cong chan phase 4: dung-do-xoa lien tiep ma khong het RAM."""
    baseline = free_memory_mib()
    print(f"RAM node con trong luc bat dau: {baseline:.0f} MiB")
    print("")
    for i in range(1, times + 1):
        print(f"=== VONG {i}/{times} ===")
        if cmd_create(tm) != 0:
            print(f"CONG CHAN PHASE 4: CHUA DAT - hong o vong {i} khi dung.")
            return 1
        cmd_load_state(tm)
        if cmd_destroy(tm) != 0:
            print(f"CONG CHAN PHASE 4: CHUA DAT - hong o vong {i} khi xoa.")
            return 1
        print("")

    final = free_memory_mib()
    print(f"RAM node con trong luc ket thuc: {final:.0f} MiB")
    # Ro ri RAM: sau khi xoa het twin, RAM phai ve gan muc ban dau. Cho lech 300 MiB
    # vi bo nho dem dia va metrics dao dong tu nhien.
    if baseline > 0 and final > 0 and baseline - final > 300:
        print(f"CANH BAO: thieu {baseline - final:.0f} MiB so voi luc bat dau. "
              f"Co the co thu gi do khong duoc don sach.")
    print(f"\nCONG CHAN PHASE 4: DAT - {times} vong dung-do-xoa lien tiep.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Dieu khien Digital Twin")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--create", action="store_true")
    g.add_argument("--load-state", action="store_true")
    g.add_argument("--destroy", action="store_true")
    g.add_argument("--cycle", type=int, metavar="N",
                   help="chay N vong dung-do-xoa lien tiep")
    g.add_argument("--load", type=int, metavar="GIAY",
                   help="bom tai vao twin trong bao nhieu giay")
    g.add_argument("--measure", action="store_true",
                   help="do RED cua twin ngay bay gio")
    ap.add_argument("--users", type=int, default=10,
                    help="so nguoi dung ao khi bom tai (mac dinh 10, bang production)")
    args = ap.parse_args()

    tm = TwinManager()
    if args.status:
        return cmd_status(tm)
    if args.create:
        return cmd_create(tm)
    if args.load_state:
        return cmd_load_state(tm)
    if args.destroy:
        return cmd_destroy(tm)
    if args.load:
        return cmd_load(args.load, args.users)
    if args.measure:
        return cmd_measure()
    return cmd_cycle(tm, args.cycle)


if __name__ == "__main__":
    raise SystemExit(main())
