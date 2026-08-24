#!/usr/bin/env python3
"""
Minimal GitHub REST helper: authenticated GET with pagination + rate-limit
handling, built on `requests` only (no PyGithub dependency, matching the
RUNBOOK venv). Shared by collect_issue_metrics.py and collect_review_metrics.py.
"""
import logging
import os
import time

import requests

API = "https://api.github.com"


def get_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not tok:
        # Fall back to a .env in the study root if present.
        for env_path in (".env", os.path.join(os.path.dirname(__file__), "..", "..", ".env")):
            try:
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("GITHUB_TOKEN=") and not line.startswith("#"):
                            tok = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
            except OSError:
                continue
            if tok:
                break
    return tok or None


def _headers(token):
    h = {"Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _sleep_for_rate_limit(resp):
    """If we hit the primary/secondary rate limit, wait until reset. Returns
    True if the caller should retry the same request."""
    if resp.status_code not in (403, 429):
        return False
    remaining = resp.headers.get("X-RateLimit-Remaining")
    if remaining == "0":
        reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
        wait = max(reset - int(time.time()), 1) + 2
        logging.warning("Rate limit hit; sleeping %ds until reset", wait)
        time.sleep(min(wait, 3600))
        return True
    retry_after = resp.headers.get("Retry-After")
    if retry_after:  # secondary rate limit
        wait = int(retry_after) + 1
        logging.warning("Secondary rate limit; sleeping %ds", wait)
        time.sleep(min(wait, 300))
        return True
    return False


def get_json(url, token, params=None, max_retries=5):
    """Single GET returning parsed JSON (or None on hard failure)."""
    for attempt in range(max_retries):
        resp = requests.get(url, headers=_headers(token), params=params, timeout=60)
        if resp.status_code == 200:
            return resp.json()
        if _sleep_for_rate_limit(resp):
            continue
        if resp.status_code in (500, 502, 503):
            time.sleep(2 ** attempt)
            continue
        logging.warning("GET %s -> %s: %s", url, resp.status_code, resp.text[:200])
        return None
    return None


def paginate(path, token, params=None, cap=None):
    """Yield items across all pages of a list endpoint. `cap` bounds the total
    number of items yielded (None = unbounded); returns how many were skipped
    via the generator's `.skipped` attribute is not possible, so callers should
    compare yielded count against the endpoint's total when they need it."""
    params = dict(params or {})
    params.setdefault("per_page", 100)
    url = f"{API}{path}" if path.startswith("/") else path
    yielded = 0
    while url:
        for attempt in range(5):
            resp = requests.get(url, headers=_headers(token), params=params, timeout=60)
            if resp.status_code == 200:
                break
            if _sleep_for_rate_limit(resp):
                continue
            if resp.status_code in (500, 502, 503):
                time.sleep(2 ** attempt)
                continue
            logging.warning("GET %s -> %s: %s", url, resp.status_code, resp.text[:200])
            return
        else:
            return
        items = resp.json()
        if not isinstance(items, list):
            return
        for it in items:
            yield it
            yielded += 1
            if cap is not None and yielded >= cap:
                return
        # Follow RFC 5988 Link header for next page.
        url = resp.links.get("next", {}).get("url")
        params = None  # next url already carries query params
