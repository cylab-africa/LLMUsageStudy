#!/usr/bin/env python3
"""
AI-Impact orchestrator: one command to evaluate a single repo end-to-end.

Wraps repo outputs/RUNBOOK.md into an automated pipeline:
  clone -> enumerate branches -> study velocity -> AI-agent detection ->
  GitHub issue/review collectors -> unify AI operations (adoption month) ->
  (Docker SonarQube + warnings) -> merge into repo_report/<owner_repo>/ ->
  single-repo before/after analysis.

Reuses the study's own scripts/*.py (does not reimplement velocity/SonarQube).
Every stage is skippable so config-only repos or no-token runs still produce the
git-only half. Every stage outcome is recorded in meta.json ("stages"), so an
unattended batch can be audited afterwards without re-reading logs.

Usage:
  python run_ai_impact.py --repo-url https://github.com/OWNER/NAME.git \
     --out "repo outputs/repo_report" [--port 9011] [--since 2023-01] \
     [--skip-sonar] [--skip-github] [--skip-warnings] [--max-prs 300] \
     [--workspace-root DIR] [--keep-workspace]

Prereqs: Docker Desktop running (unless --skip-sonar), Python 3.10+, git.
GITHUB_TOKEN in env or <study>/.env enables issue/review collection.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional, Sequence

import requests

TOOLS = Path(__file__).resolve().parent
STUDY = TOOLS.parent.parent  # repo outputs/_tools -> repo outputs -> CursorStudy
SCRIPTS = STUDY / "scripts"

WORKSPACE_MARKER = ".ai-impact-workspace"
OWNER_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
# Upstream collect_sonarqube_warnings.py hardcodes the study's own adoption
# window; matched here so the throwaway workspace copy can be widened.
WARNINGS_FILTER_RE = re.compile(
    r'\(treatment_df\["event"\] > (\d+)\)\s*&\s*'
    r'\(treatment_df\["event"\] <= (\d+)\)'
)

STAGES: dict[str, str] = {}


class StageError(RuntimeError):
    """A required stage failed; this repo cannot produce a valid report."""


def record_stage(stage: str, status: str) -> None:
    """Record ok|failed|skipped for meta.json and echo it into the log."""
    STAGES[stage] = status
    level = logging.ERROR if status == "failed" else logging.INFO
    logging.log(level, "stage %s: %s", stage, status)


def run(cmd: Sequence[Any], stage: str, required: bool = True,
        **kw: Any) -> subprocess.CompletedProcess:
    """Run a child process, check its exit code, and record the outcome.

    A non-zero exit (or a missing executable) from a required stage aborts the
    repo; an optional stage logs a loud warning and is recorded as failed so a
    partial report is never mistaken for a complete one.
    """
    argv = [str(c) for c in cmd]
    logging.info("$ %s", " ".join(argv))
    try:
        proc = subprocess.run(argv, **kw)
    except (OSError, subprocess.SubprocessError) as exc:
        record_stage(stage, "failed")
        msg = "stage %r could not run (%s): %s" % (stage, exc, " ".join(argv))
        if required:
            raise StageError(msg) from exc
        logging.warning("OPTIONAL %s -- continuing without it", msg)
        return subprocess.CompletedProcess(argv, 1)
    if proc.returncode == 0:
        record_stage(stage, "ok")
        return proc
    record_stage(stage, "failed")
    msg = "stage %r exited %d: %s" % (stage, proc.returncode, " ".join(argv))
    if required:
        raise StageError(msg)
    logging.warning("OPTIONAL %s -- continuing without it", msg)
    return proc


def git_out(repo: Path, *args: str) -> str:
    """Read-only git query; empty string (and a warning) on failure."""
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          text=True, capture_output=True)
    if proc.returncode != 0:
        logging.warning("git %s failed in %s: %s", " ".join(args), repo,
                        proc.stderr.strip()[:200])
        return ""
    return proc.stdout


def owner_name_from_url(url: str) -> str:
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not m:
        sys.exit(f"Cannot parse owner/name from {url}")
    owner, name = m.group(1), m.group(2)
    if not (OWNER_NAME_RE.match(owner) and OWNER_NAME_RE.match(name)):
        sys.exit(f"Unsafe owner/name {owner}/{name!r} parsed from {url}; "
                 "expected only [A-Za-z0-9_.-]")
    return f"{owner}/{name}"


def wait_sonar_up(port: int, timeout: Optional[int] = None) -> bool:
    """Poll until SonarQube reports UP. Slow VMs need more than the old 5 min,
    and a boot that times out silently costs a whole repo's quality series."""
    if timeout is None:
        timeout = int(os.environ.get("SONAR_UP_TIMEOUT", "600"))
    url = f"http://localhost:{port}/api/system/status"
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200 and r.json().get("status") == "UP":
                return True
        except (requests.RequestException, ValueError):
            pass
        time.sleep(5)
    return False


