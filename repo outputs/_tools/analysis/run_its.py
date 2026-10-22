#!/usr/bin/env python3
"""Interrupted time-series (segmented regression) for AI adoption.

WHY THIS AND NOT A PRE/POST RATIO
A pre/post comparison cannot distinguish an intervention effect from a trend
that was already running. A codebase grows month after month with or without
AI, so "ncloc is 11% higher after adoption" is partly just time passing. ITS
fits the PRE-adoption trend explicitly and asks what happens ON TOP of it.

MODEL (panel segmented regression, event time)

    y_it = alpha_i + b1*tau_it + b2*POST_it + b3*(tau_it * POST_it) + e_it

    alpha_i  repository fixed effect (each repo is its own baseline)
    tau      event time in months, 0 = that repo's adoption month
    POST     1 from the adoption month onward
    b1       PRE-ADOPTION TREND -- the counterfactual "natural growth"
    b2       LEVEL CHANGE at adoption (immediate jump)
    b3       SLOPE CHANGE after adoption (does growth accelerate?)

b2 and b3 are the causal-flavoured quantities: both are measured net of b1.

Outcomes are logged where they are strictly positive and scale-varying, so
coefficients read as approximate proportional change and repo fixed effects
absorb size differences multiplicatively rather than additively.

Standard errors are clustered by repository: months within a repo are strongly
autocorrelated and would otherwise be treated as independent observations.
"""
import numpy as np, pandas as pd, statsmodels.formula.api as smf

PANEL = "repo outputs/analytics/panel_ai_impact.csv"
DEV   = "repo outputs/analytics/velocity_develop_monthly.csv"
OUT   = "repo outputs/analytics/its_results.csv"
WIN   = (-10, 3)          # event-time window actually populated
MIN_PRE, MIN_POST = 3, 1  # a repo must straddle the event to inform b2/b3


def mord(s):
    s = s.astype(str)
    return s.str[:4].astype(int) * 12 + s.str[5:7].astype(int) - 1


def load(branch_scope="all"):
    d = pd.read_csv(PANEL)
    d["mi"] = mord(d["month"])
    for c in ("commits", "lines_added", "ncloc", "cognitive_complexity",
              "code_smells", "technical_debt", "prs_opened"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    if branch_scope == "develop":
        # replace all-branch velocity with integration-branch velocity
        v = pd.read_csv(DEV)[["repo_name", "month", "commits", "lines_added"]]
        d = d.drop(columns=["commits", "lines_added"]).merge(
            v, on=["repo_name", "month"], how="left")
    d = d[d["adoption_coding"].notna()].copy()
    d["tau"] = d["mi"] - mord(d["adoption_coding"])
    d = d[(d["tau"] >= WIN[0]) & (d["tau"] <= WIN[1])]
    d["post"] = (d["tau"] >= 0).astype(int)
    d["tau_post"] = d["tau"] * d["post"]
    return d


def its(d, outcome, log=True):
    x = d[["repo_name", "tau", "post", "tau_post", outcome]].dropna()
    x = x[x[outcome] > 0] if log else x
    # keep only repos that actually straddle the event
    keep = [r for r, g in x.groupby("repo_name")
            if (g.tau < 0).sum() >= MIN_PRE and (g.tau >= 0).sum() >= MIN_POST]
    x = x[x.repo_name.isin(keep)]
    if x.repo_name.nunique() < 6 or len(x) < 40:
        return None
    x = x.copy()
    x["y"] = np.log(x[outcome]) if log else x[outcome]
    m = smf.ols("y ~ tau + post + tau_post + C(repo_name)", data=x).fit(
        cov_type="cluster", cov_kwds={"groups": x["repo_name"]})
    return dict(outcome=outcome, log=log, n_obs=int(m.nobs),
                n_repos=x.repo_name.nunique(),
                pre_trend=m.params["tau"],      p_pre=m.pvalues["tau"],
                level=m.params["post"],         p_level=m.pvalues["post"],
                slope_chg=m.params["tau_post"], p_slope=m.pvalues["tau_post"])


OUTCOMES = [("ncloc", True), ("cognitive_complexity", True),
            ("code_smells", True), ("technical_debt", True),
            ("commits", True), ("lines_added", True), ("prs_opened", True)]


def pct(b):
    """log coefficient -> approximate % change"""
    return (np.exp(b) - 1) * 100


def main():
    rows = []
    for scope in ("all", "develop"):
        d = load(scope)
        for out, lg in OUTCOMES:
            r = its(d, out, lg)
            if r:
                r["branch_scope"] = scope
                rows.append(r)
    R = pd.DataFrame(rows)
    R.to_csv(OUT, index=False)

    for scope in ("all", "develop"):
        s = R[R.branch_scope == scope]
        if s.empty:
            continue
        print("\n" + "=" * 86)
        print("ITS — velocity branch scope: %s   (log outcomes; %% per month / %% level)"
              % scope.upper())
        print("=" * 86)
        print("%-24s %12s %14s %14s %6s %5s" %
              ("outcome", "PRE-TREND", "LEVEL CHANGE", "SLOPE CHANGE", "nobs", "repos"))
        print("%-24s %12s %14s %14s" % ("", "b1 %/mo", "b2 %", "b3 %/mo"))
        print("-" * 86)
        for _, r in s.iterrows():
            def f(b, p):
                st = "***" if p < .001 else "**" if p < .01 else "*" if p < .05 else ""
                return "%+7.2f%s" % (pct(b), st)
            print("%-24s %12s %14s %14s %6d %5d" %
                  (r.outcome, f(r.pre_trend, r.p_pre), f(r.level, r.p_level),
                   f(r.slope_chg, r.p_slope), r.n_obs, r.n_repos))
    print("\n*** p<.001  ** p<.01  * p<.05   SEs clustered by repository")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
