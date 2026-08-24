#!/usr/bin/env python3
"""
Collect GitHub issue-resolution metrics for one repo.

For every issue (state=all, PRs excluded) writes:
  issues.csv        : number, created_at, closed_at, resolution_hours, state,
                      labels, closed_by, author, is_bug
  issue_monthly.csv : month, opened, closed, median_resolution_hours,
                      mean_resolution_hours, open_bug_backlog

"Resolution time" = closed_at - created_at (hours) for closed issues.
`is_bug` = any label matching /bug|defect|regression|crash|fix/i.

Usage:
  python collect_issue_metrics.py owner/name /out/dir [--since 2023-01]
Reads GITHUB_TOKEN from env or ../../.env.
"""
import argparse
import csv
import logging
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_signatures import match_login  # noqa: E402
from gh_rest import get_json, get_token, paginate  # noqa: E402

BUG_LABELS = ("bug", "defect", "regression", "crash", "fix")


def _parse(ts):
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _month(ts):
    d = _parse(ts)
    return d.strftime("%Y-%m") if d else ""


def month_range(months):
    """Contiguous YYYY-MM list from min to max of the given months (inclusive),
    so monthly series have no phantom gaps for months with no activity."""
    ms = [m for m in months if m]
    if not ms:
        return []
    lo, hi = min(ms), max(ms)

    def nxt(m):
        y, mo = (int(x) for x in m.split("-"))
        mo += 1
        if mo > 12:
            y, mo = y + 1, 1
        return f"{y:04d}-{mo:02d}"

    out, cur = [], lo
    while cur <= hi:
        out.append(cur)
        cur = nxt(cur)
    return out


def _first_response_hours(repo, token, number, author, created):
    """Hours from issue open to first comment by someone other than the author.
    Costs one API call per issue; skipped when first_response is disabled."""
    if not created:
        return ""
    comments = get_json(
        f"https://api.github.com/repos/{repo}/issues/{number}/comments",
        token, params={"per_page": 100}) or []
    for c in comments:
        who = (c.get("user") or {}).get("login", "")
        if who and who != author:
            delta = _parse(c["created_at"]) - _parse(created)
            return round(delta.total_seconds() / 3600.0, 2)
    return ""


def collect(repo, token, since=None, first_response=True, max_issues=None):
    params = {"state": "all", "sort": "created", "direction": "asc", "per_page": 100}
    if since:
        # since filters by updated_at; we still keep created-based windowing below.
        params["since"] = f"{since}-01T00:00:00Z"
    rows = []
    n_seen = n_pr = n_fr = 0
    for it in paginate(f"/repos/{repo}/issues", token, params):
        n_seen += 1
        if "pull_request" in it:  # the issues endpoint returns PRs too — drop them
            n_pr += 1
            continue
        created = it.get("created_at")
        if since and _month(created) < since:
            continue
        closed = it.get("closed_at")
        res_hours = ""
        if closed and created:
            delta = _parse(closed) - _parse(created)
            res_hours = round(delta.total_seconds() / 3600.0, 2)
        labels = [lb.get("name", "") for lb in it.get("labels", [])]
        is_bug = any(any(b in lb.lower() for b in BUG_LABELS) for lb in labels)
        author = (it.get("user") or {}).get("login", "")
        closed_by = (it.get("closed_by") or {}).get("login", "") if it.get("closed_by") else ""
        a_agent, a_cat = match_login(author)
        c_agent, c_cat = match_login(closed_by)
        assignees = ";".join((a or {}).get("login", "") for a in it.get("assignees", []))
        number = it.get("number")
        fr = ""
        if first_response and (max_issues is None or n_fr < max_issues):
            fr = _first_response_hours(repo, token, number, author, created)
            n_fr += 1
        rows.append({
            "repo_name": repo,
            "number": number,
            "created_at": created or "",
            "closed_at": closed or "",
            "resolution_hours": res_hours,
            "first_response_hours": fr,
            "state": it.get("state", ""),
            "labels": ";".join(labels),
            "n_comments": it.get("comments", 0),
            "author": author,
            "author_ai_agent": a_agent if a_cat in ("coding", "review") else "",
            "closed_by": closed_by,
            "closed_by_ai_agent": c_agent if c_cat in ("coding", "review") else "",
            "assignees": assignees,
            "is_bug": is_bug,
        })
    logging.info("issues: %d items from endpoint, %d were PRs (dropped), %d real issues kept "
                 "(first-response fetched for %d)", n_seen, n_pr, len(rows), n_fr)
    return rows


