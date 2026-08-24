#!/usr/bin/env python3
"""
AI-Impact orchestrator: one command to evaluate a single repo end-to-end.

Wraps repo outputs/RUNBOOK.md into an automated pipeline:
  clone -> enumerate branches -> (Docker SonarQube) -> study velocity+quality
  scripts -> AI-agent detection -> GitHub issue/review collectors -> merge into
  repo_report/<owner_repo>/ -> single-repo before/after analysis.

Reuses the study's own scripts/*.py (does not reimplement velocity/SonarQube).
Every stage is skippable so config-only repos or no-token runs still produce the
git-only half.

Usage:
  python run_ai_impact.py --repo-url https://github.com/OWNER/NAME.git \
     --out "repo outputs/repo_report" [--port 9011] [--since 2023-01] \
     [--skip-sonar] [--skip-github] [--max-prs 300] [--keep-workspace]

Prereqs: Docker Desktop running (unless --skip-sonar), Python 3.10+, git.
GITHUB_TOKEN in env or <study>/.env enables issue/review collection.
"""
import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
STUDY = TOOLS.parent.parent  # repo outputs/_tools -> repo outputs -> CursorStudy
SCRIPTS = STUDY / "scripts"


def run(cmd, **kw):
    logging.info("$ %s", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, **kw)


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, text=True, capture_output=True, **kw)


def owner_name_from_url(url):
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not m:
        sys.exit(f"Cannot parse owner/name from {url}")
    return f"{m.group(1)}/{m.group(2)}"


def wait_sonar_up(port, timeout=300):
    url = f"http://localhost:{port}/api/system/status"
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if b'"status":"UP"' in r.read():
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def curl(args):
    return sh("curl -s " + args).stdout


def setup_sonar(port, container):
    logging.info("Starting Dockerized SonarQube on port %s ...", port)
    sh(f"docker rm -f {container} 2>/dev/null")
    run(["docker", "run", "-d", "--name", container, "-p", f"{port}:9000",
         "-e", "SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true", "sonarqube:community"])
    sh("docker pull sonarsource/sonar-scanner-cli")
    if not wait_sonar_up(port):
        sys.exit("SonarQube did not come UP within timeout")
    newpass = "AiImpact!Scan2026"
    curl(f'-u admin:admin -X POST "http://localhost:{port}/api/users/change_password" '
         f'-d "login=admin&previousPassword=admin&password={newpass}"')
    tok_json = curl(f'-u admin:{newpass} -X POST '
                    f'"http://localhost:{port}/api/user_tokens/generate" -d "name=scan-{port}"')
    try:
        token = json.loads(tok_json)["token"]
    except Exception:
        sys.exit(f"Could not mint SonarQube token: {tok_json[:200]}")
    return token


def build_workspace(ws, repo_name, repo_clone, port, token):
    """Recreate the RUNBOOK §6 isolated workspace so study scripts never touch data/."""
    cs = ws / "CursorStudy"
    (cs / "data").mkdir(parents=True, exist_ok=True)
    (ws / "CursorRepos").mkdir(parents=True, exist_ok=True)
    if (cs / "scripts").exists():
        shutil.rmtree(cs / "scripts")
    shutil.copytree(SCRIPTS, cs / "scripts")
    (cs / "scripts" / "__init__.py").touch()
    (cs / "data" / "repos.csv").write_text(f"repo_name\n{repo_name}\n")
    dest = ws / "CursorRepos" / repo_name.replace("/", "_")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(repo_clone, dest)
    scanner = ws / "sonar-scanner.sh"
    (cs / ".env").write_text(
        f"GITHUB_TOKEN=unused\nSONAR_TOKEN={token}\n"
        f"SONAR_HOST=http://localhost:{port}\nSONAR_SCANNER_PATH={scanner}\n")
    scanner.write_text(
        '#!/bin/bash\n'
        'args=(); for a in "$@"; do args+=("${a//localhost/host.docker.internal}"); done\n'
        'exec docker run --rm -v "$PWD:/usr/src" -w /usr/src '
        'sonarsource/sonar-scanner-cli "${args[@]}"\n')
    scanner.chmod(0o755)
    return cs


def write_fork_launcher(ws, module, argv):
    p = ws / f"launch_{module}.py"
    p.write_text(
        'import multiprocessing as mp; mp.set_start_method("fork", force=True)\n'
        f'import sys; sys.argv={argv!r}\n'
        f'from scripts import {module}; {module}.main()\n')
    return p


