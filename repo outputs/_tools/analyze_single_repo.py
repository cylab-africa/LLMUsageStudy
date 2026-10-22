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
from typing import Optional, Sequence

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAVE_MPL = True
except Exception:
    HAVE_MPL = False

MIN_PERIOD_MONTHS = 3
LOW_N_MARK = "†"
DEBT_KEYS = ("sqale_index", "technical_debt",
             "software_quality_maintainability_remediation_effort")


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


def slope(pairs: Sequence[tuple[int, Optional[float]]]) -> Optional[float]:
    """Least-squares slope of y over x, where x is a calendar-month offset.

    Callers must pass real month distances (see month_pairs), not positional
    indices: a 4-month hole in the series has to cost 4 steps, otherwise the
    slope silently reports "per observation" while claiming "per month".
    """
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


def mean(vals: Sequence[Optional[float]]) -> Optional[float]:
    nums = [v for v in vals if v is not None]
    return sum(nums) / len(nums) if nums else None


def n_valid(vals: Sequence[Optional[float]]) -> int:
    """Count of usable monthly observations behind a reported figure."""
    return sum(1 for v in vals if v is not None)


def split_by_month(rows: Sequence[dict], month_key: str,
                   adoption: Optional[str]) -> tuple[list[dict], list[dict]]:
    """Split rows at the adoption month (the adoption month itself is post).

    With no adoption month there is nothing to split on, so every row is
    returned as one whole-history period in `pre` and `post` is empty. Callers
    must then render a single whole-history column (MetricTable(split=False)):
    a pre/post table whose post cells all read "n/a" invites the reader to see
    a before/after comparison that was never made.
    """
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


def adoption_month_of(row: dict) -> str:
    """YYYY-MM of an ai_adoption.csv row, taken from the UTC column.

    build_ai_operations picks the earliest row by true UTC instant but records
    `first_action_date` verbatim (git writes a local offset, the GitHub API
    writes Zulu). Slicing that raw string yields the LOCAL month of the
    UTC-earliest action, which can be a month later than the earliest action in
    ai_operations.csv — so read `first_action_date_utc`, and fall back only for
    report dirs written before that column existed.
    """
    return ((row.get("first_action_date_utc")
             or row.get("first_action_date") or "")[:7])


def adoption_by_category(report) -> tuple:
    """Earliest adoption month per category, as (coding, review).

    These are two different interventions and must not be merged. An AI review
    bot comments on code humans wrote; a coding agent writes it. In this cohort
    they are a median of 7 months apart, so a single "first AI action" split
    point attributes code-generation effects to a review-bot date.
    """
    coding = review = None
    for r in read_csv(report / "ai_adoption.csv"):
        if r.get("agent") == "__OVERALL__":
            continue
        m = adoption_month_of(r)
        if not m:
            continue
        cat = r.get("category")
        if cat == "coding":
            coding = m if coding is None else min(coding, m)
        elif cat == "review":
            review = m if review is None else min(review, m)
    return coding, review


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
                earliest = adoption_month_of(r)
                continue
            fm = adoption_month_of(r)
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


def fmt(v: Optional[float], nd: int = 2, suffix: str = "",
        low_n: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{nd}f}{suffix}{LOW_N_MARK if low_n else ''}"


def underpowered(n: int) -> bool:
    """True when a figure exists but rests on fewer than MIN_PERIOD_MONTHS."""
    return 0 < n < MIN_PERIOD_MONTHS


def delta_line(label: str, pre: Optional[float], post: Optional[float],
               n_pre: int, n_post: int, nd: int = 2, suffix: str = "",
               split: bool = True) -> str:
    if not split:
        return f"| {label} | {fmt(pre, nd, suffix, underpowered(n_pre))} | {n_pre} |"
    d = (post - pre) if (pre is not None and post is not None) else None
    arrow = ""
    if d is not None:
        arrow = " ↑" if d > 0 else (" ↓" if d < 0 else " →")
    return (f"| {label} | {fmt(pre, nd, suffix, underpowered(n_pre))} | "
            f"{fmt(post, nd, suffix, underpowered(n_post))} | "
            f"{fmt(d, nd, suffix)}{arrow} | {n_pre}/{n_post} |")


