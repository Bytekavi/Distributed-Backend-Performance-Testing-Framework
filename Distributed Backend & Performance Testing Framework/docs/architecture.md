# Architecture and Design Notes

## Responsibilities

### Python control plane

The FastAPI service validates requests, stores durable test metadata, divides
the connection budget into exact shards, pipelines jobs into Redis, accepts
idempotent node results, and computes global reports. The aggregate average is
weighted by successful requests. Percentiles are derived from merged
histograms rather than averaging node percentiles.

### Java worker

The worker separates orchestration from socket generation. It reserves jobs
with Redis `BRPOPLPUSH`, uses a bounded thread pool, launches the C++ binary,
posts structured JSON to the control plane, and acknowledges work only after
the result is accepted. Its Jedis pool is intentionally small and reused for
the process lifetime.

### C++ generator

The native executable uses one Linux `epoll` instance per CPU thread and
non-blocking sockets. Each logical client repeatedly opens a connection,
sends one HTTP request, records time to first response byte, and reconnects
until the deadline. Atomics collect totals and histogram buckets without a
global per-request lock.

### Storage and visibility

MySQL is the system of record for test metadata and results. Redis is transient
coordination infrastructure. Prometheus scrapes the control plane, and Grafana
is provisioned with a dashboard on first startup.

## Test lifecycle

1. The client submits a target, duration, total connections, and worker count.
2. The API inserts a `queued` MySQL record.
3. Connections are divided into one Redis job per requested worker.
4. Java workers atomically move jobs from the ready list to the processing
   list.
5. Each worker executes the native generator for its shard.
6. The worker posts its histogram and totals to the API.
7. The API upserts `(test_id, node_id)` and updates the received-worker count.
8. When all shards have reported, the test becomes `completed`.
9. The report endpoint merges all node data.

## Delivery semantics

The queue is at-least-once. A process failure after reservation leaves a job in
the processing list; an operational recovery job should move stale items back
to the ready list. A worker-level error immediately requeues the payload.
MySQL's unique key on `(test_id, node_id)` prevents retries from inflating
reports.

For a larger production deployment, replace the two-list reservation with
Redis Streams consumer groups or a managed queue with visibility timeouts and
dead-letter policies.

## Scaling model

The control plane is stateless except for its external dependencies and can be
replicated behind a load balancer. Workers are horizontally scalable. The
native event loop is bounded by:

- available file descriptors;
- ephemeral ports when targeting a single host from one source IP;
- CPU needed for connection churn;
- network bandwidth and the target's capacity.

Distributing workers across EC2 nodes and subnets adds source IPs and CPU. A
10,000-connection test across two nodes assigns 5,000 connections to each.

## Failure modes

| Failure | Behavior | Recovery |
|---|---|---|
| Redis unavailable | New jobs cannot enqueue; workers retry polling | Restore Redis; resubmit orphaned queued tests |
| MySQL unavailable | Readiness fails and result writes stop | Restore MySQL; workers requeue unacknowledged jobs |
| Worker exits during test | Reserved job remains in processing | Requeue stale processing entries |
| Duplicate result | Unique key updates the existing node result | No operator action |
| Target refuses connections | Failures are counted; test still reports | Inspect error rate and target limits |
| API restarts | Durable test state remains in MySQL | Service reconnects on startup |

## Security boundaries

The target is supplied by an API caller, so production deployments must add
authentication, authorization, audit logs, and an allowlist to prevent SSRF or
unauthorized load generation. Redis and MySQL should be reachable only inside
private networks and require encryption and managed credentials.