def filter_ts_since(cs, since):
    """Trim ts_repos_monthly.csv to months >= since (YYYY-MM), in place, so the
    SonarQube pass and the analysis window honor --since for the git data too."""
    import csv as _csv
    src = cs / "data" / "ts_repos_monthly.csv"
    if not src.exists() or not since:
        return
    with src.open() as f:
        rows = list(_csv.DictReader(f))
        cols = rows[0].keys() if rows else []
    kept = [r for r in rows if r.get("month", "") >= since]
    if not cols:
        return
    with src.open("w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=list(cols))
        w.writeheader()
        w.writerows(kept)
    logging.info("Trimmed ts_repos_monthly.csv to months >= %s: %d/%d rows kept",
                 since, len(kept), len(rows))


def run_study_scripts(cs, ws, do_sonar, since=None):
    env = dict(os.environ, PYTHONPATH=str(cs),
               OBJC_DISABLE_INITIALIZE_FORK_SAFETY="YES")
    py = sys.executable
    # 1. velocity + cursor detection -> data/ts_repos_monthly.csv
    lp = write_fork_launcher(ws, "analyze_repos", ["analyze_repos", "--aggregation=month"])
    run([py, str(lp)], cwd=cs, env=env)
    filter_ts_since(cs, since)  # bound the window before the expensive SonarQube pass
    if do_sonar:
        # 2. SonarQube quality appended in-place to ts_repos_monthly.csv.
        #    run_sonar_full.py widens the study's hardcoded 2024-01..2025-08 window
        #    and blocks on each CE task, so ONE pass covers every month reliably.
        senv = dict(env)
        senv["SONAR_START"] = f"{since}-01" if since else "2020-01-01"
        senv["SONAR_END"] = "2035-12-31"
        run([py, str(TOOLS / "run_sonar_full.py")], cwd=cs, env=senv)
        # 3. warnings — needs a nominal treatment event to drive it
        repo_name = (cs / "data" / "repos.csv").read_text().strip().splitlines()[-1]
        (cs / "data" / "panel_event_monthly.csv").write_text(
            f"repo_name,month,event\n{repo_name},2025-01,2025-01\n")
        run([py, "-m", "scripts.collect_sonarqube_warnings"], cwd=cs, env=env)


def enumerate_branches(repo_clone):
    out = sh(f'git -C "{repo_clone}" branch -r').stdout
    branches = []
    for line in out.splitlines():
        b = line.strip()
        if not b or "->" in b:
            continue
        branches.append(b.replace("origin/", "", 1))
    return sorted(set(branches))


def split_combined_csv(cs, report, repo_name):
    """ts_repos_monthly.csv carries both velocity and quality columns; expose it
    under both names the analyzer expects (it selects the columns it needs)."""
    src = cs / "data" / "ts_repos_monthly.csv"
    if not src.exists():
        logging.warning("No ts_repos_monthly.csv produced")
        return
    shutil.copy(src, report / "velocity_monthly.csv")
    shutil.copy(src, report / "quality_monthly.csv")
    for name in ("sonarqube_warnings.csv", "sonarqube_warning_definitions.csv"):
        p = cs / "data" / name
        if p.exists():
            shutil.copy(p, report / ("warnings.csv" if "warnings.csv" == name else name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-url", required=True)
    ap.add_argument("--out", default=str(STUDY / "repo outputs" / "repo_report"))
    ap.add_argument("--port", type=int, default=9011)
    ap.add_argument("--since", help="YYYY-MM lower bound for GitHub collectors")
    ap.add_argument("--max-prs", type=int, help="cap PRs in review collector")
    ap.add_argument("--skip-sonar", action="store_true")
    ap.add_argument("--skip-github", action="store_true")
    ap.add_argument("--keep-workspace", action="store_true")
    ap.add_argument("--adoption", help="override adoption month YYYY-MM for analysis")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    repo_name = owner_name_from_url(args.repo_url)
    slug = repo_name.replace("/", "_")
    ws = Path("/tmp") / f"ai-impact-{slug}"
    repo_clone = ws / "repo"
    report = Path(args.out) / slug
    report.mkdir(parents=True, exist_ok=True)
    container = f"aiimpact-sonar-{args.port}"

    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    logging.info("Cloning %s (full history)...", args.repo_url)
    if run(["git", "clone", args.repo_url, str(repo_clone)]).returncode != 0:
        sys.exit("git clone failed")

    branches = enumerate_branches(repo_clone)
    head = sh(f'git -C "{repo_clone}" rev-parse HEAD').stdout.strip()
    default_branch = sh(f'git -C "{repo_clone}" rev-parse --abbrev-ref HEAD').stdout.strip()

    token = None
    do_sonar = not args.skip_sonar
    try:
        if do_sonar:
            token = setup_sonar(args.port, container)
        cs = build_workspace(ws, repo_name, repo_clone, args.port, token or "unused")
        run_study_scripts(cs, ws, do_sonar, args.since)
        split_combined_csv(cs, report, repo_name)

        # AI coding-agent detection (git-only, always run)
        run([sys.executable, str(TOOLS / "detect_ai_agents.py"),
             str(repo_clone), repo_name, str(report)])

        # GitHub collectors (issues, reviews) — need a token
        if not args.skip_github:
            common = [repo_name, str(report)]
            if args.since:
                common += ["--since", args.since]
            run([sys.executable, str(TOOLS / "collect_issue_metrics.py")] + common)
            rev = [sys.executable, str(TOOLS / "collect_review_metrics.py")] + common
            if args.max_prs:
                rev += ["--max-prs", str(args.max_prs)]
            run(rev)

        # Unify all AI-attributable operations (commit/merge/push/PR/review/issue)
        # and derive adoption = first trackable AI action of any kind.
        run([sys.executable, str(TOOLS / "build_ai_operations.py"), str(report)])

        # meta.json
        (report / "meta.json").write_text(json.dumps({
            "repo_name": repo_name, "repo_url": args.repo_url,
            "head": head, "default_branch": default_branch,
            "n_branches": len(branches), "branches": branches,
            "sonar": do_sonar, "github": not args.skip_github,
            "since": args.since, "generated_by": "run_ai_impact.py",
        }, indent=2))

        # Analysis layer
        anl = [sys.executable, str(TOOLS / "analyze_single_repo.py"), str(report)]
        if args.adoption:
            anl += ["--adoption", args.adoption]
        run(anl)
    finally:
        if do_sonar:
            sh(f"docker rm -f {container} 2>/dev/null")
        if not args.keep_workspace:
            shutil.rmtree(ws, ignore_errors=True)

    print(f"\n=== DONE ===\nReport: {report}\n  SUMMARY.md, meta.json, *_monthly.csv, "
          f"ai_agent_*.csv, issues.csv, reviews.csv, plots/")


if __name__ == "__main__":
    main()
