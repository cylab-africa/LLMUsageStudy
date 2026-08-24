# AI-Impact toolkit (`_tools/`)

Implements `AI_IMPACT_PIPELINE_PLAN.md`: evaluate one repo's AI-tool usage and
its effect on velocity, code quality, bugs, issue-resolution times, and review
automation — with a before/after-adoption analysis. Per-repo CSVs are
schema-compatible with the study's `data/*.csv` for later population scale-up.

## Files
| File | Role |
|---|---|
| `ai_signatures.py` | Single source of truth: coding-agent + AI-review-bot signatures |
| `detect_ai_agents.py` | AI attribution of commits **and merges** across all branches — explicit markers (config files, identities, trailers) + author/committer login; records `operation` |
| `detect_ai_latent.py` | Infers *undeclared* AI usage (leaks, code telltales, bulk, throughput) → per-author likelihood |
| `gh_rest.py` | GitHub REST helper (`requests` only): pagination + rate-limit |
| `collect_issue_metrics.py` | Issue resolution times + percentiles, first-response, comments, AI actors, bug backlog |
| `collect_review_metrics.py` | PR review comments + AI review-bot share; `prs.csv` (who opened/merged each PR) |
| `build_ai_operations.py` | Unifies every AI operation (commit/merge/push/PR/review/issue) → `ai_operations.csv` + `ai_adoption.csv`; adoption = **first trackable AI action of any kind** |
| `analyze_single_repo.py` | Before/after-adoption `SUMMARY.md` (ops breakdown, quality slopes, issue stats, SonarQube glossary) + plots |
| `run_ai_impact.py` | Orchestrator: clone → all collectors → unify → analyze |

## One-command run
```bash
STUDY=/Users/mbohbless/Software/Upanzi/CursorStudy
export GITHUB_TOKEN=ghp_xxx          # or put GITHUB_TOKEN=... in $STUDY/.env

python "$STUDY/repo outputs/_tools/run_ai_impact.py" \
  --repo-url https://github.com/OWNER/NAME.git \
  --out "$STUDY/repo outputs/repo_report" --port 9011
```
Prereqs: Docker Desktop running (for SonarQube), Python 3.10+ with
`requests`, `GitPython`, `pandas` (matplotlib optional for plots), git.

Useful flags: `--skip-sonar` (git+GitHub only, no Docker), `--skip-github`
(no token), `--since 2023-01`, `--max-prs 300` (bound the heaviest calls),
`--adoption YYYY-MM` (override split point), `--keep-workspace` (debug).

Output → `repo_report/<owner_repo>/`: `SUMMARY.md`, `meta.json`,
`velocity_monthly.csv`, `quality_monthly.csv`, `warnings.csv`,
`ai_agent_*.csv`, `issues.csv` + `issue_monthly.csv`,
`reviews.csv` + `review_monthly.csv`, `plots/`.

## Run collectors individually
```bash
python collect_issue_metrics.py  OWNER/NAME  /out/dir  [--since 2023-01] [--no-first-response] [--max-issues N]
python collect_review_metrics.py OWNER/NAME  /out/dir  [--since 2023-01] [--max-prs 300]
python detect_ai_agents.py       /path/to/repo  OWNER/NAME  /out/dir
python detect_ai_latent.py       /path/to/repo  OWNER/NAME  /out/dir  [--labels ai_agent_commits.csv]
python build_ai_operations.py    /out/dir
python analyze_single_repo.py    /out/dir  [--adoption YYYY-MM]
```

## Notes
- A `GITHUB_TOKEN` is required for issue/review collection at any real scale
  (unauthenticated = 60 req/hr and will stall on large repos).
- SonarQube: `run_sonar_full.py` widens the study's hardcoded date window and
  blocks on each Community-Edition analysis task, so a single pass reliably
  captures every month (no more "run twice"). Each SonarQube metric is defined
  in the SUMMARY.md appendix.
- **AI adoption** is the *first trackable AI action of any kind* — commit, merge,
  push, PR opened/merged, review, or issue — computed by `build_ai_operations.py`,
  not the first agent config file. `other-bot` automation (dependabot/CI) is
  recorded for transparency but never counted as AI.
- Single-repo output is **descriptive** before/after, not causal. For a causal
  estimate, run over many repos and `concat` the CSVs into the study's DiD /
  panel R notebooks (schemas already match).
