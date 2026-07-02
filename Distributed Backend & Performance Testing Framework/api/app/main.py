from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .domain import NodeResult, aggregate_results, shard_connections
from .metrics import ACTIVE_TESTS, REPORT_LATENCY, RESULTS_RECEIVED, TESTS_SUBMITTED
from .schemas import NodeResultCreate, Report, TestCreate, TestRecord
from .settings import get_settings
from .storage import Storage

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("control-plane")


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage = Storage(settings)
    await storage.connect()
    app.state.storage = storage
    logger.info("control plane connected to MySQL and Redis")
    try:
        yield
    finally:
        await storage.close()


app = FastAPI(
    title="Distributed Performance Testing Control Plane",
    version="1.0.0",
    description="Queues distributed load tests and aggregates node-level results.",
    lifespan=lifespan,
)


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


@app.get("/healthz", tags=["operations"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["operations"])
async def readiness(request: Request) -> dict[str, object]:
    dependencies = await get_storage(request).ready()
    if not all(dependencies.values()):
        raise HTTPException(status_code=503, detail=dependencies)
    return {"status": "ready", "dependencies": dependencies}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/tests", response_model=TestRecord, status_code=status.HTTP_202_ACCEPTED)
async def create_test(payload: TestCreate, request: Request) -> TestRecord:
    if payload.workers > payload.concurrent_connections:
        raise HTTPException(
            status_code=422,
            detail="workers cannot exceed concurrent_connections",
        )

    test_id = str(uuid.uuid4())
    storage = get_storage(request)
    record = {
        "id": test_id,
        "name": payload.name,
        "target_host": payload.target_host,
        "target_port": payload.target_port,
        "target_path": payload.target_path,
        "concurrent_connections": payload.concurrent_connections,
        "duration_seconds": payload.duration_seconds,
        "expected_workers": payload.workers,
    }
    await storage.create_test(record)
    shards = shard_connections(payload.concurrent_connections, payload.workers)
    jobs = [
        {
            "test_id": test_id,
            "shard_id": index,
            "target_host": payload.target_host,
            "target_port": payload.target_port,
            "target_path": payload.target_path,
            "connections": connections,
            "duration_seconds": payload.duration_seconds,
        }
        for index, connections in enumerate(shards)
    ]
    await storage.enqueue_jobs(jobs)
    TESTS_SUBMITTED.inc()
    ACTIVE_TESTS.inc()
    created = await storage.get_test(test_id)
    assert created is not None
    return TestRecord.model_validate(created)


@app.get("/api/v1/tests", response_model=list[TestRecord])
async def list_tests(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[TestRecord]:
    rows = await get_storage(request).list_tests(limit)
    return [TestRecord.model_validate(row) for row in rows]


@app.get("/api/v1/tests/{test_id}", response_model=TestRecord)
async def get_test(test_id: str, request: Request) -> TestRecord:
    row = await get_storage(request).get_test(test_id)
    if row is None:
        raise HTTPException(status_code=404, detail="test not found")
    return TestRecord.model_validate(row)


@app.post("/api/v1/tests/{test_id}/results", status_code=status.HTTP_202_ACCEPTED)
async def receive_result(
    test_id: str,
    payload: NodeResultCreate,
    request: Request,
) -> dict[str, str]:
    storage = get_storage(request)
    test = await storage.get_test(test_id)
    if test is None:
        raise HTTPException(status_code=404, detail="test not found")
    await storage.save_result(test_id, payload.model_dump())
    RESULTS_RECEIVED.inc()
    refreshed = await storage.get_test(test_id)
    if refreshed and refreshed["status"] == "completed" and test["status"] != "completed":
        ACTIVE_TESTS.dec()
    return {"status": "accepted"}


@app.get("/api/v1/tests/{test_id}/report", response_model=Report)
async def get_report(test_id: str, request: Request) -> Report:
    started = perf_counter()
    storage = get_storage(request)
    test = await storage.get_test(test_id)
    if test is None:
        raise HTTPException(status_code=404, detail="test not found")
    rows = await storage.get_results(test_id)
    node_results = [
        NodeResult(
            total_requests=row["total_requests"],
            successful_requests=row["successful_requests"],
            failed_requests=row["failed_requests"],
            requests_per_second=row["requests_per_second"],
            average_latency_ms=row["average_latency_ms"],
            latency_histogram=row["latency_histogram"],
        )
        for row in rows
    ]
    report = aggregate_results(node_results)
    REPORT_LATENCY.observe(perf_counter() - started)
    return Report(test=TestRecord.model_validate(test), **report)

