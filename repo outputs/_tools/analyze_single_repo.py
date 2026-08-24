#!/usr/bin/env python3
"""
Single-repo "what did AI change?" analysis layer.

Reads the merged per-repo CSVs in a report folder, determines the AI-adoption
month (earliest signal from ai_agent_summary.csv), splits every monthly series
into pre / post adoption, and reports:
  * velocity delta   (mean monthly commits & net lines, pre vs post)
  * size growth      (ncloc growth rate, pre vs post)
  * quality slope    (code_smells, bugs, cognitive_complexity, tech debt: trend
                      per month, pre vs post) -> the paper's speed-vs-quality signal
  * issue health     (median resolution hours, open-bug backlog, pre vs post)
  * review automation (ai_review_share trend)

Writes SUMMARY.md (numerical, always) and plots/ (if matplotlib is available).
Descriptive before/after for one repo — NOT a causal effect (see caveat emitted
into SUMMARY.md).

Usage:
  python analyze_single_repo.py /path/to/repo_report/<owner_repo>
"""
import argparse
import csv
import sys
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAVE_MPL = True
except Exception:
    HAVE_MPL = False


def read_csv(path):
    p = Path(path)
    if not p.exists():
        return []
    with p.open() as f:
        return list(csv.DictReader(f))


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def slope(pairs):
    """Least-squares slope of y over sequential x index. pairs: list of (idx, y)."""
    pts = [(x, y) for x, y in pairs if y is not None]
    n = len(pts)
    if n < 2:
        return None
    sx = sum(x for x, _ in pts)
    sy = sum(y for _, y in pts)
    sxx = sum(x * x for x, _ in pts)
    sxy = sum(x * y for x, y in pts)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    return (n * sxy - sx * sy) / denom


def mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def split_by_month(rows, month_key, adoption):
    """Return (pre, post) lists of rows split at adoption month (inclusive post)."""
    pre, post = [], []
    for r in rows:
        m = r.get(month_key, "")
        if not m:
            continue
        (post if (adoption and m >= adoption) else pre).append(r)
    return pre, post


def series(rows, month_key, val_key):
    """Return list of (index, value) ordered by month."""
    ordered = sorted((r for r in rows if r.get(month_key)), key=lambda r: r[month_key])
    return [(i, fnum(r.get(val_key))) for i, r in enumerate(ordered)], [r[month_key] for r in ordered]


def find_adoption(report):
    """Adoption = the FIRST TRACKABLE AI ACTION OF ANY KIND (commit, merge, push,
    PR opened/merged, review, issue) — read from ai_adoption.csv when present.
    Falls back to the commit-only ai_agent_summary.csv. Returns (month, agents)
    where agents is a list of (agent, first_month, detail)."""
    adopt = read_csv(report / "ai_adoption.csv")
    if adopt:
        agents, earliest = [], None
        for r in adopt:
            if r.get("agent") == "__OVERALL__":
                earliest = (r.get("first_action_date") or "")[:7]
                continue
            fm = (r.get("first_action_date") or "")[:7]
            agents.append((r.get("agent", ""), fm,
                           f"{r.get('first_operation','')}·{r.get('operations_breakdown','')}"))
        if earliest:
            return earliest, sorted(agents, key=lambda a: a[1] or "9999")
    # fallback: commit-only summary
    summ = read_csv(report / "ai_agent_summary.csv")
    if not summ:
        return None, []
    agents, earliest = [], None
    for r in summ:
        fs = (r.get("first_seen") or "")[:7]
        agents.append((r.get("agent", ""), fs, f"{r.get('n_commits','')} commits"))
        if fs and (earliest is None or fs < earliest):
            earliest = fs
    return earliest, sorted(agents, key=lambda a: a[1] or "9999")


def fmt(v, nd=2, suffix=""):
    if v is None:
        return "n/a"
    return f"{v:.{nd}f}{suffix}"


def delta_line(label, pre, post, nd=2, suffix=""):
    d = (post - pre) if (pre is not None and post is not None) else None
    arrow = ""
    if d is not None:
        arrow = " ↑" if d > 0 else (" ↓" if d < 0 else " →")
    return (f"| {label} | {fmt(pre, nd, suffix)} | {fmt(post, nd, suffix)} | "
            f"{fmt(d, nd, suffix)}{arrow} |")


def _month_ord(m):
    """'YYYY-MM' -> integer month ordinal (year*12+month) for time-proportional x."""
    try:
        y, mo = m.split("-")[:2]
        return int(y) * 12 + (int(mo) - 1)
    except Exception:
        return None


