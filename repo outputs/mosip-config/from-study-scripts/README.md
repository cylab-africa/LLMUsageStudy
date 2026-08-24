# Outputs from the study's OWN scripts (scripts/*.py), run on mosip/mosip-config

Produced by running the unmodified CursorStudy scripts against a one-repo
population, in an isolated workspace (so the real data/*.csv was never touched).

Scripts run (in order):
1. scripts/analyze_repos.py       -> ts_repos_monthly.csv, ts_contributors_monthly.csv
2. scripts/run_sonarqube.py       -> SonarQube metric columns appended to ts_repos_monthly.csv
3. scripts/collect_sonarqube_warnings.py -> ran OK but collected 0 issues (see notes)

Setup needed to make a one-repo run possible:
- data/repos.csv = single row `mosip/mosip-config`
- clone placed at ../CursorRepos/mosip_mosip-config
- .env with SONAR_TOKEN / SONAR_HOST (Dockerized SonarQube on :9011)
- SONAR_SCANNER_PATH -> sonar-scanner.sh (wrapper that calls the Docker scanner,
  since no local sonar-scanner binary was installed)

Two portability fixes (the scripts assume Linux `fork`; macOS defaults to `spawn`):
- launch_analyze.py / launch_sonar.py force multiprocessing start method = fork.
  Without this, the module-global TIME_KEY set in main() is lost in worker
  processes and the month column is written unnamed -> KeyError.

Notes / fidelity:
- run_sonarqube.py numbers are IDENTICAL to the earlier custom driver
  (code_smells 1->3->5, technical_debt 5->15->25, ncloc 3079->3586), confirming
  equivalence.
- cursor column = False for all months (no Cursor adoption), matching the
  multi-agent detector's finding of zero agent usage.
- collect_sonarqube_warnings.py needs a treatment adoption event; mosip-config
  has none, so a NOMINAL event (2025-01) was supplied only to drive the script.
  It found 0 introduced issues per period — the SonarQube-API limitation the
  script's own docstring documents (issue creation dates anchor to the first
  scan). The complete 6-warning set is in ../sonarqube_warnings.csv.