def docker_rm(container: str) -> None:
    """Best-effort container teardown; never raises (docker may not be installed)."""
    try:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
    except OSError as exc:
        logging.warning("Could not remove container %s: %s", container, exc)


def sonar_password() -> str:
    """Fresh per-run admin password; never reused, never passed on argv."""
    return "Ai1!" + secrets.token_urlsafe(24)


def setup_sonar(port: int, container: str) -> Optional[str]:
    """Start Dockerized SonarQube and mint a scan token, or None if unusable."""
    logging.info("Starting Dockerized SonarQube on port %d ...", port)
    docker_rm(container)
    # Heaps are pinned rather than left to SonarQube's defaults: several of these
    # instances run concurrently (one per lane) on a fixed-memory host, and an
    # untuned instance sizes its Elasticsearch heap for a machine it does not
    # have. Measured at ~2.2 GiB with larger heaps; these tighter values leave
    # headroom for the concurrent scanner JVMs. Three lanes at the previous
    # sizes plus three scanners on large Java repos exhausted a 15 GiB host
    # and the OOM killer took out the whole batch.
    started = run(["docker", "run", "-d", "--name", container,
                   "-p", f"{port}:9000",
                   # Hard cap so an over-large instance is killed by Docker
                   # instead of the host OOM killer, which previously took out
                   # every concurrent lane at once. A dead container costs one
                   # lane's scans (logged); a host OOM costs the whole batch.
                   "--memory", "2800m", "--memory-swap", "3500m",
                   "-e", "SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true",
                   "-e", "SONAR_WEB_JAVAOPTS=-Xmx384m -Xms128m",
                   "-e", "SONAR_CE_JAVAOPTS=-Xmx768m -Xms128m",
                   "-e", "SONAR_SEARCH_JAVAOPTS=-Xmx512m -Xms512m",
                   "sonarqube:community"], "sonar_container", required=False)
    if started.returncode != 0:
        return None
    run(["docker", "pull", "sonarsource/sonar-scanner-cli"],
        "sonar_scanner_image", required=False)
    if not wait_sonar_up(port):
        record_stage("sonar_token", "failed")
        logging.error("SonarQube did not come UP within timeout on port %d", port)
        return None
    host = f"http://localhost:{port}"
    newpass = sonar_password()
    try:
        changed = requests.post(
            f"{host}/api/users/change_password", auth=("admin", "admin"),
            data={"login": "admin", "previousPassword": "admin",
                  "password": newpass}, timeout=30)
        if changed.status_code not in (200, 204):
            logging.warning("SonarQube password change returned HTTP %d",
                            changed.status_code)
        minted = requests.post(
            f"{host}/api/user_tokens/generate", auth=("admin", newpass),
            data={"name": f"scan-{port}-{secrets.token_hex(4)}"}, timeout=30)
        minted.raise_for_status()
        token = str(minted.json()["token"])
    except (requests.RequestException, ValueError, KeyError) as exc:
        record_stage("sonar_token", "failed")
        logging.error("Could not mint SonarQube token: %s", exc)
        return None
    record_stage("sonar_token", "ok")
    return token


