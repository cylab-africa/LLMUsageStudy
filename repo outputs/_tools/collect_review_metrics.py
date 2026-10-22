#!/usr/bin/env python3
"""
Collect GitHub pull-request review metrics for one repo, including detection of
AI code-review bots (Copilot review, CodeRabbit, Sourcery, Qodo Merge, ...).

Writes:
  reviews.csv        : pr_number, pr_created_at, pr_merged_at, reviewer, is_ai_bot,
                       ai_bot_name, review_state, submitted_at, n_review_comments
  review_monthly.csv : month (by PR creation), prs_opened, prs_merged,
                       median_review_comments, n_reviews, n_ai_reviews, ai_review_share

This answers "potential AI tool used to automate code review" — a bot actually
leaving reviews on PRs, distinct from a coding agent that writes commits.

Per-PR review/comment calls make this the heaviest collector. Bound with
--since and --max-prs; skipped PRs are logged (never silently dropped).

Usage:
  python collect_review_metrics.py owner/name /out/dir [--since 2023-01]
      [--max-prs N] [--no-merged-by]
"""
import argparse
import csv
import json
import logging
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_signatures import match_login, match_review_bot  # noqa: E402
from gh_rest import API, get_json, get_token, paginate  # noqa: E402


def _month(ts):
    if not ts:
        return ""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y-%m")


def _month_range(months):
    """Contiguous YYYY-MM list from min to max (inclusive) — no phantom gaps."""
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


def collect(
    repo: str,
    token: Optional[str],
    since: Optional[str] = None,
    max_prs: Optional[int] = None,
    fetch_merged_by: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[Any, Dict[str, str]]]:
    review_rows: List[Dict[str, Any]] = []
    pr_meta: Dict[Any, Dict[str, str]] = {}  # pr_number -> dict(created, merged)
    n_pr = 0
    skipped = 0
    detail_calls = 0
    detail_failures = 0
    params = {"state": "all", "sort": "created", "direction": "desc", "per_page": 100}
    for pr in paginate(f"/repos/{repo}/pulls", token, params):
        created = pr.get("created_at")
        if since and _month(created) < since:
            # Sorted desc by creation → once we cross the window we can stop.
            break
        if max_prs is not None and n_pr >= max_prs:
            skipped += 1
            continue
        n_pr += 1
        num = pr.get("number")
        author = (pr.get("user") or {}).get("login", "")
        # The API reports the account type; match_login needs it to accept a bare
        # product name like "Copilot" that would otherwise be indistinguishable
        # from a human display name.
        author_is_bot = (pr.get("user") or {}).get("type") == "Bot"
        merged_at = pr.get("merged_at") or ""
        # The list endpoint returns a slimmed PR object without `merged_by`;
        # only GET /pulls/{n} carries it, so merged PRs need one extra call.
        merged_by = ""
        merged_by_is_bot = False
        if merged_at and fetch_merged_by:
            detail_calls += 1
            detail = get_json(f"{API}/repos/{repo}/pulls/{num}", token)
            if detail is None:
                detail_failures += 1
            else:
                merger = detail.get("merged_by") or {}
                merged_by = merger.get("login") or ""
                merged_by_is_bot = merger.get("type") == "Bot"
        a_agent, a_cat = match_login(author, is_bot=author_is_bot)
        m_agent, m_cat = match_login(merged_by, is_bot=merged_by_is_bot)
        pr_meta[num] = {
            "created_at": created or "",
            "merged_at": merged_at,
            "month": _month(created),
            "author": author,
            "author_agent": a_agent or "",
            "author_category": a_cat or "",
            "merged_by": merged_by,
            "merged_by_agent": m_agent or "",
            "merged_by_category": m_cat or "",
        }

        # Inline review comments count for this PR.
        n_comments = 0
        for _ in paginate(f"/repos/{repo}/pulls/{num}/comments", token):
            n_comments += 1

        # Formal reviews (APPROVED / CHANGES_REQUESTED / COMMENTED). Must
        # paginate: the default page size of 30 silently truncates busy PRs.
        reviews = list(paginate(f"/repos/{repo}/pulls/{num}/reviews", token))
        if not reviews:
            # No formal review — still record a stub row so PR is counted.
            review_rows.append({
                "repo_name": repo, "pr_number": num,
                "pr_created_at": created or "", "pr_merged_at": merged_at,
                "reviewer": "", "is_ai_bot": False, "ai_bot_name": "",
                "review_state": "", "submitted_at": "", "n_review_comments": n_comments,
            })
        for rv in reviews:
            login = (rv.get("user") or {}).get("login", "")
            bot = match_review_bot(login)
            review_rows.append({
                "repo_name": repo, "pr_number": num,
                "pr_created_at": created or "", "pr_merged_at": merged_at,
                "reviewer": login,
                "is_ai_bot": bot is not None,
                "ai_bot_name": bot or "",
                "review_state": rv.get("state", ""),
                "submitted_at": rv.get("submitted_at") or "",
                "n_review_comments": n_comments,
            })
    if skipped:
        logging.warning("--max-prs=%s reached: %d PRs skipped (NOT collected)", max_prs, skipped)
    if fetch_merged_by:
        logging.info("merged_by detail calls: %d (%d failed)",
                     detail_calls, detail_failures)
    else:
        logging.info("--no-merged-by set: merged_by left blank for all PRs")
    logging.info("PRs processed: %d  review rows: %d", n_pr, len(review_rows))
    return review_rows, pr_meta


