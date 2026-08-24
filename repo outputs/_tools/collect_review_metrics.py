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
  python collect_review_metrics.py owner/name /out/dir [--since 2023-01] [--max-prs N]
"""
import argparse
import csv
import logging
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_signatures import match_login, match_review_bot  # noqa: E402
from gh_rest import get_json, get_token, paginate  # noqa: E402


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


def collect(repo, token, since=None, max_prs=None):
    review_rows = []
    pr_meta = {}  # pr_number -> dict(created, merged)
    n_pr = 0
    skipped = 0
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
        merged_by = (pr.get("merged_by") or {}).get("login", "") if pr.get("merged_by") else ""
        a_agent, a_cat = match_login(author)
        m_agent, m_cat = match_login(merged_by)
        pr_meta[num] = {
            "created_at": created or "",
            "merged_at": pr.get("merged_at") or "",
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

        # Formal reviews (APPROVED / CHANGES_REQUESTED / COMMENTED).
        reviews = get_json(
            f"https://api.github.com/repos/{repo}/pulls/{num}/reviews", token) or []
        if not reviews:
            # No formal review — still record a stub row so PR is counted.
            review_rows.append({
                "repo_name": repo, "pr_number": num,
                "pr_created_at": created or "", "pr_merged_at": pr.get("merged_at") or "",
                "reviewer": "", "is_ai_bot": False, "ai_bot_name": "",
                "review_state": "", "submitted_at": "", "n_review_comments": n_comments,
            })
        for rv in reviews:
            login = (rv.get("user") or {}).get("login", "")
            bot = match_review_bot(login)
            review_rows.append({
                "repo_name": repo, "pr_number": num,
                "pr_created_at": created or "", "pr_merged_at": pr.get("merged_at") or "",
                "reviewer": login,
                "is_ai_bot": bot is not None,
                "ai_bot_name": bot or "",
                "review_state": rv.get("state", ""),
                "submitted_at": rv.get("submitted_at") or "",
                "n_review_comments": n_comments,
            })
    if skipped:
        logging.warning("--max-prs=%s reached: %d PRs skipped (NOT collected)", max_prs, skipped)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="owner/name")
    ap.add_argument("out", help="output directory")
    ap.add_argument("--since", help="YYYY-MM lower bound on PR creation month")
    ap.add_argument("--max-prs", type=int, help="cap PRs processed (heaviest calls)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    token = get_token()
    if not token:
        logging.warning("No GITHUB_TOKEN found — unauthenticated (60 req/hr).")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    review_rows, pr_meta = collect(args.repo, token, args.since, args.max_prs)
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
    print(f"Wrote {out/'reviews.csv'}, {out/'review_monthly.csv'}, {out/'prs.csv'}")


if __name__ == "__main__":
    main()
