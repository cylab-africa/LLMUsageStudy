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
| **Per-branch coverage** (metrics across branches, not just default) | partial | 🆕 branch enumeration in orchestrator |
| **Change-in-quality / speed-vs-quality summary** (before vs after AI adoption) | R notebooks do it causally for populations | 🆕 build `analyze_single_repo.py` |
| **One-command orchestrator** | RUNBOOK is manual | 🆕 build `run_ai_impact.py` |

---

## 1. Architecture

```
repo outputs/_tools/
  detect_ai_agents.py        # existing — AI coding-agent adoption
  collect_issue_metrics.py   # NEW — GitHub issues: resolution time, labels, who closed
  collect_review_metrics.py  # NEW — GitHub PRs: review comments, reviewers, AI review bots
  analyze_single_repo.py     # NEW — before/after-adoption summary + plots
  run_ai_impact.py           # NEW — orchestrator: clone → all collectors → merge → analyze
lib/
  ai_signatures.py           # NEW — shared agent + review-bot signature tables (single source of truth)
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
  meta.json                    # repo url, HEAD, default branch, branches[], run timestamp, tool versions
  velocity_monthly.csv         # month, commits, lines_added, lines_removed, contributors, branch
  quality_monthly.csv          # month, ncloc, bugs, vulnerabilities, code_smells, duplication,
                               #        comment_lines_density, cognitive_complexity, sqale_index(debt)
  warnings.csv                 # rule, type, severity, count, month
  ai_agent_commits.csv         # (from detect_ai_agents.py) commit, agent, signals, files, date
  ai_agent_summary.csv         # (from detect_ai_agents.py) agent, n_commits, first/last seen
  issues.csv                   # number, created_at, closed_at, resolution_hours, state, labels, closed_by, is_bug
  issue_monthly.csv            # month, opened, closed, median_resolution_hours, open_bug_count
  reviews.csv                  # pr_number, reviewer, is_ai_bot, review_state, n_comments, submitted_at, merged
  review_monthly.csv           # month, prs_opened, prs_merged, median_review_comments, ai_review_share
  SUMMARY.md                   # human-readable before/after-adoption report (like existing EVALUATION.md)
  plots/                       # velocity, quality, issue-time, review trends w/ adoption line
```

---

## 3. The new components — build order & spec

Build in this order; each is independently testable.

### 3.1 `lib/ai_signatures.py` (do first — everything else imports it)
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
Uses PyGithub (already a dependency). For `state=all` issues (excluding PRs):
- pull `created_at`, `closed_at`, `state`, `labels`, `closed_by`, `user`
- `resolution_hours = (closed_at - created_at) / 3600` for closed issues
- `is_bug = any label matches /bug|defect|regression|fix/i`
- write `issues.csv`; aggregate to `issue_monthly.csv` (opened, closed, median
  resolution hours, open-bug backlog).

CLI: `python collect_issue_metrics.py owner/name /out/dir` (reads `GITHUB_TOKEN`
from `.env`). Handle pagination + rate limits (reuse the `handle_rate_limit`
decorator pattern in `scripts/fetch_github.py`). For repos with thousands of
issues, expose `--since YYYY-MM` to bound the window.

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
2. **Enumerate branches** (`git branch -r`), record in `meta.json`. For the
   monthly quality series, analyze the **default branch**; additionally scan
   each **branch tip** once so branches can be compared at HEAD (keeps scan
   count bounded — full monthly series per branch would be N×20 scans).
3. Build the isolated study workspace (RUNBOOK §6): one-row `repos.csv`, clone
   into `../CursorRepos/<owner_repo>`, write `.env`, Docker scanner wrapper.
4. Start Dockerized SonarQube on a free port; wait for `status:UP`; mint token
   (RUNBOOK §3–4). Force multiprocessing `fork` on macOS (RUNBOOK §7).
5. Run, in sequence: `analyze_repos` (velocity) → `run_sonarqube` (quality) →
   `collect_sonarqube_warnings` → `detect_ai_agents` → `collect_issue_metrics`
   → `collect_review_metrics`.
6. Copy/rename outputs into `repo_report/<owner_repo>/`.
7. Call `analyze_single_repo.py`.
8. Tear down the container (RUNBOOK §10).

Design it as thin subprocess calls to the existing scripts (don't reimplement
velocity/SonarQube). Make each stage independently skippable
(`--skip-sonar`, `--skip-github`) so a repo with no GitHub token or a config-only
repo (like mosip-config) still produces the git-only half.

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
STUDY=/Users/mbohbless/Software/Upanzi/CursorStudy
cp "$STUDY/.env.example" "$STUDY/.env"    # add GITHUB_TOKEN (for issues/reviews)

python "$STUDY/repo outputs/_tools/run_ai_impact.py" \
  --repo-url https://github.com/OWNER/NAME.git \
  --out "$STUDY/repo outputs/repo_report" \
  --port 9011                    # any free port for Docker SonarQube
# flags: --skip-sonar  --skip-github  --since 2023-01  --branches all
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
- **SonarQube async gotcha:** last month may need a second scan pass (RUNBOOK §Notes).
- **Log every cap:** `--since` windows and skipped PRs/issues must be logged, not
  silently dropped, so "no signal" is never confused with "not collected".

---

## 7. Build checklist (suggested order)
1. [ ] `lib/ai_signatures.py` — extract shared tables + add `REVIEW_BOTS`; repoint `detect_ai_agents.py`.
2. [ ] `collect_issue_metrics.py` + test on a small public repo.
3. [ ] `collect_review_metrics.py` + synthetic-bot test.
4. [ ] `run_ai_impact.py` orchestrator (wrap RUNBOOK, add branch enumeration).
5. [ ] `analyze_single_repo.py` (before/after summary + plots).
6. [ ] End-to-end on one AI-using repo + regression on mosip-config.
7. [ ] (Later) population concat → R notebooks for the causal layer.
```
```
