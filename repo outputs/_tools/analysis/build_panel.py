#!/usr/bin/env python3
"""Pool the per-repo AI-Impact reports into a cross-repo dataset and summary.

Reads only repos whose .batch_state.json says "done", so a repo still being
written is never half-read. Emits:
  panel_ai_impact.csv   repo x month panel (velocity + quality + treatment),
                        schema-compatible with the study's DiD/panel notebooks
  repo_effects.csv      one row per repo: pre/post velocity means, quality
                        slopes, n months each side
  CROSS_REPO_SUMMARY.md human-readable findings
"""
import csv, datetime, glob, json, os, statistics, sys
from collections import defaultdict

BASE = os.path.expanduser("~/aiimpact")
REPORTS = os.path.join(BASE, "reports")
OUT = os.path.join(BASE, "analytics")
os.makedirs(OUT, exist_ok=True)

QUAL = ["ncloc", "bugs", "vulnerabilities", "code_smells", "cognitive_complexity",
        "technical_debt", "duplicated_lines_density", "comment_lines_density"]
VEL = ["commits", "lines_added", "lines_removed", "contributors"]
MIN_MONTHS = 3   # below this a slope is reported but flagged underpowered

# The month the run happens in is INCOMPLETE and must be excluded. Adoption here
# lands in 2026-05/06, so the 2-5 month post window sits at the very end of the
# series and a 3-day stub month would drag every post-mean down -- an artefact
# pointing the wrong way on precisely the velocity claim under test.
_today = datetime.date.today()
CUTOFF_MONTH = os.environ.get("AI_IMPACT_CUTOFF") or "%04d-%02d" % (
    _today.year if _today.month > 1 else _today.year - 1,
    _today.month - 1 if _today.month > 1 else 12)


def in_window(m):
    """True if this month is complete (<= the last fully elapsed month)."""
    return bool(m) and m <= CUTOFF_MONTH


def read(p):
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return list(csv.DictReader(f))


def fnum(v):
    try:
        x = float(v)
        return None if x != x else x        # drop NaN
    except (TypeError, ValueError):
        return None


def mord(m):
    try:
        y, mo = m.split("-")[:2]
        return int(y) * 12 + int(mo) - 1
    except Exception:
        return None


def slope(pairs):
    """Least-squares slope of y over CALENDAR month index (gaps are elapsed
    time, not one step)."""
    pts = [(x, y) for x, y in pairs if y is not None and x is not None]
    n = len(pts)
    if n < 2:
        return None, n
    sx = sum(x for x, _ in pts); sy = sum(y for _, y in pts)
    sxx = sum(x * x for x, _ in pts); sxy = sum(x * y for x, y in pts)
    den = n * sxx - sx * sx
    return ((n * sxy - sx * sy) / den if den else None), n


