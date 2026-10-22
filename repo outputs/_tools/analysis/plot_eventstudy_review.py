#!/usr/bin/env python3
"""Event-study box plots: every repo indexed to its own AI-adoption month.

Two alignments, because MOSIP had two distinct interventions six months apart:
  review  -- CodeRabbit, Nov 2025, org-wide. Balanced -10..+9 window.
  coding  -- Cursor / Codex / Claude Code, mid-2026. Dies after +2.

Size-varying metrics are expressed as a ratio to the repo's OWN pre-adoption
median (rel -6..-1), so 1.0 = baseline and the boxes show proportional change.
Without that, ncloc spanning 7.9k..356k across repos makes every box a picture
of between-repo scale rather than within-repo movement. Metrics that are
already rates (per-kloc densities, AI review share) are plotted raw.
"""
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

PANEL = "repo outputs/analytics/panel_ai_impact.csv"
OUT = "repo outputs/analytics"
MIN_REPOS = 8          # drop relative months thinner than this
BASE = (-6, -1)        # pre-adoption baseline window

def mord(s):
    s = s.astype(str)
    return s.str[:4].astype(int) * 12 + s.str[5:7].astype(int) - 1

def load():
    d = pd.read_csv(PANEL)
    d["mi"] = mord(d["month"])
    for c in ("commits", "ncloc", "cognitive_complexity", "code_smells",
              "technical_debt", "bugs", "ai_review_share", "prs_opened",
              "median_resolution_hours", "contributors"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    k = d["ncloc"] / 1000.0
    d["cx_per_kloc"] = d["cognitive_complexity"] / k
    d["smells_per_kloc"] = d["code_smells"] / k
    d["debt_per_kloc"] = d["technical_debt"] / k
    return d

def align(d, col):
    x = d[d[col].notna()].copy()
    x["rel"] = x["mi"] - mord(x[col])
    return x

def normalise(x, metric):
    """Ratio to each repo's own pre-adoption median."""
    out = []
    for repo, g in x.groupby("repo_name"):
        base = g[(g["rel"] >= BASE[0]) & (g["rel"] <= BASE[1])][metric].median()
        if not np.isfinite(base) or base == 0:
            continue
        gg = g.copy()
        gg["val"] = gg[metric] / base
        out.append(gg)
    return pd.concat(out) if out else pd.DataFrame()

# metric, label, normalise?, log axis?
METRICS = [
    ("commits",          "Commits / month\n(ratio to pre-adoption)",      True,  True),
    ("ncloc",            "Code size ncloc\n(ratio to pre-adoption)",      True,  False),
    ("cx_per_kloc",      "Cognitive complexity\nper 1k lines",            False, False),
    ("smells_per_kloc",  "Code smells\nper 1k lines",                     False, False),
    ("debt_per_kloc",    "Technical debt (min)\nper 1k lines",            False, False),
    ("ai_review_share",  "AI share of PR reviews",                        False, False),
]

def draw(x, lo, hi, title, fname, band_label):
    rels = [r for r in range(lo, hi + 1)]
    fig, axes = plt.subplots(2, 3, figsize=(16.5, 8.2))
    fig.patch.set_facecolor("white")
    for ax, (metric, label, do_norm, log) in zip(axes.ravel(), METRICS):
        src = normalise(x, metric) if do_norm else x.assign(val=x[metric])
        data, pos, ns = [], [], []
        for r in rels:
            v = src[(src["rel"] == r)]["val"].replace([np.inf, -np.inf], np.nan).dropna()
            if len(v) < MIN_REPOS:
                continue
            data.append(v.values); pos.append(r); ns.append(len(v))
        if not data:
            ax.set_visible(False); continue
        ax.axvspan(-0.45, 0.45, color="#B98BE8", alpha=0.55, zorder=0, lw=0)
        bp = ax.boxplot(data, positions=pos, widths=0.62, showfliers=False,
                        patch_artist=True, zorder=3)
        for b in bp["boxes"]:
            b.set(facecolor="white", edgecolor="#3A3A3A", linewidth=0.9)
        for k in ("whiskers", "caps"):
            for e in bp[k]:
                e.set(color="#3A3A3A", linewidth=0.9)
        for m in bp["medians"]:
            m.set(color="#111111", linewidth=1.7)
        if do_norm:
            ax.axhline(1.0, color="#888888", lw=0.8, ls=(0, (4, 3)), zorder=1)
        if log:
            ax.set_yscale("log")
            ax.yaxis.set_major_formatter(FuncFormatter(
                lambda v, _: ("%g" % v) if v >= 0.1 else "%.2g" % v))
        ax.set_xlabel("Month index relative to adoption", fontsize=10)
        ax.set_ylabel(label, fontsize=10)
        ax.set_xticks([r for r in pos if r % 2 == 0])
        ax.set_xticklabels([str(r) for r in pos if r % 2 == 0], fontsize=9)
        ax.tick_params(axis="y", labelsize=9)
        ax.grid(axis="y", color="#E6E6E6", lw=0.7, zorder=0)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color("#999999")
        ax.set_title("n = %d–%d repos" % (min(ns), max(ns)), fontsize=8.5,
                     color="#777777", loc="right", pad=4)
    fig.suptitle(title, fontsize=13, y=0.985)
    fig.text(0.5, 0.945, band_label, ha="center", fontsize=9.5, color="#6A3FA0")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    p = "%s/%s" % (OUT, fname)
    fig.savefig(p, dpi=170, facecolor="white")
    plt.close(fig)
    print("wrote", p)

def main():
    d = load()
    rev = align(d, "adoption_review")
    cod = align(d, "adoption_coding")
    draw(rev, -10, 9,
         "MOSIP: metrics indexed to each repository's AI code-review adoption (CodeRabbit)",
         "eventstudy_review.png",
         "purple band = adoption month (month 0) · 19 repositories, mostly Nov 2025")
    draw(cod, -10, 2,
         "MOSIP: metrics indexed to each repository's AI coding-agent adoption (Cursor / Codex / Claude Code)",
         "eventstudy_coding.png",
         "purple band = adoption month (month 0) · 19 repositories, mostly Jun 2026 · "
         "post-window ends at +2 for lack of data")

if __name__ == "__main__":
    main()
