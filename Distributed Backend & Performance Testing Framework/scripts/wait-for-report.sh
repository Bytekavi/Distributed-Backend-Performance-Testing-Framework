#!/usr/bin/env bash
set -Eeuo pipefail

test_id="${1:?Usage: wait-for-report.sh TEST_ID}"
api_url="${API_URL:-http://localhost:8000}"
timeout_seconds="${TIMEOUT_SECONDS:-900}"
deadline=$((SECONDS + timeout_seconds))

while (( SECONDS < deadline )); do
  record="$(curl --fail-with-body --silent "${api_url}/api/v1/tests/${test_id}")"
  status="$(printf '%s' "${record}" | python -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  if [[ "${status}" == "completed" || "${status}" == "failed" ]]; then
    curl --fail-with-body --silent "${api_url}/api/v1/tests/${test_id}/report"
    echo
    exit 0
  fi
  sleep 3
done

echo "Timed out waiting for test ${test_id}" >&2
exit 1

