# Operations Guide

## Preflight for high connection counts

Before a 10,000+ connection run:

1. Confirm written authorization for the target and test window.
2. Run a 100-connection smoke test.
3. Verify `nofile` is at least 65,536 on every worker.
4. Check source ephemeral-port capacity and distribute across nodes if needed.
5. Confirm target-side rate limits, autoscaling policy, and rollback contacts.
6. Watch error rate, target saturation, Redis clients, queue depth, and API
   readiness during the test.

Docker Compose and the Terraform worker both configure a 65,536 descriptor
limit. Host policy can still impose a lower ceiling.

## Useful commands

```bash
docker compose ps
docker compose logs -f api worker
docker compose exec redis redis-cli LLEN load-tests
docker compose exec redis redis-cli LLEN load-tests-processing
docker compose exec redis redis-cli INFO clients
docker compose exec mysql mysql -uperf -p performance
```

## Recovery of reserved jobs

The local implementation keeps reserved jobs in `load-tests-processing`.
Inspect workers before requeuing; moving an active job causes duplicate
execution, though result storage remains idempotent.

```bash
docker compose exec redis redis-cli RPOPLPUSH load-tests-processing load-tests
```

Repeat only for confirmed stale entries. Production systems should automate
visibility timeouts and dead-letter handling.

## Shutdown

Preserve database and monitoring volumes:

```bash
docker compose down
```

Delete all local state:

```bash
docker compose down -v --remove-orphans
```

## Alert suggestions

- `/readyz` unavailable for more than two minutes
- Redis connected clients above 80% of `maxclients`
- ready queue growing for more than five minutes
- processing queue items older than test duration plus two minutes
- result ingestion errors
- worker node CPU or file descriptors above 85%