def aggregate_monthly(repo, review_rows, pr_meta):
    prs_opened = defaultdict(set)
    prs_merged = defaultdict(set)
    comments_by_month = defaultdict(list)
    reviews_by_month = defaultdict(int)
    ai_reviews_by_month = defaultdict(int)

    for num, m in pr_meta.items():
        mon = m["month"]
        prs_opened[mon].add(num)
        if m["merged_at"]:
            prs_merged[_month(m["merged_at"])].add(num)

    seen_pr_comment = set()
    for r in review_rows:
        mon = _month(r["pr_created_at"])
        if r["pr_number"] not in seen_pr_comment:
            comments_by_month[mon].append(r["n_review_comments"])
            seen_pr_comment.add(r["pr_number"])
        if r["review_state"]:  # an actual review submission
            rmon = _month(r["submitted_at"]) or mon
            reviews_by_month[rmon] += 1
            if r["is_ai_bot"]:
                ai_reviews_by_month[rmon] += 1

    months = _month_range(list(prs_opened) + list(prs_merged) +
                          list(reviews_by_month))
    out = []
    for mon in months:
        n_rev = reviews_by_month.get(mon, 0)
        n_ai = ai_reviews_by_month.get(mon, 0)
        comments = comments_by_month.get(mon, [])
        out.append({
            "repo_name": repo,
            "month": mon,
            "prs_opened": len(prs_opened.get(mon, ())),
            "prs_merged": len(prs_merged.get(mon, ())),
            "median_review_comments": round(statistics.median(comments), 1) if comments else "",
            "n_reviews": n_rev,
            "n_ai_reviews": n_ai,
            "ai_review_share": round(n_ai / n_rev, 3) if n_rev else "",
        })
    return out


def write_csv(path, rows, cols):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


MARKER_NAME = "review_collection.json"
MARKER_SCHEMA = 1
OUTPUT_FILES = ("reviews.csv", "review_monthly.csv", "prs.csv")


def _run_params(args: argparse.Namespace) -> Dict[str, Any]:
    """The inputs a cached result must match before --resume may reuse it."""
    return {
        "repo": args.repo,
        "since": args.since or "",
        "max_prs": args.max_prs,
        "merged_by": not args.no_merged_by,
    }


