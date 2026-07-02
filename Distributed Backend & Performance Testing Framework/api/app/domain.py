from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping

HISTOGRAM_BOUNDS_MS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000)


@dataclass(frozen=True)
class NodeResult:
    total_requests: int
    successful_requests: int
    failed_requests: int
    requests_per_second: float
    average_latency_ms: float
    latency_histogram: Mapping[str, int]


def shard_connections(total_connections: int, workers: int) -> list[int]:
    """Distribute connections evenly while preserving the exact requested total."""
    if total_connections < 1:
        raise ValueError("total_connections must be positive")
    if workers < 1:
        raise ValueError("workers must be positive")
    if workers > total_connections:
        raise ValueError("workers cannot exceed total_connections")

    quotient, remainder = divmod(total_connections, workers)
    return [quotient + (1 if index < remainder else 0) for index in range(workers)]


def percentile_from_histogram(histogram: Mapping[str, int], percentile: float) -> float:
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in the interval (0, 1]")

    ordered = [(bound, int(histogram.get(str(bound), 0))) for bound in HISTOGRAM_BOUNDS_MS]
    overflow = int(histogram.get("+Inf", 0))
    total = sum(count for _, count in ordered) + overflow
    if total == 0:
        return 0.0

    target = math.ceil(total * percentile)
    cumulative = 0
    for bound, count in ordered:
        cumulative += count
        if cumulative >= target:
            return float(bound)
    return float(HISTOGRAM_BOUNDS_MS[-1])


def aggregate_results(results: Iterable[NodeResult]) -> dict[str, object]:
    rows = list(results)
    if not rows:
        return {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "requests_per_second": 0.0,
            "average_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "p99_latency_ms": 0.0,
            "error_rate": 0.0,
            "latency_histogram": {},
        }

    total = sum(row.total_requests for row in rows)
    successful = sum(row.successful_requests for row in rows)
    failed = sum(row.failed_requests for row in rows)
    weighted_latency = sum(row.average_latency_ms * row.successful_requests for row in rows)
    histogram: dict[str, int] = {str(bound): 0 for bound in HISTOGRAM_BOUNDS_MS}
    histogram["+Inf"] = 0
    for row in rows:
        for bucket, count in row.latency_histogram.items():
            histogram[bucket] = histogram.get(bucket, 0) + int(count)

    return {
        "total_requests": total,
        "successful_requests": successful,
        "failed_requests": failed,
        "requests_per_second": round(sum(row.requests_per_second for row in rows), 2),
        "average_latency_ms": round(weighted_latency / successful, 2) if successful else 0.0,
        "p95_latency_ms": percentile_from_histogram(histogram, 0.95),
        "p99_latency_ms": percentile_from_histogram(histogram, 0.99),
        "error_rate": round((failed / total) * 100, 3) if total else 0.0,
        "latency_histogram": histogram,
    }