class MetricTable:
    """A pre/post metric table that degrades to one whole-history column.

    Every row carries the number of months actually behind it, and any figure
    resting on fewer than MIN_PERIOD_MONTHS is marked and named in a warning
    under the table — a 3-point post-slope must not read like a 30-point one.
    """

    def __init__(self, split: bool, pre_hdr: str = "pre",
                 post_hdr: str = "post", delta_hdr: str = "Δ",
                 whole_hdr: str = "whole history") -> None:
        self.split = split
        self.pre_hdr = pre_hdr
        self.post_hdr = post_hdr
        self.delta_hdr = delta_hdr
        self.whole_hdr = whole_hdr
        self.rows: list[str] = []
        self.low: list[tuple[str, str, int]] = []

    def add(self, label: str, pre: Optional[float], post: Optional[float],
            n_pre: int, n_post: int, nd: int = 2, suffix: str = "") -> None:
        self.rows.append(delta_line(label, pre, post, n_pre, n_post, nd,
                                    suffix, self.split))
        if underpowered(n_pre):
            self.low.append((label, self.pre_hdr if self.split else "", n_pre))
        if self.split and underpowered(n_post):
            self.low.append((label, self.post_hdr, n_post))

    def _warning(self) -> str:
        groups: dict[tuple[str, int], list[str]] = {}
        for label, period, n in self.low:
            groups.setdefault((period, n), []).append(label)
        parts = []
        for (period, n), labels in groups.items():
            names = ("all metrics" if len(labels) == len(self.rows)
                     else ", ".join(labels))
            parts.append(f"{names} ({period} n={n})" if period
                         else f"{names} (n={n})")
        return (f"> ⚠ **Underpowered ({LOW_N_MARK})** — fewer than "
                f"{MIN_PERIOD_MONTHS} months of data behind "
                + "; ".join(parts) +
                ". Read those as indicative only, not as a trend.")

    def render(self) -> list[str]:
        if self.split:
            out = [f"| Metric | {self.pre_hdr} | {self.post_hdr} | "
                   f"{self.delta_hdr} | n months (pre/post) |",
                   "|---|--:|--:|--:|--:|"]
        else:
            out = [f"| Metric | {self.whole_hdr} | n months |", "|---|--:|--:|"]
        out.extend(self.rows)
        if self.low:
            out.append("")
            out.append(self._warning())
        return out


def mean_table(pre: Sequence[dict], post: Sequence[dict],
               specs: Sequence[tuple[str, str, int]],
               split: bool) -> MetricTable:
    """Mean-per-month table over (column, label, decimals) specs."""
    tbl = MetricTable(split)
    for key, lbl, nd in specs:
        pre_v = [fnum(r.get(key)) for r in pre]
        post_v = [fnum(r.get(key)) for r in post]
        tbl.add(lbl, mean(pre_v), mean(post_v), n_valid(pre_v),
                n_valid(post_v), nd)
    return tbl


def _month_ord(m: str) -> Optional[int]:
    """'YYYY-MM' -> integer month ordinal (year*12+month) for time-proportional x."""
    try:
        y, mo = m.split("-")[:2]
        return int(y) * 12 + (int(mo) - 1)
    except Exception:
        return None


def first_val(row: dict, keys: Sequence[str]) -> Optional[float]:
    """Value of the first of `keys` this row actually populates."""
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return fnum(v)
    return None


def month_pairs(rows: Sequence[dict], keys: Sequence[str],
                month_key: str = "month"
                ) -> list[tuple[int, Optional[float]]]:
    """Time-proportional (x, y) points for slope(), x = months since the first
    month of this period. Months absent from the CSV (no commits, or a skipped
    snapshot) stay absent, so the gap they leave is real distance on x."""
    pts = []
    for r in rows:
        o = _month_ord(r.get(month_key, "") or "")
        if o is None:
            continue
        pts.append((o, first_val(r, keys)))
    if not pts:
        return []
    pts.sort(key=lambda p: p[0])
    base = pts[0][0]
    return [(o - base, y) for o, y in pts]


