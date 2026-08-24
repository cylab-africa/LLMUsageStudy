#!/usr/bin/env python3
"""
Replicate the CursorStudy per-repo scan data for mosip/mosip-config.

Mirrors:
  - analyze_repos.py        -> monthly git activity (commits, lines, contributors)
  - run_sonarqube.py        -> monthly SonarQube quality metrics
  - collect_sonarqube_warnings.py -> warnings list + rule definitions

Output: /tmp/mosip-scan/output/*.csv
"""
import logging
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import git
import pandas as pd
import requests

REPO_PATH = Path("/tmp/mosip-scan/repo")
OUT = Path("/tmp/mosip-scan/output")
OUT.mkdir(exist_ok=True)

REPO_NAME = "mosip/mosip-config"
PROJECT_KEY = "mosip_mosip-config"

PORT = Path("/tmp/mosip-scan/sonar_port.txt").read_text().strip()
SONAR_HOST = f"http://localhost:{PORT}"
SONAR_TOKEN = Path("/tmp/mosip-scan/sonar_token.txt").read_text().strip()

# Same window as run_sonarqube.py
START_DATE = "2024-01-01"
END_DATE = "2025-08-31"

# Same metric list as run_sonarqube.py
METRICS_OF_INTEREST = [
    "ncloc",
    "bugs",
    "vulnerabilities",
    "code_smells",
    "duplicated_lines_density",
    "comment_lines_density",
    "cognitive_complexity",
    "software_quality_maintainability_remediation_effort",  # technical debt
]
ISSUE_TYPES = ["BUG", "VULNERABILITY", "CODE_SMELL"]

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s",
                    level=logging.INFO, handlers=[logging.StreamHandler(sys.stdout)])


def monthly_git_stats(repo: git.Repo) -> dict:
    """Per-month commit/line/contributor stats (analyze_repos.py logic)."""
    stats = defaultdict(lambda: {"commits": 0, "lines_added": 0, "lines_removed": 0,
                                 "contributors": set(), "latest_commit": None,
                                 "latest_commit_time": None})
    for commit in repo.iter_commits("master"):
        ct = datetime.fromtimestamp(commit.committed_date)
        key = ct.strftime("%Y-%m")
        s = stats[key]
        s["commits"] += 1
        s["contributors"].add(f"{commit.author.name} <{commit.author.email}>")
        if s["latest_commit_time"] is None or ct > s["latest_commit_time"]:
            s["latest_commit"] = commit.hexsha
            s["latest_commit_time"] = ct
        if commit.parents:
            parent = commit.parents[0]
            r = subprocess.run(["git", "-C", str(REPO_PATH), "diff", "--numstat",
                                f"{parent.hexsha}..{commit.hexsha}"],
                               capture_output=True, text=True)
            for line in r.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 2:
                    if parts[0] != "-":
                        try:
                            s["lines_added"] += int(parts[0])
                        except ValueError:
                            pass
                    if parts[1] != "-":
                        try:
                            s["lines_removed"] += int(parts[1])
                        except ValueError:
                            pass
    return stats


