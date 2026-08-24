# mosip/mosip-config — full evaluation (AI agent usage + all paper metrics)

Evaluates `mosip/mosip-config` against every dimension the paper *"Speed at the
Cost of Quality"* measures, generalized from Cursor-only to **all major AI
coding agents**. HEAD = 2cc684a (2025-12-16). Star gating skipped per request.

## 1. AI coding-agent usage (the "treatment" / AI-usage signal)
Detected via 3 independent signals — config files, bot/author identities, and
commit-message co-author trailers — for: Cursor, Claude Code, GitHub Copilot,
Windsurf, Codeium, Cline, Roo Code, Aider, Continue, Sourcegraph Cody, Gemini,
OpenAI Codex / AGENTS.md, Amazon Q, Tabnine, Junie, Kilo Code, Zed AI, Qodo,
Devin, Sweep.

**Result: NONE detected.** Across **16,053 non-merge commits** on all branches
and **317 distinct authors**:
- 0 agent config files ever committed (no `.cursor*`, `CLAUDE.md`, `.claude/`,
  `copilot-instructions.md`, `AGENTS.md`, `.windsurf*`, `.aider*`, etc.)
- 0 AI-bot author/committer identities
- 243 `Co-authored-by` trailers — **all human contributors**, 0 AI agents

Detector validated against synthetic agent commits (all matched). See
`ai_agent_commits.csv` / `ai_agent_summary.csv` (both empty = no usage) and the
reusable tool `../_tools/detect_ai_agents.py`.

## 2. Velocity metrics (per month, 2024-01 → 2025-08, 16 active months)
From git history: ~255 commits in window; monthly commits 1–62; large churn
spikes (e.g. +6170 lines 2024-05). Full series in `ts_mosip_config_monthly.csv`
(columns: commits, lines_added, lines_removed, contributors).

## 3. Quality / complexity metrics (SonarQube 26.6, per month)
| Metric | 2024-01 | 2025-08 | Trend |
|---|---|---|---|
| ncloc | 3079 | 3586 | +16% (XML files only) |
| bugs | 0 | 0 | flat |
| vulnerabilities | 1 | 1 | flat (hard-coded credential, `hazelcast_cache.xml`) |
| code_smells | 1 | 5 | rising |
| technical_debt (min) | 5 | 25 | rising |
| duplicated_lines_density | 0% | 0% | flat |
| comment_lines_density | 4.7% | 4.7% | flat |
| cognitive_complexity | n/a | n/a | not computed (XML-only sources) |

Warnings breakdown in `sonarqube_warnings.csv` / `sonarqube_warning_definitions.csv`:
5× commented-out code (`xml:S125`, CODE_SMELL) + 1× hard-coded password
(`xml:S2068`, VULNERABILITY).

## 4. Dependency health / technical lag
**N/A** — no dependency manifests (`package.json`, `pom.xml`, etc.) in this
config repo, so the paper's dependency-lag metrics do not apply.

## Interpretation
mosip-config is a **configuration repository with zero AI-agent adoption**. In
the paper's framework it cannot be a *treatment* unit (no adoption event); it
can only ever be a **control candidate**. Its quality did drift mildly worse
(code_smells 1→5, debt 5→25 min) but with no agent usage, none of that is
attributable to AI — it's just normal config growth.

## Limitation: this is one repo
The paper's claim ("agents raise short-term velocity but long-term complexity")
is an *average causal effect* estimated by comparing many agent-adopting repos
against matched controls via DiD / panel GMM. A single repo — especially one
with no agent usage — cannot produce that finding. To actually compare
Claude Code vs Cursor vs Copilot etc., the detector here must be run over a
**population** of repos to build per-agent treatment cohorts + matched controls,
then fed to the study's matching + DiD notebooks.
