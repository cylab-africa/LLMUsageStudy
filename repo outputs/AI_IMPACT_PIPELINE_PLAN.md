# AI-Impact Pipeline — design & step-by-step build guide

**Goal.** Given *one repository URL*, evaluate — across its branches and commit
history — code quality, change in quality, velocity (speed / code size), bugs,
issue-resolution times, review comments, which AI coding/review tools were used,
and then produce an analysis of what (if anything) AI usage changed. The tool is
built per-repo but its outputs are **row-appendable**, so running it over many
repos yields the population dataset the study's R notebooks (DiD / panel GMM)
already consume.

Decisions baked into this plan (from scoping):
- **Unit:** single-repo tool, designed to scale to a population.
- **Granularity:** monthly snapshots for the expensive SonarQube quality scans.
- Reuses the study's own `scripts/*.py` wherever they already do the job.

> **Before quoting any number from `SUMMARY.md`, read §8 (known limitations).**
> The headline hazard: `adoption_month` is the first AI action of *any* kind, so
> an AI review bot can set the before/after split point months before an agent
> writes a line of code.

---

## 0. What already exists vs. what is new

| Dimension | Source | Status |
|---|---|---|
| Velocity: commits, lines +/-, contributors (monthly) | `scripts/analyze_repos.py` | ✅ reuse |
| Quality/complexity: ncloc, bugs, vulns, code_smells, duplication, comment density, cognitive complexity, tech debt (monthly snapshots) | `scripts/run_sonarqube.py` | ✅ reuse |
| Warnings breakdown per rule | `scripts/collect_sonarqube_warnings.py` + `classify_sonarqube_warnings.py` | ✅ reuse |
| AI coding-agent usage (20+ agents, 3 signals) | `repo outputs/_tools/detect_ai_agents.py` | ✅ reuse |
| Single-repo orchestration (Docker SonarQube, isolated workspace) | `repo outputs/RUNBOOK.md` | ✅ reuse, wrap in a CLI |
| **Issue-resolution times** (open→close durations, distributions) | — | 🆕 build `collect_issue_metrics.py` |
| **PR review comments + AI review-bot detection** (Copilot review, CodeRabbit, Sourcery, Qodo Merge, …) | — | 🆕 build `collect_review_metrics.py` |
| **Per-branch coverage** (metrics across branches, not just default) | partial | ⚠️ **branch *names* only** — `enumerate_branches()` writes `branches[]` into `meta.json`; velocity + quality are default-branch HEAD only (`analyze_repos.py` → `repo.iter_commits()`); only `detect_ai_agents.py` is all-branches (`git log --all`) — §8.2 |
| **Change-in-quality / speed-vs-quality summary** (before vs after AI adoption) | R notebooks do it causally for populations | 🆕 build `analyze_single_repo.py` |
| **One-command orchestrator** | RUNBOOK is manual | 🆕 build `run_ai_impact.py` |

---

## 1. Architecture

```
repo outputs/_tools/          # everything lives flat here; there is no lib/ package
  ai_signatures.py           # shared agent + review-bot signature tables (single source of truth)
  detect_ai_agents.py        # AI attribution of commits + merges across all branches
  gh_rest.py                 # GitHub REST helper: pagination + rate-limit handling
  collect_issue_metrics.py   # GitHub issues: resolution time, first response, labels, who closed
  collect_review_metrics.py  # GitHub PRs: review comments, reviewers, AI review bots, prs.csv
  build_ai_operations.py     # unify every AI operation → ai_operations.csv + ai_adoption.csv
  analyze_single_repo.py     # before/after-adoption summary + plots
  run_sonar_full.py          # widened-window, CE-task-blocking wrapper for scripts/run_sonarqube.py
  run_ai_impact.py           # orchestrator: clone → all collectors → unify → analyze
  scan_mosip.py              # one-off historical mosip-config scan (not part of the pipeline)
```

Every collector writes a flat CSV keyed by `repo_name` (and `month` where
time-series). The orchestrator merges them into one `repo_report/` folder per
repo. To scale to a population, run the orchestrator per repo and `concat` the
CSVs — column schemas are identical to the study's `data/*.csv`, so the R
notebooks read them unchanged.

