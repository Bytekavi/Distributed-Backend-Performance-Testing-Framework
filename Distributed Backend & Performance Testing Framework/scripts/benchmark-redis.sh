#!/usr/bin/env bash
set -Eeuo pipefail

redis_host="${REDIS_HOST:-127.0.0.1}"
redis_port="${REDIS_PORT:-6379}"
clients="${CLIENTS:-64}"
requests="${REQUESTS:-100000}"

mkdir -p results
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="results/redis-${timestamp}.txt"

docker run --rm --network host redis:7.4-alpine \
  redis-benchmark \
  -h "${redis_host}" \
  -p "${redis_port}" \
  -c "${clients}" \
  -n "${requests}" \
  -t ping_inline,set,get \
  --csv | tee "${output}"

echo "Saved ${output}"

