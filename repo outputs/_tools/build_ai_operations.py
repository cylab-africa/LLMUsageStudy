#!/usr/bin/env python3
"""
Unify every AI-attributable operation in a repo into one view, and define
AI adoption as the FIRST TRACKABLE AI ACTION OF ANY KIND — not merely the first
commit of a config file (CLAUDE.md / AGENTS.md / .cursor/...).

Reads whatever collectors produced in the report dir:
  ai_agent_commits.csv  -> commit / merge  (author wrote, committer pushed/applied)
  prs.csv               -> pr_opened / pr_merged
  reviews.csv           -> pr_reviewed
  issues.csv            -> issue_opened / issue_closed

Writes:
  ai_operations.csv  — one row per AI operation: date, date_utc, agent, operation,
                       category, actor, ref, signal
  ai_adoption.csv    — per-agent first action (date/op) + operation counts, and a
                       final row agent="__OVERALL__" = earliest AI action in repo

"category" is coding | review | other-bot. 'other-bot' automation (dependabot,
CI, release bots — whatever ai_signatures.match_login classifies as other-bot)
is recorded in ai_operations.csv for transparency but EXCLUDED from adoption.
other-bot rows come from the GitHub-actor sources only (PR author / merger, PR
reviewer, issue author / closer): ai_agent_commits.csv contains AI detections
exclusively, so non-AI bot commits are not visible to this script.

Dates arrive in two incomparable string formats — git writes strict ISO with a
real UTC offset ("2026-04-28T17:44:20+05:30"), the GitHub API writes Zulu
("2025-11-05T15:47:23Z") — so every date is parsed to an aware UTC datetime
before any sort/min, and the normalized value is written out as "date_utc".

Usage:  python build_ai_operations.py /path/to/repo_report/<owner_repo>
"""
import csv
import logging
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_signatures import match_login, match_review_bot  # noqa: E402

AI_CATEGORIES = ("coding", "review")
OP_COLS = ["date", "date_utc", "agent", "operation", "category", "actor", "ref",
           "signal"]
ADOPTION_COLS = ["agent", "category", "first_action_date", "first_action_date_utc",
                 "first_operation", "first_ref", "n_operations",
                 "operations_breakdown"]
_COMPACT_TZ = re.compile(r"([+-]\d{2})(\d{2})$")


