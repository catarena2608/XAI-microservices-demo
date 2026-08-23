"""Danh gia rieng chat luong XAI, chua co agent.

  python scripts/eval_xai.py --estimate     uoc tinh token va chi phi, KHONG goi API
  python scripts/eval_xai.py --once S2      chay 1 lan cho 1 kich ban, xem ket qua
  python scripts/eval_xai.py --runs 5       chay day du 5 lan moi kich ban

Doc snapshot da luu trong data/runs/, KHONG dung toi cluster. Nghia la chay lai duoc
bat cu luc nao, ke ca khi da tat may ao.

Muc 8 KLTN.md yeu cau moi kich ban chay toi thieu 5 lan de co do lech chuan, vi LLM
khong on dinh. Vi vay --runs > 1 tu TAT cache: cache tra ve y het ket qua cu, do do
lech chuan tren cache thi luon ra 0.
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

from dotenv import load_dotenv

# Doc khoa API tu file .env o thu muc goc repo. File nay KHONG duoc commit
# (.gitignore da chan). Khong co dong nay thi phai tu dat bien moi truong moi lan
# mo terminal.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src_thesis.eval.metrics import aggregate, score_case
from src_thesis.eval.replay import load_cases
from src_thesis.xai.reasoner import DEFAULT_PROVIDER, PROVIDERS, XaiReasoner

RESULTS_DIR = Path(__file__).resolve().parents[1] / "data" / "eval"


def pick_cases(cases: list[dict], only: str | None) -> list[dict]:
    if only:
        return [c for c in cases if c["scenario"] == only]
    # Moi kich ban lay ban CHAY GAN NHAT. Cac lan chay hong o phase 2 van nam trong
    # data/runs/ nhung khong nen dua vao bang diem.
    latest: dict[str, dict] = {}
    for c in cases:
        latest[c["scenario"]] = c
    return [latest[k] for k in sorted(latest)]


def cmd_estimate(cases, provider, model, runs):
    """Uoc tinh khoi luong. KHONG goi API nen khong ton tien va khong can khoa."""
    p = PROVIDERS[provider]
    mdl = model or p.default_model
    print(f"Nha cung cap: {provider}   model: {mdl}")
    print(f"So kich ban: {len(cases)}   so lan moi kich ban: {runs}")
    print("")
    total_chars = 0
    for c in cases:
        n = len(c["prompt_text"])
        total_chars += n
        print(f"  {c['scenario']:6s} {n:6d} ky tu snapshot")

    # Uoc luong tho: khoang 4 ky tu mot token voi van ban tieng Anh nhieu chu so.
    # Con so THAT lay tu usage cua lan goi dau tien, dung con so do cho bao cao.
    overhead = 3500                       # system prompt + vi du few-shot
    tok_in = (total_chars + overhead * len(cases)) // 4
    tok_out = 900 * len(cases)
    cost = (tok_in * runs * p.input_price + tok_out * runs * p.output_price) / 1_000_000

    print("")
    print(f"Uoc tinh mot luot     : ~{tok_in} token vao, ~{tok_out} token ra")
    print(f"Ca loat {len(cases)} x {runs} lan  : ~{tok_in * runs} vao, ~{tok_out * runs} ra")
    if p.input_price == 0:
        print("Chi phi                : 0 USD (goi mien phi)")
        print("Luu y: goi mien phi co han muc moi phut va moi ngay.")
    else:
        print(f"Chi phi uoc tinh       : ~{cost:.3f} USD")
    print("")
    print("Day chi la uoc luong theo ky tu. So token that lay tu lan chay dau tien.")
    return 0


def run_cases(cases: list[dict], provider: str, model: str | None,
              runs: int, use_cache: bool) -> int:
    try:
        reasoner = XaiReasoner(provider=provider, model=model, use_cache=use_cache)
    except RuntimeError as e:
        print(f"KHONG CHAY DUOC: {e}")
        return 1
    all_scores = []
    per_scenario: dict[str, list] = {}
    records = []
    t0 = time.time()

    for c in cases:
        sid = c["scenario"]
        gt = c["ground_truth"]
        print(f"\n=== {sid}  (dap an: {gt['target_service']} / {gt['fault_type']}) ===")
        for i in range(1, runs + 1):
            res = reasoner.diagnose(c["prompt_text"])
            if not res.ok:
                print(f"  lan {i}: THAT BAI sau {res.attempts} lan thu — "
                      f"{res.errors[-1][:120] if res.errors else 'khong ro'}")
                records.append({"scenario": sid, "run": i, "ok": False,
                                "errors": res.errors})
                continue
            e = res.explanation
            sc = score_case(e, gt, sid)
            all_scores.append(sc)
            per_scenario.setdefault(sid, []).append(sc)
            records.append({
                "scenario": sid, "run": i, "ok": True,
                "score": sc.to_dict(), "result": res.to_dict(),
            })
            mark = "DUNG" if sc.root_cause_correct else "SAI "
            print(f"  lan {i}: {mark} doan '{e.root_cause_service}' "
                  f"({e.fault_type}, tin cay {e.confidence:.2f}), "
                  f"lan truyen {sc.propagation_jaccard:.2f}, "
                  f"hanh dong {'dung' if sc.action_correct else 'sai'}, "
                  f"{res.input_tokens + res.output_tokens} token")

    print("\n" + "=" * 70)
    print("KET QUA THEO KICH BAN")
    print("=" * 70)
    for sid in sorted(per_scenario):
        a = aggregate(per_scenario[sid])
        print(f"  {sid:6s} root cause {a.root_cause_accuracy * 100:5.1f}% "
              f"(sd {a.root_cause_std:.2f})   "
              f"lan truyen {a.propagation_mean:.2f} (sd {a.propagation_std:.2f})   "
              f"hanh dong {a.action_accuracy * 100:5.1f}%   "
              f"loai loi {a.fault_type_accuracy * 100:5.1f}%")

    overall = aggregate(all_scores)
    print("\nTONG HOP")
    print(f"  so ca cham diem     : {overall.n}")
    print(f"  ROOT CAUSE ACCURACY : {overall.root_cause_accuracy * 100:.1f}% "
          f"(do lech chuan {overall.root_cause_std:.3f})")
    print(f"  PROPAGATION ACCURACY: {overall.propagation_mean:.3f} "
          f"(do lech chuan {overall.propagation_std:.3f})")
    print(f"  hanh dong dung      : {overall.action_accuracy * 100:.1f}%")
    print(f"  loai loi dung       : {overall.fault_type_accuracy * 100:.1f}%")
    print(f"  tin cay trung binh  : {overall.mean_confidence:.2f}")
    print(f"  thoi gian chay      : {time.time() - t0:.0f}s")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{reasoner.provider.name}_{reasoner.model.replace('/', '_')}"
    out = RESULTS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_xai_{tag}.json"
    out.write_text(json.dumps({
        "provider": reasoner.provider.name, "model": reasoner.model,
        "runs_per_scenario": runs,
        "overall": overall.to_dict(),
        "per_scenario": {k: aggregate(v).to_dict() for k, v in per_scenario.items()},
        "records": records,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nda ghi: {out}")

    # Cong chan phase 3 theo KLTN-PLAN.md
    if overall.root_cause_accuracy < 0.5:
        print("\nCONG CHAN PHASE 3: CHUA DAT — root cause accuracy duoi 50%.")
        print("Sua prompt truoc khi xay agent len tren mot XAI doan bua.")
        return 1
    print("\nCONG CHAN PHASE 3: DAT")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Danh gia XAI tren snapshot da luu")
    ap.add_argument("--provider", default=DEFAULT_PROVIDER,
                    choices=sorted(PROVIDERS), help="groq (mien phi) hoac openai")
    ap.add_argument("--model", default=None, help="de trong thi dung model mac dinh")
    ap.add_argument("--runs", type=int, default=5, help="so lan chay moi kich ban")
    ap.add_argument("--once", metavar="SID", help="chay 1 lan cho 1 kich ban, vi du S2")
    ap.add_argument("--estimate", action="store_true",
                    help="chi uoc tinh token va chi phi, khong goi API")
    args = ap.parse_args()

    cases = pick_cases(load_cases(), args.once)
    if not cases:
        print("Khong tim thay ca nao trong data/runs/. Chay phase 2 truoc.")
        return 1

    if args.estimate:
        return cmd_estimate(cases, args.provider, args.model, args.runs)
    if args.once:
        return run_cases(cases, args.provider, args.model, 1, use_cache=True)
    # Nhieu lan chay thi phai tat cache, neu khong do lech chuan luon bang 0.
    return run_cases(cases, args.provider, args.model, args.runs, use_cache=False)


if __name__ == "__main__":
    raise SystemExit(main())
