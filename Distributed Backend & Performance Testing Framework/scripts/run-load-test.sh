#!/usr/bin/env bash
set -Eeuo pipefail

host="${1:-127.0.0.1}"
port="${2:-8080}"
connections="${3:-1000}"
duration="${4:-30}"

ulimit -n 65536

docker build -t distributed-loadgen:local ./load-generator-cpp
docker run --rm \
  --network host \
  --ulimit nofile=65536:65536 \
  distributed-loadgen:local \
  --host "${host}" \
  --port "${port}" \
  --path / \
  --connections "${connections}" \
  --duration "${duration}"