def read(path: Path) -> List[Dict[str, str]]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def parse_date(value: str) -> Optional[datetime]:
    """Parse a git ('...+05:30') or GitHub ('...Z') stamp to an aware UTC datetime.

    Naive stamps are read as UTC. Returns None for anything unusable so callers
    can count what they drop rather than sort garbage.
    """
    s = (value or "").strip()
    if not s:
        return None
    if s[-1] in "Zz":
        s = s[:-1] + "+00:00"
    # tolerate git's `%ci` spelling ("2026-04-28 17:44:20 +0530") as well as %cI
    s = s.replace(" ", "T", 1).replace(" ", "")
    s = _COMPACT_TZ.sub(r"\1:\2", s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_dates(ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach an aware-UTC datetime ('_dt') + 'date_utc' string to every op.

    Ops whose date is missing or unparseable are dropped, but never silently:
    each class is counted and logged.
    """
    kept: List[Dict[str, Any]] = []
    missing = 0
    unparseable = 0
    for o in ops:
        dt = parse_date(o.get("date", ""))
        if dt is None:
            if (o.get("date") or "").strip():
                unparseable += 1
                logging.debug("unparseable date %r on %s %s", o.get("date"),
                              o.get("operation"), o.get("ref"))
            else:
                missing += 1
            continue
        # fixed-width UTC so the column is also safe to sort lexicographically
        o["date_utc"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        o["_dt"] = dt
        kept.append(o)
    if missing:
        logging.warning("dropped %d operation(s) with an empty date", missing)
    if unparseable:
        logging.warning("dropped %d operation(s) with an unparseable date "
                        "(each listed at DEBUG level)", unparseable)
    return kept


def agent_category(agent: str) -> str:
    """review-bot names are category 'review'; everything else coding."""
    _, cat = match_login(agent)
    if cat in AI_CATEGORIES:
        return cat
    # agent came from a name/trailer, not a login; classify by review-bot match
    return "review" if match_review_bot(agent) else "coding"


def build(report: Path) -> List[Dict[str, Any]]:
    ops: List[Dict[str, Any]] = []

    # --- commits & merges ---
    for r in read(report / "ai_agent_commits.csv"):
        op = r.get("operation") or "commit"
        # committer-login(push) signal => the AI pushed/applied it
        sig = r.get("signals", "")
        actor = r.get("author", "")
        if "committer-login(push)" in sig and "author-login" not in sig:
            actor = r.get("committer", "") or actor
        ops.append(dict(date=r.get("date", ""), agent=r.get("agent", ""),
                        operation=op, category=agent_category(r.get("agent", "")),
                        actor=actor, ref=r.get("commit", "")[:12], signal=sig))

    # --- PRs opened / merged ---
    for r in read(report / "prs.csv"):
        a_cat = r.get("author_category") or ""
        if a_cat in ("coding", "other-bot") and r.get("author_agent"):
            ops.append(dict(date=r.get("created_at", ""), agent=r["author_agent"],
                            operation="pr_opened", category=a_cat,
                            actor=r.get("author", ""),
                            ref=f"PR#{r.get('pr_number','')}",
                            signal="pr-author-login"))
        m_cat = r.get("merged_by_category") or ""
        if m_cat in ("coding", "review", "other-bot") and r.get("merged_by_agent"):
            ops.append(dict(date=r.get("merged_at", ""), agent=r["merged_by_agent"],
                            operation="pr_merged", category=m_cat,
                            actor=r.get("merged_by", ""),
                            ref=f"PR#{r.get('pr_number','')}",
                            signal="pr-merged-by-login"))

    # --- PR reviews ---
    for r in read(report / "reviews.csv"):
        date = r.get("submitted_at", "") or r.get("pr_created_at", "")
        ref = f"PR#{r.get('pr_number','')}"
        reviewer = r.get("reviewer", "")
        if str(r.get("is_ai_bot")).lower() == "true" and r.get("ai_bot_name"):
            ops.append(dict(date=date, agent=r["ai_bot_name"],
                            operation="pr_reviewed", category="review",
                            actor=reviewer, ref=ref, signal="review-login"))
            continue
        bot, cat = match_login(reviewer)
        if cat == "other-bot":
            ops.append(dict(date=date, agent=bot, operation="pr_reviewed",
                            category=cat, actor=reviewer, ref=ref,
                            signal="review-login"))

    # --- issue open / close ---
    for r in read(report / "issues.csv"):
        ref = f"issue#{r.get('number','')}"
        author = r.get("author", "")
        a_bot, a_cat = match_login(author)
        a_agent = r.get("author_ai_agent") or (a_bot if a_cat == "other-bot" else "")
        if a_agent:
            ops.append(dict(date=r.get("created_at", ""), agent=a_agent,
                            operation="issue_opened", category=a_cat or "coding",
                            actor=author, ref=ref, signal="issue-author-login"))
        closed_by = r.get("closed_by", "")
        c_bot, c_cat = match_login(closed_by)
        c_agent = (r.get("closed_by_ai_agent")
                   or (c_bot if c_cat == "other-bot" else ""))
        if c_agent:
            ops.append(dict(date=r.get("closed_at", ""), agent=c_agent,
                            operation="issue_closed", category=c_cat or "coding",
                            actor=closed_by, ref=ref,
                            signal="issue-closed-by-login"))

    ops = normalize_dates(ops)
    ops.sort(key=lambda o: o["_dt"])
    return ops


def adoption_table(ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-agent first action + operation counts; overall earliest AI action.
    Only coding/review categories count toward adoption (not other-bot)."""
    ai_ops = [o for o in ops if o["category"] in AI_CATEGORIES]
    by_agent = defaultdict(list)
    for o in ai_ops:
        by_agent[o["agent"]].append(o)
    rows: List[Dict[str, Any]] = []
    for agent, os_ in sorted(by_agent.items(),
                             key=lambda kv: min(o["_dt"] for o in kv[1])):
        opcount = defaultdict(int)
        for o in os_:
            opcount[o["operation"]] += 1
        first = min(os_, key=lambda o: o["_dt"])
        rows.append({
            "agent": agent,
            "category": first["category"],
            # Emit the normalized instant, NOT the raw offset-bearing string:
            # the row is chosen by UTC, so a local-offset date here would yield a
            # month that is neither min(raw) nor min(UTC) and can only push real
            # AI activity into the "pre-adoption" bucket. Consumers take
            # first_action_date[:7] as the split point.
            "first_action_date": first["date_utc"],
            "first_action_date_utc": first["date_utc"],
            "first_operation": first["operation"],
            "first_ref": first["ref"],
            "n_operations": len(os_),
            "operations_breakdown": ";".join(f"{k}={opcount[k]}"
                                             for k in sorted(opcount)),
        })
    if ai_ops:
        earliest = min(ai_ops, key=lambda o: o["_dt"])
        opcount = defaultdict(int)
        for o in ai_ops:
            opcount[o["operation"]] += 1
        rows.append({
            "agent": "__OVERALL__",
            "category": "",
            "first_action_date": earliest["date_utc"],
            "first_action_date_utc": earliest["date_utc"],
            "first_operation": f"{earliest['operation']} by {earliest['agent']}",
            "first_ref": earliest["ref"],
            "n_operations": len(ai_ops),
            "operations_breakdown": ";".join(f"{k}={opcount[k]}"
                                             for k in sorted(opcount)),
        })
    return rows


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    if len(sys.argv) < 2:
        sys.exit("usage: build_ai_operations.py <report_dir>")
    report = Path(sys.argv[1])
    ops = build(report)
    adoption = adoption_table(ops)

    with (report / "ai_operations.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OP_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(ops)
    with (report / "ai_adoption.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ADOPTION_COLS)
        w.writeheader()
        w.writerows(adoption)

    ai_ops = [o for o in ops if o["category"] in AI_CATEGORIES]
    print(f"AI operations (coding+review): {len(ai_ops)}  "
          f"(+{len(ops)-len(ai_ops)} other-bot, excluded from adoption)")
    opcount = defaultdict(int)
    for o in ai_ops:
        opcount[o["operation"]] += 1
    for k in sorted(opcount, key=lambda k: -opcount[k]):
        print(f"    {k:14s} {opcount[k]}")
    overall = next((r for r in adoption if r["agent"] == "__OVERALL__"), None)
    if overall:
        print(f"FIRST AI ACTION (adoption): {overall['first_action_date_utc'][:10]} UTC"
              f"  {overall['first_operation']}  ({overall['first_ref']})")
    else:
        print("No AI operations detected.")
    print(f"Wrote ai_operations.csv, ai_adoption.csv to {report}/")


if __name__ == "__main__":
    main()
