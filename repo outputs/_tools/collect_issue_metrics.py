#!/usr/bin/env python3
"""
Collect GitHub issue-resolution metrics for one repo.

For every issue (state=all, PRs excluded) writes:
  issues.csv        : number, created_at, closed_at, resolution_hours, state,
                      labels, closed_by, author, is_bug
  issue_monthly.csv : month, opened, closed, median_resolution_hours,
                      mean_resolution_hours, open_bug_backlog
  issue_stats.csv   : one repo-wide row, including which population the counts
                      describe (see --since below)

"Resolution time" = closed_at - created_at (hours) for closed issues.
`is_bug` = a label whose *words* include bug/defect/regression/crash/hotfix, or
whose whole label is fix/fixes/fixed. Word matching keeps "prefix" and
"documentation-fix" out of the bug population.

--since is a CREATED-month window. The API is asked for `since=<month>-01`,
which filters by UPDATED_at (that is all the endpoint offers), and rows created
before the window are then dropped locally. So `total_issues` counts issues
CREATED in the window, not every issue the repo has; issue_stats.csv records
this explicitly in `total_issues_basis`.

Usage:
  python collect_issue_metrics.py owner/name /out/dir [--since 2023-01] [--resume]
Reads GITHUB_TOKEN/GH_TOKEN from the environment, else a .env next to the
toolkit (see gh_rest.get_token).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_signatures import match_login  # noqa: E402
from gh_rest import GitHubApiError, get_json, get_token, paginate  # noqa: E402

# Matched against the *words* of a label, not as substrings.
BUG_LABEL_WORDS = frozenset({
    "bug", "bugs", "bugfix", "bugfixes", "defect", "defects",
    "regression", "regressions", "crash", "crashes", "hotfix",
})
# Weak words: only a bug when they are the entire label, so "documentation-fix"
# and "prefix" stay out while a bare "fix" label still counts.
BUG_LABEL_WEAK_WORDS = frozenset({"fix", "fixes", "fixed"})
NON_BUG_WORDS = frozenset({"not", "non", "notabug"})
_LABEL_WORD_SPLIT = re.compile(r"[^a-z0-9]+")

MARKER_NAME = "issue_collection.json"
MARKER_SCHEMA = 1
OUTPUT_FILES = ("issues.csv", "issue_monthly.csv", "issue_stats.csv")


def is_bug_label(label: str) -> bool:
    """Word-boundary bug-label test (substring matching used to score labels
    like 'prefix' or 'documentation-fix' as bugs)."""
    words = [w for w in _LABEL_WORD_SPLIT.split(label.lower()) if w]
    if not words or NON_BUG_WORDS.intersection(words):
        return False
    if BUG_LABEL_WORDS.intersection(words):
        return True
    return len(words) == 1 and words[0] in BUG_LABEL_WEAK_WORDS


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _month(ts: Optional[str]) -> str:
    d = _parse(ts)
    return d.strftime("%Y-%m") if d else ""


def month_range(months: Iterable[str]) -> List[str]:
    """Contiguous YYYY-MM list from min to max of the given months (inclusive),
    so monthly series have no phantom gaps for months with no activity."""
    ms = [m for m in months if m]
    if not ms:
        return []
    lo, hi = min(ms), max(ms)

    def nxt(m: str) -> str:
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


def _first_response_hours(repo: str, token: Optional[str], number: Optional[int],
                          author: str, created: Optional[str]) -> Union[float, str]:
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
            opened_at = _parse(created)
            replied_at = _parse(c.get("created_at"))
            if opened_at is None or replied_at is None:
                return ""
            delta = replied_at - opened_at
            return round(delta.total_seconds() / 3600.0, 2)
    return ""


def collect(repo: str, token: Optional[str], since: Optional[str] = None,
            first_response: bool = True, max_issues: Optional[int] = None
            ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Fetch issues for `repo`, returning (rows, meta).

    Raises GitHubApiError if any page could not be fetched: a short row list is
    never returned, because the caller cannot tell it apart from a complete one.
    """
    params: Dict[str, Any] = {"state": "all", "sort": "created",
                              "direction": "asc", "per_page": 100}
    if since:
        # The endpoint can only filter by updated_at, so this is a cheap
        # pre-filter; the created-month window is applied locally below.
        params["since"] = f"{since}-01T00:00:00Z"
    rows: List[Dict[str, Any]] = []
    n_seen = n_pr = n_before = n_fr = 0
    for it in paginate(f"/repos/{repo}/issues", token, params):
        n_seen += 1
        if "pull_request" in it:  # the issues endpoint returns PRs too - drop them
            n_pr += 1
            continue
        created = it.get("created_at")
        if since and _month(created) < since:
            n_before += 1
            continue
        closed = it.get("closed_at")
        res_hours: Union[float, str] = ""
        if closed and created:
            delta = _parse(closed) - _parse(created)
            res_hours = round(delta.total_seconds() / 3600.0, 2)
        labels = [lb.get("name", "") for lb in it.get("labels", [])]
        is_bug = any(is_bug_label(lb) for lb in labels)
        author = (it.get("user") or {}).get("login", "")
        # Pass the API's account type through: match_login only accepts a bare
        # product name ("Copilot") when the caller can confirm it is a bot.
        author_is_bot = (it.get("user") or {}).get("type") == "Bot"
        closer = it.get("closed_by") or {}
        closed_by = closer.get("login", "") or ""
        closed_by_is_bot = closer.get("type") == "Bot"
        a_agent, a_cat = match_login(author, is_bot=author_is_bot)
        c_agent, c_cat = match_login(closed_by, is_bot=closed_by_is_bot)
        assignees = ";".join((a or {}).get("login", "")
                             for a in it.get("assignees", []))
        number = it.get("number")
        fr: Union[float, str] = ""
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
    basis = (f"issues created on or after {since}-01" if since
             else "all issues in the repo")
    meta: Dict[str, Any] = {
        "since": since or "",
        "api_since_filter": (f"updated_at >= {since}-01T00:00:00Z" if since
                             else "none"),
        "total_issues_basis": basis,
        "issues_fetched_from_api": n_seen,
        "pull_requests_dropped": n_pr,
        "issues_dropped_created_before_since": n_before,
        "first_response_fetched": n_fr,
    }
    logging.info(
        "issues: %d items fetched (API filter: %s), %d were PRs (dropped), "
        "%d updated in window but created earlier (dropped), %d kept - "
        "'total_issues' therefore means: %s; first-response fetched for %d",
        n_seen, meta["api_since_filter"], n_pr, n_before, len(rows), basis, n_fr)
    if since and n_before:
        logging.info("since=%s cost ~%d wasted rows: the API filters on "
                     "updated_at while rows are windowed on created_at",
                     since, n_before)
    return rows, meta


