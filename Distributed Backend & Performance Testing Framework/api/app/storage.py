from __future__ import annotations

import json
from typing import Any

import aiomysql
import redis.asyncio as redis

from .settings import Settings


class Storage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.mysql: aiomysql.Pool | None = None
        self.redis: redis.Redis | None = None

    async def connect(self) -> None:
        self.mysql = await aiomysql.create_pool(
            host=self.settings.mysql_host,
            port=self.settings.mysql_port,
            user=self.settings.mysql_user,
            password=self.settings.mysql_password,
            db=self.settings.mysql_database,
            minsize=2,
            maxsize=16,
            autocommit=True,
            pool_recycle=300,
        )
        pool = redis.ConnectionPool(
            host=self.settings.redis_host,
            port=self.settings.redis_port,
            password=self.settings.redis_password or None,
            max_connections=self.settings.redis_max_connections,
            decode_responses=True,
            health_check_interval=30,
        )
        self.redis = redis.Redis.from_pool(pool)
        await self.redis.ping()

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()
        if self.mysql is not None:
            self.mysql.close()
            await self.mysql.wait_closed()

    async def ready(self) -> dict[str, bool]:
        mysql_ready = False
        redis_ready = False
        if self.mysql is not None:
            async with self.mysql.acquire() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    mysql_ready = bool(await cursor.fetchone())
        if self.redis is not None:
            redis_ready = bool(await self.redis.ping())
        return {"mysql": mysql_ready, "redis": redis_ready}

    async def create_test(self, record: dict[str, Any]) -> None:
        assert self.mysql is not None
        sql = """
            INSERT INTO load_tests
                (id, name, target_host, target_port, target_path,
                 concurrent_connections, duration_seconds, expected_workers)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        values = (
            record["id"],
            record["name"],
            record["target_host"],
            record["target_port"],
            record["target_path"],
            record["concurrent_connections"],
            record["duration_seconds"],
            record["expected_workers"],
        )
        async with self.mysql.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(sql, values)

    async def enqueue_jobs(self, jobs: list[dict[str, Any]]) -> None:
        assert self.redis is not None
        async with self.redis.pipeline(transaction=False) as pipeline:
            for job in jobs:
                pipeline.rpush(self.settings.job_queue, json.dumps(job))
            await pipeline.execute()

    async def list_tests(self, limit: int) -> list[dict[str, Any]]:
        assert self.mysql is not None
        sql = "SELECT * FROM load_tests ORDER BY created_at DESC LIMIT %s"
        async with self.mysql.acquire() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(sql, (limit,))
                return list(await cursor.fetchall())

    async def get_test(self, test_id: str) -> dict[str, Any] | None:
        assert self.mysql is not None
        async with self.mysql.acquire() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM load_tests WHERE id = %s", (test_id,))
                return await cursor.fetchone()

    async def save_result(self, test_id: str, result: dict[str, Any]) -> None:
        assert self.mysql is not None
        sql = """
            INSERT INTO load_results
                (test_id, node_id, total_requests, successful_requests, failed_requests,
                 requests_per_second, average_latency_ms, p95_latency_ms, p99_latency_ms,
                 latency_histogram)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                total_requests = VALUES(total_requests),
                successful_requests = VALUES(successful_requests),
                failed_requests = VALUES(failed_requests),
                requests_per_second = VALUES(requests_per_second),
                average_latency_ms = VALUES(average_latency_ms),
                p95_latency_ms = VALUES(p95_latency_ms),
                p99_latency_ms = VALUES(p99_latency_ms),
                latency_histogram = VALUES(latency_histogram)
        """
        values = (
            test_id,
            result["node_id"],
            result["total_requests"],
            result["successful_requests"],
            result["failed_requests"],
            result["requests_per_second"],
            result["average_latency_ms"],
            result["p95_latency_ms"],
            result["p99_latency_ms"],
            json.dumps(result["latency_histogram"]),
        )
        async with self.mysql.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(sql, values)
                await cursor.execute(
                    """
                    UPDATE load_tests t
                    SET t.received_workers = (
                            SELECT COUNT(*) FROM load_results r WHERE r.test_id = t.id
                        ),
                        t.status = CASE
                            WHEN (SELECT COUNT(*) FROM load_results r WHERE r.test_id = t.id)
                                 >= t.expected_workers THEN 'completed'
                            ELSE 'running'
                        END,
                        t.completed_at = CASE
                            WHEN (SELECT COUNT(*) FROM load_results r WHERE r.test_id = t.id)
                                 >= t.expected_workers THEN CURRENT_TIMESTAMP(6)
                            ELSE NULL
                        END
                    WHERE t.id = %s
                    """,
                    (test_id,),
                )

    async def get_results(self, test_id: str) -> list[dict[str, Any]]:
        assert self.mysql is not None
        async with self.mysql.acquire() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT * FROM load_results WHERE test_id = %s ORDER BY node_id",
                    (test_id,),
                )
                rows = list(await cursor.fetchall())
        for row in rows:
            value = row["latency_histogram"]
            if isinstance(value, (str, bytes, bytearray)):
                row["latency_histogram"] = json.loads(value)
        return rows
