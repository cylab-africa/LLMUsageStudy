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
  ai_operations.csv  — one row per AI operation: date, agent, operation, category,
                       actor, ref, signal
  ai_adoption.csv    — per-agent first action (date/op) + operation counts, and a
                       final row agent="__OVERALL__" = earliest AI action in repo

"category" is coding | review; 'other-bot' automation (dependabot/CI) is recorded
in ai_operations.csv for transparency but EXCLUDED from adoption.

Usage:  python build_ai_operations.py /path/to/repo_report/<owner_repo>
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_signatures import match_login  # noqa: E402


def read(path):
    p = Path(path)
    return list(csv.DictReader(p.open())) if p.exists() else []


def agent_category(agent):
    """review-bot names are category 'review'; everything else coding."""
    _, cat = match_login(agent)
    if cat in ("review", "coding"):
        return cat
    # agent came from a name/trailer, not a login; classify by review-bot match
    from ai_signatures import match_review_bot
    return "review" if match_review_bot(agent) else "coding"


def build(report):
    ops = []  # dict rows

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
        if r.get("author_category") == "coding" and r.get("author_agent"):
            ops.append(dict(date=r.get("created_at", ""), agent=r["author_agent"],
                            operation="pr_opened", category="coding",
                            actor=r.get("author", ""), ref=f"PR#{r.get('pr_number','')}",
                            signal="pr-author-login"))
        if r.get("merged_by_category") in ("coding", "review") and r.get("merged_by_agent"):
            ops.append(dict(date=r.get("merged_at", ""), agent=r["merged_by_agent"],
                            operation="pr_merged", category=r["merged_by_category"],
                            actor=r.get("merged_by", ""), ref=f"PR#{r.get('pr_number','')}",
                            signal="pr-merged-by-login"))

    # --- PR reviews ---
    for r in read(report / "reviews.csv"):
        if str(r.get("is_ai_bot")).lower() == "true" and r.get("ai_bot_name"):
            ops.append(dict(date=r.get("submitted_at", "") or r.get("pr_created_at", ""),
                            agent=r["ai_bot_name"], operation="pr_reviewed",
                            category="review", actor=r.get("reviewer", ""),
                            ref=f"PR#{r.get('pr_number','')}", signal="review-login"))

    # --- issue open / close ---
    for r in read(report / "issues.csv"):
        if r.get("author_ai_agent"):
            _, cat = match_login(r.get("author", ""))
            ops.append(dict(date=r.get("created_at", ""), agent=r["author_ai_agent"],
                            operation="issue_opened", category=cat or "coding",
                            actor=r.get("author", ""), ref=f"issue#{r.get('number','')}",
                            signal="issue-author-login"))
        if r.get("closed_by_ai_agent"):
            _, cat = match_login(r.get("closed_by", ""))
            ops.append(dict(date=r.get("closed_at", ""), agent=r["closed_by_ai_agent"],
                            operation="issue_closed", category=cat or "coding",
                            actor=r.get("closed_by", ""), ref=f"issue#{r.get('number','')}",
                            signal="issue-closed-by-login"))

    ops = [o for o in ops if o["date"]]
    ops.sort(key=lambda o: o["date"])
    return ops


def adoption_table(ops):
    """Per-agent first action + operation counts; overall earliest AI action.
    Only coding/review categories count toward adoption (not other-bot)."""
    ai_ops = [o for o in ops if o["category"] in ("coding", "review")]
    by_agent = defaultdict(list)
    for o in ai_ops:
        by_agent[o["agent"]].append(o)
    rows = []
    for agent, os_ in sorted(by_agent.items(), key=lambda kv: min(o["date"] for o in kv[1])):
        opcount = defaultdict(int)
        for o in os_:
            opcount[o["operation"]] += 1
        first = min(os_, key=lambda o: o["date"])
        rows.append({
            "agent": agent,
            "category": first["category"],
            "first_action_date": first["date"],
            "first_operation": first["operation"],
            "first_ref": first["ref"],
            "n_operations": len(os_),
            "operations_breakdown": ";".join(f"{k}={opcount[k]}" for k in sorted(opcount)),
        })
    if ai_ops:
        earliest = min(ai_ops, key=lambda o: o["date"])
        opcount = defaultdict(int)
        for o in ai_ops:
            opcount[o["operation"]] += 1
        rows.append({
            "agent": "__OVERALL__",
            "category": "",
            "first_action_date": earliest["date"],
            "first_operation": f"{earliest['operation']} by {earliest['agent']}",
            "first_ref": earliest["ref"],
            "n_operations": len(ai_ops),
            "operations_breakdown": ";".join(f"{k}={opcount[k]}" for k in sorted(opcount)),
        })
    return rows


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: build_ai_operations.py <report_dir>")
    report = Path(sys.argv[1])
    ops = build(report)
    adoption = adoption_table(ops)

    with (report / "ai_operations.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "agent", "operation", "category",
                                          "actor", "ref", "signal"])
        w.writeheader()
        w.writerows(ops)
    with (report / "ai_adoption.csv").open("w", newline="") as f:
        cols = ["agent", "category", "first_action_date", "first_operation",
                "first_ref", "n_operations", "operations_breakdown"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(adoption)

    ai_ops = [o for o in ops if o["category"] in ("coding", "review")]
    print(f"AI operations (coding+review): {len(ai_ops)}  "
          f"(+{len(ops)-len(ai_ops)} other-bot, excluded from adoption)")
    opcount = defaultdict(int)
    for o in ai_ops:
        opcount[o["operation"]] += 1
    for k in sorted(opcount, key=lambda k: -opcount[k]):
        print(f"    {k:14s} {opcount[k]}")
    overall = next((r for r in adoption if r["agent"] == "__OVERALL__"), None)
    if overall:
        print(f"FIRST AI ACTION (adoption): {overall['first_action_date'][:10]}  "
              f"{overall['first_operation']}  ({overall['first_ref']})")
    else:
        print("No AI operations detected.")
    print(f"Wrote ai_operations.csv, ai_adoption.csv to {report}/")


if __name__ == "__main__":
    main()