def plot_series(months, values, adoption, title, ylabel, path, scale=1.0,
                review=None, adoption_label="AI adoption"):
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

    drew = False
    # Review-bot adoption first, so the coding-agent line sits on top of it when
    # a repo adopted both in the same month.
    if review and _month_ord(review) is not None:
        ax.axvline(_month_ord(review) - lo, color="#2C5C4C", ls=(0, (5, 3)),
                   lw=1.2, label=f"AI review bot ({review})")
        drew = True
    if adoption and _month_ord(adoption) is not None:
        ax.axvline(_month_ord(adoption) - lo, color="crimson", ls="--", lw=1.4,
                   label=f"{adoption_label} ({adoption})")
        drew = True
    if drew:
        ax.legend(fontsize=8)
    ax.set_title(title, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=8)
    ax.margins(x=0.02)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", help="repo_report/<owner_repo> directory")
    ap.add_argument("--adoption", help="override adoption month YYYY-MM")
    ap.add_argument("--split-on", choices=("coding", "review", "any"),
                    default="coding",
                    help="which event is month 0: the first CODING agent "
                         "(default), the first review bot, or the first AI "
                         "action of any kind (the old behaviour)")
    args = ap.parse_args()
    report = Path(args.report)
    if not report.exists():
        sys.exit(f"No such report dir: {report}")
    plots = report / "plots"
    plots.mkdir(exist_ok=True)

    any_adoption, agents = find_adoption(report)
    coding, review = adoption_by_category(report)
    if args.split_on == "coding":
        # fall back to the any-kind date so a repo with only a review bot still
        # gets a split rather than silently losing its pre/post comparison
        adoption = coding or any_adoption
        adoption_label = ("AI coding agent" if coding else "first AI action")
    elif args.split_on == "review":
        adoption = review or any_adoption
        adoption_label = ("AI review bot" if review else "first AI action")
    else:
        adoption = any_adoption
        adoption_label = "AI adoption"
    if args.adoption:
        adoption, adoption_label = args.adoption, "adoption (override)"
    # never draw the same month twice
    if review == adoption:
        review = None
    split = bool(adoption)

    velocity = read_csv(report / "velocity_monthly.csv")
    quality = read_csv(report / "quality_monthly.csv")
    issues = read_csv(report / "issue_monthly.csv")
    reviews = read_csv(report / "review_monthly.csv")

    L = []
    L.append(f"# {report.name} — AI-impact evaluation\n")
    if adoption:
        WHAT = {
            "AI coding agent": "the first commit or PR attributable to an AI "
                               "*coding* agent (Cursor, Codex, Claude Code, …) — "
                               "the point at which AI began writing code here",
            "AI review bot": "the first review left by an AI *review* bot "
                             "(CodeRabbit, Copilot review, …)",
            "first AI action": "the first trackable AI action of any kind "
                               "(commit, merge, push, PR, review or issue)",
            "adoption (override)": "supplied on the command line",
        }.get(adoption_label, "the first trackable AI action")
        L.append(f"**Split point: `{adoption}`** — {adoption_label}, defined as "
                 f"{WHAT}.\n")
        if review:
            L.append(f"An AI **review bot** arrived earlier, in `{review}`. That is a "
                     f"different intervention — it comments on code people wrote, it "
                     f"does not write code — so it is drawn on every plot as a second "
                     f"marker but is not the split point. Reading a code-generation "
                     f"effect off a review-bot date is the main interpretation hazard "
                     f"in this report.\n")
        L.append("Per-agent first action: " +
                 ", ".join(f"{a} ({fs})" for a, fs, _ in agents if fs) + "\n")
    else:
        L.append("**No AI usage detected** (no attributable commit, merge, PR, "
                 "review, or issue) — there is no adoption split, so every "
                 "table below reports a single whole-history column rather "
                 "than a before/after comparison.\n")

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
        L.extend(mean_table(pre, post, [
            ("commits", "mean monthly commits", 2),
            ("lines_added", "mean monthly lines added", 2),
            ("lines_removed", "mean monthly lines removed", 2),
            ("contributors", "mean monthly contributors", 2)], split).render())
        (idx, months) = series(velocity, "month", "commits")
        plot_series(months, [v for _, v in idx], adoption,
                    "Monthly commits", "commits", plots / "velocity_commits.png",
                    review=review, adoption_label=adoption_label)

    # ---- Size + Quality ----
    if quality:
        pre, post = split_by_month(quality, "month", adoption)
        L.append("\n## 2. Code size & quality (SonarQube, monthly snapshots)\n")
        L.append("Quality is reported as **trend slope** (change per calendar "
                 "month): positive slope on smells/bugs/debt = worsening. "
                 "Months missing from the series count as elapsed time, not as "
                 "one step.\n")
        tbl = MetricTable(split, "pre-slope", "post-slope", "Δ slope",
                          "whole-history slope")
        # Each entry: (label, [candidate column names in priority order]).
        for lbl, keys in [("size (ncloc)", ["ncloc"]),
                          ("bugs", ["bugs"]),
                          ("vulnerabilities", ["vulnerabilities"]),
                          ("code smells", ["code_smells"]),
                          ("cognitive complexity", ["cognitive_complexity"]),
                          ("technical debt (remediation min)", list(DEBT_KEYS)),
                          ("duplication %", ["duplicated_lines_density"]),
                          ("comment density %", ["comment_lines_density"])]:
            pre_pts = month_pairs(pre, keys)
            post_pts = month_pairs(post, keys)
            tbl.add(lbl, slope(pre_pts), slope(post_pts),
                    n_valid([y for _, y in pre_pts]),
                    n_valid([y for _, y in post_pts]), nd=3)
        L.extend(tbl.render())
        debt_key = next((k for k in DEBT_KEYS
                         if any((r.get(k) or "").strip() for r in quality)),
                        "sqale_index")
        for key, ylabel in [("code_smells", "code smells"),
                            ("cognitive_complexity", "cognitive complexity"),
                            (debt_key, "tech debt (min)"),
                            ("ncloc", "ncloc")]:
            idx, months = series(quality, "month", key)
            plot_series(months, [v for _, v in idx], adoption,
                        f"Monthly {ylabel}", ylabel, plots / f"quality_{key}.png",
                        review=review, adoption_label=adoption_label)

    # ---- Issue health ----
    if issues:
        pre, post = split_by_month(issues, "month", adoption)
        L.append("\n## 3. Issue-resolution health\n")
        L.extend(mean_table(pre, post, [
            ("median_resolution_hours", "median resolution (hours)", 1),
            ("opened", "mean monthly issues opened", 1),
            ("open_bug_backlog", "mean open bug backlog", 1)], split).render())
        idx, months = series(issues, "month", "median_resolution_hours")
        plot_series(months, [v for _, v in idx], adoption,
                    "Median issue resolution time (per close-month)", "days",
                    plots / "issue_resolution.png", scale=1.0 / 24.0,
                    review=review, adoption_label=adoption_label)
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
        L.extend(mean_table(pre, post, [
            ("ai_review_share", "mean AI-review share", 3),
            ("prs_opened", "mean monthly PRs opened", 1),
            ("median_review_comments", "median review comments/PR", 1)],
            split).render())

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
    L.append("\n*In §2, each metric is shown as a **slope** (change per calendar "
             "month, gaps in the monthly series included). A "
             "positive slope on smells/complexity/debt means quality is degrading "
             "over time; the pre-vs-post Δ shows whether AI adoption changed that rate. "
             "Raw counts rise with `ncloc`, so also read them per-1k-lines when comparing "
             "periods of different size. The `n months` column is the sample behind each "
             f"figure; a {LOW_N_MARK} marks fewer than {MIN_PERIOD_MONTHS} months.*\n")

    (report / "SUMMARY.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Wrote {report/'SUMMARY.md'}")
    if HAVE_MPL:
        print(f"Plots in {plots}/")
    else:
        print("matplotlib not installed — SUMMARY.md written without plots "
              "(pip install matplotlib to enable).")


if __name__ == "__main__":
    main()
