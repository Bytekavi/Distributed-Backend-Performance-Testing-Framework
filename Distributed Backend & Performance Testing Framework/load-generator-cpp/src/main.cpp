#include <arpa/inet.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/tcp.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace {

using Clock = std::chrono::steady_clock;
constexpr std::array<double, 13> kBucketsMs{
    1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000
};

struct Options {
    std::string host = "127.0.0.1";
    std::string path = "/";
    int port = 80;
    int connections = 1000;
    int duration_seconds = 60;
    int threads = std::max(1u, std::thread::hardware_concurrency());
};

struct Metrics {
    std::atomic<std::uint64_t> total{0};
    std::atomic<std::uint64_t> successful{0};
    std::atomic<std::uint64_t> failed{0};
    std::atomic<std::uint64_t> latency_microseconds{0};
    std::array<std::atomic<std::uint64_t>, kBucketsMs.size() + 1> buckets{};
};

struct Client {
    int fd = -1;
    std::size_t sent = 0;
    Clock::time_point started{};
};

int parse_positive(const char* value, std::string_view flag) {
    try {
        int parsed = std::stoi(value);
        if (parsed < 1) {
            throw std::invalid_argument("non-positive");
        }
        return parsed;
    } catch (const std::exception&) {
        throw std::invalid_argument(std::string(flag) + " requires a positive integer");
    }
}

Options parse_options(int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        std::string_view flag(argv[index]);
        if (index + 1 >= argc) {
            throw std::invalid_argument(std::string(flag) + " requires a value");
        }
        if (flag == "--host") {
            options.host = argv[++index];
        } else if (flag == "--path") {
            options.path = argv[++index];
        } else if (flag == "--port") {
            options.port = parse_positive(argv[++index], flag);
        } else if (flag == "--connections") {
            options.connections = parse_positive(argv[++index], flag);
        } else if (flag == "--duration") {
            options.duration_seconds = parse_positive(argv[++index], flag);
        } else if (flag == "--threads") {
            options.threads = parse_positive(argv[++index], flag);
        } else {
            throw std::invalid_argument("unknown option: " + std::string(flag));
        }
    }
    if (options.path.empty() || options.path.front() != '/') {
        throw std::invalid_argument("--path must start with '/'");
    }
    if (options.port > 65535) {
        throw std::invalid_argument("--port must not exceed 65535");
    }
    options.threads = std::min(options.threads, options.connections);
    return options;
}

sockaddr_in resolve_target(const Options& options) {
    addrinfo hints{};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    addrinfo* results = nullptr;
    const int status = getaddrinfo(options.host.c_str(), std::to_string(options.port).c_str(), &hints, &results);
    if (status != 0 || results == nullptr) {
        throw std::runtime_error("cannot resolve target: " + std::string(gai_strerror(status)));
    }
    sockaddr_in address = *reinterpret_cast<sockaddr_in*>(results->ai_addr);
    freeaddrinfo(results);
    return address;
}

std::string make_request(const Options& options) {
    return "GET " + options.path + " HTTP/1.1\r\n"
        "Host: " + options.host + "\r\n"
        "User-Agent: distributed-loadgen/1.0\r\n"
        "Accept: */*\r\n"
        "Connection: close\r\n\r\n";
}

void close_client(int epoll_fd, Client& client) {
    if (client.fd >= 0) {
        epoll_ctl(epoll_fd, EPOLL_CTL_DEL, client.fd, nullptr);
        close(client.fd);
        client.fd = -1;
        client.sent = 0;
    }
}

bool connect_client(int epoll_fd, Client& client, const sockaddr_in& target) {
    const int fd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd < 0) {
        return false;
    }
    int enabled = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &enabled, sizeof(enabled));

    client.fd = fd;
    client.sent = 0;
    client.started = Clock::now();
    epoll_event event{};
    event.events = EPOLLOUT | EPOLLERR | EPOLLHUP;
    event.data.ptr = &client;
    if (epoll_ctl(epoll_fd, EPOLL_CTL_ADD, fd, &event) < 0) {
        close_client(epoll_fd, client);
        return false;
    }
    const int status = connect(fd, reinterpret_cast<const sockaddr*>(&target), sizeof(target));
    if (status < 0 && errno != EINPROGRESS) {
        close_client(epoll_fd, client);
        return false;
    }
    return true;
}

