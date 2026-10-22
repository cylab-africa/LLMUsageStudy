#!/usr/bin/env python3
"""
Generalized AI coding-agent usage detector (extends CursorStudy's Cursor-only
`find_cursor_commits` to the whole ecosystem).

Detects adoption of AI coding agents in a git repo via THREE independent signals:
  1. Config/marker files committed (e.g. CLAUDE.md, .cursor/, copilot-instructions.md)
  2. Bot / agent author or committer identities (e.g. Copilot, devin-ai-
     integration[bot]), matched on the commit E-MAIL (%ae/%ce) — never on
     the free-text display name
  3. Commit-message co-author trailers & "generated with" markers
     (how Claude Code, Copilot, Aider, Gemini, etc. actually sign commits)

Each detection records an `operation`:
  commit — an agent identity authored it
  push   — an agent identity applied/committed work it did not author
  merge  — the commit has >1 parent

Outputs, per repo:
  - ai_agent_commits.csv : commit-level detections (which agent, which signal)
  - ai_agent_summary.csv  : per-agent first/last seen (UTC), #commits, #files,
                            signals
Run:  python detect_ai_agents.py /path/to/repo  owner/name  /out/dir
"""
import csv
import logging
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Shared signature tables live in ai_signatures.py (single source of truth).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_signatures import PATH_RES, TEXT_RES, match_login  # noqa: E402

LOG = logging.getLogger("detect_ai_agents")

FS = "\x1f"
N_FIELDS = 8
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
GH_NOREPLY = "users.noreply.github.com"

Meta = Dict[str, Dict[str, str]]
Paths = Dict[str, List[str]]