def aggregate_monthly(repo: str, rows: List[Dict[str, Any]]
                      ) -> List[Dict[str, Any]]:
    opened: Dict[str, int] = defaultdict(int)
    closed: Dict[str, int] = defaultdict(int)
    res_by_month: Dict[str, List[float]] = defaultdict(list)  # by close-month
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


def _pct(sorted_vals: List[float], q: float) -> Union[float, str]:
    """Simple percentile (nearest-rank) on a pre-sorted list."""
    if not sorted_vals:
        return ""
    k = max(0, min(len(sorted_vals) - 1,
                   int(round(q / 100.0 * (len(sorted_vals) - 1)))))
    return round(sorted_vals[k], 2)


def overall_stats(repo: str, rows: List[Dict[str, Any]],
                  meta: Dict[str, Any]) -> Dict[str, Any]:
    """Repo-wide issue statistics (one row) - the 'proper issue data' summary.

    `total_issues` counts the rows in issues.csv, whose population is spelled
    out by `total_issues_basis` / `since` so a --since run is not read as a
    whole-repo total.
    """
    closed = sorted(float(r["resolution_hours"]) for r in rows
                    if r["resolution_hours"] != "")
    fr = sorted(float(r["first_response_hours"]) for r in rows
                if r["first_response_hours"] != "")
    n_open = sum(1 for r in rows if r["state"] == "open")
    n_bug = sum(1 for r in rows if r["is_bug"])
    n_bug_open = sum(1 for r in rows if r["is_bug"] and r["state"] == "open")
    ai_authored = sum(1 for r in rows if r["author_ai_agent"])
    ai_closed = sum(1 for r in rows if r["closed_by_ai_agent"])
    return {
        "repo_name": repo,
        "total_issues": len(rows),
        "total_issues_basis": meta["total_issues_basis"],
        "since": meta["since"],
        "api_since_filter": meta["api_since_filter"],
        "issues_fetched_from_api": meta["issues_fetched_from_api"],
        "pull_requests_dropped": meta["pull_requests_dropped"],
        "issues_dropped_created_before_since":
            meta["issues_dropped_created_before_since"],
        "first_response_fetched": meta["first_response_fetched"],
        "collection_complete": True,
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


def write_csv(path: Path, rows: List[Dict[str, Any]], cols: List[str]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


def _run_params(args: argparse.Namespace) -> Dict[str, Any]:
    """The inputs a cached result must match before --resume may reuse it."""
    return {
        "repo": args.repo,
        "since": args.since or "",
        "first_response": not args.no_first_response,
        "max_issues": args.max_issues,
    }


def read_marker(out: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads((out / MARKER_NAME).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_complete(out: Path, params: Dict[str, Any]) -> bool:
    """True only if a previous run of the SAME parameters finished and every
    output it promised is still present and non-empty. Partial or interrupted
    output has no marker (it is cleared before collection) and so never counts
    as complete."""
    marker = read_marker(out)
    if not marker or marker.get("schema") != MARKER_SCHEMA:
        return False
    if not marker.get("complete") or marker.get("params") != params:
        return False
    return all((out / name).is_file() and (out / name).stat().st_size > 0
               for name in OUTPUT_FILES)


def clear_marker(out: Path) -> None:
    (out / MARKER_NAME).unlink(missing_ok=True)


def write_marker(out: Path, params: Dict[str, Any],
                 stats: Dict[str, Any]) -> None:
    payload = {
        "schema": MARKER_SCHEMA,
        "complete": True,
        "params": params,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "outputs": list(OUTPUT_FILES),
        "total_issues": stats["total_issues"],
        "total_issues_basis": stats["total_issues_basis"],
    }
    (out / MARKER_NAME).write_text(json.dumps(payload, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="owner/name")
    ap.add_argument("out", help="output directory")
    ap.add_argument("--since", help="YYYY-MM lower bound on issue created month")
    ap.add_argument("--no-first-response", action="store_true",
                    help="skip per-issue first-response time (saves 1 API call/issue)")
    ap.add_argument("--max-issues", type=int,
                    help="cap issues for first-response fetch (logged if reached)")
    ap.add_argument("--resume", action="store_true",
                    help="skip this repo if a complete run with the same options "
                         "already wrote its CSVs (see issue_collection.json)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    params = _run_params(args)
    if args.resume and is_complete(out, params):
        logging.info("--resume: %s already collected (%s); skipping",
                     args.repo, out / MARKER_NAME)
        print(f"repo={args.repo}  SKIPPED (complete output already present)")
        return 0

    token = get_token()
    if not token:
        logging.warning("No GITHUB_TOKEN found - unauthenticated (60 req/hr). "
                        "Set GITHUB_TOKEN for full collection.")
    clear_marker(out)  # whatever is on disk now is about to be superseded

    try:
        rows, meta = collect(args.repo, token, args.since,
                             first_response=not args.no_first_response,
                             max_issues=args.max_issues)
    except GitHubApiError as exc:
        logging.error("issue collection for %s FAILED and produced no output "
                      "(previous CSVs, if any, were left untouched): %s",
                      args.repo, exc)
        return 2

    monthly = aggregate_monthly(args.repo, rows)
    stats = overall_stats(args.repo, rows, meta)

    write_csv(out / "issues.csv", rows,
              ["repo_name", "number", "created_at", "closed_at", "resolution_hours",
               "first_response_hours", "state", "labels", "n_comments",
               "author", "author_ai_agent", "closed_by", "closed_by_ai_agent",
               "assignees", "is_bug"])
    write_csv(out / "issue_monthly.csv", monthly,
              ["repo_name", "month", "opened", "closed", "median_resolution_hours",
               "mean_resolution_hours", "open_bug_backlog"])
    write_csv(out / "issue_stats.csv", [stats], list(stats.keys()))
    write_marker(out, params, stats)

    print(f"repo={args.repo}  issues={stats['total_issues']}  "
          f"open={stats['open_issues']}  closed={stats['closed_issues']}  "
          f"close_rate={stats['close_rate']}")
    print(f"  population: {stats['total_issues_basis']}")
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
    print(f"Wrote issues.csv, issue_monthly.csv, issue_stats.csv, "
          f"{MARKER_NAME} to {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