def write_study_env(cs: Path, ws: Path, port: int, token: str) -> None:
    """Write the workspace .env (0600 — it holds the SonarQube token)."""
    env_file = cs / ".env"
    env_file.write_text(
        f"GITHUB_TOKEN=unused\nSONAR_TOKEN={token}\n"
        f"SONAR_HOST=http://localhost:{port}\n"
        f"SONAR_SCANNER_PATH={ws / 'sonar-scanner.sh'}\n")
    env_file.chmod(0o600)


def build_workspace(ws: Path, repo_name: str, port: int) -> Path:
    """Recreate the RUNBOOK §6 isolated workspace so study scripts never touch
    data/. The clone already lives at ws/CursorRepos/<slug>, which is exactly
    where the study scripts look for it, so nothing is duplicated."""
    cs = ws / "CursorStudy"
    (cs / "data").mkdir(parents=True, exist_ok=True)
    if (cs / "scripts").exists():
        shutil.rmtree(cs / "scripts")
    shutil.copytree(SCRIPTS, cs / "scripts")
    (cs / "scripts" / "__init__.py").touch()
    (cs / "data" / "repos.csv").write_text(f"repo_name\n{repo_name}\n")
    scanner = ws / "sonar-scanner.sh"
    # Cache lives beside the workspace root, not inside it: workspaces are
    # deleted per repo, and re-downloading the scanner JRE 20 times is waste.
    scanner.write_text(_scanner_wrapper(ws.parent / ".sonar-scanner-cache"))
    scanner.chmod(0o755)
    write_study_env(cs, ws, port, "unused")
    return cs


def _scanner_wrapper(cache_dir: Path) -> str:
    """Shell wrapper the study's run_sonarqube.py invokes as SONAR_SCANNER_PATH.

    Platform-specific, and both halves were verified on the target host:

    * Networking. Docker Desktop (macOS/Windows) resolves `host.docker.internal`
      but does not support `--network host`; Linux is the exact opposite, so a
      wrapper that rewrites localhost -> host.docker.internal silently fails to
      reach SonarQube on Linux.
    * Ownership. The scanner image runs as uid 1000 (`scanner-cli`). When the
      checkout is owned by any other uid the container cannot create
      `.scannerwork/`, so `report-task.txt` never appears on the host and the
      CE-task wait in run_sonar_full.py degrades to a blind sleep — the exact
      race that wrapper exists to eliminate. `--user` fixes the ownership, and
      the container then needs a writable /tmp and an explicit working directory
      because its default (`/tmp/.scannerwork`) is root-owned.
    """
    if sys.platform == "linux":
        # The scanner cache MUST live outside the repo working tree. It holds a
        # JRE the scanner downloads once and re-executes on every later scan, and
        # run_sonarqube.py runs `git reset --hard` + `git clean -fd` before each
        # monthly checkout — which deletes any untracked directory inside the
        # repo. Caching under /usr/src therefore yields exactly one successful
        # month per repo, then "Cannot run program .../bin/java" forever after.
        # Mounting it separately also means the JRE downloads once per host
        # rather than once per scan.
        return (
            '#!/bin/bash\n'
            '# Linux: reach the host via --network host and run as the invoking\n'
            '# user so .scannerwork/report-task.txt lands on the host.\n'
            f'CACHE="{cache_dir}"\n'
            'mkdir -p "$CACHE"\n'
            'exec docker run --rm --network host --user "$(id -u):$(id -g)" \\\n'
            '  --memory 1800m --memory-swap 2600m \\\n'
            '  --tmpfs /tmp:rw,exec,size=2g \\\n'
            '  -v "$PWD:/usr/src" -v "$CACHE:/sonarcache" -w /usr/src \\\n'
            '  -e SONAR_SCANNER_OPTS="-Xmx768m" \\\n'
            '  -e SONAR_USER_HOME=/sonarcache -e HOME=/sonarcache \\\n'
            '  sonarsource/sonar-scanner-cli \\\n'
            '  -Dsonar.working.directory=/usr/src/.scannerwork "$@"\n')
    return (
        '#!/bin/bash\n'
        '# Docker Desktop: no --network host, so rewrite the host address.\n'
        'args=(); for a in "$@"; do '
        'args+=("${a//localhost/host.docker.internal}"); done\n'
        'exec docker run --rm -v "$PWD:/usr/src" -w /usr/src '
        'sonarsource/sonar-scanner-cli "${args[@]}"\n')


