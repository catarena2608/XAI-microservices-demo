"""Chay agent ReAct tren he thong that.

  python scripts/agent_run.py --dry-run           thu graph, KHONG dung toi cluster
  python scripts/agent_run.py                     chay che do twin_verified
  python scripts/agent_run.py --mode direct       bo qua twin (doi chung)
  python scripts/agent_run.py --mode xai_only     chi chan doan, khong hanh dong
  python scripts/agent_run.py --settle 60         rut ngan thoi gian cho (chi de thu)

BA CHE DO, de phase 6 so sanh (muc 8 KLTN.md):

  twin_verified  hanh dong `hard` phai qua twin xac nhan — day la de tai nay
  direct         hanh dong nao cung ap thang — DOI CHUNG, co y lam lieu
  xai_only       chi chan doan, khong hanh dong — do rieng chat luong XAI

CANH BAO: che do `direct` va `twin_verified` DOI THAT he thong production. Chay khi
dang co loi tiem vao thi agent se sua that. Muon xem agent nghi gi ma khong dong vao
gi thi dung `--mode xai_only` hoac `--dry-run`.

CANH BAO VE THOI GIAN: mac dinh cho 300 giay sau moi hanh dong, dung bang mot cua so
quan sat. Rut ngan bang `--settle` thi so lieu do lai con lan trang thai cu va agent
se ket luan nham rang hanh dong khong co tac dung — chi dung khi thu cho chay duoc,
dung dung cho so lieu bao cao.
"""

import argparse
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

from dotenv import load_dotenv

# Doc khoa API tu .env o thu muc goc repo. File nay KHONG duoc commit.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src_thesis.agent.react_loop import ReactAgent
from src_thesis.xai.reasoner import XaiReasoner


def describe_round(r: dict) -> None:
    print(f"\n--- VONG {r['round_no']} ---")
    print(f"  trang thai   : {r.get('diff_summary', '?')}")

    if not r.get("reasoning_ran"):
        print("  XAI          : khong chay — he thong khoe manh, khong can chan doan")
        return
    if not r.get("reasoning_ok"):
        print(f"  XAI          : THAT BAI — {r.get('reasoning_error', '')[:150]}")
        return

    exp = r.get("explanation") or {}
    print(f"  XAI chan doan: {exp.get('root_cause_service')} / "
          f"{exp.get('fault_type')} (tin cay {exp.get('confidence', 0):.2f})")
    for step in (exp.get("reasoning_chain") or [])[:3]:
        print(f"      {step}")

    act = r.get("chosen_action") or {}
    if act:
        print(f"  hanh dong    : {act.get('action')} tren {act.get('target')} "
              f"[{r.get('risk_class', '?')}]")

    if r.get("twin_used"):
        v = r.get("twin_verdict") or {}
        print(f"  twin         : {v.get('verdict', '?').upper()} — "
              f"{v.get('reason', '')[:120]}")

    res = r.get("action_result")
    if res:
        mark = "DA AP" if res.get("ok") else "KHONG AP DUOC"
        print(f"  ket qua      : {mark} — {res.get('detail', '')[:150]}")
    elif r.get("skipped_reason"):
        print(f"  ket qua      : BI CHAN — {r['skipped_reason'][:150]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Chay agent ReAct")
    ap.add_argument("--mode", default="twin_verified",
                    choices=["twin_verified", "direct", "xai_only"])
    ap.add_argument("--namespace", default="default")
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--settle", type=int, default=300,
                    help="giay cho sau moi hanh dong (mac dinh 300 = mot cua so)")
    ap.add_argument("--dry-run", action="store_true",
                    help="thu graph, khong dung toi cluster va khong goi LLM that")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--provider", default="openai",
                    choices=["openai", "groq"],
                    help="mac dinh openai: groq goi mien phi chi cho 8000 token moi "
                         "phut, ma prompt cua agent da khoang 6000 nen de dinh 413")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    if args.settle < 300 and not args.dry_run:
        print(f"CANH BAO: --settle {args.settle} ngan hon cua so quan sat 300 giay.")
        print("So lieu do lai se con lan trang thai cu. Chi dung de thu cho chay duoc.")
        print("")

    try:
        reasoner = XaiReasoner(provider=args.provider, model=args.model)
        agent = ReactAgent(
            mode=args.mode,
            namespace=args.namespace,
            max_rounds=args.max_rounds,
            settle_seconds=args.settle,
            dry_run=args.dry_run,
            reasoner=reasoner,
        )
    except RuntimeError as e:
        print(f"KHONG CHAY DUOC: {e}")
        return 1

    print(f"Che do: {args.mode}   namespace: {args.namespace}   "
          f"tran {args.max_rounds} vong")
    print(f"LLM: {reasoner.provider.name} / {reasoner.model}")
    if agent.baseline is not None:
        print(f"Anh nen: {agent.baseline_source}")
    else:
        # KHONG de canh bao nay thanh mot dong log mo nhat. Chay khong co nen thi
        # agent bo sot toan bo kich ban cham, va no bo sot MOT CACH IM LANG — bao
        # "he thong khoe manh" tren mot he thong dang hong.
        print("")
        print("CANH BAO NANG: khong co anh nen.")
        print(f"  {agent.baseline_source}")
        print("  Khong co nen thi chi bat duoc canh cham hon 500ms tuyet doi.")
        print("  So do that cua S1, S4, S5 deu duoi 500ms, nen agent se BO SOT ca ba")
        print("  va bao 'he thong khoe manh' tren mot he thong dang hong.")
        print("")
    if args.mode == "direct":
        print("CANH BAO: che do direct bo qua twin, moi hanh dong ap thang len "
              "production.")
    print("")

    # In ngay khi moi vong xong, khong doi het ca.
    report = agent.run(run_id=args.run_id, on_round=describe_round)

    print("\n" + "=" * 70)
    print("TONG KET")
    print("=" * 70)
    print(f"  so vong da dung     : {report['rounds_used']}/{report['max_rounds']}")
    print(f"  he thong cuoi cung  : "
          f"{'KHOE MANH' if report['healthy_at_end'] else 'VAN CON LECH'}")
    print(f"  ly do dung          : {report['stop_reason']}")
    print(f"  hanh dong da ap     : {report['actions_applied']}")
    print(f"  bi twin chan        : {report['actions_rejected_by_twin']}")
    print(f"  token               : {report['total_input_tokens']} vao, "
          f"{report['total_output_tokens']} ra")
    print(f"  thoi gian           : {report['took_s']:.0f}s")
    if report.get("saved_to"):
        print(f"\nda ghi: {report['saved_to']}")

    # Cong chan phase 5: file log phai du de dung lai toan bo cau chuyen mot ca.
    missing = [k for k in ("rounds", "mode", "stop_reason") if k not in report]
    if missing or not report["rounds"]:
        print(f"\nCONG CHAN PHASE 5: CHUA DAT — log thieu {missing or 'rounds'}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