def run_scan(commit_hash: str, version: str) -> None:
    repo = git.Repo(str(REPO_PATH))
    repo.git.reset("--hard")
    repo.git.clean("-fd")
    repo.git.checkout(commit_hash, force=True)
    cmd = ["docker", "run", "--rm", "-v", f"{REPO_PATH}:/usr/src",
           "sonarsource/sonar-scanner-cli",
           f"-Dsonar.projectKey={PROJECT_KEY}",
           f"-Dsonar.projectName={PROJECT_KEY}",
           f"-Dsonar.projectVersion={version}",
           "-Dsonar.sources=.",
           "-Dsonar.host.url=http://host.docker.internal:" + PORT,
           f"-Dsonar.token={SONAR_TOKEN}",
           "-Dsonar.scm.disabled=true"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        logging.error("scan failed %s: %s", version, res.stderr[-500:])
    else:
        logging.info("scan ok %s (%s)", version, commit_hash[:8])


def get_analyses() -> list:
    h = {"Authorization": f"Bearer {SONAR_TOKEN}"}
    out, page = [], 1
    while True:
        r = requests.get(f"{SONAR_HOST}/api/project_analyses/search",
                         headers=h, params={"project": PROJECT_KEY, "category": "VERSION",
                                            "p": page, "ps": 100})
        r.raise_for_status()
        a = r.json().get("analyses", [])
        out += [{"version": x.get("projectVersion"), "date": x.get("date")} for x in a if x.get("projectVersion")]
        if len(a) < 100:
            break
        page += 1
    return out


def get_metrics_for_date(analysis_date: str) -> dict:
    h = {"Authorization": f"Bearer {SONAR_TOKEN}"}
    r = requests.get(f"{SONAR_HOST}/api/measures/search_history", headers=h,
                     params={"component": PROJECT_KEY, "metrics": ",".join(METRICS_OF_INTEREST),
                             "from": analysis_date, "to": analysis_date})
    r.raise_for_status()
    m = {}
    for meas in r.json().get("measures", []):
        hist = meas.get("history", [])
        if hist and "value" in hist[0]:
            m[meas["metric"]] = float(hist[0]["value"])
    return m


def collect_warnings() -> list:
    """All issues at latest analysis (collect_sonarqube_warnings.py shape)."""
    h = {"Authorization": f"Bearer {SONAR_TOKEN}"}
    rows = []
    for t in ISSUE_TYPES:
        page = 1
        while True:
            r = requests.get(f"{SONAR_HOST}/api/issues/search", headers=h,
                             params={"componentKeys": PROJECT_KEY, "types": t,
                                     "ps": 500, "p": page})
            r.raise_for_status()
            issues = r.json().get("issues", [])
            for i in issues:
                rows.append({"repo_name": REPO_NAME, "issue_key": i.get("key"),
                             "type": i.get("type"), "severity": i.get("severity"),
                             "message": i.get("message"), "component": i.get("component"),
                             "line": i.get("line"), "rule": i.get("rule"),
                             "effort": i.get("effort"), "creation_date": i.get("creationDate")})
            if len(issues) < 500:
                break
            page += 1
    return rows


def main():
    repo = git.Repo(str(REPO_PATH))
    head = repo.head.commit.hexsha
    logging.info("Computing monthly git stats...")
    gstats = monthly_git_stats(repo)

    start = pd.Timestamp(START_DATE).strftime("%Y-%m")
    end = pd.Timestamp(END_DATE).strftime("%Y-%m")
    months = sorted([m for m in gstats if start <= m <= end])
    logging.info("Active months in window %s..%s: %d", start, end, len(months))

    # Scan latest commit of each active month
    for m in months:
        run_scan(gstats[m]["latest_commit"], m)

    # Map versions -> dates, pull metrics
    analyses = get_analyses()
    ver_date = {a["version"]: a["date"] for a in analyses}

    rows = []
    for m in months:
        s = gstats[m]
        row = {"month": m, "repo_name": REPO_NAME, "latest_commit": s["latest_commit"],
               "commits": s["commits"], "lines_added": s["lines_added"],
               "lines_removed": s["lines_removed"], "contributors": len(s["contributors"])}
        if m in ver_date:
            row.update(get_metrics_for_date(ver_date[m]))
        rows.append(row)

    df = pd.DataFrame(rows)
    df.rename(columns={"software_quality_maintainability_remediation_effort": "technical_debt"}, inplace=True)
    # order columns like ts_repos_monthly.csv (subset we can produce)
    cols = ["month", "repo_name", "latest_commit", "commits", "lines_added",
            "lines_removed", "contributors", "ncloc", "bugs", "vulnerabilities",
            "code_smells", "duplicated_lines_density", "comment_lines_density",
            "cognitive_complexity", "technical_debt"]
    df = df[[c for c in cols if c in df.columns]]
    df.to_csv(OUT / "ts_mosip_config_monthly.csv", index=False)
    logging.info("Wrote ts_mosip_config_monthly.csv (%d rows)", len(df))

    # Restore HEAD and scan it for the warnings snapshot (current state)
    repo.git.reset("--hard")
    repo.git.checkout("master", force=True)

    warnings = collect_warnings()
    if warnings:
        wdf = pd.DataFrame(warnings)
        defs = wdf[["rule", "type", "severity", "effort", "message"]].drop_duplicates("rule")
        defs = defs.rename(columns={"message": "example_message"}).sort_values("rule")
        defs.to_csv(OUT / "sonarqube_warning_definitions.csv", index=False)
        wdf.drop(columns=["type", "severity", "message", "effort"]).to_csv(
            OUT / "sonarqube_warnings.csv", index=False)
        logging.info("Wrote %d warnings, %d unique rules", len(wdf), len(defs))
        logging.info("By type:\n%s", wdf.groupby("type").size())
        logging.info("By severity:\n%s", wdf.groupby("severity").size())

    print("\n===== MONTHLY TIME SERIES =====")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
