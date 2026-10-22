#!/usr/bin/env python3
"""Code-review practice: is there MORE public review, and who is doing it?

Splits every review submission into three actors and builds monthly
repo-level series:

  AI        a known AI review bot (CodeRabbit, Copilot review, Sourcery, ...)
  other-bot non-AI automation (Dependabot, CI, release bots) -- these review
            and comment too, and lumping them with humans overstates human
            engagement
  human     everything else

The headline question the supervisor asked is COVERAGE, not volume: what
fraction of PRs receive any review at all? A bot that reviews every PR raises
coverage even if humans do exactly what they did before.
"""
import csv, glob, os, re, sys
import numpy as np, pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ai_signatures import match_login            # noqa: E402

REPORTS = "repo outputs/repo_report"
OUT     = "repo outputs/analytics/review_actor_monthly.csv"


def classify(login: str) -> str:
    if not login or not str(login).strip():
        return "none"
    agent, cat = match_login(str(login))
    if cat == "review":
        return "ai"
    if cat == "coding":
        return "ai"            # an agent that reviews still counts as AI review
    if cat == "other-bot":
        return "otherbot"
    # match_login is conservative; catch remaining automation by suffix
    if re.search(r"\[bot\]$|-bot$|^dependabot|^renovate|^snyk|^greenkeeper",
                 str(login), re.I):
        return "otherbot"
    return "human"


def month(ts):
    return str(ts)[:7] if ts and str(ts)[:4].isdigit() else ""


def main():
    rows = []
    for d in sorted(glob.glob(REPORTS + "/*/")):
        repo = os.path.basename(d.rstrip("/")).replace("mosip_", "mosip/", 1)
        rv = os.path.join(d, "reviews.csv")
        if not os.path.exists(rv):
            continue
        pr_month, pr_actors = {}, {}
        counts = {}
        for r in csv.DictReader(open(rv)):
            pr = r["pr_number"]
            m = month(r.get("pr_created_at"))
            if not m:
                continue
            pr_month[pr] = m
            who = classify(r.get("reviewer"))
            pr_actors.setdefault(pr, set())
            if r.get("review_state"):          # an actual review submission
                pr_actors[pr].add(who)
                sm = month(r.get("submitted_at")) or m
                counts.setdefault(sm, {"ai": 0, "human": 0, "otherbot": 0})
                if who in counts[sm]:
                    counts[sm][who] += 1
        # monthly PR coverage, keyed by PR creation month
        cov = {}
        for pr, m in pr_month.items():
            a = pr_actors.get(pr, set())
            c = cov.setdefault(m, dict(prs=0, any=0, human=0, ai=0, otherbot=0))
            c["prs"] += 1
            if a - {"none"}:
                c["any"] += 1
            for k in ("human", "ai", "otherbot"):
                if k in a:
                    c[k] += 1
        for m in sorted(set(cov) | set(counts)):
            c = cov.get(m, dict(prs=0, any=0, human=0, ai=0, otherbot=0))
            n = counts.get(m, {"ai": 0, "human": 0, "otherbot": 0})
            rows.append(dict(repo_name=repo, month=m,
                             prs=c["prs"], prs_reviewed=c["any"],
                             prs_human=c["human"], prs_ai=c["ai"],
                             prs_otherbot=c["otherbot"],
                             n_ai=n["ai"], n_human=n["human"],
                             n_otherbot=n["otherbot"]))
    R = pd.DataFrame(rows)
    R.to_csv(OUT, index=False)
    print("wrote %s  (%d repo-months, %d repos)" % (OUT, len(R), R.repo_name.nunique()))

    tot = R[["n_ai", "n_human", "n_otherbot"]].sum()
    print("\nREVIEW SUBMISSIONS BY ACTOR (whole window)")
    for k, v in tot.items():
        print("  %-10s %7d  (%.1f%%)" % (k.replace("n_", ""), v, 100 * v / tot.sum()))

    print("\nPR REVIEW COVERAGE — fraction of PRs receiving any review")
    ad = pd.read_csv("repo outputs/analytics/panel_ai_impact.csv")
    a = ad.groupby("repo_name")["adoption_review"].first()
    R = R.join(a, on="repo_name")
    R = R[R.adoption_review.notna() & (R.month <= "2026-08")]
    def mo(s): return s.str[:4].astype(int) * 12 + s.str[5:7].astype(int) - 1
    R["tau"] = mo(R.month.astype(str)) - mo(R.adoption_review.astype(str))
    for lo, hi, lab in ((-6, -1, "pre  (tau -6..-1)"), (1, 6, "post (tau +1..+6)")):
        w = R[(R.tau >= lo) & (R.tau <= hi)]
        g = w.groupby("repo_name")[["prs", "prs_reviewed", "prs_human",
                                    "prs_ai", "prs_otherbot"]].sum()
        g = g[g.prs > 0]
        print("  %s  n=%d repos" % (lab, len(g)))
        for col, name in (("prs_reviewed", "any review"), ("prs_human", "human review"),
                          ("prs_ai", "AI review"), ("prs_otherbot", "other-bot review")):
            print("      %-18s %5.1f%% of PRs" % (name, 100 * (g[col] / g.prs).median()))


if __name__ == "__main__":
    main()