def mean(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def completed_repos():
    out = []
    for f in glob.glob(os.path.join(REPORTS, "*", ".batch_state.json")):
        try:
            if json.load(open(f)).get("status") == "done":
                out.append(os.path.dirname(f))
        except Exception:
            pass
    return sorted(out)


def adoption(d):
    """Return (overall, coding_only, review_only) adoption months.

    The pipeline's headline adoption is the first AI action of ANY kind, which
    merges review bots with code-generating agents. Those are different
    interventions, so the coding-only month is carried separately: a velocity /
    complexity claim should be split on when AI started WRITING code.
    """
    rows = read(os.path.join(d, "ai_adoption.csv"))
    overall = coding = review = None
    for r in rows:
        m = (r.get("first_action_date_utc") or r.get("first_action_date") or "")[:7]
        if not m:
            continue
        if r.get("agent") == "__OVERALL__":
            overall = m
        elif r.get("category") == "coding":
            coding = m if coding is None else min(coding, m)
        elif r.get("category") == "review":
            review = m if review is None else min(review, m)
    return overall, coding, review


def main():
    repos = completed_repos()
    print("Pooling %d completed repos (months through %s; later months are "
          "incomplete and excluded)" % (len(repos), CUTOFF_MONTH))
    panel, effects = [], []

    for d in repos:
        name = os.path.basename(d).replace("mosip_", "mosip/", 1)
        ov, coding, review = adoption(d)
        vel = {r["month"]: r for r in read(os.path.join(d, "velocity_monthly.csv"))
               if in_window(r.get("month"))}
        qual = {r["month"]: r for r in read(os.path.join(d, "quality_monthly.csv"))
                if in_window(r.get("month"))}
        iss = {r["month"]: r for r in read(os.path.join(d, "issue_monthly.csv"))
               if in_window(r.get("month"))}
        rev = {r["month"]: r for r in read(os.path.join(d, "review_monthly.csv"))
               if in_window(r.get("month"))}
        ops = read(os.path.join(d, "ai_operations.csv"))

        ops_by_month = defaultdict(int)
        for o in ops:
            mo = (o.get("date_utc") or o.get("date") or "")[:7]
            if mo and o.get("category") in ("coding", "review"):
                ops_by_month[mo] += 1

        split = coding or ov          # prefer the coding-agent split point
        for m in sorted(set(vel) | set(qual)):
            v, q = vel.get(m, {}), qual.get(m, {})
            row = {"repo_name": name, "month": m,
                   "adoption_month": split or "", "adoption_overall": ov or "",
                   "adoption_coding": coding or "", "adoption_review": review or "",
                   "post": int(bool(split) and m >= split),
                   "ai_ops": ops_by_month.get(m, 0)}
            for k in VEL:
                row[k] = v.get(k, "")
            for k in QUAL:
                row[k] = q.get(k, "")
            row["issues_opened"] = iss.get(m, {}).get("opened", "")
            row["median_resolution_hours"] = iss.get(m, {}).get(
                "median_resolution_hours", "")
            row["prs_opened"] = rev.get(m, {}).get("prs_opened", "")
            row["ai_review_share"] = rev.get(m, {}).get("ai_review_share", "")
            panel.append(row)

        eff = {"repo_name": name, "adoption_overall": ov or "",
               "adoption_coding": coding or "", "adoption_review": review or "",
               "split_used": split or "", "n_ai_ops": len(ops)}
        pre_m = [m for m in vel if not split or m < split]
        post_m = [m for m in vel if split and m >= split]
        eff["n_pre_months"] = len(pre_m); eff["n_post_months"] = len(post_m)
        for k in VEL:
            a = mean([fnum(vel[m].get(k)) for m in pre_m])
            b = mean([fnum(vel[m].get(k)) for m in post_m])
            eff["pre_" + k] = round(a, 2) if a is not None else ""
            eff["post_" + k] = round(b, 2) if b is not None else ""
            eff["d_" + k] = round(b - a, 2) if (a is not None and b is not None) else ""
        qpre = [m for m in qual if (not split or m < split)
                and fnum(qual[m].get("ncloc")) is not None]
        qpost = [m for m in qual if split and m >= split
                 and fnum(qual[m].get("ncloc")) is not None]
        eff["n_qual_pre"] = len(qpre); eff["n_qual_post"] = len(qpost)
        for k in QUAL:
            sa, na = slope([(mord(m), fnum(qual[m].get(k))) for m in qpre])
            sb, nb = slope([(mord(m), fnum(qual[m].get(k))) for m in qpost])
            eff["slope_pre_" + k] = round(sa, 4) if sa is not None else ""
            eff["slope_post_" + k] = round(sb, 4) if sb is not None else ""
            eff["dslope_" + k] = (round(sb - sa, 4)
                                  if (sa is not None and sb is not None) else "")
        eff["underpowered"] = int(min(eff["n_qual_pre"], eff["n_qual_post"]) < MIN_MONTHS)
        effects.append(eff)

    def dump(fn, rows):
        if not rows:
            return
        cols = list(rows[0].keys())
        with open(os.path.join(OUT, fn), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in cols})
        print("  wrote %s (%d rows)" % (fn, len(rows)))

    dump("panel_ai_impact.csv", panel)
    dump("repo_effects.csv", effects)
    json.dump({"repos": len(repos), "panel_rows": len(panel)},
              open(os.path.join(OUT, "meta.json"), "w"), indent=1)
    print("Done -> %s" % OUT)


if __name__ == "__main__":
    main()
