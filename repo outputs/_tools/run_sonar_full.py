#!/usr/bin/env python3
"""
Wrapper around the study's scripts/run_sonarqube.py that fixes two things for
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

Run (fork required on macOS so the Pool workers inherit the monkeypatch):
  PYTHONPATH=<workspace/CursorStudy> SONAR_START=2025-01-01 SONAR_END=2035-12-31 \
    python run_sonar_full.py
"""
import logging
import multiprocessing as mp
import os
import sys
import time

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

_orig_scan = rs.run_sonar_scan


def _read_ce_task_id(repo_path):
    p = os.path.join(str(repo_path), ".scannerwork", "report-task.txt")
    try:
        with open(p) as f:
            for line in f:
                if line.startswith("ceTaskId="):
                    return line.strip().split("=", 1)[1]
    except OSError:
        return None
    return None


def _wait_ce_task(task_id, timeout=900):
    """Block until a specific CE task finishes. Returns final status or None."""
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


def scan_and_wait(repo_path, commit_hash, version, project_key):
    ok = _orig_scan(repo_path, commit_hash, version, project_key)
    if ok:
        task_id = _read_ce_task_id(repo_path)
        if task_id:
            status = _wait_ce_task(task_id)
            logging.info("CE task for %s @ %s -> %s", project_key, version, status)
        else:
            # Fallback: brief pause + component-queue drain if report-task.txt missing.
            time.sleep(5)
    return ok


rs.run_sonar_scan = scan_and_wait

if __name__ == "__main__":
    rs.main()
