#!/usr/bin/env python3
"""
Generalized AI coding-agent usage detector (extends CursorStudy's Cursor-only
`find_cursor_commits` to the whole ecosystem).

Detects adoption of AI coding agents in a git repo via THREE independent signals:
  1. Config/marker files committed (e.g. CLAUDE.md, .cursor/, copilot-instructions.md)
  2. Bot / agent author or committer identities (e.g. Copilot, devin-ai-integration[bot])
  3. Commit-message co-author trailers & "generated with" markers
     (how Claude Code, Copilot, Aider, Gemini, etc. actually sign commits)

Outputs, per repo:
  - ai_agent_commits.csv : commit-level detections (which agent, which signal)
  - ai_agent_summary.csv  : per-agent first/last seen, #commits, #files, signals
Run:  python detect_ai_agents.py /path/to/repo  owner/name  /out/dir
"""
import csv
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# Shared signature tables live in ai_signatures.py (single source of truth).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_signatures import PATH_RES, TEXT_RES, match_login  # noqa: E402

RS, FS = "\x1e", "\x1f"


def git(repo, args):
    return subprocess.run(["git", "-C", str(repo)] + args,
                          capture_output=True, text=True, errors="replace").stdout


def collect(repo):
    # Pass 1: identity + full body per commit, INCLUDING merges (%P = parents).
    fmt = FS.join(["%H", "%cI", "%an", "%ae", "%cn", "%ce", "%P", "%B"]) + RS
    raw = git(repo, ["log", "--all", f"--format={fmt}"])
    meta = {}
    for rec in raw.split(RS):
        rec = rec.strip("\n")
        if not rec:
            continue
        parts = rec.split(FS)
        if len(parts) < 8:
            continue
        h, date, an, ae, cn, ce, parents, body = parts[:8]
        is_merge = len(parents.split()) > 1
        meta[h] = dict(date=date, an=an, ae=ae, cn=cn, ce=ce, body=body,
                       operation="merge" if is_merge else "commit")

    # Pass 2: changed paths per commit (non-merges only; merges have no diff here)
    raw2 = git(repo, ["log", "--all", "--no-merges", "--name-only",
                      f"--format={RS}%H"])
    paths = defaultdict(list)
    cur = None
    for line in raw2.split("\n"):
        if line.startswith(RS):
            cur = line[1:].strip()
        elif line.strip() and cur:
            paths[cur].append(line.strip())
    return meta, paths


def detect(meta, paths):
    """Return list of per-commit/merge AI detections, attributed by operation."""
    out = []
    for h, m in meta.items():
        blob = "%s <%s> | %s <%s> | %s" % (m["an"], m["ae"], m["cn"], m["ce"], m["body"])
        hits = {}  # agent -> set(signals)
        # 1) identity + commit-message trailer signals
        for agent, res in TEXT_RES.items():
            if any(r.search(blob) for r in res):
                hits.setdefault(agent, set()).add("identity/trailer")
        # 2) login-based attribution — author wrote it, committer applied/pushed it
        a_agent, a_cat = match_login(m["an"])
        if a_cat in ("coding", "review"):
            hits.setdefault(a_agent, set()).add("author-login")
        c_agent, c_cat = match_login(m["cn"])
        if c_cat in ("coding", "review"):
            hits.setdefault(c_agent, set()).add("committer-login(push)")
        # 3) config/marker file paths (non-merges only)
        matched_paths = defaultdict(list)
        for p in paths.get(h, []):
            for agent, res in PATH_RES.items():
                if any(r.search(p) for r in res):
                    hits.setdefault(agent, set()).add("config-file")
                    matched_paths[agent].append(p)
        for agent, signals in hits.items():
            out.append(dict(commit=h, date=m["date"], author=m["an"],
                            committer=m["cn"], operation=m["operation"],
                            agent=agent, signals=";".join(sorted(signals)),
                            files=";".join(sorted(set(matched_paths.get(agent, []))))))
    return out


def main():
    repo = Path(sys.argv[1])
    name = sys.argv[2] if len(sys.argv) > 2 else repo.name
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(".")
    out.mkdir(parents=True, exist_ok=True)

    total_commits = int(git(repo, ["rev-list", "--all", "--count"]).strip() or 0)
    meta, paths = collect(repo)
    dets = detect(meta, paths)
    for d in dets:
        d["repo_name"] = name

    # commit-level CSV (now includes merges + operation + committer)
    cf = out / "ai_agent_commits.csv"
    cols = ["repo_name", "agent", "operation", "commit", "date", "author",
            "committer", "signals", "files"]
    with cf.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for d in sorted(dets, key=lambda x: x["date"]):
            w.writerow({k: d.get(k, "") for k in cols})

    # per-agent summary
    by_agent = defaultdict(list)
    for d in dets:
        by_agent[d["agent"]].append(d)
    sf = out / "ai_agent_summary.csv"
    with sf.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["repo_name", "agent", "n_commits", "first_seen", "last_seen",
                    "signals", "example_files"])
        for agent, ds in sorted(by_agent.items(), key=lambda kv: -len(kv[1])):
            dates = sorted(d["date"] for d in ds)
            sigs = sorted({s for d in ds for s in d["signals"].split(";") if s})
            files = sorted({fp for d in ds for fp in d["files"].split(";") if fp})[:5]
            w.writerow([name, agent, len(ds), dates[0], dates[-1],
                        ";".join(sigs), ";".join(files)])

    print(f"repo={name}  total_commits(incl. merges)={total_commits}")
    print(f"AI-agent-attributed commits/merges: {len(dets)}")
    if by_agent:
        for agent, ds in sorted(by_agent.items(), key=lambda kv: -len(kv[1])):
            dd = sorted(d["date"] for d in ds)
            print(f"  - {agent:28s} {len(ds):4d} commits  first={dd[0][:10]} last={dd[-1][:10]}")
    else:
        print("  NO AI coding-agent usage detected (any agent, any signal).")
    print(f"\nWrote: {cf}\n       {sf}")


if __name__ == "__main__":
    main()