def write_fork_launcher(ws: Path, module: str, argv: list[str]) -> Path:
    p = ws / f"launch_{module}.py"
    p.write_text(
        'import multiprocessing as mp; mp.set_start_method("fork", force=True)\n'
        f'import sys; sys.argv={argv!r}\n'
        f'from scripts import {module}; {module}.main()\n')
    return p


def study_env(cs: Path) -> dict[str, str]:
    return dict(os.environ, PYTHONPATH=str(cs),
                OBJC_DISABLE_INITIALIZE_FORK_SAFETY="YES")


def filter_ts_since(cs: Path, since: Optional[str]) -> None:
    """Trim ts_repos_monthly.csv to months >= since (YYYY-MM), in place, so the
    SonarQube pass and the analysis window honor --since for the git data too."""
    src = cs / "data" / "ts_repos_monthly.csv"
    if not src.exists() or not since:
        return
    with src.open() as f:
        rows = list(csv.DictReader(f))
        cols = list(rows[0].keys()) if rows else []
    kept = [r for r in rows if r.get("month", "") >= since]
    if not cols:
        return
    with src.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(kept)
    logging.info("Trimmed ts_repos_monthly.csv to months >= %s: %d/%d rows kept",
                 since, len(kept), len(rows))


def run_velocity(cs: Path, ws: Path, since: Optional[str]) -> None:
    """Study velocity pass -> data/ts_repos_monthly.csv (required)."""
    launcher = write_fork_launcher(ws, "analyze_repos",
                                   ["analyze_repos", "--aggregation=month"])
    run([sys.executable, launcher], "velocity", required=True,
        cwd=cs, env=study_env(cs))
    filter_ts_since(cs, since)  # bound the window before the expensive scans


def run_sonar_stage(cs: Path, since: Optional[str]) -> list[str]:
    """One full-window SonarQube pass; returns the months whose compute-engine
    task did not reach SUCCESS (empty when everything scanned cleanly)."""
    env = study_env(cs)
    env["SONAR_START"] = f"{since}-01" if since else "2020-01-01"
    env["SONAR_END"] = "2035-12-31"
    fail_log = cs / "sonar_ce_failures.log"
    env["SONAR_CE_FAILURES"] = str(fail_log)
    run([sys.executable, TOOLS / "run_sonar_full.py"], "sonar", required=False,
        cwd=cs, env=env)
    if not fail_log.exists():
        return []
    failures = [ln for ln in fail_log.read_text().splitlines() if ln.strip()]
    if failures:
        logging.warning("%d SonarQube month(s) have no fresh metrics: %s",
                        len(failures), "; ".join(failures[:20]))
    return failures


def month_to_int(month: str) -> Optional[int]:
    """'YYYY-MM...' -> 202501, or None if it is not a month."""
    m = re.match(r"^(\d{4})-(\d{2})", month or "")
    return int(m.group(1) + m.group(2)) if m else None


def month_ord(month: str) -> Optional[int]:
    m = re.match(r"^(\d{4})-(\d{2})", month or "")
    return int(m.group(1)) * 12 + int(m.group(2)) - 1 if m else None


def adoption_month(report: Path) -> Optional[str]:
    """Real adoption month = ai_adoption.csv's __OVERALL__ first AI action.

    Read from `first_action_date_utc`, not the raw `first_action_date`: the
    latter keeps whatever offset the source wrote, so its month prefix can be a
    month later than the action it names. analyze_single_repo derives its
    pre/post split the same way, so the warnings window and SUMMARY.md agree.
    """
    path = report / "ai_adoption.csv"
    if not path.exists():
        return None
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("agent") == "__OVERALL__":
                month = ((row.get("first_action_date_utc")
                          or row.get("first_action_date") or "")[:7])
                return month if month_to_int(month) else None
    return None