def git(repo: Path, args: List[str]) -> str:
    """Run a git command in `repo`; log (but do not raise on) failures."""
    proc = subprocess.run(["git", "-C", str(repo)] + args,
                          capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        LOG.warning("git %s in %s failed (rc=%d): %s", " ".join(args[:2]), repo,
                    proc.returncode, proc.stderr.strip()[:300])
    return proc.stdout


def parse_date(value: str) -> datetime:
    """Parse a git %cI timestamp into an aware UTC datetime (epoch on failure)."""
    text = (value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        LOG.warning("unparsable commit date %r", value)
        return EPOCH
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utc_str(value: str) -> str:
    """Normalize a git timestamp to fixed-width UTC ("2024-03-01T09:00:00Z").

    first_seen/last_seen are chosen by true UTC order, so they must also be
    WRITTEN in UTC: emitting the raw offset-bearing %cI string lets the pair read
    first_seen > last_seen, and analyze_single_repo.find_adoption() slices
    first_seen[:7] for the adoption month, which would then be the local month of
    the UTC-earliest commit rather than its real one.
    """
    return parse_date(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def account_login(email: str) -> str:
    """Best-effort account login for a git identity, derived from its e-mail.

    `1234+octocat@users.noreply.github.com` -> `octocat`,
    `cursoragent@cursor.com` -> `cursoragent`, `` -> ``.
    Display names (%an/%cn) are deliberately not used: they are free text, so a
    human contributor named "Claude" or "Cody" must not read as an agent.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return ""
    local, _, domain = email.partition("@")
    if domain == GH_NOREPLY and "+" in local:
        local = local.split("+", 1)[1]
    return local


def collect(repo: Path) -> Tuple[Meta, Paths]:
    """Read commit identities/bodies and changed paths from `git log --all`.

    Records are NUL-delimited (`-z`) and fields are \\x1f-separated, with the
    body taken as the remainder after the 7th separator — so a commit message
    containing either delimiter can neither split a record nor truncate a body.
    """
    fmt = FS.join(["%H", "%cI", "%an", "%ae", "%cn", "%ce", "%P", "%B"])
    raw = git(repo, ["log", "--all", "-z", "--format=" + fmt])
    meta: Meta = {}
    bad = 0
    for rec in raw.split("\0"):
        rec = rec.strip("\n")
        if not rec:
            continue
        parts = rec.split(FS)
        if len(parts) < N_FIELDS:
            bad += 1
            continue
        h = parts[0].strip()
        if not SHA_RE.match(h):
            bad += 1
            continue
        date, an, ae, cn, ce, parents = parts[1:7]
        meta[h] = dict(date=date, an=an, ae=ae, cn=cn, ce=ce,
                       body=FS.join(parts[7:]),
                       operation="merge" if len(parents.split()) > 1 else "commit")
    if bad:
        LOG.warning("collect: skipped %d unparsable commit record(s) in %s", bad, repo)

    # Pass 2: changed paths per commit (non-merges only; merges have no diff here)
    raw2 = git(repo, ["log", "--all", "--no-merges", "--name-only", "--format=%x00%H"])
    paths: Paths = defaultdict(list)
    bad2 = 0
    for chunk in raw2.split("\0"):
        if not chunk.strip():
            continue
        lines = chunk.split("\n")
        h = lines[0].strip()
        if not SHA_RE.match(h):
            bad2 += 1
            continue
        paths[h].extend(ln.strip() for ln in lines[1:] if ln.strip())
    if bad2:
        LOG.warning("collect: skipped %d unparsable name-only record(s) in %s",
                    bad2, repo)
    return meta, paths


def detect(meta: Meta, paths: Paths) -> List[Dict[str, str]]:
    """Return list of per-commit/merge AI detections, attributed by operation."""
    out: List[Dict[str, str]] = []
    for h, m in meta.items():
        blob = "%s <%s> | %s <%s> | %s" % (m["an"], m["ae"], m["cn"], m["ce"],
                                           m["body"])
        hits: Dict[str, Set[str]] = {}
        for agent, res in TEXT_RES.items():
            if any(r.search(blob) for r in res):
                hits.setdefault(agent, set()).add("identity/trailer")

        # Identity attribution runs on the e-mail-derived login, never on %an/%cn.
        a_agent, a_cat = match_login(account_login(m["ae"]), m["ae"])
        if a_cat in ("coding", "review"):
            hits.setdefault(a_agent, set()).add("author-login")
        c_agent, c_cat = match_login(account_login(m["ce"]), m["ce"])
        if c_cat in ("coding", "review"):
            hits.setdefault(c_agent, set()).add("committer-login(push)")

        matched_paths = defaultdict(list)
        for p in paths.get(h, []):
            for agent, res in PATH_RES.items():
                if any(r.search(p) for r in res):
                    hits.setdefault(agent, set()).add("config-file")
                    matched_paths[agent].append(p)

        for agent, signals in hits.items():
            operation = m["operation"]
            # An agent that committed work it did not author applied ("pushed")
            # it; a merge stays a merge, which is the more specific operation.
            if (operation != "merge" and "committer-login(push)" in signals
                    and "author-login" not in signals):
                operation = "push"
            out.append(dict(commit=h, date=m["date"], author=m["an"],
                            committer=m["cn"], operation=operation,
                            agent=agent, signals=";".join(sorted(signals)),
                            files=";".join(sorted(set(matched_paths.get(agent, []))))))
    return out


def write_commits_csv(path: Path, dets: List[Dict[str, str]], cols: List[str]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for d in sorted(dets, key=lambda x: parse_date(x["date"])):
            w.writerow({k: d.get(k, "") for k in cols})


def write_summary_csv(path: Path, name: str,
                      by_agent: Dict[str, List[Dict[str, str]]]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["repo_name", "agent", "n_commits", "first_seen", "last_seen",
                    "signals", "example_files"])
        for agent, ds in sorted(by_agent.items(), key=lambda kv: -len(kv[1])):
            ordered = sorted(ds, key=lambda d: parse_date(d["date"]))
            sigs = sorted({s for d in ds for s in d["signals"].split(";") if s})
            files = sorted({fp for d in ds for fp in d["files"].split(";") if fp})[:5]
            w.writerow([name, agent, len(ds), utc_str(ordered[0]["date"]),
                        utc_str(ordered[-1]["date"]), ";".join(sigs),
                        ";".join(files)])


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: detect_ai_agents.py /path/to/repo [owner/name] [/out/dir]",
              file=sys.stderr)
        return 2
    repo = Path(argv[0])
    if not (repo / ".git").exists() and not (repo / "HEAD").exists():
        LOG.error("not a git repository: %s", repo)
        return 2
    name = argv[1] if len(argv) > 1 else repo.name
    out = Path(argv[2]) if len(argv) > 2 else Path(".")
    out.mkdir(parents=True, exist_ok=True)

    total_commits = int(git(repo, ["rev-list", "--all", "--count"]).strip() or 0)
    meta, paths = collect(repo)
    if total_commits and not meta:
        LOG.error("parsed 0 commits from %s but rev-list reports %d", repo,
                  total_commits)
        return 1
    if total_commits and len(meta) < total_commits:
        LOG.warning("parsed %d of %d commits in %s; %d record(s) unaccounted for",
                    len(meta), total_commits, repo, total_commits - len(meta))
    dets = detect(meta, paths)
    for d in dets:
        d["repo_name"] = name

    cf = out / "ai_agent_commits.csv"
    cols = ["repo_name", "agent", "operation", "commit", "date", "author",
            "committer", "signals", "files"]
    write_commits_csv(cf, dets, cols)

    by_agent: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for d in dets:
        by_agent[d["agent"]].append(d)
    sf = out / "ai_agent_summary.csv"
    write_summary_csv(sf, name, by_agent)

    print("repo=%s  total_commits(incl. merges)=%d" % (name, total_commits))
    print("AI-agent-attributed commits/merges: %d" % len(dets))
    if by_agent:
        for agent, ds in sorted(by_agent.items(), key=lambda kv: -len(kv[1])):
            ordered = sorted(ds, key=lambda d: parse_date(d["date"]))
            print("  - %-28s %4d commits  first=%s last=%s (UTC)"
                  % (agent, len(ds), utc_str(ordered[0]["date"])[:10],
                     utc_str(ordered[-1]["date"])[:10]))
    else:
        print("  NO AI coding-agent usage detected (any agent, any signal).")
    print("\nWrote: %s\n       %s" % (cf, sf))
    return 0


if __name__ == "__main__":
    sys.exit(main())
