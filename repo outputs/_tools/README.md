# AI-Impact toolkit (`_tools/`)

Implements `AI_IMPACT_PIPELINE_PLAN.md`: evaluate one repo's AI-tool usage and
its effect on velocity, code quality, bugs, issue-resolution times, and review
automation — with a before/after-adoption analysis. Per-repo CSVs are
schema-compatible with the study's `data/*.csv` for later population scale-up.

> **Read "Known caveats" below before quoting any number out of `SUMMARY.md`.**
> The headline hazard: adoption is the first AI action of *any* kind, so an AI
> review bot can set the before/after split point months before an agent writes
> a single line of code.

## Files
| File | Role |
|---|---|
| `ai_signatures.py` | Single source of truth: coding-agent + AI-review-bot signatures |
| `detect_ai_agents.py` | AI attribution of commits, pushes **and merges** across all branches (`git log --all`) — explicit markers (config files, commit-e-mail identities, trailers); records `operation` (`commit`/`push`/`merge`) |
| `gh_rest.py` | GitHub REST helper (`requests` only): pagination + rate-limit |
| `collect_issue_metrics.py` | Issue resolution times + percentiles, first-response, comments, AI actors, bug backlog |
| `collect_review_metrics.py` | PR review comments + AI review-bot share; `prs.csv` (who opened/merged each PR) |
| `build_ai_operations.py` | Unifies every AI operation (commit/merge/PR opened/PR merged/review/issue) → `ai_operations.csv` + `ai_adoption.csv`; adoption = **first trackable AI action of any kind** |
| `analyze_single_repo.py` | Before/after-adoption `SUMMARY.md` (ops breakdown, quality slopes, issue stats, SonarQube glossary) + plots |
| `run_sonar_full.py` | Wrapper on the study's `run_sonarqube.py`: widens its hardcoded date window and blocks on each Community-Edition analysis task |
| `run_ai_impact.py` | Orchestrator: clone → all collectors → unify → analyze |
| `scan_mosip.py` | One-off standalone scan of `mosip/mosip-config` (hardcoded `/tmp` paths); kept for reference, not part of the pipeline |

> **Planned, not built:** a latent-usage detector (`detect_ai_latent.py` —
> inferring *undeclared* AI usage from leaks, code telltales, bulk and throughput
> into a per-author likelihood) is a backlog idea in the plan only. No such file
> ships here and nothing in this pipeline infers undeclared usage: every
> detection is an explicit marker file, identity, or commit trailer.

## One-command run
```bash
STUDY="$(git rev-parse --show-toplevel)"   # run from inside your checkout,
                                           # or set STUDY to it explicitly
export GITHUB_TOKEN=ghp_xxx                # or put GITHUB_TOKEN=... in $STUDY/.env

python "$STUDY/repo outputs/_tools/run_ai_impact.py" \
  --repo-url https://github.com/OWNER/NAME.git \
  --out "$STUDY/repo outputs/repo_report" --port 9011
```
Prereqs: Docker Desktop running (for SonarQube), Python 3.10+ with
`requests`, `GitPython`, `pandas` (matplotlib optional for plots), git.

Useful flags: `--skip-sonar` (git+GitHub only, no Docker), `--skip-github`
(no token), `--skip-warnings`, `--since 2023-01`, `--max-prs 300` (bound the
heaviest calls), `--adoption YYYY-MM` (override split point),
`--workspace-root DIR` (where the throwaway workspace goes), and
`--keep-workspace` (debug).

## Output → `repo_report/<owner_repo>/`
| File(s) | Contents |
|---|---|
| `SUMMARY.md` | Before/after report written by `analyze_single_repo.py` |
| `meta.json` | Repo URL, HEAD, default branch, branch **names** + count, `--since`, and the outcome of every stage (`stages`, `failed_stages`, `aborted`, `sonar_ce_failures`) — check it first after an unattended run |
| `velocity_monthly.csv`, `quality_monthly.csv` | Two copies of the study's combined `ts_repos_monthly.csv` (git activity **and** SonarQube columns); the analyzer selects the columns it needs from each |
| `sonarqube_warnings.csv`, `sonarqube_warning_definitions.csv` | Per-issue warnings and the rule → type/severity/effort table, copied under the study's own filenames — **no `warnings.csv` is produced** |
| `ai_agent_commits.csv`, `ai_agent_summary.csv` | Commit/merge-level AI attribution + per-agent totals and first/last seen |
| `ai_operations.csv`, `ai_adoption.csv` | Unified AI operations (with a normalised `date_utc`, since git and the GitHub API disagree on format) + per-agent first action and the `__OVERALL__` adoption row |
| `issues.csv`, `issue_monthly.csv`, `issue_stats.csv` | Per-issue records, monthly aggregates, one-row repo-wide statistics |
| `reviews.csv`, `review_monthly.csv`, `prs.csv` | Per-review records, monthly review aggregates, per-PR author/merger attribution |
| `plots/` | PNG trends with an adoption line — written only when matplotlib is installed |

The GitHub CSVs are absent when the run used `--skip-github`; the SonarQube CSVs
are absent under `--skip-sonar`.

## Run collectors individually
```bash
python collect_issue_metrics.py  OWNER/NAME  /out/dir  [--since 2023-01] [--no-first-response] [--max-issues N] [--resume]
python collect_review_metrics.py OWNER/NAME  /out/dir  [--since 2023-01] [--max-prs 300] [--no-merged-by]
python detect_ai_agents.py       /path/to/repo  OWNER/NAME  /out/dir
python build_ai_operations.py    /out/dir
python analyze_single_repo.py    /out/dir  [--adoption YYYY-MM]
```