def data_window_midpoint(cs: Path) -> Optional[str]:
    """Midpoint month of the scanned window — the fallback event when no AI
    action exists, so the ±6 sample still straddles the middle of the data."""
    src = cs / "data" / "ts_repos_monthly.csv"
    if not src.exists():
        return None
    with src.open() as f:
        months = sorted(o for o in
                        (month_ord(r.get("month", "")) for r in csv.DictReader(f))
                        if o is not None)
    if not months:
        return None
    mid = (months[0] + months[-1]) // 2
    return f"{mid // 12:04d}-{mid % 12 + 1:02d}"


def widen_warnings_window(cs: Path, event: str) -> bool:
    """Let the workspace copy of collect_sonarqube_warnings.py accept `event`.

    Upstream hardcodes 202407 < event <= 202503 (the study's own adoption
    window). Real adoption months fall outside it, and the script then silently
    collects nothing. The workspace scripts/ tree is a throwaway copy under the
    run dir, so widening it there is safe; canonical scripts/ is untouched.
    Returns False when the expected filter is missing (upstream changed).
    """
    path = cs / "scripts" / "collect_sonarqube_warnings.py"
    try:
        text = path.read_text()
    except OSError as exc:
        logging.warning("Cannot read %s: %s", path, exc)
        return False
    m = WARNINGS_FILTER_RE.search(text)
    if not m:
        return False
    lo, hi = int(m.group(1)), int(m.group(2))
    event_int = month_to_int(event) or 0
    if lo < event_int <= hi:
        return True
    path.write_text(WARNINGS_FILTER_RE.sub(
        '(treatment_df["event"] > 0) & (treatment_df["event"] <= 999912)',
        text, count=1))
    logging.info("Widened workspace warnings filter (%d, %d] so event %s survives",
                 lo, hi, event)
    return True


def run_warnings_stage(cs: Path, report: Path, repo_name: str) -> Optional[str]:
    """Sample SonarQube warnings around the REAL adoption month.

    The event month comes from ai_adoption.csv (written by build_ai_operations,
    which is why detection and the GitHub collectors run before this stage);
    with no AI detected it falls back to the midpoint of the data window.
    """
    event = adoption_month(report)
    origin = "ai_adoption.csv __OVERALL__"
    if not event:
        event = data_window_midpoint(cs)
        origin = "midpoint of the data window (no AI action detected)"
    if not event:
        logging.warning("No event month available; skipping SonarQube warnings")
        record_stage("warnings", "skipped")
        return None
    logging.info("SonarQube warnings event month %s (from %s)", event, origin)
    if not widen_warnings_window(cs, event):
        logging.warning("collect_sonarqube_warnings.py no longer carries the "
                        "expected event filter; skipping warnings for %s", event)
        record_stage("warnings", "skipped")
        return None
    (cs / "data" / "panel_event_monthly.csv").write_text(
        f"repo_name,month,event\n{repo_name},{event},{event}\n")
    run([sys.executable, "-m", "scripts.collect_sonarqube_warnings"],
        "warnings", required=False, cwd=cs, env=study_env(cs))
    return event


def enumerate_branches(repo_clone: Path) -> list[str]:
    branches = []
    for line in git_out(repo_clone, "branch", "-r").splitlines():
        b = line.strip()
        if not b or "->" in b:
            continue
        branches.append(b.replace("origin/", "", 1))
    return sorted(set(branches))


def split_combined_csv(cs: Path, report: Path) -> None:
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
            shutil.copy(p, report / name)