def aggregate_monthly(repo, rows):
    opened = defaultdict(int)
    closed = defaultdict(int)
    res_by_month = defaultdict(list)  # by close-month
    for r in rows:
        if r["created_at"]:
            opened[_month(r["created_at"])] += 1
        if r["closed_at"]:
            m = _month(r["closed_at"])
            closed[m] += 1
            if r["resolution_hours"] != "":
                res_by_month[m].append(float(r["resolution_hours"]))

    # Open bug backlog at end of each month = bugs created <= month and (still
    # open OR closed after that month). Use a CONTIGUOUS month axis (zero-filled).
    months = month_range(list(opened) + list(closed))
    bug_rows = [r for r in rows if r["is_bug"]]
    out = []
    for m in months:
        end = f"{m}-31"
        backlog = 0
        for r in bug_rows:
            if _month(r["created_at"]) <= m and (
                not r["closed_at"] or _month(r["closed_at"]) > m
            ):
                backlog += 1
        res = res_by_month.get(m, [])
        out.append({
            "repo_name": repo,
            "month": m,
            "opened": opened.get(m, 0),
            "closed": closed.get(m, 0),
            "median_resolution_hours": round(statistics.median(res), 2) if res else "",
            "mean_resolution_hours": round(statistics.mean(res), 2) if res else "",
            "open_bug_backlog": backlog,
        })
    return out


def _pct(sorted_vals, q):
    """Simple percentile (nearest-rank) on a pre-sorted list."""
    if not sorted_vals:
        return ""
    k = max(0, min(len(sorted_vals) - 1, int(round(q / 100.0 * (len(sorted_vals) - 1)))))
    return round(sorted_vals[k], 2)


def overall_stats(repo, rows):
    """Repo-wide issue statistics (one row) — the 'proper issue data' summary."""
    closed = sorted(float(r["resolution_hours"]) for r in rows if r["resolution_hours"] != "")
    fr = sorted(float(r["first_response_hours"]) for r in rows if r["first_response_hours"] != "")
    n_open = sum(1 for r in rows if r["state"] == "open")
    n_bug = sum(1 for r in rows if r["is_bug"])
    n_bug_open = sum(1 for r in rows if r["is_bug"] and r["state"] == "open")
    ai_authored = sum(1 for r in rows if r["author_ai_agent"])
    ai_closed = sum(1 for r in rows if r["closed_by_ai_agent"])
    return {
        "repo_name": repo,
        "total_issues": len(rows),
        "open_issues": n_open,
        "closed_issues": len(closed),
        "close_rate": round(len(closed) / len(rows), 3) if rows else "",
        "bug_issues": n_bug,
        "open_bug_issues": n_bug_open,
        "ai_authored_issues": ai_authored,
        "ai_closed_issues": ai_closed,
        "resolution_hours_p25": _pct(closed, 25),
        "resolution_hours_median": _pct(closed, 50),
        "resolution_hours_p75": _pct(closed, 75),
        "resolution_hours_p90": _pct(closed, 90),
        "resolution_hours_mean": round(statistics.mean(closed), 2) if closed else "",
        "first_response_hours_median": _pct(fr, 50),
        "first_response_hours_p90": _pct(fr, 90),
    }


def write_csv(path, rows, cols):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="owner/name")
    ap.add_argument("out", help="output directory")
    ap.add_argument("--since", help="YYYY-MM lower bound on issue created month")
    ap.add_argument("--no-first-response", action="store_true",
                    help="skip per-issue first-response time (saves 1 API call/issue)")
    ap.add_argument("--max-issues", type=int,
                    help="cap issues for first-response fetch (logged if reached)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    token = get_token()
    if not token:
        logging.warning("No GITHUB_TOKEN found — unauthenticated (60 req/hr). "
                        "Set GITHUB_TOKEN for full collection.")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = collect(args.repo, token, args.since,
                   first_response=not args.no_first_response, max_issues=args.max_issues)
    monthly = aggregate_monthly(args.repo, rows)
    stats = overall_stats(args.repo, rows)

    write_csv(out / "issues.csv", rows,
              ["repo_name", "number", "created_at", "closed_at", "resolution_hours",
               "first_response_hours", "state", "labels", "n_comments",
               "author", "author_ai_agent", "closed_by", "closed_by_ai_agent",
               "assignees", "is_bug"])
    write_csv(out / "issue_monthly.csv", monthly,
              ["repo_name", "month", "opened", "closed", "median_resolution_hours",
               "mean_resolution_hours", "open_bug_backlog"])
    write_csv(out / "issue_stats.csv", [stats], list(stats.keys()))

    print(f"repo={args.repo}  issues={stats['total_issues']}  "
          f"open={stats['open_issues']}  closed={stats['closed_issues']}  "
          f"close_rate={stats['close_rate']}")
    if stats["resolution_hours_median"] != "":
        print(f"  resolution (days): p25={float(stats['resolution_hours_p25'])/24:.1f} "
              f"median={float(stats['resolution_hours_median'])/24:.1f} "
              f"p75={float(stats['resolution_hours_p75'])/24:.1f} "
              f"p90={float(stats['resolution_hours_p90'])/24:.1f}")
    if stats["first_response_hours_median"] != "":
        print(f"  first response (hrs): median={stats['first_response_hours_median']} "
              f"p90={stats['first_response_hours_p90']}")
    print(f"  bugs={stats['bug_issues']} (open {stats['open_bug_issues']})  "
          f"AI-authored issues={stats['ai_authored_issues']}")
    print(f"Wrote issues.csv, issue_monthly.csv, issue_stats.csv to {out}/")


if __name__ == "__main__":
    main()
