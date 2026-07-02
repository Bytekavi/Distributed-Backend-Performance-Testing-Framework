package dev.performance.worker;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import redis.clients.jedis.Jedis;
import redis.clients.jedis.JedisPool;
import redis.clients.jedis.JedisPoolConfig;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

public final class WorkerApplication {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final String queue;
    private final String processingQueue;
    private final String apiBaseUrl;
    private final String nodeId;
    private final JedisPool redisPool;
    private final ExecutorService executor;
    private final HttpClient httpClient;

    private WorkerApplication() {
        String redisHost = env("REDIS_HOST", "redis");
        int redisPort = integerEnv("REDIS_PORT", 6379);
        String redisPassword = System.getenv("REDIS_PASSWORD");
        int workerThreads = integerEnv("WORKER_THREADS", 2);
        int poolSize = Math.max(integerEnv("REDIS_POOL_SIZE", workerThreads + 2), workerThreads + 2);

        this.queue = env("JOB_QUEUE", "load-tests");
        this.processingQueue = env("PROCESSING_QUEUE", "load-tests-processing");
        this.apiBaseUrl = env("API_BASE_URL", "http://api:8000").replaceAll("/+$", "");
        this.nodeId = env("WORKER_NODE_ID", env("HOSTNAME", "worker"));
        this.executor = Executors.newFixedThreadPool(workerThreads);
        this.httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();

        JedisPoolConfig config = new JedisPoolConfig();
        config.setMaxTotal(poolSize);
        config.setMaxIdle(poolSize);
        config.setMinIdle(1);
        config.setTestOnBorrow(true);
        config.setBlockWhenExhausted(true);
        config.setMaxWait(Duration.ofSeconds(5));
        if (redisPassword == null || redisPassword.isBlank()) {
            this.redisPool = new JedisPool(config, redisHost, redisPort, 5_000);
        } else {
            this.redisPool = new JedisPool(config, redisHost, redisPort, 5_000, redisPassword);
        }
    }

    public static void main(String[] args) {
        WorkerApplication application = new WorkerApplication();
        Runtime.getRuntime().addShutdownHook(new Thread(application::shutdown));
        application.run();
    }

    private void run() {
        System.out.printf("worker=%s queue=%s threads-ready%n", nodeId, queue);
        while (!Thread.currentThread().isInterrupted()) {
            try (Jedis jedis = redisPool.getResource()) {
                String payload = jedis.brpoplpush(queue, processingQueue, 5);
                if (payload != null) {
                    executor.submit(() -> process(payload));
                }
            } catch (Exception exception) {
                System.err.printf("queue poll failed: %s%n", exception.getMessage());
                sleepOneSecond();
            }
        }
    }

    private void process(String rawJob) {
        String testId = "unknown";
        try {
            Map<String, Object> job = JSON.readValue(rawJob, MAP_TYPE);
            testId = String.valueOf(job.get("test_id"));
            int shardId = asInteger(job, "shard_id");
            String resultNodeId = nodeId + "-shard-" + shardId;

            List<String> command = List.of(
                "/usr/local/bin/loadgen",
                "--host", String.valueOf(job.get("target_host")),
                "--port", String.valueOf(asInteger(job, "target_port")),
                "--path", String.valueOf(job.get("target_path")),
                "--connections", String.valueOf(asInteger(job, "connections")),
                "--duration", String.valueOf(asInteger(job, "duration_seconds"))
            );
            JsonNode loadResult = runLoadGenerator(command);
            postResult(testId, resultNodeId, loadResult);
            removeFromProcessing(rawJob);
            System.out.printf("test=%s node=%s completed%n", testId, resultNodeId);
        } catch (Exception exception) {
            System.err.printf("test=%s failed: %s%n", testId, exception.getMessage());
            requeue(rawJob);
        }
    }

    private JsonNode runLoadGenerator(List<String> command) throws IOException, InterruptedException {
        Process process = new ProcessBuilder(command).redirectError(ProcessBuilder.Redirect.INHERIT).start();
        boolean exited = process.waitFor(24, TimeUnit.HOURS);
        if (!exited) {
            process.destroyForcibly();
            throw new IOException("load generator timed out");
        }
        Optional<String> lastLine;
        try (BufferedReader reader = new BufferedReader(
            new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8)
        )) {
            lastLine = reader.lines().filter(line -> !line.isBlank()).reduce((first, second) -> second);
        }
        if (process.exitValue() != 0 || lastLine.isEmpty()) {
            throw new IOException("load generator exited with code " + process.exitValue());
        }
        return JSON.readTree(lastLine.get());
    }

    private void postResult(String testId, String resultNodeId, JsonNode loadResult)
        throws IOException, InterruptedException {
        Map<String, Object> payload = JSON.convertValue(loadResult, MAP_TYPE);
        payload.put("node_id", resultNodeId);
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create(apiBaseUrl + "/api/v1/tests/" + testId + "/results"))
            .timeout(Duration.ofSeconds(30))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(payload)))
            .build();
        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IOException("control plane returned " + response.statusCode() + ": " + response.body());
        }
    }

    private void removeFromProcessing(String payload) {
        try (Jedis jedis = redisPool.getResource()) {
            jedis.lrem(processingQueue, 1, payload);
        }
    }

    private void requeue(String payload) {
        try (Jedis jedis = redisPool.getResource()) {
            jedis.lrem(processingQueue, 1, payload);
            jedis.rpush(queue, payload);
        } catch (Exception exception) {
            System.err.printf("could not requeue job: %s%n", exception.getMessage());
        }
    }

    private void shutdown() {
        executor.shutdown();
        try {
            if (!executor.awaitTermination(10, TimeUnit.SECONDS)) {
                executor.shutdownNow();
            }
        } catch (InterruptedException exception) {
            executor.shutdownNow();
            Thread.currentThread().interrupt();
        }
        redisPool.close();
    }

    private static int asInteger(Map<String, Object> values, String key) {
        Object value = values.get(key);
        if (value instanceof Number number) {
            return number.intValue();
        }
        return Integer.parseInt(String.valueOf(value));
    }

    private static int integerEnv(String name, int fallback) {
        return Integer.parseInt(env(name, String.valueOf(fallback)));
    }

    private static String env(String name, String fallback) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? fallback : value;
    }

    private static void sleepOneSecond() {
        try {
            Thread.sleep(1_000);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
        }
    }
}
