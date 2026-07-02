from prometheus_client import Counter, Gauge, Histogram

TESTS_SUBMITTED = Counter(
    "performance_tests_submitted_total",
    "Number of distributed performance tests submitted.",
)
RESULTS_RECEIVED = Counter(
    "performance_results_received_total",
    "Number of worker result payloads received.",
)
ACTIVE_TESTS = Gauge(
    "performance_tests_active",
    "Tests that have not yet received all worker results.",
)
REPORT_LATENCY = Histogram(
    "performance_report_seconds",
    "Time spent building an aggregate report.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

