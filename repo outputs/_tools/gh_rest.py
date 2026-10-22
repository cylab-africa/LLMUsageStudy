#!/usr/bin/env python3
"""
Minimal GitHub REST helper: authenticated GET with pagination, retry and
rate-limit handling, built on `requests` only (no PyGithub dependency, matching
the RUNBOOK venv). Shared by collect_issue_metrics.py and
collect_review_metrics.py.

Tuned for long unattended batches:
  * waiting out a rate limit never consumes the retry budget, so a throttled
    stretch cannot silently truncate a result set;
  * anything that would truncate a result raises `GitHubApiError` instead of
    returning short data a caller cannot tell apart from a complete answer;
  * remaining quota is logged periodically so a 15-hour log shows progress.
"""
from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import requests

API = "https://api.github.com"

MAX_RETRIES = 6
REQUEST_TIMEOUT_S = 60
MAX_SINGLE_WAIT_S = 3600.0
MAX_TOTAL_WAIT_S = 4 * 3600.0
SECONDARY_BASE_WAIT_S = 5.0
SECONDARY_MAX_WAIT_S = 300.0
QUOTA_LOG_EVERY = 250
QUOTA_LOG_INTERVAL_S = 600.0
LOW_QUOTA_LOG_INTERVAL_S = 30.0
LOW_QUOTA_THRESHOLD = 100

TOKEN_ENV_KEYS = ("GITHUB_TOKEN", "GH_TOKEN")


class GitHubApiError(RuntimeError):
    """A request could not be completed, so anything built from it would be
    silently truncated. Callers must treat this as a failed collection rather
    than as an empty or partial result."""


def _token_from_env_file(path: Path) -> Optional[str]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep and key.strip() in TOKEN_ENV_KEYS:
            tok = value.strip().strip('"').strip("'")
            if tok:
                return tok
    return None


def get_token() -> Optional[str]:
    """Return a GitHub token, or None if none is configured.

    Environment variables win. The .env fallbacks are resolved relative to this
    module (never the process CWD), so the same token is found no matter where
    the pipeline was launched from. Logs which source supplied the token, never
    the token itself.
    """
    for key in TOKEN_ENV_KEYS:
        tok = (os.environ.get(key) or "").strip()
        if tok:
            logging.info("GitHub token source: environment variable %s", key)
            return tok
    here = Path(__file__).resolve().parent
    candidates = (here / ".env", here.parent / ".env", here.parent.parent / ".env")
    for env_path in candidates:
        tok = _token_from_env_file(env_path)
        if tok:
            logging.info("GitHub token source: %s", env_path)
            return tok
    logging.warning("No GitHub token found: checked env %s and %s",
                    "/".join(TOKEN_ENV_KEYS),
                    ", ".join(str(p) for p in candidates))
    return None