## Operation and category vocabulary
`operation` in `ai_operations.csv` is one of `commit`, `push`, `merge`,
`pr_opened`, `pr_merged`, `pr_reviewed`, `issue_opened`, `issue_closed`.
`push` means an agent identity *committed work it did not author* (the
`committer-login(push)` signal without `author-login`); the `actor` column then
holds the committer. A commit with more than one parent stays a `merge`.

`category` is `coding`, `review`, or `other-bot`. Automation that is not a known
AI tool (dependabot, CI, release bots) is classified `other-bot` by
`match_login()`: those rows are written to `ai_operations.csv` for transparency
and **never** counted toward adoption or into the AI totals. They come from the
GitHub-actor sources only (PR author/merger, PR reviewer, issue author/closer) —
`ai_agent_commits.csv` holds AI detections exclusively, so a non-AI bot's commits
are invisible to this stage and no other-bot `commit`/`push`/`merge` row exists.

## Known caveats
### 1. Adoption merges AI *review* with AI *coding*
`adoption_month` is the first trackable AI action **of any kind**, so a review
bot commenting on PRs sets the split point exactly as readily as an agent
writing code. On `Mosip/esignet` adoption resolves to **2025-11** (CodeRabbit
reviews) while the first coding agents appear five to seven months later —
Codex 2026-04, Claude Code 2026-06, Cursor 2026-06. Every "post-adoption" month
in between had *no AI writing any code*, yet `SUMMARY.md` invites reading
velocity against the quality slope across that split "as the paper's core
finding". Taken at face value it attributes to AI code generation a period in
which none happened. The volumes make the same point: that run's AI operations
were 778 review actions against 67 coding actions.

Report the two adoptions separately. `ai_adoption.csv` already carries a
`category` per agent, so:
- **review adoption** = earliest `first_action_date` among `category=review` rows
- **coding adoption** = earliest `first_action_date` among `category=coding` rows

When the question is "did AI *writing* code change quality", re-run
`analyze_single_repo.py --adoption YYYY-MM` with the coding-adoption month; keep
the default split only for "did AI *touching* the project change anything". A
repo whose two months differ must never be summarised with one split point.

### 2. AI counts and velocity counts cover different commits
`detect_ai_agents.py` walks `git log --all` — **every branch**, including
unmerged ones. Velocity and the SonarQube monthly series come from the study's
`scripts/analyze_repos.py`, which walks `repo.iter_commits()` — **HEAD of the
default branch only**. The two are computed over different commit sets, so "N AI
commits" and "M commits/month" are not directly comparable and an AI share
cannot be obtained by dividing one by the other. `meta.json` records branch
*names* only; no metric is computed per branch.

### 3. GitHub API budget (plan for rate limits)
Both GitHub collectors are REST, with per-item calls. Roughly:

```
calls ≈ (issues + PRs) / 100   # issue/PR list pages, 100 items per page
      + issues                 # first-response comment fetch, 1 per issue
      + 2 × PRs                # ≥1 reviews page + ≥1 inline-comments page per PR
      + merged PRs             # GET /pulls/{n} for merged_by (--no-merged-by skips)
```

| Target | PRs | Issues | ≈ API calls |
|---|--:|--:|--:|
| `Mosip/esignet` | 833 | 311 | ≈ 2,600 (≈ 2,000 with `--no-merged-by`) |
| 20 MOSIP repos of that size | — | — | ≈ 50,000 |

An authenticated PAT gets **5,000 requests/hour**, so one esignet-sized repo
costs about half an hour's quota and ~2 such repos/hour is the ceiling. A
15-hour 20-repo run averages under the limit, but the review collector issues
calls back-to-back so bursts do hit it. `gh_rest.py` logs the remaining quota as
it goes, sleeps until `X-RateLimit-Reset` on the primary limit (one wait capped
at 1 h), backs off with jitter on secondary limits, and raises `GitHubApiError`
once one request has waited more than 4 h in total — so a rate-limited run
stalls or fails loudly, never returns silently truncated data. Budget for
stalls: one exhausted hour is one lost hour. Per-PR review and comment calls dominate the bill, so `--max-prs N`
(skipped PRs are logged, never silently dropped) is the effective lever;
`--since YYYY-MM` bounds both collectors, `--no-first-response` saves one
call per issue and `--no-merged-by` one per merged PR (at the cost of the
`pr_merged` attribution). `--resume` on the issue collector makes a re-run
after an interrupted overnight batch free rather than a second full bill.

## Notes
- A `GITHUB_TOKEN` is required for issue/review collection at any real scale
  (unauthenticated = 60 req/hr and will stall on large repos).
- SonarQube: `run_sonar_full.py` widens the study's hardcoded date window and
  blocks on each Community-Edition analysis task, so a single pass reliably
  captures every month (no more "run twice"). Each SonarQube metric is defined
  in the SUMMARY.md appendix.
- **AI adoption** is the *first trackable AI action of any kind* — commit,
  push, merge, PR opened/merged, review, or issue — computed by
  `build_ai_operations.py`, not the first agent config file. See caveat 1: that
  definition mixes review bots with coding agents.
- Single-repo output is **descriptive** before/after, not causal. For a causal
  estimate, run over many repos and `concat` the CSVs into the study's DiD /
  panel R notebooks (schemas already match).
