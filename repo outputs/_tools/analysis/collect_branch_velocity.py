#!/usr/bin/env python3
"""Branch-scope velocity, collected directly from local clones.

Produces the two things the panel cannot supply, because the panel records
all-branch activity only:

  velocity_develop_monthly.csv  monthly commits / lines / authors on the
                                INTEGRATION branch (develop where it exists,
                                else the repository default) -- the same tree
                                the SonarQube snapshots analyse
  branch_scope.csv              commits reachable from master, develop and all
                                branches, per repository -- the evidence for
                                the branch-scope table in the paper

WHY THIS EXISTS
MOSIP follows gitflow and no single branch captures development: roughly 30%
of commits are reachable from the repository default, 45% from `develop`, and
the remainder sit on feature branches merged into neither. Any velocity figure
therefore depends on a branch choice that has to be stated and defended, so
the numbers behind that choice are collected here rather than by hand.

USAGE
    python collect_branch_velocity.py --clones /path/to/clones \
        [--since 2025-01-01] [--until 2026-09-01] [--out repo outputs/analytics]

`--clones` is a directory of bare-or-working clones named after the repository
(e.g. `esignet/`). Remote-tracking refs must be present: clone normally, do not
use `--single-branch`.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

RS = "\x1e"


def git(repo: Path, *args: str) -> str:
    """Read-only git query. Returns '' on failure rather than raising, since a
    missing branch is an expected condition here, not an error."""
    p = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, errors="replace")
    return p.stdout if p.returncode == 0 else ""


def has_ref(repo: Path, ref: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", ref],
                          capture_output=True).returncode == 0


def default_branch(repo: Path) -> str:
    """The repository's own default branch, from origin/HEAD."""
    s = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
    if s.startswith("origin/"):
        return s[len("origin/"):]
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()


def count(repo: Path, ref: str, since: str, until: str) -> int:
    if ref != "--all" and not has_ref(repo, ref):
        return 0
    args = ["rev-list", "--count", f"--since={since}", f"--until={until}", ref]
    out = git(repo, *args).strip()
    return int(out) if out.isdigit() else 0


def integration_branch(repo: Path) -> str:
    """develop if it exists, else the repository default."""
    return "develop" if has_ref(repo, "origin/develop") else default_branch(repo)


def monthly(repo: Path, branch: str, since: str, until: str) -> list[dict]:
    """Per-month commits, lines added/removed and distinct authors on `branch`."""
    ref = f"origin/{branch}"
    if not has_ref(repo, ref):
        return []
    fmt = f"{RS}%cd\x1f%ae"
    raw = git(repo, "log", ref, f"--since={since}", f"--until={until}",
              f"--format={fmt}", "--date=format:%Y-%m", "--numstat")
    stats: dict[str, dict] = defaultdict(
        lambda: {"commits": 0, "add": 0, "rem": 0, "authors": set()})
    cur = None
    for line in raw.split("\n"):
        if line.startswith(RS):
            rec = line[1:].split("\x1f")
            if len(rec) < 2:
                cur = None
                continue
            cur, email = rec[0], rec[1]
            stats[cur]["commits"] += 1
            stats[cur]["authors"].add(email)
        elif cur and line.strip():
            parts = line.split("\t")
            if len(parts) >= 2:
                if parts[0] != "-":
                    stats[cur]["add"] += int(parts[0] or 0)
                if parts[1] != "-":
                    stats[cur]["rem"] += int(parts[1] or 0)
    return [dict(month=m, branch=branch, commits=v["commits"],
                 lines_added=v["add"], lines_removed=v["rem"],
                 authors=len(v["authors"]))
            for m, v in sorted(stats.items())]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clones", required=True,
                    help="directory holding one clone per repository")
    ap.add_argument("--owner", default="mosip")
    ap.add_argument("--since", default="2025-01-01")
    ap.add_argument("--until", default="2026-09-01")
    ap.add_argument("--out", default="repo outputs/analytics")
    a = ap.parse_args()

    root = Path(a.clones).expanduser()
    if not root.is_dir():
        sys.exit(f"no such directory: {root}")
    repos = sorted(p for p in root.iterdir() if (p / ".git").exists())
    if not repos:
        sys.exit(f"no git clones found under {root}")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    scope_rows, vel_rows = [], []
    for repo in repos:
        name = f"{a.owner}/{repo.name}"
        dflt = default_branch(repo)
        integ = integration_branch(repo)
        scope_rows.append(dict(
            repo_name=name, default_branch=dflt,
            master=count(repo, "origin/master", a.since, a.until),
            develop=count(repo, "origin/develop", a.since, a.until),
            default=count(repo, f"origin/{dflt}", a.since, a.until),
            all_branches=count(repo, "--all", a.since, a.until)))
        for r in monthly(repo, integ, a.since, a.until):
            r["repo_name"] = name
            vel_rows.append(r)
        print("  %-32s default=%-8s integration=%s" % (repo.name, dflt, integ))

    sp = out / "branch_scope.csv"
    with sp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["repo_name", "default_branch", "master",
                                          "develop", "default", "all_branches"])
        w.writeheader()
        w.writerows(scope_rows)

    vp = out / "velocity_develop_monthly.csv"
    cols = ["repo_name", "month", "branch", "commits", "lines_added",
            "lines_removed", "authors"]
    with vp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in vel_rows:
            w.writerow({k: r.get(k, "") for k in cols})

    tot_m = sum(r["master"] for r in scope_rows)
    tot_d = sum(r["develop"] for r in scope_rows)
    tot_a = sum(r["all_branches"] for r in scope_rows)
    print("\n%d repositories, %s .. %s" % (len(scope_rows), a.since, a.until))
    print("  master   %6d  (%.0f%% of all)" % (tot_m, 100 * tot_m / max(tot_a, 1)))
    print("  develop  %6d  (%.0f%%)" % (tot_d, 100 * tot_d / max(tot_a, 1)))
    print("  all      %6d" % tot_a)
    print("  (counts overlap: a merged commit is reachable from both branches)")
    print("\nwrote %s\n      %s" % (sp, vp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
