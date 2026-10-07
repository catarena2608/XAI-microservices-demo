"""Danh gia LOI GIAI THICH cua XAI, khong phai do chinh xac cua chan doan.

  python scripts/xai_audit.py check                     E1 + kiem nhat quan tren moi ca da luu
  python scripts/xai_audit.py check data/agent_runs/x.json   chi mot file
  python scripts/xai_audit.py rules                     bo chan doan bang luat lam moc
  python scripts/xai_audit.py counterfactual --dry-run  xem truoc phep thu phan thuc, KHONG goi API
  python scripts/xai_audit.py counterfactual --repeats 3 --max-cases 10

Ba cau hoi, ba lenh:

  check           E1: moi con so, moi khang dinh trong evidence va reasoning_chain co
                  dung voi snapshot LLM da doc khong (soundness 0/1/2 theo Zytek et
                  al. 2024). Va: hanh dong de xuat co khop voi chinh loi giai thich
                  khong. Cuoi cung la BANG "DANG TIN": ca qua kiem co dung nhieu hon
                  ca khong qua khong — day moi la cau tra loi cho "XAI giup biet khi
                  nao nen tin".
  rules           Cung bo snapshot, chan doan bang luat viet tay. LLM co hon luat khong.
  counterfactual  E2: sua bang chung DA TRICH ve trang thai khoe, xem chan doan co doi
                  khong; so voi sua tin hieu KHONG trich, va voi goi lai y nguyen.
                  Lenh nay GOI API va TON TIEN — chay --dry-run truoc.

Doc file da luu, KHONG dung toi cluster. `check` va `rules` khong goi LLM.

DU LIEU: E1 va E2 can snapshot day du. Nhat ky agent tu 2026-10-07 co san. Nhat ky
cu hon chi kiem duoc mot phan (bang RED rut gon), va ket qua phase 3 can file snapshot
"-sau" trong data/runs/ — thu muc nay nam ngoai git.
"""

import argparse
import difflib
import json
import sys
import time
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

# Doc khoa API tu .env o thu muc goc repo. Chi lenh counterfactual can toi.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src_thesis.eval import counterfactual as CF
from src_thesis.eval.consistency import check_consistency
from src_thesis.eval.facts import build_fact_table, build_partial_table
from src_thesis.eval.grounding import check_explanation
from src_thesis.eval.replay import load_cases as load_snapshot_cases
from src_thesis.eval.rule_baseline import diagnose_by_rules
from src_thesis.eval.xai_cases import correctness, load_cases

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "xai_audit"
# Snapshot KHOE tren k3s, dung cluster voi phien 20261007-065802. E2 lay p95 / ti le loi
# luc khoe cua tung service tu day. data/runs/ nam ngoai git: may khac khong co file
# nay thi E2 dung HEALTHY_FALLBACK va bao ro.
HEALTHY_SNAPSHOT = (Path(__file__).resolve().parents[1] / "data" / "runs"
                    / "20261006-234811_smoke-k3s-moi.json")


