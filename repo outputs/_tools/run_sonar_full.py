#!/usr/bin/env python3
"""
Wrapper around the study's scripts/run_sonarqube.py that fixes three things for
single-repo full-window scanning, WITHOUT editing the canonical study script:

  1. Window: the study hardcodes END_DATE="2025-08-31" (and START="2024-01-01").
     We override both from SONAR_START / SONAR_END env vars so every month in
     ts_repos_monthly.csv is scanned.
  2. Async metrics: SonarQube Community processes each analysis in a serial
     background (CE) task queue and returns from the scanner before it finishes,
     so metrics fetched immediately are missing (hence the study's "run twice"
     note). We monkeypatch run_sonar_scan to block on the exact CE task id (from
     .scannerwork/report-task.txt) until it reaches SUCCESS/FAILED, so a single
     pass reliably captures metrics for every month.
  3. Failure visibility: a CE task that ends FAILED/CANCELED (or never finishes)
     leaves that month with stale or missing metrics. Those months are recorded
     to $SONAR_CE_FAILURES and the process exits non-zero, so the orchestrator
     cannot mistake a partial pass for a complete one.

Run (fork required on macOS so the Pool workers inherit the monkeypatch):
  PYTHONPATH=<workspace/CursorStudy> SONAR_START=2025-01-01 SONAR_END=2035-12-31 \
    python run_sonar_full.py
"""
import logging
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path
from typing import Optional

mp.set_start_method("fork", force=True)

import requests  # noqa: E402

sys.argv = ["run_sonarqube", "--aggregation=month"]
from scripts import run_sonarqube as rs  # noqa: E402

# 1) Widen the hardcoded analysis window.
rs.START_DATE = os.environ.get("SONAR_START", "2020-01-01")
rs.END_DATE = os.environ.get("SONAR_END", "2035-12-31")
# Serialize: the CE queue is serial anyway; single process keeps waiting
# deterministic and avoids Elasticsearch pressure on one machine.
rs.NUM_PROCESSES = 1

FAILURE_LOG = Path(os.environ.get("SONAR_CE_FAILURES", "sonar_ce_failures.log"))

_orig_scan = rs.run_sonar_scan


def _read_ce_task_id(repo_path: Path) -> Optional[str]:
    p = Path(repo_path) / ".scannerwork" / "report-task.txt"
    try:
        with p.open() as f:
            for line in f:
                if line.startswith("ceTaskId="):
                    return line.strip().split("=", 1)[1]
    except OSError:
        return None
    return None


def _wait_ce_task(task_id: str, timeout: Optional[int] = None) -> Optional[str]:
    """Block until a specific CE task finishes. Returns final status or None."""
    if timeout is None:
        timeout = int(os.environ.get("SONAR_CE_TIMEOUT", "1800"))
    headers = {"Authorization": f"Bearer {rs.SONAR_TOKEN}"}
    url = f"{rs.SONAR_HOST}/api/ce/task"
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, headers=headers, params={"id": task_id}, timeout=30)
            if r.status_code == 200:
                status = r.json().get("task", {}).get("status")
                if status in ("SUCCESS", "FAILED", "CANCELED"):
                    return status
        except requests.RequestException as e:
            logging.warning("CE task poll error: %s", e)
        time.sleep(3)
    logging.warning("CE task %s wait timed out after %ds", task_id, timeout)
    return None


def _record_failure(project_key: str, version: str, reason: str) -> None:
    """Pool workers are forked, so failures reach the parent through a file."""
    try:
        with FAILURE_LOG.open("a") as f:
            f.write(f"{project_key},{version},{reason}\n")
    except OSError as e:
        logging.warning("Could not record failed month %s @ %s: %s",
                        project_key, version, e)


def scan_and_wait(repo_path: Path, commit_hash: str, version: str,
                  project_key: str) -> bool:
    """Scan, then report success only if the CE task actually reached SUCCESS."""
    ok = _orig_scan(repo_path, commit_hash, version, project_key)
    if not ok:
        _record_failure(project_key, version, "scanner-failed")
        return False
    task_id = _read_ce_task_id(repo_path)
    if not task_id:
        logging.warning("No ceTaskId under %s for %s @ %s; cannot confirm the "
                        "background task, metrics may be stale", repo_path,
                        project_key, version)
        time.sleep(5)
        return True
    status = _wait_ce_task(task_id)
    if status != "SUCCESS":
        logging.error("CE task %s for %s @ %s ended as %s: that month has no "
                      "fresh metrics", task_id, project_key, version,
                      status or "TIMEOUT")
        _record_failure(project_key, version, status or "TIMEOUT")
        return False
    logging.info("CE task for %s @ %s -> SUCCESS", project_key, version)
    return True


rs.run_sonar_scan = scan_and_wait


def main() -> None:
    try:
        FAILURE_LOG.unlink()
    except OSError:
        pass
    rs.main()
    failures = [ln for ln in FAILURE_LOG.read_text().splitlines()
                if ln.strip()] if FAILURE_LOG.exists() else []
    if failures:
        logging.error("%d month(s) did not complete their SonarQube analysis: %s",
                      len(failures), "; ".join(failures[:20]))
        sys.exit(1)
    logging.info("Every scanned month completed its compute-engine task")


if __name__ == "__main__":
    main()
