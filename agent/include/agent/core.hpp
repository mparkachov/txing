#pragma once

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace txing::agent {
using Bytes = std::vector<std::uint8_t>;
using Time = std::chrono::steady_clock::time_point;
enum class Stream { telemetry, video };
enum class Media { data, h264 };
enum class Role { viewer, master };
enum class Connection { stopped, connecting, connected, failed };
struct TransportConfig {
    std::string channel, region, label, ca_path;
    Media media = Media::data;
    Role role = Role::viewer;
};
struct Profile { TransportConfig telemetry, video; };
Profile profile(const std::string& registered_type, const std::string& thing,
                const std::string& region, const std::string& ca_path);
struct Lifecycle { bool born = false; int redcon = 4; };
struct EncodedVideo {
    Bytes bytes;
    std::string codec;
    // KVS presentation timestamp: 100 ns media clock ticks, not wall time.
    std::uint64_t presentation_100ns = 0;
    std::chrono::system_clock::time_point received;
};
bool valid_mavlink2(const Bytes& bytes);

// Bounded by both item count and bytes. Never call consumer code while locked.
// Overflow drops the oldest observation; an oversized observation is rejected.
template<class T> class Queue {
public:
    Queue(std::size_t count, std::size_t bytes) : max_count_(count), max_bytes_(bytes) {}
    bool push(T item, std::size_t bytes) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (closed_ || bytes > max_bytes_) { ++dropped_; return false; }
        while (!items_.empty() && (items_.size() >= max_count_ || size_ + bytes > max_bytes_)) {
            size_ -= items_.front().second; items_.pop_front(); ++dropped_;
        }
        size_ += bytes; items_.emplace_back(std::move(item), bytes); ready_.notify_one(); return true;
    }
    std::optional<T> pop(bool wait = false) {
        std::unique_lock<std::mutex> lock(mutex_);
        if (wait) ready_.wait(lock, [&] { return closed_ || !items_.empty(); });
        if (items_.empty()) return {};
        T value = std::move(items_.front().first);
        size_ -= items_.front().second; items_.pop_front(); return value;
    }
    void close() { std::lock_guard<std::mutex> lock(mutex_); closed_ = true; ready_.notify_all(); }
    std::size_t dropped() const { std::lock_guard<std::mutex> lock(mutex_); return dropped_; }
private:
    const std::size_t max_count_, max_bytes_;
    mutable std::mutex mutex_;
    std::condition_variable ready_;
    std::deque<std::pair<T, std::size_t>> items_;
    std::size_t size_ = 0, dropped_ = 0;
    bool closed_ = false;
};

struct TransportEvents {
    std::function<void(Bytes, bool)> data;
    std::function<void(EncodedVideo)> video;
};
class Transport {
public:
    virtual ~Transport() = default;
    virtual void start(const TransportConfig&, TransportEvents) = 0;
    // Initiate shutdown without joining network operations on the control tick.
    // Destruction joins; finished permits prompt retirement without blocking.
    virtual void stop() noexcept = 0;
    virtual bool finished() const = 0;
    virtual Connection state() const = 0;
    virtual std::string error() const = 0;
    virtual bool send(const Bytes&, bool binary) = 0;
};
using TransportFactory = std::function<std::unique_ptr<Transport>()>;

// Actions enqueue requests; acquire returning true is not a board grant.
// send rejects traffic without a current grant and fences queued frames to
// that grant, so authority loss/reacquisition cannot authorize old traffic.
// Control changes arrive asynchronously. client_activity is explicit presence,
// independent of arm/disarm and of the renewal timer.
class Actions {
public:
    virtual ~Actions() = default;
    virtual bool acquire(std::string actor) = 0;
    virtual bool send(Bytes frame) = 0;
    virtual void release() = 0;
    virtual void client_activity() = 0;
};
class Operator {
public:
    virtual ~Operator() = default;
    virtual void telemetry(const Bytes&) = 0;
    // Video has a separate consumer thread; implementations synchronize state
    // shared with telemetry/events. Callbacks must return for orderly shutdown.
    virtual void video(const EncodedVideo&) = 0;
    virtual void connection(Stream, Connection, const std::string&) = 0;
    virtual void control(bool held, const std::string& reason) = 0;
};

class Session final : public Actions {
public:
    Session(Profile, TransportFactory, Operator&, Time now);
    ~Session();
    // Hosting calls tick regularly and supplies a new authoritative lifecycle
    // only after a successful read. The monotonic verification deadline is
    // independent of network/API duration and connection recovery.
    void verified(Lifecycle, Time);
    bool tick(Time);
    void shutdown(const std::string& reason);
    const std::string& stop_reason() const { return stop_reason_; }
    bool acquire(std::string) override;
    bool send(Bytes) override;
    void release() override;
    void client_activity() override;
    std::size_t video_dropped() const { return videos_.dropped(); }
private:
    struct Link {
        TransportConfig config;
        std::unique_ptr<Transport> transport;
        std::unique_ptr<Transport> retiring;
        std::shared_ptr<std::atomic<bool>> accepting;
        std::shared_ptr<std::atomic<std::uint64_t>> received;
        std::uint64_t received_count = 0;
        Connection previous = Connection::stopped;
        Time attempted{}, retry_at{}, last_received{};
        int backoff = 1;
        std::string last_error;
    };
    struct Observation {
        enum Kind { telemetry, connection, control } kind;
        Bytes bytes;
        Stream stream = Stream::telemetry;
        Connection state = Connection::stopped;
        bool held = false;
        std::string detail;
    };
    struct Command {
        enum Kind { acquire, send, release, activity } kind;
        Bytes bytes;
        std::string actor;
        std::uint64_t authority_generation = 0;
    };
    void update(Link&, Stream, bool wanted, Time);
    bool text(const std::string&);
    void response(const std::string&, Time);
    void lose(const std::string&, bool release = true);
    void emit_control(bool, const std::string&);
    void request(const std::string&, const std::string&, Time);
    Profile profile_;
    TransportFactory factory_;
    Operator& operator_;
    Link telemetry_, video_;
    Lifecycle lifecycle_;
    Time last_verified_, last_client_{}, last_renewed_{}, next_renew_{}, request_at_{};
    bool has_verification_ = false, stopped_ = false, held_ = false;
    std::uint64_t epoch_ = 0, sequence_ = 0;
    std::uint64_t control_generation_ = 0;
    std::atomic<std::uint64_t> authorized_generation_{0};
    std::string session_id_, pending_id_, pending_type_;
    std::string stop_reason_;
    Queue<Observation> observations_{256, 256 * 1024};
    Queue<Observation> events_{64, 64 * 4096};
    Queue<EncodedVideo> videos_{4, 8 * 1024 * 1024};
    Queue<std::string> responses_{64, 64 * 4096};
    std::atomic<bool> response_overflow_{false};
    std::atomic<bool> delivery_stopped_{false};
    std::mutex commands_mutex_;
    std::deque<Command> commands_;
    std::thread observation_thread_, video_thread_;
    bool enqueue(Command);
};
}
