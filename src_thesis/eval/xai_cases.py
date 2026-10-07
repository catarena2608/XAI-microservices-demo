"""Gom mọi lời giải thích đã lưu thành một danh sách ca để đánh giá XAI.

Ba nguồn, ba khuôn dạng khác nhau:

  1. Nhật ký agent (`data/agent_runs/*.json`, do `ReactAgent.run` ghi). Mỗi vòng có
     chẩn đoán là một ca. Từ 2026-10-07 mỗi vòng có `snapshot` và `prompt_text`;
     nhật ký cũ hơn chỉ có bảng RED rút gọn.
  2. Ca của bộ chạy phase 6 (`data/eval/<phiên>/*.json`, do `EvalRunner` ghi). Như
     nguồn 1, cộng thêm đáp án nằm sẵn trong file.
  3. Kết quả đánh giá XAI rời (`data/eval/*_xai_*.json`, do `scripts/eval_xai.py` ghi).
     Snapshot nằm ở data/runs/; bản ghi mới có `snapshot_file`, bản ghi cũ phải đoán
     theo tên kịch bản và được đánh dấu `snapshot_guessed`.

Mỗi ca là một dict cùng khuôn: id, source, explanation, snapshot (có thể None), red,
prompt_text, ground_truth (danh sách, có thể rỗng), llm, scenario. Phần đánh giá chỉ
đọc khuôn chung này, không cần biết ca đến từ đâu.
"""

from __future__ import annotations

import json
from pathlib import Path

from src_thesis.eval.metrics import action_correct, root_cause_correct

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "data" / "runs"
AGENT_DIR = ROOT / "data" / "agent_runs"
EVAL_DIR = ROOT / "data" / "eval"

# Dap an chi duoc gan cho mot vong agent neu loi duoc tiem TRONG khoang nay truoc
# luc quan sat. Khong co tran thi mot lan chay agent tren he thong sach se nhan dap
# an cua lan tiem loi hom truoc.
GT_MAX_AGE_S = 3600


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _ground_truths(runs_dir: Path = RUNS_DIR) -> list[dict]:
    out = []
    for p in sorted(runs_dir.glob("*groundtruth*.json")):
        d = _load(p)
        if d and "injected_at" in d:
            out.append(d)
    return sorted(out, key=lambda d: float(d["injected_at"]))


def _gt_before(truths: list[dict], t: float) -> list[dict]:
    prior = [g for g in truths if 0 <= t - float(g["injected_at"]) <= GT_MAX_AGE_S]
    return prior[-1:] if prior else []


def _rounds_to_cases(rounds: list[dict], source: str, base_id: str, llm: dict,
                     ground_truth: list[dict] | None, scenario: str,
                     truths: list[dict]) -> list[dict]:
    cases = []
    for r in rounds:
        exp = r.get("explanation")
        if not exp:
            continue
        gt = ground_truth if ground_truth is not None else _gt_before(
            truths, float(r.get("observed_at") or 0))
        cases.append({
            "id": f"{base_id}/r{r.get('round_no')}",
            "source": source,
            "round_no": r.get("round_no"),
            "explanation": exp,
            "snapshot": r.get("snapshot") or None,
            "red": r.get("red") or {},
            "prompt_text": r.get("prompt_text") or None,
            "ground_truth": gt,
            "llm": llm,
            "scenario": scenario,
        })
    return cases


def load_file(path: Path, truths: list[dict] | None = None) -> list[dict]:
    """Đọc một file bất kỳ trong ba khuôn dạng. File lạ thì trả về rỗng."""
    d = _load(path)
    if not isinstance(d, dict):
        return []
    truths = truths if truths is not None else _ground_truths()

    if "report" in d and "case_id" in d:                       # nguon 2
        rep = d.get("report") or {}
        return _rounds_to_cases(rep.get("rounds") or [], str(path), d["case_id"],
                                rep.get("llm") or {"model": d.get("model")},
                                d.get("ground_truth") or [], d.get("scenario", ""),
                                truths)
    if "rounds" in d and "run_id" in d:                         # nguon 1
        return _rounds_to_cases(d["rounds"], str(path), d["run_id"],
                                d.get("llm") or {}, None, "", truths)
    if "records" in d:                                          # nguon 3
        return _xai_eval_cases(d, path)
    return []


