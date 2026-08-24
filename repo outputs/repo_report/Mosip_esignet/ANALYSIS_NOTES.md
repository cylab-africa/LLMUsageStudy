# Mosip/esignet — analyst notes (window: 2025-01 → 2026-07)

Companion to `SUMMARY.md` (auto-split on coding-agent adoption) and
`SUMMARY_coderabbit_2025-11.md` (split on AI-review adoption). This run has
**complete SonarQube quality coverage for all 18 months** and **review data back
to 2025-01** (the earlier run's gaps are fixed).

## Headline
esignet has **two separate AI-adoption events**, and they must not be conflated:
1. **AI code review — CodeRabbit, adopted 2025-11.** Clean, sustained. 9 months
   of post-adoption history → genuinely analyzable.
2. **AI coding agents — Codex/AGENTS.md (2026-04), Cursor & Claude Code (2026-06).**
   ~1–3 months old → too recent to measure; any before/after is edge-dominated.

## AI tools detected
| AI tool | Type | Adoption | Evidence |
|---|---|---|---|
| CodeRabbit | Code review (bot) | **2025-11** (0% → 33% → ~40–48% sustained) | 763 of ~1.9k reviews |
| OpenAI Codex / AGENTS.md | Coding agent (config) | 2026-04-28 | `AGENTS.md`, `esignet-service/AGENTS.md` (6 commits) |
| Claude Code | Coding agent | 2026-06-18 | co-author trailers (4 commits) |
| Cursor | Coding agent | 2026-06-29 | co-author trailers (55 commits) |

CodeRabbit AI-review share by month: 0% every month Jan–Oct 2025, then
Nov 0.33 · Dec 0.49 · 2026: 0.42, 0.31, 0.42, 0.46, 0.40, 0.45, 0.36.

## Analysis A — AI code review (CodeRabbit), split at 2025-11  ← the durable finding
Pre = 2025-01…2025-10 (no AI review). Post = 2025-11…2026-07 (CodeRabbit active).
Quality **degradation slope flattens markedly** after adoption:

| Metric (slope = change/month) | pre-slope | post-slope | interpretation |
|---|--:|--:|---|
| code smells | +45.4 | +3.8 | rise nearly stops |
| cognitive complexity | +82.5 | +25.2 | rise slows ~3× |
| technical debt (min) | +363.2 | **−198.6** | debt now *declining* |
| ncloc | +1523 | +152 | code growth also slows |
| bugs | −2.35 | −0.11 | already falling pre; flattens |
| vulnerabilities | −1.07 | 0.00 | resolved pre-adoption, stays 0-ish |

**Read with care.** ncloc growth also slowed (~1523→152 loc/mo), so part of the
debt/smell flattening is simply *less new code*, not necessarily CodeRabbit
catching issues. Still, technical debt going **negative** (active cleanup) while
the codebase keeps growing is consistent with review automation surfacing
maintainability issues. Directionally this is the **opposite** of the paper's
coding-agent finding: AI *review* here tracks with slower quality decay.

## Analysis B — AI coding agents, split at 2026-04 (the auto SUMMARY.md)
Post = only 2026-04, -05, -07 (2026-06 has no master-branch monthly row; -07
duplicates -05's HEAD). **Do not read these deltas as AI impact:**
- Velocity "drop" 29.7→5 commits/mo = window edge; monthly commits taper because
  recent months are unfinished (2026-03:7, -04:4, -05:9, -07:2).
- Issue backlog "jump" 0→98 = recent issues simply not closed yet.
- Quality post-slopes now exist but rest on 3 noisy points → not interpretable.
Genuine AI-authored code is only ~6 weeks old; revisit in a few months.

## Full quality trend (all 18 months, 2025-01 → 2026-07)
Steady rise across 2025, plateau + minor cleanup in 2026:
| | 2025-01 | 2025-10 (pre-CR end) | 2026-07 |
|---|--:|--:|--:|
| ncloc | 39,313 | 51,247 | 52,483 |
| code_smells | 2,192 | 2,580 | 2,631 |
| cognitive_complexity | 2,595 | 3,302 | 3,547 |
| technical_debt (min) | 19,856 | 23,178 | 22,480 |
| bugs | 74 | 59 | 58 |
| vulnerabilities | 10 | 3 | 3 |

Bugs (74→58) and vulnerabilities (10→3) both improved, mostly in mid-2025,
before either AI adoption.

## Issue resolution
302 issues opened since 2025-01, 74 closed, **median resolution ≈ 28 days**
(mean 28.4). Rising backlog reflects recent unclosed issues, not a regression.

## Coverage / validity of this run
- ✅ SonarQube: all 18 months scanned (fix: widened the study's hardcoded
  2024-01…2025-08 window + block on each SonarQube CE task before reading metrics).
- ✅ Reviews: full window from 2025-01 (800 PRs / 2,696 reviews).
- ⚠️ Single repo, descriptive — no causal control. The CodeRabbit flattening is
  confounded by the concurrent slowdown in code-growth rate.
- ⚠️ Coding-agent window too short to assess (weeks old).

## Bottom line
The measurable AI story in esignet is **code-review automation**: CodeRabbit was
adopted in Nov 2025 and now handles ~40% of all PR reviews, and the period since
shows the quality-degradation slope flattening (tech debt even declining) —
though partly attributable to slower code growth. The **coding-agent** adoption
is too recent to evaluate; re-run in a few months, or place esignet in a
multi-repo cohort with matched controls to separate AI from the window edge and
the activity slowdown.