**Determine the AI-adoption event once** (earliest AI signal from
`detect_ai_agents.py`) and reuse that single `adoption_month` across every
analysis so "before vs after" is consistent.

---

## 2. Output data model (per repo)

```
repo_report/<owner_repo>/
  meta.json                    # repo url, HEAD, default branch, branch NAMES + count, --since,
                               #   plus per-stage outcome (stages / failed_stages /
                               #   aborted / sonar_ce_failures)
  velocity_monthly.csv         # copy of the study's ts_repos_monthly.csv: repo_name, month,
                               #   latest_commit, cursor, commits, lines_added, lines_removed,
                               #   contributors + the SonarQube columns (default branch HEAD only)
  quality_monthly.csv          # IDENTICAL copy of that same file; the analyzer selects ncloc, bugs,
                               #   vulnerabilities, code_smells, duplicated_lines_density,
                               #   comment_lines_density, cognitive_complexity, technical_debt
  sonarqube_warnings.csv       # repo_name, issue_key, component, line, rule, creation_date
  sonarqube_warning_definitions.csv   # rule, type, severity, effort, example_message
  ai_agent_commits.csv         # (detect_ai_agents.py) agent, operation (commit/push/merge),
                               #   commit, date, author, committer, signals, files
  ai_agent_summary.csv         # (detect_ai_agents.py) agent, n_commits, first/last seen, signals
  ai_operations.csv            # (build_ai_operations.py) date, date_utc, agent,
                               #   operation, category, actor, ref, signal
  ai_adoption.csv              # per-agent first action + counts, plus the __OVERALL__ adoption row
  issues.csv                   # number, created_at, closed_at, resolution_hours, first_response_hours,
                               #   state, labels, n_comments, author, closed_by, assignees, is_bug
  issue_monthly.csv            # month, opened, closed, median/mean resolution hours, open_bug_backlog
  issue_stats.csv              # one row: totals, close rate, resolution percentiles, AI actors
  reviews.csv                  # pr_number, pr_created_at, pr_merged_at, reviewer, is_ai_bot,
                               #   ai_bot_name, review_state, submitted_at, n_review_comments
  review_monthly.csv           # month, prs_opened, prs_merged, median_review_comments, ai_review_share
  prs.csv                      # pr_number, author + merged_by with AI attribution for each
  SUMMARY.md                   # human-readable before/after-adoption report (like existing EVALUATION.md)
  plots/                       # velocity, quality, issue-time trends w/ adoption line (matplotlib only)
```