def _snapshot_index(runs_dir: Path = RUNS_DIR) -> tuple[dict, dict]:
    """(tên file -> snapshot, kịch bản -> snapshot "-sau" MỚI NHẤT)."""
    by_file, latest = {}, {}
    for p in sorted(runs_dir.glob("*.json")):
        if "groundtruth" in p.name or p.name == "active_fault.json":
            continue
        d = _load(p)
        if not d or not str(d.get("label", "")).endswith("-sau"):
            continue
        by_file[p.name] = d
        sid = d["label"][:-len("-sau")]
        if sid not in latest or d.get("taken_at", 0) > latest[sid].get("taken_at", 0):
            latest[sid] = d
    return by_file, latest


def _xai_eval_cases(d: dict, path: Path) -> list[dict]:
    by_file, latest = _snapshot_index()
    truths = _ground_truths()
    llm = {"provider": d.get("provider"), "model": d.get("model")}
    cases = []
    for i, rec in enumerate(d.get("records") or []):
        exp = (rec.get("result") or {}).get("explanation")
        if not rec.get("ok") or not exp:
            continue
        sid = rec.get("scenario", "")
        snap, guessed = None, False
        if rec.get("snapshot_file"):
            snap = by_file.get(rec["snapshot_file"])
        elif sid in latest:
            # Ban ghi truoc 2026-10-07 khong ghi snapshot nao. eval_xai.py luc do lay
            # snapshot MOI NHAT cua kich ban, nen doan giong vay — va danh dau la doan.
            snap, guessed = latest[sid], True
        gt = _gt_before(truths, float(snap.get("taken_at", 0))) if snap else []
        cases.append({
            "id": f"{path.name}/{sid}#{rec.get('run', i)}",
            "source": str(path),
            "round_no": 1,
            "explanation": exp,
            "snapshot": snap,
            "snapshot_guessed": guessed,
            "red": {},
            "prompt_text": None,
            "ground_truth": gt,
            # Diem da cham luc chay. Dung khi khong tim lai duoc file dap an.
            "recorded_score": rec.get("score") or {},
            "llm": llm,
            "scenario": sid,
        })
    return cases


def default_paths() -> list[Path]:
    paths = sorted(AGENT_DIR.glob("*.json"))
    paths += sorted(p for p in EVAL_DIR.glob("*/*.json") if p.name != "index.json")
    paths += sorted(EVAL_DIR.glob("*_xai_*.json"))
    return paths


def load_cases(paths: list[Path] | None = None) -> list[dict]:
    truths = _ground_truths()
    out: list[dict] = []
    for p in paths or default_paths():
        if p.is_dir():
            for q in sorted(p.glob("*.json")):
                if q.name != "index.json":
                    out += load_file(q, truths)
        else:
            out += load_file(p, truths)
    return out


def correctness(case: dict) -> dict | None:
    """Chẩn đoán của ca có đúng đáp án không. None nếu ca không có đáp án.

    Kịch bản kép có nhiều đáp án: chỉ đúng MỘT trong các service bị tiêm là đúng
    root cause, và hành động được tính đúng theo đáp án của chính service đó.
    """
    exp = case["explanation"]
    pred = exp.get("root_cause_service", "")
    actions = [a.get("action", "") for a in exp.get("proposed_actions") or []]
    gts = case.get("ground_truth") or []
    if gts:
        hit = [g for g in gts if root_cause_correct(pred, g.get("target_service", ""))]
        g = hit[0] if hit else gts[0]
        return {
            "root_correct": bool(hit),
            "fault_correct": exp.get("fault_type") == g.get("fault_type"),
            "action_correct": action_correct(actions, g.get("correct_actions", [])),
            "expected_root": g.get("target_service", ""),
        }
    rec = case.get("recorded_score") or {}
    if rec:
        return {
            "root_correct": bool(rec.get("root_cause_correct")),
            "fault_correct": bool(rec.get("fault_type_correct")),
            "action_correct": bool(rec.get("action_correct")),
            "expected_root": rec.get("expected_root", ""),
        }
    return None