def plot_series(months, values, adoption, title, ylabel, path, scale=1.0):
    """Time-aware monthly plot.

    - x is the real month ordinal, so gaps between non-consecutive months show as
      real gaps (no time distortion).
    - the connecting line is BROKEN wherever a month is missing, so we never draw
      a misleading straight interpolation across an empty stretch.
    - ticks are ~10 evenly spaced real months; values may be rescaled (e.g. hours→days).
    """
    if not HAVE_MPL:
        return
    pts = [(_month_ord(m), (v * scale)) for m, v in zip(months, values)
           if v is not None and _month_ord(m) is not None]
    pts.sort()
    if len(pts) < 2:
        return  # too sparse for a meaningful line
    base = _month_ord(months[0]) if _month_ord(months[0]) is not None else pts[0][0]
    lo = min(min(o for o, _ in pts), base)
    hi = max(o for o, _ in pts)

    fig, ax = plt.subplots(figsize=(9, 4))
    # Draw markers for every data point; connect only consecutive months.
    xs = [o - lo for o, _ in pts]
    ys = [v for _, v in pts]
    ax.scatter(xs, ys, s=18, zorder=3, color="#1f77b4")
    seg_x, seg_y = [xs[0]], [ys[0]]
    for i in range(1, len(pts)):
        if pts[i][0] - pts[i - 1][0] == 1:          # adjacent month → connect
            seg_x.append(xs[i]); seg_y.append(ys[i])
        else:                                        # gap → break the line
            ax.plot(seg_x, seg_y, color="#1f77b4", lw=1.4, zorder=2)
            seg_x, seg_y = [xs[i]], [ys[i]]
    ax.plot(seg_x, seg_y, color="#1f77b4", lw=1.4, zorder=2)

    # Evenly spaced, readable month ticks across the full time span.
    span = hi - lo
    step = max(1, round(span / 10))
    ticks = list(range(0, span + 1, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{(lo + t)//12:04d}-{(lo + t)%12 + 1:02d}" for t in ticks],
                       rotation=45, ha="right", fontsize=7)

    if adoption and _month_ord(adoption) is not None:
        ax.axvline(_month_ord(adoption) - lo, color="crimson", ls="--", lw=1.2,
                   label=f"AI adoption ({adoption})")
        ax.legend(fontsize=8)
    ax.set_title(title, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=8)
    ax.margins(x=0.02)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report", help="repo_report/<owner_repo> directory")
    ap.add_argument("--adoption", help="override adoption month YYYY-MM")
    args = ap.parse_args()
    report = Path(args.report)
    if not report.exists():
        sys.exit(f"No such report dir: {report}")
    plots = report / "plots"
    plots.mkdir(exist_ok=True)

    adoption, agents = find_adoption(report)
    if args.adoption:
        adoption = args.adoption

    velocity = read_csv(report / "velocity_monthly.csv")
    quality = read_csv(report / "quality_monthly.csv")
    issues = read_csv(report / "issue_monthly.csv")
    reviews = read_csv(report / "review_monthly.csv")

    L = []
    L.append(f"# {report.name} — AI-impact evaluation\n")
    if adoption:
        L.append(f"**AI-adoption month (split point): `{adoption}`** — defined as the "
                 f"*first trackable AI action of any kind* (commit, merge, push, PR "
                 f"open/merge, review, or issue), not the first config file.\n")
        L.append("Per-agent first action: " +
                 ", ".join(f"{a} ({fs})" for a, fs, _ in agents if fs) + "\n")
    else:
        L.append("**No AI usage detected** (no attributable commit, merge, PR, "
                 "review, or issue) — no adoption split; metrics below are "
                 "whole-history trends only.\n")

    # ---- AI operations breakdown ----
    ops = read_csv(report / "ai_operations.csv")
    if ops:
        ai_ops = [o for o in ops if o.get("category") in ("coding", "review")]
        by_op = {}
        by_agent_op = {}
        for o in ai_ops:
            by_op[o["operation"]] = by_op.get(o["operation"], 0) + 1
            key = (o["agent"], o["operation"])
            by_agent_op[key] = by_agent_op.get(key, 0) + 1
        L.append("\n## 0. AI operations detected (what did AI actually do?)\n")
        L.append("Counts of AI-attributed actions across **all branches**, by "
                 "operation type. `commit`=authored, `merge`/`pr_merged`=integrated, "
                 "`push`=applied by an agent identity, `pr_opened`/`pr_reviewed`/"
                 "`issue_*`=platform actions.\n")
        L.append("| Operation | count |")
        L.append("|---|--:|")
        for op in sorted(by_op, key=lambda k: -by_op[k]):
            L.append(f"| {op} | {by_op[op]} |")
        L.append("\nBy agent × operation:\n")
        L.append("| Agent | operation | count |")
        L.append("|---|---|--:|")
        for (agent, op), c in sorted(by_agent_op.items(), key=lambda kv: -kv[1]):
            L.append(f"| {agent} | {op} | {c} |")

    # ---- Velocity ----
    if velocity:
        pre, post = split_by_month(velocity, "month", adoption)
        L.append("\n## 1. Velocity (speed)\n")
        L.append("| Metric | pre | post | Δ |")
        L.append("|---|--:|--:|--:|")
        for key, lbl in [("commits", "mean monthly commits"),
                         ("lines_added", "mean monthly lines added"),
                         ("lines_removed", "mean monthly lines removed"),
                         ("contributors", "mean monthly contributors")]:
            L.append(delta_line(lbl, mean([fnum(r.get(key)) for r in pre]),
                                mean([fnum(r.get(key)) for r in post])))
        (idx, months) = series(velocity, "month", "commits")
        plot_series(months, [v for _, v in idx], adoption,
                    "Monthly commits", "commits", plots / "velocity_commits.png")

    # ---- Size + Quality ----
    if quality:
        pre, post = split_by_month(quality, "month", adoption)
        L.append("\n## 2. Code size & quality (SonarQube, monthly snapshots)\n")
        L.append("Quality is reported as **trend slope** (change per month): "
                 "positive slope on smells/bugs/debt = worsening.\n")
        L.append("| Metric | pre-slope | post-slope | Δ slope |")
        L.append("|---|--:|--:|--:|")
        # Each entry: (label, [candidate column names in priority order]).
        for lbl, keys in [("size (ncloc)", ["ncloc"]),
                          ("bugs", ["bugs"]),
                          ("vulnerabilities", ["vulnerabilities"]),
                          ("code smells", ["code_smells"]),
                          ("cognitive complexity", ["cognitive_complexity"]),
                          ("technical debt (remediation min)",
                           ["sqale_index", "technical_debt",
                            "software_quality_maintainability_remediation_effort"]),
                          ("duplication %", ["duplicated_lines_density"]),
                          ("comment density %", ["comment_lines_density"])]:
            def getv(r):
                for k in keys:
                    if r.get(k) not in (None, ""):
                        return fnum(r.get(k))
                return None
            pre_s = slope([(i, getv(r)) for i, r in
                           enumerate(sorted(pre, key=lambda x: x.get("month", "")))])
            post_s = slope([(i, getv(r)) for i, r in
                            enumerate(sorted(post, key=lambda x: x.get("month", "")))])
            L.append(delta_line(lbl, pre_s, post_s, nd=3))
        debt_key = next((k for k in ("sqale_index", "technical_debt",
                        "software_quality_maintainability_remediation_effort")
                        if quality and quality[0].get(k) not in (None,)), "sqale_index")
        for key, ylabel in [("code_smells", "code smells"),
                            ("cognitive_complexity", "cognitive complexity"),
                            (debt_key, "tech debt (min)"),
                            ("ncloc", "ncloc")]:
            idx, months = series(quality, "month", key)
            plot_series(months, [v for _, v in idx], adoption,
                        f"Monthly {ylabel}", ylabel, plots / f"quality_{key}.png")

    # ---- Issue health ----
    if issues:
        pre, post = split_by_month(issues, "month", adoption)
        L.append("\n## 3. Issue-resolution health\n")
        L.append("| Metric | pre | post | Δ |")
        L.append("|---|--:|--:|--:|")
        L.append(delta_line("median resolution (hours)",
                            mean([fnum(r.get("median_resolution_hours")) for r in pre]),
                            mean([fnum(r.get("median_resolution_hours")) for r in post]), nd=1))
        L.append(delta_line("mean monthly issues opened",
                            mean([fnum(r.get("opened")) for r in pre]),
                            mean([fnum(r.get("opened")) for r in post]), nd=1))
        L.append(delta_line("mean open bug backlog",
                            mean([fnum(r.get("open_bug_backlog")) for r in pre]),
                            mean([fnum(r.get("open_bug_backlog")) for r in post]), nd=1))
        idx, months = series(issues, "month", "median_resolution_hours")
        plot_series(months, [v for _, v in idx], adoption,
                    "Median issue resolution time (per close-month)", "days",
                    plots / "issue_resolution.png", scale=1.0 / 24.0)
        # Repo-wide issue statistics (percentiles, first response, AI actors).
        stats = read_csv(report / "issue_stats.csv")
        if stats:
            s = stats[0]
            def days(h):
                return f"{float(h)/24:.1f}d" if h not in (None, "") else "n/a"
            L.append("\n**Whole-repo issue statistics:**\n")
            L.append(f"- total={s.get('total_issues')} · open={s.get('open_issues')} · "
                     f"closed={s.get('closed_issues')} · close-rate={s.get('close_rate')}")
            L.append(f"- resolution: p25={days(s.get('resolution_hours_p25'))} · "
                     f"median={days(s.get('resolution_hours_median'))} · "
                     f"p75={days(s.get('resolution_hours_p75'))} · "
                     f"p90={days(s.get('resolution_hours_p90'))} · "
                     f"mean={days(s.get('resolution_hours_mean'))}")
            fr = s.get('first_response_hours_median')
            L.append(f"- first response: median={fr if fr not in (None,'') else 'n/a'}h · "
                     f"p90={s.get('first_response_hours_p90') or 'n/a'}h")
            L.append(f"- bugs={s.get('bug_issues')} (open {s.get('open_bug_issues')}) · "
                     f"AI-authored issues={s.get('ai_authored_issues')} · "
                     f"AI-closed issues={s.get('ai_closed_issues')}")

    # ---- Review automation ----
    if reviews:
        pre, post = split_by_month(reviews, "month", adoption)
        L.append("\n## 4. Code-review automation\n")
        ai_bots = read_csv(report / "reviews.csv")
        bots = sorted({r.get("ai_bot_name") for r in ai_bots
                       if r.get("is_ai_bot") in ("True", "true", True)} - {"", None})
        L.append(f"**AI review bots detected:** {', '.join(bots) if bots else 'NONE'}\n")
        L.append("| Metric | pre | post | Δ |")
        L.append("|---|--:|--:|--:|")
        L.append(delta_line("mean AI-review share",
                            mean([fnum(r.get("ai_review_share")) for r in pre]),
                            mean([fnum(r.get("ai_review_share")) for r in post]), nd=3))
        L.append(delta_line("mean monthly PRs opened",
                            mean([fnum(r.get("prs_opened")) for r in pre]),
                            mean([fnum(r.get("prs_opened")) for r in post]), nd=1))
        L.append(delta_line("median review comments/PR",
                            mean([fnum(r.get("median_review_comments")) for r in pre]),
                            mean([fnum(r.get("median_review_comments")) for r in post]), nd=1))

    # ---- Interpretation + caveat ----
    L.append("\n## Interpretation\n")
    if adoption:
        L.append("Read §1 (velocity) against §2 (quality slope): the paper's core "
                 "finding is *velocity rises but complexity/debt slope worsens after "
                 "adoption*. Compare the Δ columns to see whether this repo follows "
                 "that pattern or not.\n")
    L.append("\n> **Caveat — single repo, descriptive only.** This is a before/after "
             "comparison, not a causal effect. Confounds (project maturity, "
             "contributor influx, release cycles) are not controlled here. A causal "
             "estimate requires many AI-adopting repos vs matched controls fed to the "
             "study's DiD / panel notebooks — the per-repo CSVs in this folder are "
             "schema-compatible for exactly that scale-up.\n")

    # ---- SonarQube metric glossary (so §2 is self-explaining) ----
    L.append("\n## Appendix — what the SonarQube metrics mean\n")
    L.append("| Metric | Type | Plain-English meaning | Direction |")
    L.append("|---|---|---|---|")
    for metric, typ, meaning, direction in [
        ("ncloc", "size", "Non-comment lines of code — logic size, excluding blanks/comments.", "neutral (context)"),
        ("bugs", "reliability", "Code SonarQube judges demonstrably wrong — will misbehave at runtime.", "lower = better"),
        ("vulnerabilities", "security", "Security weaknesses (e.g. hard-coded secrets, injection).", "lower = better"),
        ("code_smells", "maintainability", "Working but poorly-structured code (dupes, long methods, dead code). Not bugs — maintainability debt.", "lower = better"),
        ("cognitive_complexity", "maintainability", "How hard the code is for a human to follow (nesting, branching). Rises even at constant size.", "lower = better"),
        ("technical_debt", "maintainability", "Estimated minutes to fix all code smells (SonarQube 'remediation effort').", "lower = better"),
        ("duplicated_lines_density", "maintainability", "% of lines that are copy-pasted duplicates.", "lower = better"),
        ("comment_lines_density", "documentation", "Comments as % of (code + comments). Very low or very high can both be smells.", "context"),
    ]:
        L.append(f"| `{metric}` | {typ} | {meaning} | {direction} |")
    L.append("\n*In §2, each metric is shown as a **slope** (change per month). A "
             "positive slope on smells/complexity/debt means quality is degrading "
             "over time; the pre-vs-post Δ shows whether AI adoption changed that rate. "
             "Raw counts rise with `ncloc`, so also read them per-1k-lines when comparing "
             "periods of different size.*\n")

    (report / "SUMMARY.md").write_text("\n".join(L))
    print(f"Wrote {report/'SUMMARY.md'}")
    if HAVE_MPL:
        print(f"Plots in {plots}/")
    else:
        print("matplotlib not installed — SUMMARY.md written without plots "
              "(pip install matplotlib to enable).")


if __name__ == "__main__":
    main()
