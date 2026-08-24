#!/bin/bash
# Wrapper so the study's run_sonarqube.py (which execs $SONAR_SCANNER_PATH) uses
# the Docker scanner. Rewrites localhost->host.docker.internal and mounts cwd.
args=()
for a in "$@"; do args+=("${a//localhost/host.docker.internal}"); done
exec docker run --rm -v "$PWD:/usr/src" -w /usr/src sonarsource/sonar-scanner-cli "${args[@]}"
