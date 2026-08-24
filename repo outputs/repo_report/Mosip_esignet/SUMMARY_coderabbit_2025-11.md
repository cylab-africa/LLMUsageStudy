# Mosip_esignet — AI-impact evaluation

**AI-adoption month (split point): `2025-11`**  — earliest of: OpenAI Codex / AGENTS.md (2026-04), Cursor (2026-06), Claude Code (2026-06)


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
| median resolution (hours) | n/a | 735.3 | n/a |
| mean monthly issues opened | 1.0 | 60.2 | 59.2 ↑ |
| mean open bug backlog | 0.0 | 78.6 | 78.6 ↑ |

## 4. Code-review automation

**AI review bots detected:** CodeRabbit

| Metric | pre | post | Δ |
|---|--:|--:|--:|
| mean AI-review share | 0.000 | 0.404 | 0.404 ↑ |
| mean monthly PRs opened | 40.1 | 44.3 | 4.2 ↑ |
| median review comments/PR | 0.0 | 1.4 | 1.4 ↑ |

## Interpretation

Read §1 (velocity) against §2 (quality slope): the paper's core finding is *velocity rises but complexity/debt slope worsens after adoption*. Compare the Δ columns to see whether this repo follows that pattern or not.


> **Caveat — single repo, descriptive only.** This is a before/after comparison, not a causal effect. Confounds (project maturity, contributor influx, release cycles) are not controlled here. A causal estimate requires many AI-adopting repos vs matched controls fed to the study's DiD / panel notebooks — the per-repo CSVs in this folder are schema-compatible for exactly that scale-up.
