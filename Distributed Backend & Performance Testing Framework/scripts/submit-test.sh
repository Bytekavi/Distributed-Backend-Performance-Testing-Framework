#!/usr/bin/env bash
set -Eeuo pipefail

api_url="${API_URL:-http://localhost:8000}"
workers="${WORKERS:-2}"
connections="${CONNECTIONS:-10000}"
duration="${DURATION:-60}"

curl --fail-with-body --silent --show-error \
  -X POST "${api_url}/api/v1/tests" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"${connections}-connection distributed run\",
    \"target_host\": \"demo-target\",
    \"target_port\": 80,
    \"target_path\": \"/\",
    \"concurrent_connections\": ${connections},
    \"duration_seconds\": ${duration},
    \"workers\": ${workers}
  }"
echo