def _save(kind: str, payload: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_{kind}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _paths(args) -> list[Path] | None:
    return [Path(p) for p in args.paths] if args.paths else None


def _frac(k: int, n: int) -> str:
    return f"{k}/{n} ({k / n * 100:.0f}%)" if n else "0/0"


# ======================================================================
# CHECK — E1 + nhat quan + bang dang tin
# ======================================================================

def audit_case(case: dict) -> dict:
    exp = case["explanation"]
    if case.get("snapshot"):
        table = build_fact_table(case["snapshot"], case.get("prompt_text"))
    elif case.get("red"):
        table = build_partial_table(case["red"])
    else:
        table = None
    e1 = check_explanation(exp, table).to_dict() if table is not None else None
    c = check_consistency(exp).to_dict()
    top = (exp.get("proposed_actions") or [{}])[0]
    return {
        "id": case["id"],
        "source": case["source"],
        "scenario": case.get("scenario", ""),
        "llm": case.get("llm") or {},
        "snapshot_guessed": case.get("snapshot_guessed", False),
        "root": exp.get("root_cause_service"),
        "fault_type": exp.get("fault_type"),
        "action": top.get("action"),
        "target": top.get("target"),
        "confidence": exp.get("confidence"),
        "correct": correctness(case),
        "e1": e1,
        "consistency": c,
    }


def passes(row: dict) -> bool | None:
    """Ca này có qua MỌI phép kiểm lời giải thích không. None = không kiểm được E1."""
    e1, c = row["e1"], row["consistency"]
    if not c["consistent"]:
        return False
    if not e1 or e1["soundness"] is None:
        return None
    return e1["soundness"] == 2 and e1.get("root_supported") is not False


def trust_rows(rows: list[dict], key, label: str) -> list[str]:
    """Độ chính xác của từng nhóm. Nhóm do `key(row)` quyết định."""
    groups: dict = {}
    for r in rows:
        if r["correct"] is None:
            continue
        groups.setdefault(key(r), []).append(r)
    lines = [f"  {label}"]
    for g in sorted(groups, key=lambda x: str(x)):
        rs = groups[g]
        root = sum(r["correct"]["root_correct"] for r in rs)
        fault = sum(r["correct"]["fault_correct"] for r in rs)
        act = sum(r["correct"]["action_correct"] for r in rs)
        lines.append(f"    {str(g):<22} n={len(rs):<4} root dung {_frac(root, len(rs)):<14} "
                     f"loai loi dung {_frac(fault, len(rs)):<14} "
                     f"hanh dong dung {_frac(act, len(rs))}")
    return lines


def cmd_check(args) -> int:
    cases = load_cases(_paths(args))
    if not cases:
        print("Khong tim thay loi giai thich nao. Truyen duong dan file, vi du "
              "data/agent_runs/<ten>.json")
        return 1
    rows = [audit_case(c) for c in cases]

    print(f"{len(rows)} loi giai thich tu {len({r['source'] for r in rows})} file\n")
    for r in rows:
        e1 = r["e1"]
        if e1 is None:
            e1s = "E1 -  (khong co snapshot)"
        else:
            c = e1["counts"]
            e1s = (f"E1 {e1['soundness'] if e1['soundness'] is not None else '-'}  "
                   f"so {c['grounded']}/{c['grounded'] + c['misattributed'] + c['unsupported']} "
                   f"dung" + ("" if e1["complete_table"] else " [bang rut gon]"))
        cs = ",".join(v["code"] for v in r["consistency"]["violations"]) or "nhat quan"
        ok = r["correct"]
        mark = "" if ok is None else ("  [dung]" if ok["root_correct"] else "  [SAI]")
        print(f"  {r['id'][:46]:<46} {r['root']}/{r['fault_type']} -> {r['action']}"
              f"{mark}")
        print(f"      {e1s} | {cs}")
        if args.verbose and e1:
            for n in e1["numbers"]:
                if n["status"] in ("misattributed", "unsupported"):
                    print(f"        SO {n['status']:<13} {n['value']:g} ({n['owner']}): "
                          f"{n['text'][:80]} -> {n['matched'] or n['note']}")
            for t in e1["texts"]:
                if t["status"] in ("misleading", "contradicted"):
                    print(f"        CHU {t['status']:<12} {t['rule']} ({t['owner']}): "
                          f"{t['text'][:80]} -> {t['note']}")
            for p in e1["preconditions"]:
                if p["status"] == "false":
                    print(f"        DIEU KIEN SAI {p['kind']} {p['target']}={p['value']} "
                          f"(that ra {p['actual']})")

    # ---------------- tong hop ----------------
    with_e1 = [r for r in rows if r["e1"] is not None]
    s = Counter(r["e1"]["soundness"] for r in with_e1)
    tot = Counter()
    for r in with_e1:
        tot.update(r["e1"]["counts"])
    judged = tot["grounded"] + tot["misattributed"] + tot["unsupported"]
    sup = [r["e1"]["root_supported"] for r in with_e1 if r["e1"]["root_supported"] is not None]
    comp = [r["e1"]["completeness"] for r in with_e1 if r["e1"].get("completeness")]
    codes = Counter(v["code"] for r in rows for v in r["consistency"]["violations"])
    incons = sum(1 for r in rows if not r["consistency"]["consistent"])

    print("\n" + "=" * 72)
    print("E1 — BAM DU LIEU (soundness theo Zytek et al. 2024)")
    print("=" * 72)
    print(f"  ca kiem duoc E1        : {len(with_e1)}/{len(rows)}")
    print(f"  soundness 2 / 1 / 0    : {s.get(2, 0)} / {s.get(1, 0)} / {s.get(0, 0)}"
          f"   (khong kiem duoc gi: {s.get(None, 0)})")
    print(f"  con so                 : {tot['numbers']} — dung {tot['grounded']}, "
          f"dung so sai cho {tot['misattributed']}, khong co trong prompt "
          f"{tot['unsupported']}, khong kiem duoc {tot['numbers_unchecked']}")
    if judged:
        print(f"  ti le so dung          : {_frac(tot['grounded'], judged)} trong so con so kiem duoc")
    print(f"  khang dinh dang chu    : {tot['texts']} — dung {tot['text_ok']}, gay hieu "
          f"nham {tot['misleading']}, trai su that {tot['contradicted']}, khong kiem "
          f"duoc {tot['texts_unchecked']}")
    print(f"  dieu kien tien quyet   : {tot['preconditions']} — dung {tot['precondition_ok']}, "
          f"sai {tot['precondition_false']}")
    if sup:
        print(f"  root cause co can cu   : {_frac(sum(sup), len(sup))} ca co it nhat mot "
              f"bang chung dung ve chinh root cause")
    if comp:
        cs = [c["cited_share"] for c in comp if c["cited_share"] is not None]
        rs = [c["root_cited_share"] for c in comp if c["root_cited_share"] is not None]
        if cs:
            print(f"  do day du (trich)      : trung binh {sum(cs) / len(cs) * 100:.0f}% "
                  f"dau hieu bat thuong duoc trich trong evidence")
        if rs:
            print(f"  do day du (root cause) : trung binh {sum(rs) / len(rs) * 100:.0f}% "
                  f"dau hieu cua chinh root cause duoc trich")

    print("\n" + "=" * 72)
    print("NHAT QUAN GIUA LOI GIAI THICH VA HANH DONG")
    print("=" * 72)
    print(f"  khong nhat quan        : {_frac(incons, len(rows))}")
    for code, n in codes.most_common():
        print(f"    {code:<24} {n}")

    rated = [r for r in rows if r["correct"] is not None]
    if rated:
        print("\n" + "=" * 72)
        print("BANG DANG TIN — phep kiem co tach duoc ca dung khoi ca sai khong")
        print("=" * 72)
        print("  (n nho thi doc so dem, dung doc phan tram)")
        for line in trust_rows(rated, passes, "theo E1 + nhat quan "
                               "(True = qua het, False = truot, None = khong kiem duoc E1)"):
            print(line)
        for line in trust_rows(rated, lambda r: r["consistency"]["consistent"],
                               "theo nhat quan rieng"):
            print(line)
        for line in trust_rows(rated, lambda r: (r["confidence"] or 0) >= 0.9,
                               "theo confidence LLM tu khai (True = tu 0.9 tro len)"):
            print(line)

    if args.no_save:
        return 0
    out = _save("check", {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "n": len(rows), "cases": rows})
    print(f"\nda ghi: {out}")
    return 0


# ======================================================================
# RULES — bo chan doan bang luat
# ======================================================================

def cmd_rules(args) -> int:
    snaps: dict[str, dict] = {}
    # Snapshot co dap an trong data/runs/ (phase 2, 3) — khong can loi giai thich LLM.
    for c in load_snapshot_cases():
        key = f"{c['snapshot'].get('label')}@{c['snapshot'].get('taken_at')}"
        snaps[key] = {"snapshot": c["snapshot"], "gt": [c["ground_truth"]],
                      "scenario": c["scenario"], "llm": []}
    # Snapshot trong nhat ky agent va ca phase 6, kem chan doan cua LLM tren CUNG anh.
    for c in load_cases(_paths(args)):
        if not c.get("snapshot"):
            continue
        key = f"{c['snapshot'].get('label')}@{c['snapshot'].get('taken_at')}"
        row = snaps.setdefault(key, {"snapshot": c["snapshot"],
                                     "gt": c.get("ground_truth") or [],
                                     "scenario": c.get("scenario", ""), "llm": []})
        if not row["gt"] and c.get("ground_truth"):
            row["gt"] = c["ground_truth"]
        row["llm"].append(correctness(c))

    if not snaps:
        print("Khong co snapshot nao. Can file '-sau' trong data/runs/ hoac nhat ky agent "
              "tu 2026-10-07 tro di (co truong snapshot).")
        return 1

    results = []
    self_check_bad = 0
    print(f"{len(snaps)} snapshot\n")
    for key, row in snaps.items():
        exp = diagnose_by_rules(row["snapshot"])
        case = {"explanation": exp, "ground_truth": row["gt"]}
        corr = correctness(case) if row["gt"] else None
        # Tu kiem bo cham E1: loi giai thich cua luat trich so TU bang su kien, nen
        # phai dat 2/2. Khong dat la grounding.py co loi.
        e1 = check_explanation(exp, build_fact_table(row["snapshot"]))
        if e1.soundness not in (2, None):
            self_check_bad += 1
        llm = [x for x in row["llm"] if x]
        llm_s = (f" | LLM root dung {_frac(sum(x['root_correct'] for x in llm), len(llm))}"
                 if llm else "")
        mark = "" if corr is None else (" [dung]" if corr["root_correct"] else " [SAI]")
        print(f"  {row['scenario'] or key[:30]:<12} luat: {exp['root_cause_service']}/"
              f"{exp['fault_type']} -> {exp['proposed_actions'][0]['action']}{mark}"
              f"  E1 {e1.soundness}{llm_s}")
        print(f"      {exp['reasoning_chain'][-1]}")
        results.append({"key": key, "scenario": row["scenario"], "rule": exp,
                        "correct": corr, "llm_correct": row["llm"],
                        "rule_e1": e1.to_dict()})

    rated = [r for r in results if r["correct"]]
    if rated:
        n = len(rated)
        print("\nLUAT tren snapshot co dap an:")
        print(f"  root cause dung : {_frac(sum(r['correct']['root_correct'] for r in rated), n)}")
        print(f"  loai loi dung   : {_frac(sum(r['correct']['fault_correct'] for r in rated), n)}")
        print(f"  hanh dong dung  : {_frac(sum(r['correct']['action_correct'] for r in rated), n)}")
        llm = [x for r in rated for x in r["llm_correct"] if x]
        if llm:
            print(f"LLM tren CUNG cac snapshot do ({len(llm)} lan chan doan):")
            print(f"  root cause dung : {_frac(sum(x['root_correct'] for x in llm), len(llm))}")
            print(f"  loai loi dung   : {_frac(sum(x['fault_correct'] for x in llm), len(llm))}")
            print(f"  hanh dong dung  : {_frac(sum(x['action_correct'] for x in llm), len(llm))}")
    print(f"\nTu kiem bo cham E1 tren loi giai thich cua luat: "
          f"{'DAT' if not self_check_bad else f'{self_check_bad} ca KHONG dat 2/2 — xem lai grounding.py'}")

    if not args.no_save:
        print(f"da ghi: {_save('rules', {'results': results})}")
    return 0 if not self_check_bad else 1


# ======================================================================
# COUNTERFACTUAL — E2
# ======================================================================

def _show_plan(case: dict, plan: dict) -> None:
    print(f"\n=== {case['id']}")
    print(f"  dau hieu bat thuong : {', '.join(plan['signals']) or '(khong co)'}")
    print(f"  da trich (evidence) : {', '.join(plan['cited']) or '(khong co)'}")
    print(f"  khong nhac toi      : {', '.join(plan['uncited']) or '(khong co)'}")
    if plan["mentioned_only_in_reasoning"]:
        print(f"  chi co trong reasoning, khong vao nhom nao: "
              f"{', '.join(plan['mentioned_only_in_reasoning'])}")
    original = plan["variants"][0]["prompt"].splitlines()
    for v in plan["variants"][1:]:
        print(f"  --- bien the {v['name']}: {'; '.join(v['notes'])}")
        changed = [ln for ln in difflib.unified_diff(original, v["prompt"].splitlines(),
                                                     lineterm="", n=0)
                   if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
        for ln in changed[:14]:
            print(f"      {ln[:110]}")
        if len(changed) > 14:
            print(f"      ... them {len(changed) - 14} dong")


def _healthy_red(path: str) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"CANH BAO: khong doc duoc anh khoe {path} ({e}). So RED se ve "
              f"HEALTHY_FALLBACK {CF.HEALTHY_FALLBACK['service_p95_ms']:g}ms / 0% loi.")
        return {}
    if d.get("diff") and any((d["diff"].get(k) or [])
                             for k in ("slow_edges", "error_edges", "missing_edges")):
        print(f"CANH BAO: anh khoe {path} co lech so voi thiet ke — kiem lai truoc khi dung.")
    print(f"anh khoe tham chieu cho so RED: {Path(path).name} ({d.get('taken_at_human', '?')})")
    return d.get("red") or {}


def cmd_counterfactual(args) -> int:
    cases = [c for c in load_cases(_paths(args)) if c.get("snapshot")]
    if not cases:
        print("Khong co ca nao co snapshot day du. E2 can nhat ky agent tu 2026-10-07 "
              "tro di, hoac ket qua eval_xai.py co file '-sau' trong data/runs/.")
        return 1
    if args.max_cases:
        cases = cases[:args.max_cases]

    healthy_red = _healthy_red(args.healthy)
    plans = [CF.plan_case(c["snapshot"], c["explanation"], c.get("prompt_text"),
                          args.per_signal, healthy_red) for c in cases]
    inexact = [c["id"] for c, p in zip(cases, plans) if p["replay_exact"] is False]
    if inexact:
        print(f"CANH BAO: {len(inexact)} ca dung lai prompt KHONG giong tung ky tu prompt "
              f"da gui: {', '.join(inexact)}. Bien the drop_* se khac prompt goc them "
              f"mot cho ngoai phan da sua.")
    n_calls = sum(len(p["variants"]) for p in plans) * args.repeats
    chars = sum(len(v["prompt"]) for p in plans for v in p["variants"]) * args.repeats
    print(f"{len(cases)} ca, {n_calls} lan goi LLM ({args.repeats} lan moi bien the), "
          f"khoang {chars // 4 + 3500 * n_calls} token vao")

    if args.dry_run:
        for c, p in zip(cases, plans):
            _show_plan(c, p)
        print("\n--dry-run: khong goi API. Bo co nay de chay that.")
        return 0

    from src_thesis.xai.reasoner import XaiReasoner
    try:
        reasoner = XaiReasoner(provider=args.provider, model=args.model, use_cache=False)
    except RuntimeError as e:
        print(f"KHONG CHAY DUOC: {e}")
        return 1
    models = {(c.get("llm") or {}).get("model") for c in cases} - {None}
    if models and reasoner.model not in models:
        print(f"CANH BAO: loi giai thich goc sinh boi {sorted(models)}, dang chay bang "
              f"{reasoner.model}. Doi ket qua co the do doi model.")

    def cost(rs: list[dict]) -> tuple[int, int, float]:
        tin = sum(x.get("input_tokens") or 0 for r in rs for v in r["variants"]
                  for x in v["calls"])
        tout = sum(x.get("output_tokens") or 0 for r in rs for v in r["variants"]
                   for x in v["calls"])
        p = reasoner.provider
        return tin, tout, (tin * p.input_price + tout * p.output_price) / 1_000_000

    results = []
    out = None
    meta = {"model": reasoner.model, "repeats": args.repeats,
            "healthy_reference": args.healthy if healthy_red else None}
    for i, c in enumerate(cases, 1):
        print(f"\n=== [{i}/{len(cases)}] {c['id']}")
        r = CF.run_case(reasoner, c["snapshot"], c["explanation"], c.get("prompt_text"),
                        repeats=args.repeats, per_signal=args.per_signal,
                        healthy_red=healthy_red)
        r["id"] = c["id"]
        r["correct"] = correctness(c)
        results.append(r)
        print(f"  necessity {r['necessity']}  sufficiency_violation "
              f"{r['sufficiency_violation']}  gap {r['faithfulness_gap']}  "
              f"(nhieu nen {r['noise_floor']})  | da ton {cost(results)[2]:.4f} USD")
        # Ghi dan sau moi ca: dut mang giua chung thi cac ca da tra tien van con.
        payload = {**meta, "partial": i < len(cases), "cases": results}
        if out is None:
            out = _save("counterfactual", payload)
        else:
            out.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                           encoding="utf-8")

    summary = CF.summarize(results)
    print("\n" + "=" * 72)
    print("E2 — PHEP THU PHAN THUC (ti le doi root cause, tinh tren tong so lan goi)")
    print("=" * 72)
    for name, rate in summary["flip_root"].items():
        print(f"  {name:<14} {rate}  ({summary['calls'][name]} lan goi)")
    print(f"  necessity             : {summary['necessity']}   (cao la tot)")
    print(f"  sufficiency_violation : {summary['sufficiency_violation']}   (gan 0 la tot)")
    print(f"  faithfulness_gap      : {summary['faithfulness_gap']}   (cao la tot)")
    dx = summary["diagnosis"]
    print("  phu — tinh ca loai loi (root HOAC fault_type doi):")
    for name, rate in dx["flip"].items():
        print(f"    {name:<14} {rate}")
    print(f"    necessity {dx['necessity']}  sufficiency_violation "
          f"{dx['sufficiency_violation']}  faithfulness_gap {dx['faithfulness_gap']}")
    print(f"  ca khong trich dau hieu nao   : {summary['cases_without_cited_signal']}")
    print(f"  ca khong co dau hieu bi bo qua: {summary['cases_without_uncited_signal']}")
    tin, tout, usd = cost(results)
    failed = sum(1 for r in results for v in r["variants"] for x in v["calls"]
                 if x.get("root") is None)
    print(f"  lan goi hong (khong ra loi giai thich) : {failed}")
    print(f"\nchi phi that: {tin} token vao, {tout} token ra, {usd:.4f} USD")
    payload = {**meta, "partial": False, "summary": summary,
               "usage": {"input_tokens": tin, "output_tokens": tout, "usd": round(usd, 5)},
               "cases": results}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"da ghi: {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Danh gia loi giai thich cua XAI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="E1 + nhat quan + bang dang tin")
    p.add_argument("paths", nargs="*", help="file hoac thu muc; de trong = moi nguon")
    p.add_argument("-v", "--verbose", action="store_true", help="in tung khang dinh sai")
    p.add_argument("--no-save", action="store_true")

    p = sub.add_parser("rules", help="bo chan doan bang luat lam moc")
    p.add_argument("paths", nargs="*")
    p.add_argument("--no-save", action="store_true")

    p = sub.add_parser("counterfactual", help="E2, GOI API")
    p.add_argument("paths", nargs="*")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--max-cases", type=int, default=None)
    p.add_argument("--per-signal", action="store_true",
                   help="them bien the bo TUNG dau hieu da trich mot")
    p.add_argument("--provider", default="openai", choices=["openai", "groq"])
    p.add_argument("--model", default=None)
    p.add_argument("--dry-run", action="store_true", help="chi in se sua gi, khong goi API")
    p.add_argument("--healthy", default=str(HEALTHY_SNAPSHOT),
                   help="snapshot khoe de lay p95 / ti le loi luc khoe cua tung service")

    args = ap.parse_args()
    return {"check": cmd_check, "rules": cmd_rules,
            "counterfactual": cmd_counterfactual}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
