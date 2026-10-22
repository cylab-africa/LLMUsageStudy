# Runbook: scan any repo with the CursorStudy pipeline (macOS)

Reproduces, for a single GitHub repo, the paper's per-repo data: git velocity,
SonarQube quality metrics, warnings, and (extension) multi-agent AI-usage.
Runs the study's OWN `scripts/*.py` in an isolated workspace so the curated
`data/*.csv` is never overwritten.

`_tools/run_ai_impact.py` automates steps 1–10 of this runbook (and adds the
GitHub issue/review collectors); use the manual path below to debug one stage or
to run without the orchestrator. Read `_tools/README.md` → "Known caveats"
before interpreting any output either way.

## 0. Prerequisites
- Docker Desktop running
- Python 3.10+ and `git`
- The CursorStudy repo checked out (this folder)
No local SonarQube or sonar-scanner install needed — both come from Docker.

## 1. Pick the target repo and a free port
```bash
REPO_URL=https://github.com/mosip/mosip-config.git
REPO_NAME=mosip/mosip-config            # owner/name
PORT=9011                               # any free port
W=/tmp/study-run                        # isolated workspace
STUDY="$(git rev-parse --show-toplevel)" # your checkout of this repo; or set it
                                        # explicitly to the folder holding
                                        # scripts/ and "repo outputs/"
```

## 2. Clone the target repo (full history — needed for monthly snapshots)
```bash
mkdir -p /tmp/mosip-scan
git clone "$REPO_URL" /tmp/mosip-scan/repo
```

## 3. Start SonarQube + pull the scanner (Docker)
```bash
docker run -d --name mosip-sonar -p $PORT:9000 \
  -e SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true sonarqube:community
docker pull sonarsource/sonar-scanner-cli
# wait until UP (~1-2 min)
until curl -s http://localhost:$PORT/api/system/status | grep -q '"status":"UP"'; do sleep 5; done
```

## 4. Set admin password + generate an API token
The password comes from the environment — never hardcode one in this file or in
a script. SonarQube requires at least 12 characters with upper case, lower case,
a digit and a symbol; the container is a throwaway, so a generated value is fine.
```bash
# Use SONAR_PASSWORD if you exported one; otherwise generate a throwaway.
export SONAR_PASSWORD="${SONAR_PASSWORD:-$(python3 -c \
  'import secrets; print(secrets.token_urlsafe(12) + "aA1!")')}"
curl -s -u admin:admin -X POST "http://localhost:$PORT/api/users/change_password" \
  --data-urlencode "login=admin" --data-urlencode "previousPassword=admin" \
  --data-urlencode "password=$SONAR_PASSWORD"
TOKEN=$(curl -s -u "admin:$SONAR_PASSWORD" -X POST \
  "http://localhost:$PORT/api/user_tokens/generate" -d "name=scan-$RANDOM" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
echo "$TOKEN"
```
`run_ai_impact.py` does this itself in `setup_sonar()`, generating a fresh
random admin password per run, so an orchestrated run needs nothing set here.

## 5. Python venv + dependencies
```bash
python3 -m venv /tmp/mosip-scan/venv
/tmp/mosip-scan/venv/bin/pip install -q pandas requests python-dotenv GitPython
PY=/tmp/mosip-scan/venv/bin/python
```

## 6. Build the isolated workspace the scripts expect
```bash
rm -rf $W; mkdir -p $W/CursorStudy/data $W/CursorRepos
cp -R "$STUDY/scripts" $W/CursorStudy/scripts
touch $W/CursorStudy/scripts/__init__.py
# one-row population
printf 'repo_name\n%s\n' "$REPO_NAME" > $W/CursorStudy/data/repos.csv
# clone where CLONE_DIR expects it: ../CursorRepos/<owner_repo>
cp -R /tmp/mosip-scan/repo "$W/CursorRepos/$(echo $REPO_NAME | tr / _)"
# .env consumed by the scripts
cat > $W/CursorStudy/.env <<EOF
GITHUB_TOKEN=unused
SONAR_TOKEN=$TOKEN
SONAR_HOST=http://localhost:$PORT
SONAR_SCANNER_PATH=$W/sonar-scanner.sh
EOF
# scanner wrapper -> Docker scanner (rewrites localhost for the container)
cat > $W/sonar-scanner.sh <<'EOF'
#!/bin/bash
args=(); for a in "$@"; do args+=("${a//localhost/host.docker.internal}"); done
exec docker run --rm -v "$PWD:/usr/src" -w /usr/src sonarsource/sonar-scanner-cli "${args[@]}"
EOF
chmod +x $W/sonar-scanner.sh
```