void observe_success(Metrics& metrics, Clock::duration elapsed) {
    const auto micros = std::chrono::duration_cast<std::chrono::microseconds>(elapsed).count();
    const double millis = static_cast<double>(micros) / 1000.0;
    metrics.total.fetch_add(1, std::memory_order_relaxed);
    metrics.successful.fetch_add(1, std::memory_order_relaxed);
    metrics.latency_microseconds.fetch_add(static_cast<std::uint64_t>(std::max<std::int64_t>(0, micros)),
                                          std::memory_order_relaxed);
    const auto iterator = std::lower_bound(kBucketsMs.begin(), kBucketsMs.end(), millis);
    const std::size_t bucket = static_cast<std::size_t>(std::distance(kBucketsMs.begin(), iterator));
    metrics.buckets[bucket].fetch_add(1, std::memory_order_relaxed);
}

void observe_failure(Metrics& metrics) {
    metrics.total.fetch_add(1, std::memory_order_relaxed);
    metrics.failed.fetch_add(1, std::memory_order_relaxed);
}

void event_loop(int connection_count,
                const sockaddr_in target,
                const std::string request,
                const Clock::time_point deadline,
                Metrics& metrics) {
    const int epoll_fd = epoll_create1(EPOLL_CLOEXEC);
    if (epoll_fd < 0) {
        throw std::runtime_error("epoll_create1 failed");
    }

    std::vector<std::unique_ptr<Client>> clients;
    clients.reserve(static_cast<std::size_t>(connection_count));
    for (int index = 0; index < connection_count; ++index) {
        clients.push_back(std::make_unique<Client>());
        if (!connect_client(epoll_fd, *clients.back(), target)) {
            observe_failure(metrics);
        }
    }

    std::array<epoll_event, 512> events{};
    while (Clock::now() < deadline) {
        const int ready = epoll_wait(epoll_fd, events.data(), static_cast<int>(events.size()), 100);
        if (ready < 0 && errno != EINTR) {
            break;
        }
        for (int index = 0; index < std::max(0, ready); ++index) {
            auto& event = events[static_cast<std::size_t>(index)];
            auto* client = static_cast<Client*>(event.data.ptr);
            if (client == nullptr || client->fd < 0) {
                continue;
            }
            const bool unreadable_hangup =
                (event.events & EPOLLHUP) != 0U && (event.events & EPOLLIN) == 0U;
            if ((event.events & EPOLLERR) != 0U || unreadable_hangup) {
                observe_failure(metrics);
                close_client(epoll_fd, *client);
                connect_client(epoll_fd, *client, target);
                continue;
            }
            if ((event.events & EPOLLOUT) != 0U) {
                int socket_error = 0;
                socklen_t error_size = sizeof(socket_error);
                getsockopt(client->fd, SOL_SOCKET, SO_ERROR, &socket_error, &error_size);
                if (socket_error != 0) {
                    observe_failure(metrics);
                    close_client(epoll_fd, *client);
                    connect_client(epoll_fd, *client, target);
                    continue;
                }
                const char* remaining = request.data() + client->sent;
                const std::size_t remaining_size = request.size() - client->sent;
                const ssize_t sent = send(client->fd, remaining, remaining_size, MSG_NOSIGNAL);
                if (sent > 0) {
                    client->sent += static_cast<std::size_t>(sent);
                }
                if (client->sent == request.size()) {
                    epoll_event read_event{};
                    read_event.events = EPOLLIN | EPOLLERR | EPOLLHUP;
                    read_event.data.ptr = client;
                    epoll_ctl(epoll_fd, EPOLL_CTL_MOD, client->fd, &read_event);
                } else if (sent < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
                    observe_failure(metrics);
                    close_client(epoll_fd, *client);
                    connect_client(epoll_fd, *client, target);
                }
            }
            if ((event.events & EPOLLIN) != 0U && client->fd >= 0) {
                std::array<char, 512> buffer{};
                const ssize_t received = recv(client->fd, buffer.data(), buffer.size(), 0);
                if (received > 0) {
                    observe_success(metrics, Clock::now() - client->started);
                } else if (received == 0 || (errno != EAGAIN && errno != EWOULDBLOCK)) {
                    observe_failure(metrics);
                } else {
                    continue;
                }
                close_client(epoll_fd, *client);
                connect_client(epoll_fd, *client, target);
            }
        }

        const auto now = Clock::now();
        for (const auto& client : clients) {
            if (client->fd < 0) {
                connect_client(epoll_fd, *client, target);
            } else if (now - client->started > std::chrono::seconds(10)) {
                observe_failure(metrics);
                close_client(epoll_fd, *client);
                connect_client(epoll_fd, *client, target);
            }
        }
    }
    for (const auto& client : clients) {
        close_client(epoll_fd, *client);
    }
    close(epoll_fd);
}