def is_complete(out: Path, params: Dict[str, Any]) -> bool:
    """True only if a previous run with the SAME parameters finished and every
    output it promised is still present and non-empty. The marker is cleared
    before collection starts, so interrupted output never counts as complete."""
    try:
        marker = json.loads((out / MARKER_NAME).read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(marker, dict) or marker.get("schema") != MARKER_SCHEMA:
        return False
    if not marker.get("complete") or marker.get("params") != params:
        return False
    return all((out / name).is_file() and (out / name).stat().st_size > 0
               for name in OUTPUT_FILES)


def write_marker(out: Path, params: Dict[str, Any], n_prs: int) -> None:
    (out / MARKER_NAME).write_text(json.dumps({
        "schema": MARKER_SCHEMA,
        "complete": True,
        "params": params,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "outputs": list(OUTPUT_FILES),
        "n_prs": n_prs,
    }, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="owner/name")
    ap.add_argument("out", help="output directory")
    ap.add_argument("--since", help="YYYY-MM lower bound on PR creation month")
    ap.add_argument("--max-prs", type=int, help="cap PRs processed (heaviest calls)")
    ap.add_argument("--no-merged-by", action="store_true",
                    help="skip the per-merged-PR detail call that resolves "
                         "merged_by (saves 1 API call per merged PR, but "
                         "disables the pr_merged AI operation)")
    ap.add_argument("--resume", action="store_true",
                    help="skip this repo entirely when an identical run already "
                         "completed; per-PR calls dominate the API bill, so an "
                         "interrupted batch must not re-spend them")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    params = _run_params(args)
    out = Path(args.out)
    if args.resume and is_complete(out, params):
        logging.info("--resume: %s already collected (%s); skipping",
                     args.repo, out / MARKER_NAME)
        return
    if (out / MARKER_NAME).exists():
        logging.warning("Discarding existing %s: this run supersedes it",
                        MARKER_NAME)
        (out / MARKER_NAME).unlink(missing_ok=True)

    token = get_token()
    if not token:
        logging.warning("No GITHUB_TOKEN found — unauthenticated (60 req/hr).")
    out.mkdir(parents=True, exist_ok=True)

    review_rows, pr_meta = collect(args.repo, token, args.since, args.max_prs,
                                   fetch_merged_by=not args.no_merged_by)
    monthly = aggregate_monthly(args.repo, review_rows, pr_meta)

    write_csv(out / "reviews.csv", review_rows,
              ["repo_name", "pr_number", "pr_created_at", "pr_merged_at", "reviewer",
               "is_ai_bot", "ai_bot_name", "review_state", "submitted_at",
               "n_review_comments"])
    write_csv(out / "review_monthly.csv", monthly,
              ["repo_name", "month", "prs_opened", "prs_merged",
               "median_review_comments", "n_reviews", "n_ai_reviews", "ai_review_share"])

    # PR-level file: who opened / merged each PR + AI attribution (feeds the
    # unified AI-operations view: pr_opened / pr_merged operations).
    pr_rows = [dict(repo_name=args.repo, pr_number=num, **m) for num, m in pr_meta.items()]
    write_csv(out / "prs.csv", pr_rows,
              ["repo_name", "pr_number", "created_at", "merged_at", "month",
               "author", "author_agent", "author_category",
               "merged_by", "merged_by_agent", "merged_by_category"])

    ai_bots = sorted({r["ai_bot_name"] for r in review_rows if r["is_ai_bot"]})
    ai_pr_authors = sorted({m["author_agent"] for m in pr_meta.values()
                            if m["author_category"] == "coding"})
    print(f"repo={args.repo}  PRs={len(pr_meta)}  reviews={sum(1 for r in review_rows if r['review_state'])}")
    print(f"  AI review bots detected: {', '.join(ai_bots) if ai_bots else 'NONE'}")
    print(f"  AI PR authors detected:  {', '.join(ai_pr_authors) if ai_pr_authors else 'NONE'}")
    write_marker(out, params, len(pr_meta))
    print(f"Wrote {out/'reviews.csv'}, {out/'review_monthly.csv'}, "
          f"{out/'prs.csv'}, {MARKER_NAME}")


if __name__ == "__main__":
    main()
