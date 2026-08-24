# mosip/mosip-config — CursorStudy-style scan

Replicates the per-repo scan data the study collects, on `mosip/mosip-config`
(HEAD = 2cc684a, 2025-12-16). Star count ignored per request (repo selection
gating skipped).

## What was run
- **SonarQube 26.6 (community)** in Docker (`sonarsource/sonar-scanner-cli`),
  same metric set as `scripts/run_sonarqube.py`.
- Monthly snapshots: latest commit of each active month in the study window
  **2024-01 → 2025-08** (16 active months) checked out and scanned.
- Git activity per month from full history (`scripts/analyze_repos.py` logic).
- Warnings + rule definitions from the SonarQube issues API
  (`scripts/collect_sonarqube_warnings.py` shape).

## Files
- `ts_mosip_config_monthly.csv` — monthly time series (git activity + SonarQube quality metrics)
- `sonarqube_warnings.csv` — every open issue (component, line, rule, creation date)
- `sonarqube_warning_definitions.csv` — rule -> type/severity/effort/example

## Headline results (HEAD)
ncloc 3635 · files 15 analyzed · bugs 0 · vulnerabilities 1 · code_smells 5 ·
duplicated_lines_density 0% · comment_lines_density 4.6% · technical_debt 25min ·
cognitive_complexity not computed (XML-only sources).

## Notable trend over the window
- code_smells: 1 (2024) -> 3 (2025-03) -> 5 (2025-04 onward)
- technical_debt: 5min -> 15min -> 25min
- ncloc: 3079 -> 3586

## Caveats
- This is a **configuration repository**: only XML files (~15) are analyzable code
  for SonarQube community; `.properties`, `.json`, `.toml`, `.mvel` are not counted
  as ncloc, so code-centric metrics are sparse by nature.
- `creation_date` on warnings = scan date (SCM disabled), a limitation the study's
  own `collect_sonarqube_warnings.py` documents — fine-grained per-version
  attribution is not reliable.
- GitHub-API columns from the study (stars, issues, age) and dependency-lag columns
  were intentionally not collected (stars ignored per request; not part of the scan).
