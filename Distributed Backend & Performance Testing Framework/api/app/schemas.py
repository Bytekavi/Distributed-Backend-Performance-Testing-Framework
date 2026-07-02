from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TestCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    target_host: str = Field(min_length=1, max_length=255)
    target_port: int = Field(default=80, ge=1, le=65535)
    target_path: str = Field(default="/", max_length=1024)
    concurrent_connections: int = Field(default=1000, ge=1, le=200_000)
    duration_seconds: int = Field(default=60, ge=1, le=86_400)
    workers: int = Field(default=1, ge=1, le=100)

    @field_validator("target_path")
    @classmethod
    def path_must_be_absolute(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("target_path must begin with '/'")
        return value


class TestRecord(BaseModel):
    id: str
    name: str
    target_host: str
    target_port: int
    target_path: str
    concurrent_connections: int
    duration_seconds: int
    expected_workers: int
    received_workers: int
    status: Literal["queued", "running", "completed", "failed"]
    created_at: datetime
    completed_at: datetime | None = None


class NodeResultCreate(BaseModel):
    node_id: str = Field(min_length=1, max_length=160)
    total_requests: int = Field(ge=0)
    successful_requests: int = Field(ge=0)
    failed_requests: int = Field(ge=0)
    requests_per_second: float = Field(ge=0)
    average_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    p99_latency_ms: float = Field(ge=0)
    latency_histogram: dict[str, int] = Field(default_factory=dict)


class Report(BaseModel):
    test: TestRecord
    total_requests: int
    successful_requests: int
    failed_requests: int
    requests_per_second: float
    average_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    error_rate: float
    latency_histogram: dict[str, int]