def _headers(token: Optional[str]) -> Dict[str, str]:
    h = {"Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _int_header(resp: requests.Response, name: str, default: int = 0) -> int:
    try:
        return int(resp.headers.get(name, ""))
    except (TypeError, ValueError):
        return default


_QUOTA_STATE: Dict[str, float] = {"responses": 0.0, "last_log": 0.0}


def _log_quota(resp: requests.Response) -> None:
    """Periodically report remaining core quota so a human scanning a very long
    log can see the run is progressing and how much budget is left."""
    if "X-RateLimit-Remaining" not in resp.headers:
        return
    remaining = _int_header(resp, "X-RateLimit-Remaining", -1)
    if remaining < 0:
        return
    _QUOTA_STATE["responses"] += 1.0
    now = time.time()
    low = remaining <= LOW_QUOTA_THRESHOLD
    interval = LOW_QUOTA_LOG_INTERVAL_S if low else QUOTA_LOG_INTERVAL_S
    if (_QUOTA_STATE["responses"] < QUOTA_LOG_EVERY
            and now - _QUOTA_STATE["last_log"] < interval):
        return
    _QUOTA_STATE["responses"] = 0.0
    _QUOTA_STATE["last_log"] = now
    limit = _int_header(resp, "X-RateLimit-Limit")
    reset_in = max(0.0, _int_header(resp, "X-RateLimit-Reset") - now) / 60.0
    logging.log(logging.WARNING if low else logging.INFO,
                "GitHub quota: %d/%d requests left, resets in %.1f min",
                remaining, limit, reset_in)


def _jitter(seconds: float) -> float:
    return seconds + random.uniform(0.0, min(seconds, 10.0))


def _rate_limit_wait(resp: requests.Response, rounds: int) -> float:
    """Seconds to wait before retrying a rate-limited response, or 0.0 when the
    response is not a rate-limit rejection at all.

    `rounds` is how many rate-limit waits this request has already served and
    drives the backoff for secondary limits, which GitHub does not always
    annotate with Retry-After.
    """
    if resp.status_code not in (403, 429):
        return 0.0
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        wait = min(float(_int_header(resp, "Retry-After", 60) + 1),
                   SECONDARY_MAX_WAIT_S)
        wait = _jitter(wait)
        logging.warning("Secondary rate limit (Retry-After=%s); waiting %.0fs",
                        retry_after, wait)
        return wait
    if resp.headers.get("X-RateLimit-Remaining") == "0":
        reset = _int_header(resp, "X-RateLimit-Reset")
        wait = min(max(reset - time.time(), 1.0) + 2.0, MAX_SINGLE_WAIT_S)
        logging.warning("Primary rate limit exhausted; sleeping %.0fs until reset",
                        wait)
        return wait
    body = (resp.text or "")[:500].lower()
    if "secondary rate limit" in body or "abuse detection" in body:
        wait = _jitter(min(SECONDARY_BASE_WAIT_S * (2.0 ** rounds),
                           SECONDARY_MAX_WAIT_S))
        logging.warning("Secondary rate limit (no Retry-After); waiting %.0fs",
                        wait)
        return wait
    return 0.0


def _backoff(attempt: int) -> float:
    return min(60.0, 2.0 ** attempt) + random.uniform(0.0, 1.0)


def _request(url: str, token: Optional[str],
             params: Optional[Dict[str, Any]] = None,
             max_retries: int = MAX_RETRIES) -> requests.Response:
    """GET `url`, waiting out rate limits and retrying transient failures.

    Rate-limit waits do NOT consume the retry budget: only network errors and
    5xx responses do. Returns the response for any status the server answered
    definitively (200, or a non-retryable 4xx the caller must interpret).
    Raises GitHubApiError when the retry budget or the total wait budget is
    exhausted, so no caller ever mistakes a truncated result for a complete one.
    """
    attempt = 0
    rounds = 0
    waited = 0.0
    while True:
        try:
            resp = requests.get(url, headers=_headers(token), params=params,
                                timeout=REQUEST_TIMEOUT_S)
        except requests.RequestException as exc:
            attempt += 1
            if attempt >= max_retries:
                raise GitHubApiError(
                    f"GET {url} failed after {attempt} attempts: {exc}") from exc
            delay = _backoff(attempt)
            logging.warning("GET %s network error (%s); retry %d/%d in %.0fs",
                            url, exc, attempt, max_retries, delay)
            time.sleep(delay)
            continue
        _log_quota(resp)
        if resp.status_code == 200:
            return resp
        wait = _rate_limit_wait(resp, rounds)
        if wait > 0.0:
            if waited + wait > MAX_TOTAL_WAIT_S:
                raise GitHubApiError(
                    f"GET {url}: rate-limited for more than "
                    f"{MAX_TOTAL_WAIT_S / 3600.0:.0f}h; giving up")
            rounds += 1
            waited += wait
            time.sleep(wait)
            continue
        if resp.status_code in (500, 502, 503, 504):
            attempt += 1
            if attempt >= max_retries:
                raise GitHubApiError(
                    f"GET {url}: HTTP {resp.status_code} after {attempt} attempts")
            delay = _backoff(attempt)
            logging.warning("GET %s -> %s; retry %d/%d in %.0fs",
                            url, resp.status_code, attempt, max_retries, delay)
            time.sleep(delay)
            continue
        return resp


def get_json(url: str, token: Optional[str],
             params: Optional[Dict[str, Any]] = None,
             max_retries: int = MAX_RETRIES) -> Optional[Any]:
    """Single GET returning parsed JSON, or None when the endpoint answered
    definitively that there is nothing to return (404/410/other non-retryable
    4xx). Raises GitHubApiError when the request could not be completed."""
    resp = _request(url, token, params=params, max_retries=max_retries)
    if resp.status_code != 200:
        logging.warning("GET %s -> %s: %s", url, resp.status_code, resp.text[:200])
        return None
    try:
        return resp.json()
    except ValueError as exc:
        raise GitHubApiError(f"GET {url}: response body was not JSON") from exc


def paginate(path: str, token: Optional[str],
             params: Optional[Dict[str, Any]] = None,
             cap: Optional[int] = None,
             max_retries: int = MAX_RETRIES) -> Iterator[Any]:
    """Yield every item of a paginated list endpoint, following Link headers.

    `path` is an absolute URL or a path relative to the API root. `cap` bounds
    how many items are yielded (None = unbounded); reaching it is a deliberate,
    logged stop rather than a failure.

    The generator never ends early and quietly: any page it cannot fetch raises
    GitHubApiError, so a normal return always means "every item was seen". A
    410 on the first page (feature disabled for the repo) is the one benign
    empty case and is logged as such.
    """
    params = dict(params or {})
    params.setdefault("per_page", 100)
    url: Optional[str] = f"{API}{path}" if path.startswith("/") else path
    yielded = 0
    page = 0
    while url:
        resp = _request(url, token, params=params, max_retries=max_retries)
        if resp.status_code != 200:
            if page == 0 and resp.status_code == 410:
                logging.warning("paginate %s -> 410 Gone; endpoint disabled for "
                                "this repo, treating as empty", url)
                return
            raise GitHubApiError(
                f"paginate {url}: HTTP {resp.status_code} on page {page + 1} "
                f"after {yielded} items ({resp.text[:200]})")
        try:
            items = resp.json()
        except ValueError as exc:
            raise GitHubApiError(
                f"paginate {url}: page {page + 1} was not JSON") from exc
        if not isinstance(items, list):
            raise GitHubApiError(
                f"paginate {url}: expected a JSON list on page {page + 1}, "
                f"got {type(items).__name__}")
        page += 1
        for it in items:
            yield it
            yielded += 1
            if cap is not None and yielded >= cap:
                logging.info("paginate %s: item cap %d reached after %d pages",
                             url, cap, page)
                return
        url = resp.links.get("next", {}).get("url")
        params = None  # the next URL already carries the query params
