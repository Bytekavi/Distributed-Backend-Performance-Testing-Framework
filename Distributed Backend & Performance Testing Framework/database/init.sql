CREATE TABLE IF NOT EXISTS load_tests (
    id CHAR(36) PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    target_host VARCHAR(255) NOT NULL,
    target_port INT UNSIGNED NOT NULL,
    target_path VARCHAR(1024) NOT NULL,
    concurrent_connections INT UNSIGNED NOT NULL,
    duration_seconds INT UNSIGNED NOT NULL,
    expected_workers INT UNSIGNED NOT NULL,
    received_workers INT UNSIGNED NOT NULL DEFAULT 0,
    status ENUM('queued', 'running', 'completed', 'failed') NOT NULL DEFAULT 'queued',
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    completed_at TIMESTAMP(6) NULL,
    INDEX idx_load_tests_created_at (created_at),
    INDEX idx_load_tests_status (status)
);

CREATE TABLE IF NOT EXISTS load_results (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    test_id CHAR(36) NOT NULL,
    node_id VARCHAR(160) NOT NULL,
    total_requests BIGINT UNSIGNED NOT NULL,
    successful_requests BIGINT UNSIGNED NOT NULL,
    failed_requests BIGINT UNSIGNED NOT NULL,
    requests_per_second DOUBLE NOT NULL,
    average_latency_ms DOUBLE NOT NULL,
    p95_latency_ms DOUBLE NOT NULL,
    p99_latency_ms DOUBLE NOT NULL,
    latency_histogram JSON NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_results_test FOREIGN KEY (test_id) REFERENCES load_tests(id) ON DELETE CASCADE,
    UNIQUE KEY uq_test_node (test_id, node_id),
    INDEX idx_results_test_id (test_id)
);