double percentile(const Metrics& metrics, double fraction) {
    const auto successes = metrics.successful.load();
    if (successes == 0) {
        return 0.0;
    }
    const auto target = static_cast<std::uint64_t>(std::ceil(successes * fraction));
    std::uint64_t cumulative = 0;
    for (std::size_t index = 0; index < metrics.buckets.size(); ++index) {
        cumulative += metrics.buckets[index].load();
        if (cumulative >= target) {
            return index < kBucketsMs.size() ? kBucketsMs[index] : kBucketsMs.back();
        }
    }
    return kBucketsMs.back();
}

void print_json(const Metrics& metrics, double elapsed_seconds) {
    const auto total = metrics.total.load();
    const auto successes = metrics.successful.load();
    const auto failures = metrics.failed.load();
    const double average = successes == 0
        ? 0.0
        : static_cast<double>(metrics.latency_microseconds.load()) / successes / 1000.0;

    std::cout << std::fixed << std::setprecision(3)
              << "{\"total_requests\":" << total
              << ",\"successful_requests\":" << successes
              << ",\"failed_requests\":" << failures
              << ",\"requests_per_second\":" << (elapsed_seconds > 0 ? total / elapsed_seconds : 0)
              << ",\"average_latency_ms\":" << average
              << ",\"p95_latency_ms\":" << percentile(metrics, 0.95)
              << ",\"p99_latency_ms\":" << percentile(metrics, 0.99)
              << ",\"latency_histogram\":{";
    for (std::size_t index = 0; index < kBucketsMs.size(); ++index) {
        if (index > 0) {
            std::cout << ',';
        }
        std::cout << '"' << static_cast<int>(kBucketsMs[index]) << "\":"
                  << metrics.buckets[index].load();
    }
    std::cout << ",\"+Inf\":" << metrics.buckets.back().load() << "}}\n";
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_options(argc, argv);
        const sockaddr_in target = resolve_target(options);
        const std::string request = make_request(options);
        Metrics metrics;
        const auto started = Clock::now();
        const auto deadline = started + std::chrono::seconds(options.duration_seconds);

        std::vector<std::thread> threads;
        const int base = options.connections / options.threads;
        const int remainder = options.connections % options.threads;
        for (int index = 0; index < options.threads; ++index) {
            const int count = base + (index < remainder ? 1 : 0);
            threads.emplace_back(event_loop, count, target, request, deadline, std::ref(metrics));
        }
        for (auto& thread : threads) {
            thread.join();
        }
        const double elapsed = std::chrono::duration<double>(Clock::now() - started).count();
        print_json(metrics, elapsed);
        return 0;
    } catch (const std::exception& exception) {
        std::cerr << "loadgen: " << exception.what() << '\n';
        return 2;
    }
}