## 7. Fork launchers (REQUIRED on macOS)
The scripts set a module-global `TIME_KEY` in `main()` and use it inside
multiprocessing workers — only safe under Linux `fork`. macOS defaults to
`spawn`, which loses it (unnamed month column -> KeyError). Force fork:
```bash
cat > $W/launch_analyze.py <<'EOF'
import multiprocessing as mp; mp.set_start_method("fork", force=True)
import sys; sys.argv=["analyze_repos","--aggregation=month"]
from scripts import analyze_repos; analyze_repos.main()
EOF
cat > $W/launch_sonar.py <<'EOF'
import multiprocessing as mp; mp.set_start_method("fork", force=True)
import sys; sys.argv=["run_sonarqube","--aggregation=month"]
from scripts import run_sonarqube; run_sonarqube.main()
EOF
```
If fork crashes with an ObjC error, prefix the runs with
`OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`.

## 8. Run the study scripts
```bash
cd $W/CursorStudy
# (1) git velocity + cursor detection -> data/ts_repos_monthly.csv
PYTHONPATH=$W/CursorStudy $PY $W/launch_analyze.py
# (2) SonarQube metrics appended (scans latest commit of each month 2024-01..2025-08)
PYTHONPATH=$W/CursorStudy $PY $W/launch_sonar.py
# (3) warnings — needs a treatment event; supply a NOMINAL one only to drive it
printf 'repo_name,month,event\n%s,2025-01,2025-01\n' "$REPO_NAME" > data/panel_event_monthly.csv
PYTHONPATH=$W/CursorStudy $PY -m scripts.collect_sonarqube_warnings
```
Result: `data/ts_repos_monthly.csv` (velocity + ncloc/bugs/vulns/code_smells/
duplication/comment-density/cognitive-complexity/technical-debt per month).
Velocity comes from `repo.iter_commits()` — **HEAD of the default branch only**,
not all branches. The window above is the study's hardcoded 2024-01..2025-08;
`_tools/run_sonar_full.py` widens it via `SONAR_START`/`SONAR_END` and blocks on
each Community-Edition task, which is what the orchestrator uses.
Step 3 writes `sonarqube_warnings.csv` + `sonarqube_warning_definitions.csv`
(there is no `warnings.csv`).

## 9. Multi-agent AI-usage detection (the ecosystem extension)
The study detects Cursor only. To cover Claude Code, Copilot, Aider, etc.:
```bash
$PY "$STUDY/repo outputs/_tools/detect_ai_agents.py" \
   /tmp/mosip-scan/repo "$REPO_NAME" /tmp/mosip-scan/output
# -> ai_agent_commits.csv, ai_agent_summary.csv (empty = no agent usage)
```
This detector scans **all branches** (`git log --all`), while step 8's velocity
covers the default branch only — the two commit counts are not comparable. To
turn these detections plus the GitHub collectors into `ai_operations.csv` /
`ai_adoption.csv`, run `_tools/build_ai_operations.py <out/dir>`.

## 10. Cleanup
```bash
docker rm -f mosip-sonar
rm -rf /tmp/mosip-scan /tmp/study-run
```

## Notes
- Each monthly SonarQube scan reuses an existing analysis if already present, so
  re-runs are fast.
- SonarQube processes reports asynchronously; the LAST month may need a second
  `launch_sonar.py` run (the script's docstring notes this).
- For a real cross-agent study you must run this over MANY repos to form
  per-agent treatment cohorts + matched controls, then use the R notebooks.
- Interpretation hazards (adoption mixing review bots with coding agents,
  branch-scope mismatch, GitHub API budget vs. rate limits) are documented in
  `_tools/README.md` → "Known caveats" and in `AI_IMPACT_PIPELINE_PLAN.md` §8.