Two things this model does **not** deliver, despite earlier drafts: there is no
`warnings.csv` (the two SonarQube files keep the study's own names), and there is
no per-branch `branch` column — velocity and quality are the same default-branch
file copied under two names.

---

## 3. The new components — build order & spec

Build in this order; each is independently testable.

### 3.1 `_tools/ai_signatures.py` (do first — everything else imports it)
Move the `PATH_SIGS` / `TEXT_SIGS` dicts out of `detect_ai_agents.py` into a
shared module, and add a **review-bot table**:

```python
REVIEW_BOTS = {
  "GitHub Copilot review": [r"copilot-pull-request-reviewer\[bot\]", r"\bcopilot\b.*review"],
  "CodeRabbit":            [r"coderabbitai\[bot\]", r"coderabbit\.ai"],
  "Sourcery":              [r"sourcery-ai\[bot\]"],
  "Qodo Merge / PR-Agent": [r"qodo-merge-pro\[bot\]", r"codiumai-pr-agent\[bot\]", r"\bpr-agent\b"],
  "Ellipsis":              [r"ellipsis-dev\[bot\]"],
  "Greptile":              [r"greptile"],
  "Bito":                  [r"bito-code-review\[bot\]"],
  "Codacy / DeepSource":   [r"deepsource\[bot\]", r"codacy"],
  "Graphite / Diamond":    [r"graphite-app\[bot\]"],
}
```
`detect_ai_agents.py` keeps working (import from lib). One source of truth for
signatures avoids the two tables drifting apart.

### 3.2 `collect_issue_metrics.py` — issue resolution times
Built on `gh_rest.py` (`requests` only — no PyGithub, matching the RUNBOOK
venv). For `state=all` issues (excluding PRs):
- pull `created_at`, `closed_at`, `state`, `labels`, `closed_by`, `user`
- `resolution_hours = (closed_at - created_at) / 3600` for closed issues
- `is_bug = any label matches /bug|defect|regression|fix/i`
- write `issues.csv`; aggregate to `issue_monthly.csv` (opened, closed, median
  resolution hours, open-bug backlog) and a one-row `issue_stats.csv`
  (percentiles, first-response, AI actors).

CLI: `python collect_issue_metrics.py owner/name /out/dir` (reads `GITHUB_TOKEN`
from env or `.env`). Pagination and primary/secondary rate limits are handled in
`gh_rest.py`. `--since YYYY-MM` bounds the window; `--no-first-response` drops
the extra call per issue (§8.3).

### 3.3 `collect_review_metrics.py` — review comments + AI review bots
For each PR (`state=all`):
- `get_reviews()` → reviewer login, state (APPROVED/CHANGES_REQUESTED/COMMENTED),
  `submitted_at`
- `get_review_comments()` count (inline) + `get_issue_comments()` count (discussion)
- flag `is_ai_bot` by matching reviewer login against `REVIEW_BOTS`
- write `reviews.csv`; aggregate `review_monthly.csv` including
  `ai_review_share = AI-bot reviews / total reviews` per month.

This is what answers *"potential AI tool used to automate code review"* — it
detects a review bot **actually leaving reviews on PRs**, distinct from a coding
agent writing commits (which `detect_ai_agents.py` covers).

> Note: `get_reviews`/`get_review_comments` are per-PR API calls — the heaviest
> collector. Bound with `--since` and log how many PRs were skipped so coverage
> is never silently truncated.

### 3.4 Orchestrator `run_ai_impact.py`
Turns RUNBOOK.md steps 1–9 into one command. Responsibilities:
1. Parse `REPO_URL` → `owner/name`; clone full history to a temp workspace.
2. **Enumerate branches** (`git branch -r`) and record the *names* in
   `meta.json`. As built, that is all the branch handling does: the monthly
   velocity and quality series are computed on the default branch only, and the
   per-branch-tip scan sketched in earlier drafts was never implemented. Only
   `detect_ai_agents.py` is genuinely all-branches (`git log --all`) — §8.2
   explains why that asymmetry matters when reading the numbers.
3. Build the isolated study workspace (RUNBOOK §6): one-row `repos.csv`, the
   clone placed directly at `CursorRepos/<owner_repo>` (it *is* the study's
   working copy — no second copy of the tree), `.env`, Docker scanner wrapper.
4. Run, in sequence: `analyze_repos` (velocity) → `detect_ai_agents` →
   `collect_issue_metrics` → `collect_review_metrics` → `build_ai_operations`.
   The unified operations come before SonarQube because the warnings sample is
   windowed on the adoption month they derive.
5. Only then start Dockerized SonarQube on a free port, wait for `status:UP`,
   mint a token (RUNBOOK §3–4), force multiprocessing `fork` on macOS
   (RUNBOOK §7), and run `run_sonar_full.py` (quality) →
   `collect_sonarqube_warnings` (warnings sample).
6. Copy outputs into `repo_report/<owner_repo>/` (the two SonarQube CSVs keep
   their upstream names).
7. Call `analyze_single_repo.py`.
8. Tear down the container (RUNBOOK §10) and write `meta.json` — including the
   per-stage outcome map, so a partial run is never mistaken for a clean one.

Thin subprocess calls to the existing scripts (velocity/SonarQube are not
reimplemented). Each stage is independently skippable (`--skip-sonar`,
`--skip-github`, `--skip-warnings`) so a repo with no GitHub token or a
config-only repo (like mosip-config) still produces the git-only half; optional
stages that fail are recorded as `failed` in `meta.json` rather than aborting
the repo.

### 3.5 `analyze_single_repo.py` — the "what did AI change?" layer
This is the analysis you actually want. Given the merged CSVs + `adoption_month`:
- **Split** every monthly series at `adoption_month` into *pre* / *post*.
- **Velocity delta:** mean monthly commits & net lines pre vs post (speed).
- **Size delta:** ncloc growth rate pre vs post.
- **Quality delta:** slope of `code_smells`, `bugs`, `cognitive_complexity`,
  `sqale_index` (tech debt) pre vs post → the paper's core "speed up front,
  complexity later" signal, expressed per-repo.
- **Speed-vs-quality:** velocity delta plotted against quality-slope delta.
- **Issue health:** median resolution hours & open-bug backlog pre vs post.
- **Review automation:** `ai_review_share` trend; correlate with resolution time.
- Emit `SUMMARY.md` (same shape as the existing `EVALUATION.md`) + `plots/` with
  a vertical adoption line on each chart.

**State the honest caveat in the output** (the existing EVALUATION.md already
does this well): a single repo gives a *descriptive* before/after, not a causal
effect. Confounds — project maturity, contributor influx, release cycles — are
only separable across a matched population. Keep that sentence in `SUMMARY.md`.

---

## 4. Scaling to a population (the causal layer, already built)
Because every per-repo CSV matches the study's schema:
1. Run `run_ai_impact.py` over a repo list → many `repo_report/*/` folders.
2. `concat` all `velocity_monthly.csv` → `data/ts_repos_monthly.csv`; same for
   quality/issues. AI-adopting repos = treatment; the rest = control candidates.
3. Feed `scripts/matching_*.py` → `scripts/prepare_panel_event.py` → the R
   notebooks (`DiffInDiffBorusyak.Rmd`, `DynamicPanel.Rmd`) unchanged.
4. Per-agent cohorts (Cursor vs Claude Code vs Copilot) come straight from
   `ai_agent_summary.csv` — group treatment repos by `agent` to compare tools.

No new statistics code needed here — the point of matching the schema is to
inherit the paper's estimators for free.

---

## 5. Runbook (how to run it once built)

```bash
STUDY="$(git rev-parse --show-toplevel)"   # your checkout of this repo
cp "$STUDY/.env.example" "$STUDY/.env"     # add GITHUB_TOKEN (for issues/reviews)

python "$STUDY/repo outputs/_tools/run_ai_impact.py" \
  --repo-url https://github.com/OWNER/NAME.git \
  --out "$STUDY/repo outputs/repo_report" \
  --port 9011                    # any free port for Docker SonarQube
# flags: --skip-sonar  --skip-github  --skip-warnings  --since 2023-01
#        --max-prs 300  --adoption YYYY-MM  --workspace-root DIR
#        --keep-workspace                          (there is no --branches flag)
```
Prereqs unchanged from RUNBOOK.md: Docker Desktop running, Python 3.10+, git.
Output: `repo_report/<owner_repo>/SUMMARY.md` + CSVs + plots.

---

## 6. Validation before trusting results
- **Detector self-test:** the existing detect_ai_agents was validated against
  synthetic agent commits — keep that; add synthetic review-bot PRs for the new
  review detector.
- **Sanity repo:** run on a repo with *known* Claude Code / Copilot usage and
  confirm adoption month + agent are picked up; run on mosip-config and confirm
  it still reports "no AI usage" (regression check against existing EVALUATION.md).
- **SonarQube async gotcha:** the raw `run_sonarqube` returns before the
  Community-Edition task finishes, so the manual RUNBOOK path may need a second
  scan pass; `run_sonar_full.py` blocks on the CE task id, so the orchestrated
  path does not.
- **Log every cap:** `--since` windows and skipped PRs/issues must be logged, not
  silently dropped, so "no signal" is never confused with "not collected".

---

## 7. Build checklist (suggested order)
1. [x] `_tools/ai_signatures.py` — shared tables + `REVIEW_BOTS`; `detect_ai_agents.py` repointed.
2. [x] `collect_issue_metrics.py` (also emits `issue_stats.csv`).
3. [x] `collect_review_metrics.py` (also emits `prs.csv`).
4. [x] `run_ai_impact.py` orchestrator (wraps RUNBOOK; branch *names* only, §8.2).
5. [x] `analyze_single_repo.py` (before/after summary + plots).
6. [x] End-to-end on `Mosip/esignet`; mosip-config remains the "no AI usage" regression case.
7. [ ] Split coding-adoption from review-adoption in the reported summary (§8.1).
8. [ ] Latent/undeclared-usage detector (`detect_ai_latent.py`) — idea only, nothing built.
9. [ ] (Later) population concat → R notebooks for the causal layer.

---

## 8. Known limitations (verified against a real run)

### 8.1 Adoption conflates AI review with AI code generation
`build_ai_operations.py` defines adoption as the **first trackable AI action of
any kind**, which puts an AI code-*review* bot and an AI code-*generation* agent
in the same bucket — and review dominates the volume (that run: 778 review
actions against 67 coding actions). On `Mosip/esignet` adoption therefore
resolves to **2025-11** (CodeRabbit reviews), while the coding agents first
appear five to seven months later: Codex 2026-04, Claude Code 2026-06,
Cursor 2026-06. `SUMMARY.md` then
invites the reader to read §1 velocity against §2 quality slope "as the paper's
core finding" across a split point at which **no AI was writing any code**.

Mitigation — report the two adoptions separately. `ai_adoption.csv` carries a
`category` per agent, so *review adoption* is the earliest `first_action_date`
among `category=review` rows and *coding adoption* the earliest among
`category=coding` rows. Re-run `analyze_single_repo.py --adoption YYYY-MM` with
the coding-adoption month whenever the question is "did AI *writing* code change
quality". A repo whose two months differ must not be summarised with one split.

### 8.2 AI commit counts and velocity counts use different commit sets
`detect_ai_agents.py` walks `git log --all` (every branch, including unmerged
ones). `scripts/analyze_repos.py` walks `repo.iter_commits()` — HEAD of the
default branch only — and the SonarQube monthly snapshots follow the same
default-branch commits. AI operation counts and velocity counts are therefore
computed over different populations of commits: they are not directly
comparable, and an "AI share of commits" cannot be formed by dividing one by the
other. `meta.json` lists branch names; no metric is computed per branch.

### 8.3 GitHub API budget
Both GitHub collectors are REST with per-item calls:

```
calls ≈ (issues + PRs) / 100   # list pages, 100 items per page
      + issues                 # first-response comment fetch, 1 per issue
      + 2 × PRs                # ≥1 reviews page + ≥1 inline-comments page per PR
      + merged PRs             # GET /pulls/{n} for merged_by (--no-merged-by skips)
```

| Target | PRs | Issues | ≈ API calls |
|---|--:|--:|--:|
| `Mosip/esignet` | 833 | 311 | ≈ 2,600 (≈ 2,000 with `--no-merged-by`) |
| 20 MOSIP repos of that size | — | — | ≈ 50,000 |

An authenticated PAT allows 5,000 requests/hour, so one esignet-sized repo costs
about half an hour's quota and ~2 such repos/hour is the hard ceiling. A
15-hour, 20-repo run averages below the limit, but the review collector issues
calls back-to-back, so bursts hit it. `gh_rest.py` logs remaining quota as it
goes, sleeps until `X-RateLimit-Reset` on the primary limit (a single wait capped
at 1 h), backs off with jitter on secondary limits, and raises `GitHubApiError`
once one request has waited more than 4 h in total — a rate-limited run stalls or
fails loudly, it never returns silently truncated data. Per-PR review and comment
calls dominate, so `--max-prs N` is the effective lever (skipped PRs are logged,
never silently dropped); `--since YYYY-MM` bounds both collectors,
`--no-first-response` saves one call per issue and `--no-merged-by` one per
merged PR (at the cost of the `pr_merged` attribution); `--resume` on the issue
collector makes a re-run after an interrupted batch free.

### 8.4 Operation vocabulary
`ai_operations.csv` emits `commit`, `push`, `merge`, `pr_opened`, `pr_merged`,
`pr_reviewed`, `issue_opened`, `issue_closed`. `push` means an agent identity
committed work it did not author (the `committer-login(push)` signal without
`author-login`); a commit with several parents stays a `merge`.

`category` is `coding`, `review` or `other-bot`. Non-AI automation (dependabot,
CI, release bots) is classified `other-bot` by `match_login()`: it is written to
`ai_operations.csv` for transparency but never counted toward adoption or the AI
totals. Those rows come from the GitHub-actor sources only (PR author/merger, PR
reviewer, issue author/closer), because `ai_agent_commits.csv` holds AI
detections exclusively — there is no other-bot `commit`/`push`/`merge` row.
