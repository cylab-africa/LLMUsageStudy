# Mosip_esignet — AI-impact evaluation

**AI-adoption month (split point): `2025-11`** — defined as the *first trackable AI action of any kind* (commit, merge, push, PR open/merge, review, or issue), not the first config file.

Per-agent first action: CodeRabbit (2025-11), OpenAI Codex / AGENTS.md (2026-04), Claude Code (2026-06), Cursor (2026-06)


## 0. AI operations detected (what did AI actually do?)

Counts of AI-attributed actions across **all branches**, by operation type. `commit`=authored, `merge`/`pr_merged`=integrated, `push`=applied by an agent identity, `pr_opened`/`pr_reviewed`/`issue_*`=platform actions.

| Operation | count |
|---|--:|
| pr_reviewed | 778 |
| commit | 67 |

By agent × operation:

| Agent | operation | count |
|---|---|--:|
| CodeRabbit | pr_reviewed | 778 |
| Cursor | commit | 56 |
| OpenAI Codex / AGENTS.md | commit | 6 |
| Claude Code | commit | 5 |

## 1. Velocity (speed)

| Metric | pre | post | Δ |
|---|--:|--:|--:|
| mean monthly commits | 34.30 | 14.75 | -19.55 ↓ |
| mean monthly lines added | 13718.50 | 5340.62 | -8377.88 ↓ |
| mean monthly lines removed | 2701.20 | 2769.88 | 68.68 ↑ |
| mean monthly contributors | 11.00 | 6.38 | -4.62 ↓ |

## 2. Code size & quality (SonarQube, monthly snapshots)

Quality is reported as **trend slope** (change per month): positive slope on smells/bugs/debt = worsening.

| Metric | pre-slope | post-slope | Δ slope |
|---|--:|--:|--:|
| size (ncloc) | 1523.364 | 152.119 | -1371.245 ↓ |
| bugs | -2.352 | -0.107 | 2.244 ↑ |
| vulnerabilities | -1.067 | 0.000 | 1.067 ↑ |
| code smells | 45.352 | 3.833 | -41.518 ↓ |
| cognitive complexity | 82.521 | 25.179 | -57.343 ↓ |
| technical debt (remediation min) | 363.182 | -198.631 | -561.813 ↓ |
| duplication % | -0.303 | -0.085 | 0.219 ↑ |
| comment density % | -0.107 | 0.008 | 0.116 ↑ |

## 3. Issue-resolution health

| Metric | pre | post | Δ |
|---|--:|--:|--:|
| median resolution (hours) | n/a | 720.4 | n/a |
| mean monthly issues opened | 0.2 | 34.4 | 34.3 ↑ |
| mean open bug backlog | 0.0 | 44.3 | 44.3 ↑ |

**Whole-repo issue statistics:**

- total=311 · open=234 · closed=77 · close-rate=0.248
- resolution: p25=10.7d · median=28.0d · p75=43.8d · p90=60.1d · mean=28.6d
- first response: median=427.8h · p90=1559.32h
- bugs=165 (open 128) · AI-authored issues=0 · AI-closed issues=0

## 4. Code-review automation

**AI review bots detected:** CodeRabbit

| Metric | pre | post | Δ |
|---|--:|--:|--:|
| mean AI-review share | 0.000 | 0.406 | 0.406 ↑ |
| mean monthly PRs opened | 42.1 | 45.8 | 3.7 ↑ |
| median review comments/PR | 0.0 | 1.6 | 1.6 ↑ |

## Interpretation

Read §1 (velocity) against §2 (quality slope): the paper's core finding is *velocity rises but complexity/debt slope worsens after adoption*. Compare the Δ columns to see whether this repo follows that pattern or not.


> **Caveat — single repo, descriptive only.** This is a before/after comparison, not a causal effect. Confounds (project maturity, contributor influx, release cycles) are not controlled here. A causal estimate requires many AI-adopting repos vs matched controls fed to the study's DiD / panel notebooks — the per-repo CSVs in this folder are schema-compatible for exactly that scale-up.


## Appendix — what the SonarQube metrics mean

| Metric | Type | Plain-English meaning | Direction |
|---|---|---|---|
| `ncloc` | size | Non-comment lines of code — logic size, excluding blanks/comments. | neutral (context) |
| `bugs` | reliability | Code SonarQube judges demonstrably wrong — will misbehave at runtime. | lower = better |
| `vulnerabilities` | security | Security weaknesses (e.g. hard-coded secrets, injection). | lower = better |
| `code_smells` | maintainability | Working but poorly-structured code (dupes, long methods, dead code). Not bugs — maintainability debt. | lower = better |
| `cognitive_complexity` | maintainability | How hard the code is for a human to follow (nesting, branching). Rises even at constant size. | lower = better |
| `technical_debt` | maintainability | Estimated minutes to fix all code smells (SonarQube 'remediation effort'). | lower = better |
| `duplicated_lines_density` | maintainability | % of lines that are copy-pasted duplicates. | lower = better |
| `comment_lines_density` | documentation | Comments as % of (code + comments). Very low or very high can both be smells. | context |

*In §2, each metric is shown as a **slope** (change per month). A positive slope on smells/complexity/debt means quality is degrading over time; the pre-vs-post Δ shows whether AI adoption changed that rate. Raw counts rise with `ncloc`, so also read them per-1k-lines when comparing periods of different size.*
