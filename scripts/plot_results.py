"""Ve do thi cho chuong ket qua tu ket qua mot phien thi nghiem phase 6.

  python scripts/plot_results.py 20260825-0900
  python scripts/plot_results.py 20260825-0900 --out docs/figures

Sinh bon hinh PNG:

  mttr.png             MTTR ba che do, kem so ca KHONG hoi phuc ghi tren cot
  harmful.png          so hanh dong co hai va vo ich moi ca, ba che do
  root_cause.png       do chinh xac chan doan, kem thanh do lech chuan
  twin_fidelity.png    chi so 7, doc tu ket qua phase 4

QUY TAC VE DO THI CUA DE TAI NAY: khong bao gio ve mot con so trung binh ma giau
mat so ca bi cat cut. Che do `baseline` khong sua gi nen hau het cac ca cua no
khong hoi phuc; ve MTTR trung binh cua no ma khong ghi ro dieu do thi do thi noi
doi theo huong lam baseline trong TOT hon that.
"""

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

# Backend "Agg" ve thang ra file, khong can cua so do hoa. Bat buoc khi chay trong
# terminal hoac khi chay nen.
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src_thesis.eval import metrics as M

EVAL_DIR = Path(__file__).resolve().parents[1] / "data" / "eval"
FIDELITY_DIR = Path(__file__).resolve().parents[1] / "data" / "fidelity"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "docs" / "figures"

MODE_ORDER = ("baseline", "direct", "twin_verified")
MODE_LABEL = {"baseline": "Baseline\n(khong agent)",
              "direct": "Direct\n(sua thang)",
              "twin_verified": "Twin-verified\n(de tai nay)",
              "xai_only": "XAI only\n(chi chan doan)"}


def load_index(run_id: str) -> dict:
    path = EVAL_DIR / run_id / "index.json"
    if not path.exists():
        raise SystemExit(f"Khong co {path}. Chay scripts/eval_run.py truoc.")
    return json.loads(path.read_text(encoding="utf-8"))


def modes_present(index: dict) -> list[str]:
    by = index.get("by_mode") or {}
    out = [m for m in MODE_ORDER if m in by]
    out += [m for m in by if m not in out]
    return out


def plot_mttr(index: dict, out_dir: Path) -> Path:
    """Chi so 3. Cot la MTTR trung binh cua CAC CA HOI PHUC, so ca khong hoi phuc
    ghi thang tren dau cot — hai con so nay phai doc cung nhau moi co nghia."""
    by = index["by_mode"]
    modes = modes_present(index)
    values = [(by[m].get("mttr_mean_s") or 0.0) / 60 for m in modes]
    errors = [(by[m].get("mttr_std_s") or 0.0) / 60 for m in modes]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    bars = ax.bar([MODE_LABEL.get(m, m) for m in modes], values,
                  yerr=errors, capsize=5, color=["#999999", "#d95f02", "#1b9e77"])
    ax.set_ylabel("MTTR (phut) — chi tinh cac ca hoi phuc")
    ax.set_title("Chi so 3: thoi gian hoi phuc trung binh")

    for bar, m in zip(bars, modes):
        s = by[m]
        note = f"{s['n_recovered']}/{s['n_cases']} hoi phuc"
        if s["n_censored"]:
            note += f"\n{s['n_censored']} ca KHONG hoi phuc"
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(values) * 0.03 if values else 0.1,
                note, ha="center", va="bottom", fontsize=8)

    ax.margins(y=0.25)
    fig.tight_layout()
    path = out_dir / "mttr.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_harmful(index: dict, out_dir: Path) -> Path:
    """Chi so 4 va 5 — trai tim cua de tai. Ve canh nhau vi mot che do it hanh dong
    co hai nho viec khong lam gi ca thi phai nhin thay duoc dieu do."""
    by = index["by_mode"]
    modes = modes_present(index)
    harmful = [by[m]["harmful_per_case"] for m in modes]
    wasted = [by[m]["wasted_per_case"] for m in modes]
    blocked = [by[m]["rejected_by_twin_total"] / max(by[m]["n_cases"], 1)
               for m in modes]

    x = range(len(modes))
    width = 0.27
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.bar([i - width for i in x], harmful, width, label="co hai (chi so 4)",
           color="#d7191c")
    ax.bar(list(x), wasted, width, label="vo ich (chi so 5)", color="#fdae61")
    ax.bar([i + width for i in x], blocked, width, label="bi twin chan",
           color="#1b9e77")

    ax.set_xticks(list(x))
    ax.set_xticklabels([MODE_LABEL.get(m, m) for m in modes])
    ax.set_ylabel("so hanh dong moi ca")
    ax.set_title("Chi so 4 va 5: hanh dong co hai va hanh dong vo ich")
    ax.legend()
    fig.tight_layout()
    path = out_dir / "harmful.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_root_cause(index: dict, out_dir: Path) -> Path | None:
    """Chi so 1 va 2. Bo qua `baseline` vi che do do khong goi LLM."""
    by = index["by_mode"]
    modes = [m for m in modes_present(index)
             if by[m].get("root_cause_accuracy") is not None]
    if not modes:
        return None

    acc = [by[m]["root_cause_accuracy"] * 100 for m in modes]
    std = [(by[m].get("root_cause_std") or 0.0) * 100 for m in modes]
    prop = [(by[m].get("propagation_mean") or 0.0) * 100 for m in modes]

    x = range(len(modes))
    width = 0.35
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar([i - width / 2 for i in x], acc, width, yerr=std, capsize=5,
           label="chi so 1: root cause", color="#2c7fb8")
    ax.bar([i + width / 2 for i in x], prop, width,
           label="chi so 2: propagation (Jaccard)", color="#7fcdbb")
    ax.set_xticks(list(x))
    ax.set_xticklabels([MODE_LABEL.get(m, m) for m in modes])
    ax.set_ylabel("phan tram")
    ax.set_ylim(0, 105)
    ax.set_title("Chi so 1 va 2: chat luong chan doan cua XAI")
    ax.legend()
    fig.tight_layout()
    path = out_dir / "root_cause.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_fidelity(out_dir: Path) -> Path | None:
    """Chi so 7, do rieng o phase 4. Ghi ro so phep thu tren hinh: 100% tren 6 phep
    thu va 100% tren 60 phep thu la hai con so rat khac nhau."""
    files = sorted(FIDELITY_DIR.glob("*_fidelity.json"))
    if not files:
        return None
    rate, match, total = M.twin_fidelity(files[-1])
    if rate is None:
        return None

    fig, ax = plt.subplots(figsize=(5, 4.5))
    ax.bar(["khop", "lech"], [match, total - match],
           color=["#1b9e77", "#d7191c"])
    ax.set_ylabel("so phep thu")
    ax.set_title(f"Chi so 7: twin fidelity {rate * 100:.1f}% ({match}/{total})")
    ax.text(0.5, -0.18,
            f"nguon: {files[-1].name} — chi {total} phep thu, doc than trong",
            ha="center", transform=ax.transAxes, fontsize=8)
    fig.tight_layout()
    path = out_dir / "twin_fidelity.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Ve do thi ket qua phase 6")
    ap.add_argument("run_id", help="ma phien, vi du 20260825-0900")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    index = load_index(args.run_id)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    made = [plot_mttr(index, out_dir), plot_harmful(index, out_dir)]
    made.append(plot_root_cause(index, out_dir))
    made.append(plot_fidelity(out_dir))

    for p in made:
        print(f"da ve: {p}" if p else "bo qua mot hinh (thieu du lieu)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
