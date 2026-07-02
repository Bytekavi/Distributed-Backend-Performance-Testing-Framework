#!/usr/bin/env bash
set -Eeuo pipefail

workers="${1:-2}"

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

docker compose up -d --build --scale "worker=${workers}"
docker compose ps

echo
echo "API docs:  http://localhost:8000/docs"
echo "Grafana:   http://localhost:3000"
echo "Prometheus:http://localhost:9090"

