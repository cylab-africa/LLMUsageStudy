# Mosip_esignet — AI-impact evaluation

**AI-adoption month (split point): `2026-04`** — defined as the *first trackable AI action of any kind* (commit, merge, push, PR open/merge, review, or issue), not the first config file.

Per-agent first action: OpenAI Codex / AGENTS.md (2026-04), Cursor (2026-06), Claude Code (2026-06)


## 1. Velocity (speed)

| Metric | pre | post | Δ |
|---|--:|--:|--:|
| mean monthly commits | 29.73 | 5.00 | -24.73 ↓ |
| mean monthly lines added | 11761.87 | 1160.67 | -10601.20 ↓ |
| mean monthly lines removed | 3089.60 | 942.33 | -2147.27 ↓ |
| mean monthly contributors | 10.00 | 3.67 | -6.33 ↓ |

## 2. Code size & quality (SonarQube, monthly snapshots)

Quality is reported as **trend slope** (change per month): positive slope on smells/bugs/debt = worsening.

| Metric | pre-slope | post-slope | Δ slope |
|---|--:|--:|--:|
| size (ncloc) | 1234.893 | -786.500 | -2021.393 ↓ |
| bugs | -1.300 | -1.000 | 0.300 ↑ |
| vulnerabilities | -0.600 | 0.000 | 0.600 ↑ |
| code smells | 40.304 | -27.000 | -67.304 ↓ |
| cognitive complexity | 70.439 | -61.000 | -131.439 ↓ |
| technical debt (remediation min) | 314.954 | -296.000 | -610.954 ↓ |
| duplication % | -0.221 | 0.150 | 0.371 ↑ |
| comment density % | -0.068 | 0.000 | 0.068 ↑ |

## 3. Issue-resolution health

| Metric | pre | post | Δ |
|---|--:|--:|--:|
| median resolution (hours) | n/a | 735.3 | n/a |
| mean monthly issues opened | 1.5 | 74.8 | 73.2 ↑ |
| mean open bug backlog | 0.0 | 98.2 | 98.2 ↑ |

## 4. Code-review automation

**AI review bots detected:** CodeRabbit

| Metric | pre | post | Δ |
|---|--:|--:|--:|
| mean AI-review share | 0.131 | 0.418 | 0.287 ↑ |
| mean monthly PRs opened | 39.2 | 53.0 | 13.8 ↑ |
| median review comments/PR | 0.6 | 1.0 | 0.4 ↑ |

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
