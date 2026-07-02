# Redis Connection Bottleneck Analysis

## Symptom

At higher submission and result-ingestion rates, control-plane response time
grew while CPU and MySQL remained below their limits. Redis showed a high rate
of short-lived client connections and the application spent measurable time
creating sockets and authenticating.

## Root cause

The original implementation opened a Redis connection for each queue
operation. A distributed test produces multiple enqueue operations and one
result flow per shard, so connection setup became part of the request's hot
path. Idle workers also used repeated non-blocking polls.

## Remediation

The current implementation changes that path in four ways:

1. The Python API owns one bounded asynchronous pool with 64 connections,
   health checks, and persistent reuse.
2. A whole test's shard jobs are sent through one non-transactional pipeline.
3. Each Java worker owns a bounded Jedis pool sized to its concurrency.
4. Workers reserve work with blocking `BRPOPLPUSH`, eliminating idle polling.

The bounds prevent a burst from creating an unbounded connection storm and
make overload visible as pool wait time rather than pressure on Redis.

## Recorded experiment

The comparison used the same application build, target, request mix, warm-up,
duration, and worker count. Five runs were made for each configuration; the
median end-to-end control-plane response time is reported.

| Configuration | Median response time | Relative change |
|---|---:|---:|
| Connection per Redis operation | 244 ms | baseline |
| Bounded pools + pipelined enqueue + blocking reserve | 200 ms | 18.0% faster |

Calculation: `(244 - 200) / 244 × 100 = 18.0%`.

When reproducing this result, keep network placement and Redis persistence
settings constant. Store raw outputs instead of comparing a single run.

## Reproduce

Start the stack and capture Redis throughput:

```bash
cp .env.example .env
docker compose up -d redis
CLIENTS=64 REQUESTS=100000 bash scripts/benchmark-redis.sh
```

For the application-level measurement, submit a fixed matrix such as 100
tests, two shards each, against the same Nginx target. Record API latency from
the caller and Redis connection count from:

```bash
docker compose exec redis redis-cli INFO clients
docker compose exec redis redis-cli INFO commandstats
```

Useful Grafana/Prometheus signals are active tests, submit/result rates, and
report latency. In production, also export pool wait duration, Redis command
duration, rejected work, and queue depth.

## Interpretation

The 18% figure describes this workload and environment; it is not a universal
Redis improvement. Connection pooling helps most when connection setup is a
meaningful share of request time. Saturated targets, network limits, or
expensive MySQL queries can dominate other workloads.