def prepare_workspace(root: Optional[str], slug: str) -> Path:
    """Fresh workspace under $TMPDIR (or --workspace-root).

    Refuses to delete anything this tool did not create: the path must be a real
    directory carrying our marker file before it is removed.
    """
    base = Path(root).expanduser() if root else Path(tempfile.gettempdir())
    ws = base / f"ai-impact-{slug}"
    if ws.is_symlink():
        sys.exit(f"Refusing to use {ws}: it is a symlink")
    if ws.exists():
        if not ws.is_dir():
            sys.exit(f"Refusing to use {ws}: not a directory")
        if not (ws / WORKSPACE_MARKER).is_file():
            sys.exit(f"Refusing to delete {ws}: no {WORKSPACE_MARKER} marker, so "
                     "this tool did not create it. Remove it yourself or pass "
                     "--workspace-root.")
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    (ws / WORKSPACE_MARKER).write_text(json.dumps(
        {"pid": os.getpid(), "slug": slug,
         "created": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
    return ws


def cleanup_workspace(ws: Path) -> None:
    if not ws.is_symlink() and (ws / WORKSPACE_MARKER).is_file():
        shutil.rmtree(ws, ignore_errors=True)
        return
    logging.warning("Not deleting %s: missing %s marker", ws, WORKSPACE_MARKER)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-url", required=True)
    ap.add_argument("--out", default=str(STUDY / "repo outputs" / "repo_report"))
    ap.add_argument("--port", type=int, default=9011)
    ap.add_argument("--since", help="YYYY-MM lower bound for GitHub collectors")
    ap.add_argument("--max-prs", type=int, help="cap PRs in review collector")
    ap.add_argument("--skip-sonar", action="store_true")
    ap.add_argument("--skip-github", action="store_true")
    ap.add_argument("--skip-warnings", action="store_true",
                    help="skip the SonarQube warnings sample (nothing downstream "
                         "consumes it yet)")
    ap.add_argument("--workspace-root",
                    help="parent dir for the throwaway workspace (default: $TMPDIR)")
    ap.add_argument("--keep-workspace", action="store_true")
    ap.add_argument("--adoption", help="override adoption month YYYY-MM for analysis")
    ap.add_argument("--repo-path",
                    help="reuse an existing clone instead of fetching from the "
                         "network; copied with hardlinks, so the workspace stays "
                         "independently mutable for the checkouts the study "
                         "scripts perform")
    ap.add_argument("--resume", action="store_true",
                    help="forwarded to the GitHub collectors: skip a repo whose "
                         "collection already completed, so an interrupted batch "
                         "does not re-spend quota on finished repos")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    repo_name = owner_name_from_url(args.repo_url)
    slug = repo_name.replace("/", "_")
    ws = prepare_workspace(args.workspace_root, slug)
    # The clone IS the study's CursorRepos entry: no second copy of the working
    # tree. Every git-only reader below runs before the SonarQube stage, and
    # those readers use refs (git log --all / branch -r), which the study's
    # checkout/reset/clean leaves untouched.
    repo_clone = ws / "CursorRepos" / slug
    report = Path(args.out) / slug
    report.mkdir(parents=True, exist_ok=True)
    container = f"aiimpact-sonar-{args.port}"

    do_sonar = not args.skip_sonar
    head, default_branch = "", ""
    branches: list[str] = []
    warnings_event: Optional[str] = None
    sonar_failures: list[str] = []
    aborted: Optional[str] = None
    try:
        repo_clone.parent.mkdir(parents=True, exist_ok=True)
        if args.repo_path:
            src = Path(args.repo_path).expanduser().resolve()
            if not (src / ".git").is_dir():
                sys.exit(f"--repo-path {src} is not a git repository")
            # Hardlink-copy the whole directory rather than `git clone --local`:
            # a local clone transfers only refs/heads/*, which would drop the
            # source's refs/remotes/origin/* and silently reduce the
            # all-branches `git log --all` detection to the default branch.
            # Hardlinks are safe under the checkout / reset --hard the study
            # scripts run here, because git replaces files instead of editing
            # them in place, so a write breaks the link rather than corrupting
            # the source.
            logging.info("Hardlink-copying %s -> %s", src, repo_clone)
            if run(["cp", "-al", str(src), str(repo_clone)], "clone",
                   required=False).returncode != 0:
                logging.warning("Hardlink copy failed; falling back to a full copy")
                run(["cp", "-a", str(src), str(repo_clone)], "clone")
        else:
            logging.info("Cloning %s (full history) into %s ...", args.repo_url,
                         repo_clone)
            run(["git", "clone", args.repo_url, str(repo_clone)], "clone")

        branches = enumerate_branches(repo_clone)
        head = git_out(repo_clone, "rev-parse", "HEAD").strip()
        default_branch = git_out(repo_clone, "rev-parse", "--abbrev-ref",
                                 "HEAD").strip()

        cs = build_workspace(ws, repo_name, args.port)
        run_velocity(cs, ws, args.since)

        # AI coding-agent detection (git-only, always run)
        run([sys.executable, TOOLS / "detect_ai_agents.py", repo_clone, repo_name,
             report], "detect_ai_agents")

        # GitHub collectors (issues, reviews) — need a token
        if args.skip_github:
            record_stage("issues", "skipped")
            record_stage("reviews", "skipped")
        else:
            common: list[Any] = [repo_name, report]
            if args.since:
                common += ["--since", args.since]
            if args.resume:
                common.append("--resume")
            run([sys.executable, TOOLS / "collect_issue_metrics.py"] + common,
                "issues", required=False)
            rev = [sys.executable, TOOLS / "collect_review_metrics.py"] + common
            if args.max_prs:
                rev += ["--max-prs", str(args.max_prs)]
            run(rev, "reviews", required=False)

        # Unify all AI-attributable operations (commit/merge/push/PR/review/issue)
        # and derive adoption = first trackable AI action of any kind. Must come
        # before the warnings stage, which is windowed on that adoption month.
        run([sys.executable, TOOLS / "build_ai_operations.py", report],
            "ai_operations")

        if not do_sonar:
            record_stage("sonar", "skipped")
            record_stage("warnings", "skipped")
        else:
            token = setup_sonar(args.port, container)
            if token is None:
                do_sonar = False
                record_stage("sonar", "failed")
                record_stage("warnings", "skipped")
                logging.warning("SonarQube unavailable — continuing with the "
                                "git-only half for %s", repo_name)
            else:
                write_study_env(cs, ws, args.port, token)
                sonar_failures = run_sonar_stage(cs, args.since)
                if args.skip_warnings:
                    record_stage("warnings", "skipped")
                else:
                    warnings_event = run_warnings_stage(cs, report, repo_name)

        split_combined_csv(cs, report)

        anl: list[Any] = [sys.executable, TOOLS / "analyze_single_repo.py", report]
        if args.adoption:
            anl += ["--adoption", args.adoption]
        run(anl, "analysis")
    except StageError as exc:
        aborted = str(exc)
        logging.error("ABORTED %s: %s", repo_name, exc)
    except Exception as exc:  # unattended runs must still leave an audit trail
        aborted = f"unexpected {type(exc).__name__}: {exc}"
        logging.exception("ABORTED %s", repo_name)
    finally:
        meta = {
            "repo_name": repo_name, "repo_url": args.repo_url,
            "head": head, "default_branch": default_branch,
            "n_branches": len(branches), "branches": branches,
            "sonar": do_sonar, "github": not args.skip_github,
            "since": args.since,
            "warnings_event": warnings_event,
            "sonar_ce_failures": sonar_failures,
            "stages": dict(STAGES),
            "failed_stages": sorted(k for k, v in STAGES.items() if v == "failed"),
            "aborted": aborted,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "generated_by": "run_ai_impact.py",
        }
        (report / "meta.json").write_text(json.dumps(meta, indent=2))
        if not args.skip_sonar:
            docker_rm(container)
        if args.keep_workspace:
            logging.info("Keeping workspace %s", ws)
        else:
            cleanup_workspace(ws)

    failed = sorted(k for k, v in STAGES.items() if v == "failed")
    if aborted:
        sys.exit(f"FAILED {repo_name}: {aborted} (see {report}/meta.json)")
    if failed:
        logging.warning("%s finished with failed optional stage(s): %s",
                        repo_name, ", ".join(failed))
    print(f"\n=== DONE ===\nReport: {report}\n  SUMMARY.md, meta.json, "
          f"*_monthly.csv, ai_agent_*.csv, issues.csv, reviews.csv, plots/")


if __name__ == "__main__":
    main()
