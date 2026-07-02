import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.domain import NodeResult, aggregate_results, percentile_from_histogram, shard_connections


class ShardingTests(unittest.TestCase):
    def test_shards_preserve_total_and_spread_remainder(self):
        self.assertEqual(shard_connections(10_000, 3), [3334, 3333, 3333])

    def test_rejects_more_workers_than_connections(self):
        with self.assertRaises(ValueError):
            shard_connections(2, 3)


class AggregationTests(unittest.TestCase):
    def test_aggregates_node_results(self):
        report = aggregate_results(
            [
                NodeResult(100, 90, 10, 50.0, 10.0, {"10": 80, "20": 10}),
                NodeResult(200, 190, 10, 100.0, 20.0, {"10": 20, "20": 150, "50": 20}),
            ]
        )
        self.assertEqual(report["total_requests"], 300)
        self.assertEqual(report["successful_requests"], 280)
        self.assertEqual(report["failed_requests"], 20)
        self.assertEqual(report["requests_per_second"], 150.0)
        self.assertEqual(report["average_latency_ms"], 16.79)
        self.assertEqual(report["error_rate"], 6.667)
        self.assertEqual(report["p95_latency_ms"], 50.0)

    def test_empty_results_return_zero_report(self):
        self.assertEqual(aggregate_results([])["total_requests"], 0)

    def test_histogram_percentile(self):
        histogram = {"1": 10, "5": 80, "20": 10}
        self.assertEqual(percentile_from_histogram(histogram, 0.95), 20.0)


if __name__ == "__main__":
    unittest.main()

