#include "kvs_master/kvs_session.hpp"
#include "camera.hpp"

#include <arpa/inet.h>
#include <gst/app/gstappsink.h>
#include <gst/app/gstappsrc.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace {

namespace kvs = txing::board::kvs_master;
namespace quad = txing::virtual_quad;
using quad::Clock;
using namespace std::chrono_literals;
using Frame = std::vector<std::uint8_t>;

volatile std::sig_atomic_t stopping = 0;

void Stop(int) { stopping = 1; }

const char* RequireEnv(const char* name) {
    const char* value = std::getenv(name);
    if (!value || !*value) throw std::runtime_error(std::string("missing ") + name);
    return value;
}

class Telemetry {
  public:
    void Publish(Frame frame) {
        {
            std::lock_guard lock(mutex);
            frames[next++ % frames.size()] = std::move(frame);
        }
        available.notify_all();
    }

    std::mutex mutex;
    std::condition_variable available;
    std::array<Frame, 64> frames;
    std::size_t next = 0;
};

class Observer final : public kvs::BoardMavlinkPeer {
  public:
    Observer(Telemetry& telemetry, kvs::MavlinkTelemetryReceiver receiver)
        : telemetry_(telemetry), reader_([this, receiver = std::move(receiver)] {
            std::unique_lock lock(telemetry_.mutex);
            auto next = telemetry_.next;
            while (true) {
                telemetry_.available.wait(lock, [&] { return closed_ || next != telemetry_.next; });
                if (closed_) return;
                if (telemetry_.next - next > telemetry_.frames.size()) next = telemetry_.next - 1;
                auto frame = telemetry_.frames[next++ % telemetry_.frames.size()];
                lock.unlock();
                receiver(std::move(frame));
                lock.lock();
            }
        }) {}

    ~Observer() override { Close(""); }

    // The qualification adapter has no write path to SITL, including for JSON.
    std::string HandleControl(const std::string&) override {
        throw std::runtime_error("qualification data channel is receive only");
    }

    void SendFrame(const Frame&, std::uint64_t) override {}

    void Close(const std::string&) noexcept override {
        {
            std::lock_guard lock(telemetry_.mutex);
            closed_ = true;
        }
        telemetry_.available.notify_all();
        if (reader_.joinable()) reader_.join();
    }

  private:
    Telemetry& telemetry_;
    bool closed_ = false;  // Guarded by telemetry_.mutex.
    std::thread reader_;
};

class ObservationBridge final : public kvs::BoardMavlinkBridgeClient {
  public:
    explicit ObservationBridge(Telemetry& telemetry) : telemetry_(telemetry) {}

    kvs::MavlinkControlChannelConfig GetControlChannelConfig(const std::string&, const std::string&) override {
        throw std::logic_error("qualification config is supplied by the supervisor");
    }

    kvs::BridgeCredentials RefreshControlChannelCredentials() override {
        throw std::logic_error("qualification uses credentials valid for the entire run");
    }

    void ReportControlChannelState(bool, const std::string&) override {}

    std::unique_ptr<kvs::BoardMavlinkPeer> OpenPeer(
        const std::string&, kvs::MavlinkTelemetryReceiver receiver
    ) override {
        return std::make_unique<Observer>(telemetry_, std::move(receiver));
    }

  private:
    Telemetry& telemetry_;
};

struct SitlState {
    std::uint64_t frames = 0;
    std::uint64_t unframed = 0;
    std::uint64_t pose_samples = 0;
    Clock::time_point heartbeat{};
    Clock::time_point attitude{};
    Clock::time_point position{};
    Clock::time_point ekf{};
    std::uint32_t boot_ms = 0;
    bool armed = false;
    bool ekf_ready = false;
    quad::PoseHistory poses;

    bool NavigationReady(Clock::time_point now) const {
        return now - attitude < 1s && now - position < 1s && now - ekf < 1500ms && ekf_ready;
    }
};

class SitlTelemetry {
  public:
    SitlTelemetry() {
        socket_ = socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
        if (socket_ < 0) throw std::runtime_error("create SITL telemetry socket failed");
        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_port = htons(14550);
        address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        if (bind(socket_, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) != 0) {
            close(socket_);
            throw std::runtime_error("bind SITL telemetry socket failed");
        }
    }

    ~SitlTelemetry() {
        stopped_ = true;
        if (reader_.joinable()) reader_.join();
        close(socket_);
    }
    SitlTelemetry(const SitlTelemetry&) = delete;
    SitlTelemetry& operator=(const SitlTelemetry&) = delete;

    void Start(Telemetry& telemetry) {
        reader_ = std::thread([this, &telemetry] {
            try {
                pollfd socket{socket_, POLLIN, 0};
                while (!stopped_) {
                    const auto result = poll(&socket, 1, 50);
                    if (result < 0 && errno == EINTR) continue;
                    if (result < 0 || (socket.revents & (POLLERR | POLLHUP | POLLNVAL))) {
                        throw std::runtime_error("poll SITL telemetry failed");
                    }
                    if (result > 0 && (socket.revents & POLLIN)) Drain(telemetry);
                }
            } catch (...) {
                std::lock_guard lock(mutex_);
                error_ = std::current_exception();
            }
        });
    }

    SitlState Snapshot() {
        std::lock_guard lock(mutex_);
        if (error_) std::rethrow_exception(error_);
        return state_;
    }

  private:
    void Drain(Telemetry& telemetry) {
        // The pinned SITL UART UDP sender packetizes at MAVLink frame boundaries.
        // Use a fixed receive budget so shutdown and snapshots stay responsive.
        std::lock_guard lock(mutex_);
        for (unsigned i = 0; i < 64; ++i) {
            std::array<std::uint8_t, 65536> packet;
            const auto size = recv(socket_, packet.data(), packet.size(), 0);
            if (size < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) return;
            if (size < 0 && errno == EINTR) continue;
            if (size < 0) throw std::runtime_error("receive SITL telemetry failed");
            const auto length = static_cast<std::size_t>(size);
            for (std::size_t offset = 0; offset < length;) {
                const auto* bytes = packet.data() + offset;
                const auto remaining = length - offset;
                if (bytes[0] != 0xfd || remaining < 12 || (bytes[2] & ~1) != 0) {
                    ++state_.unframed;
                    break;
                }
                const std::size_t frame_size = 12 + bytes[1] + ((bytes[2] & 1) ? 13 : 0);
                if (frame_size > remaining) {
                    ++state_.unframed;
                    break;
                }
                if (bytes[5] == 1 && bytes[6] == 1 && bytes[8] == 0 && bytes[9] == 0) {
                    const auto received = Clock::now();
                    if (bytes[7] == 108) {
                        if (auto pose = quad::DecodeSimState(bytes, frame_size, received)) {
                            state_.poses.Push(*pose);
                            ++state_.pose_samples;
                        }
                    } else {
                        Observe(bytes[7], bytes[1], bytes + 10, received);
                    }
                }
                telemetry.Publish(Frame(bytes, bytes + frame_size));
                ++state_.frames;
                offset += frame_size;
            }
        }
    }

    static std::uint32_t U32(const std::uint8_t* bytes) {
        std::uint32_t result = 0;
        for (unsigned j = 0; j < 4; ++j) result |= std::uint32_t(bytes[j]) << (8 * j);
        return result;
    }

    template<typename T>
    static T Decode32(const std::uint8_t* bytes) {
        const auto raw = U32(bytes);
        T value;
        static_assert(sizeof(value) == sizeof(raw));
        std::memcpy(&value, &raw, sizeof(value));
        return value;
    }

    void Observe(unsigned message, unsigned length, const std::uint8_t* payload, Clock::time_point now) {
        if (message == 0 && length >= 9) { // HEARTBEAT
            state_.heartbeat = now;
            state_.armed = (payload[6] & 128) != 0; // MAV_MODE_FLAG_SAFETY_ARMED
        } else if (message == 30 && length >= 4) { // ATTITUDE
            state_.boot_ms = U32(payload);
            // MAVLink 2 may trim trailing zeros, including zero attitude fields.
            std::array<std::uint8_t, 16> pose{};
            for (unsigned i = 4; i < pose.size() && i < length; ++i) pose[i] = payload[i];
            if (std::isfinite(Decode32<float>(&pose[4])) &&
                std::isfinite(Decode32<float>(&pose[8])) &&
                std::isfinite(Decode32<float>(&pose[12]))) {
                state_.attitude = now;
            }
        } else if (message == 33 && length >= 12) { // GLOBAL_POSITION_INT
            const auto lat = Decode32<std::int32_t>(payload + 4);
            const auto lon = Decode32<std::int32_t>(payload + 8);
            if ((lat != 0 || lon != 0) && lat >= -900000000 && lat <= 900000000 &&
                lon >= -1800000000 && lon <= 1800000000) {
                state_.position = now;
            }
        } else if (message == 193 && length >= 21) { // EKF_STATUS_REPORT
            const unsigned flags = payload[20] | (length >= 22 ? unsigned(payload[21]) << 8 : 0);
            constexpr unsigned required = 1 | 16 | 32; // Attitude and absolute horizontal/vertical position.
            constexpr unsigned unhealthy = 128 | 1024; // Constant position or GPS glitch.
            state_.ekf_ready = (flags & required) == required && (flags & unhealthy) == 0;
            state_.ekf = now;
        }
    }

    int socket_;
    std::atomic_bool stopped_{false};
    std::mutex mutex_;
    SitlState state_;
    std::exception_ptr error_;
    std::thread reader_;
};

class CameraSource {
  public:
    CameraSource(GstAppSrc* source, SitlTelemetry& sitl, Clock::time_point origin)
        : producer_([this, source, &sitl, origin] {
            try {
                Produce(source, sitl, origin);
            } catch (...) {
                std::lock_guard lock(mutex_);
                error_ = std::current_exception();
            }
        }) {}

    ~CameraSource() {
        stopped_ = true;
        producer_.join();
    }

    void Check() {
        std::lock_guard lock(mutex_);
        if (error_) std::rethrow_exception(error_);
    }

  private:
    void Produce(GstAppSrc* source, SitlTelemetry& sitl, Clock::time_point origin) {
        constexpr auto interval = std::chrono::nanoseconds(GST_SECOND / quad::camera_fps);
        auto frame_time = Clock::now();
        std::int64_t previous_pts = -1;
        while (!stopped_) {
            std::this_thread::sleep_until(frame_time);
            if (stopped_) return;
            const auto now = Clock::now();
            frame_time += interval * ((now - frame_time) / interval);
            frame_time += interval;
            const auto state = sitl.Snapshot();
            const auto sampled = state.poses.At(Clock::now());
            if (!sampled) continue;
            const auto pts = std::chrono::duration_cast<std::chrono::nanoseconds>(sampled->received - origin).count();
            if (pts <= previous_pts) continue;

            const std::unique_ptr<GstBuffer, decltype(&gst_buffer_unref)> buffer(
                gst_buffer_new_allocate(nullptr, quad::camera_frame_bytes, nullptr), gst_buffer_unref);
            GstMapInfo bytes{};
            if (!buffer || !gst_buffer_map(buffer.get(), &bytes, GST_MAP_WRITE)) {
                throw std::runtime_error("allocate raw camera frame failed");
            }
            quad::RenderCamera(sampled->pose, bytes.data);
            gst_buffer_unmap(buffer.get(), &bytes);
            if (Clock::now() >= frame_time || stopped_) continue;
            GST_BUFFER_PTS(buffer.get()) = static_cast<GstClockTime>(pts);
            GST_BUFFER_DURATION(buffer.get()) = interval.count();
            if (gst_app_src_push_buffer(source, gst_buffer_ref(buffer.get())) != GST_FLOW_OK && !stopped_) {
                throw std::runtime_error("enqueue raw camera frame failed");
            }
            if (previous_pts < 0) {
                std::printf("QUAD_CAMERA_FIRST_POSE pts_ns=%lld\n", static_cast<long long>(pts));
            }
            previous_pts = pts;
        }
    }

    std::atomic_bool stopped_{false};
    std::mutex mutex_;
    std::exception_ptr error_;
    std::thread producer_;
};

long long UnixMilliseconds() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
}

void WriteHealth(const std::string& path, bool heartbeat, bool navigation, bool mavlink, bool video) {
    const auto pending = path + ".new";
    auto* file = std::fopen(pending.c_str(), "w");
    if (!file) throw std::runtime_error("open managed health sample failed");
    const int written = std::fprintf(file,
        "{\"observedAtMs\":%lld,\"heartbeat\":%s,\"navigation\":%s,\"mavlink\":%s,\"video\":%s}\n",
        UnixMilliseconds(), heartbeat ? "true" : "false", navigation ? "true" : "false",
        mavlink ? "true" : "false", video ? "true" : "false");
    const int closed = std::fclose(file);
    if (written < 0 || closed != 0 || std::rename(pending.c_str(), path.c_str()) != 0) {
        throw std::runtime_error("write managed health sample failed");
    }
}

void DeletePipeline(GstElement* element) {
    gst_element_set_state(element, GST_STATE_NULL);
    gst_object_unref(element);
}

void Run(bool local, bool camera) {
    const auto start = Clock::now();
    const auto start_utc = std::chrono::system_clock::now();
    const auto* health_path = std::getenv("QUAD_HEALTH_FILE");
    Telemetry telemetry;
    SitlTelemetry receiver;
    receiver.Start(telemetry);
    std::unique_ptr<kvs::KvsSession> video;
    std::unique_ptr<kvs::KvsSession> data;
    if (!local) {
        kvs::RuntimeConfig config;
        config.region = RequireEnv("AWS_REGION");
        config.channel_name = RequireEnv("QUAD_VIDEO_CHANNEL");
        config.client_id = "virtual-quad-qualification";
        config.camera.bitrate = 800'000;
        config.isolate_video_peers = camera;
        const auto credentials = kvs::ResolveAwsCredentials();
        video = kvs::CreateKvsSession(config, credentials);
        video->Start();
        std::puts("QUAD_VIDEO_MASTER_STARTED");

        config.session_kind = kvs::KvsSessionKind::kMavlinkControl;
        config.channel_name = RequireEnv("QUAD_MAVLINK_CHANNEL");
        data = kvs::CreateKvsSessionWithMavlinkBridge(
            config, credentials, std::make_unique<ObservationBridge>(telemetry));
        data->Start();
        std::puts("QUAD_MAVLINK_MASTER_STARTED");
    }

    gst_init(nullptr, nullptr);
    GError* error = nullptr;
    const std::string source = camera
        ? "appsrc name=camera is-live=true format=time max-buffers=2 max-bytes=0 leaky-type=downstream "
          "! video/x-raw,format=I420,width=640,height=360,framerate=15/1,colorimetry=bt601 "
        : "videotestsrc is-live=true pattern=ball ! video/x-raw,format=I420,width=640,height=360,framerate=15/1 ";
    const std::string pipeline_spec = source +
        "! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream "
        "! x264enc tune=zerolatency speed-preset=veryfast bitrate=800 key-int-max=15 bframes=0 byte-stream=true "
        "nal-hrd=cbr "
        "! video/x-h264,profile=constrained-baseline,level=(string)3.1 "
        "! h264parse config-interval=-1 "
        "! video/x-h264,stream-format=byte-stream,alignment=au "
        "! appsink name=out sync=false max-buffers=2 drop=true";
    std::unique_ptr<GstElement, decltype(&DeletePipeline)> pipeline(
        gst_parse_launch(pipeline_spec.c_str(), &error), DeletePipeline);
    if (error) {
        const std::string detail = error->message;
        g_error_free(error);
        throw std::runtime_error(detail);
    }
    if (!pipeline) throw std::runtime_error("create encoder pipeline failed");
    std::unique_ptr<GstElement, decltype(&gst_object_unref)> sink(
        gst_bin_get_by_name(GST_BIN(pipeline.get()), "out"), gst_object_unref);
    std::unique_ptr<GstBus, decltype(&gst_object_unref)> bus(gst_element_get_bus(pipeline.get()), gst_object_unref);
    if (!sink || !bus || gst_element_set_state(pipeline.get(), GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
        throw std::runtime_error("start encoder failed");
    }
    std::unique_ptr<GstElement, decltype(&gst_object_unref)> camera_source(
        camera ? gst_bin_get_by_name(GST_BIN(pipeline.get()), "camera") : nullptr, gst_object_unref);
    std::unique_ptr<CameraSource> camera_producer;
    if (camera) {
        if (!camera_source) throw std::runtime_error("create camera source failed");
        camera_producer = std::make_unique<CameraSource>(GST_APP_SRC(camera_source.get()), receiver, start);
    }

    auto sample_start = Clock::now();
    auto last_frame = sample_start;
    auto next_health = sample_start;
    std::uint32_t last_boot = 0;
    unsigned encoded = 0;
    unsigned keyframes = 0;
    std::uint64_t encoded_bytes = 0;
    GstClockTime first_pts = GST_CLOCK_TIME_NONE;
    bool ready = false;
    bool produced_keyframe = false;
    while (!stopping) {
        const std::unique_ptr<GstMessage, decltype(&gst_message_unref)> failure(
            gst_bus_pop_filtered(bus.get(), GST_MESSAGE_ERROR), gst_message_unref);
        if (failure) {
            GError* gst_error = nullptr;
            gst_message_parse_error(failure.get(), &gst_error, nullptr);
            const std::unique_ptr<GError, decltype(&g_error_free)> detail(gst_error, g_error_free);
            throw std::runtime_error(detail ? detail->message : "encoder pipeline failed");
        }
        const std::unique_ptr<GstSample, decltype(&gst_sample_unref)> sample(
            gst_app_sink_try_pull_sample(GST_APP_SINK(sink.get()), 100 * GST_MSECOND), gst_sample_unref);
        if (sample) {
            if (!ready && encoded == 0) {
                auto* caps = gst_sample_get_caps(sample.get());
                if (!caps) throw std::runtime_error("encoder produced a sample without caps");
                std::unique_ptr<gchar, decltype(&g_free)> text(gst_caps_to_string(caps), g_free);
                std::printf("QUAD_H264_CAPS %s\n", text.get());
            }
            auto* buffer = gst_sample_get_buffer(sample.get());
            GstMapInfo bytes{};
            if (!buffer || !GST_BUFFER_PTS_IS_VALID(buffer)) {
                throw std::runtime_error("encoded access unit has no timestamp");
            }
            const auto pts = GST_BUFFER_PTS(buffer);
            if (first_pts == GST_CLOCK_TIME_NONE) {
                first_pts = pts;
                if (camera) {
                    const auto* segment = gst_sample_get_segment(sample.get());
                    const auto running = segment ? gst_segment_to_running_time(segment, GST_FORMAT_TIME, pts) : GST_CLOCK_TIME_NONE;
                    if (running == GST_CLOCK_TIME_NONE) throw std::runtime_error("camera frame has no running timestamp");
                    const auto first_pose_utc = start_utc + std::chrono::nanoseconds(running);
                    const auto epoch_ms = std::chrono::duration<double, std::milli>(first_pose_utc.time_since_epoch()).count();
                    std::printf("QUAD_CAMERA_RTP_EPOCH epoch_ms=%.3f first_pose_ns=%llu\n", epoch_ms,
                        static_cast<unsigned long long>(running));
                }
            }
            if (pts < first_pts || !gst_buffer_map(buffer, &bytes, GST_MAP_READ)) {
                throw std::runtime_error("read encoded access unit failed");
            }
            const auto keyframe = !GST_BUFFER_FLAG_IS_SET(buffer, GST_BUFFER_FLAG_DELTA_UNIT);
            encoded_bytes += bytes.size;
            try {
                if (video) video->PushH264AccessUnit(
                    bytes.data, bytes.size, (pts - first_pts) / 100, GST_SECOND / 15 / 100, keyframe);
            } catch (...) {
                gst_buffer_unmap(buffer, &bytes);
                throw;
            }
            gst_buffer_unmap(buffer, &bytes);
            ++encoded;
            if (keyframe) {
                ++keyframes;
                produced_keyframe = true;
            }
            last_frame = Clock::now();
        }
        if (camera_producer) camera_producer->Check();
        for (auto* session : {video.get(), data.get()}) {
            if (session) {
                if (auto fatal = session->TakeFatalError()) throw std::runtime_error(*fatal);
            }
        }

        const auto sitl = receiver.Snapshot();
        const auto now = Clock::now();
        const bool pose_fresh = !camera || sitl.poses.At(now).has_value();
        if (health_path && now >= next_health) {
            if (sitl.armed) throw std::runtime_error("read-only simulator unexpectedly armed");
            const bool heartbeat = now - sitl.heartbeat < 2s;
            WriteHealth(health_path, heartbeat, sitl.NavigationReady(now) && pose_fresh,
                heartbeat && data && data->SignalingConnected(),
                pose_fresh && produced_keyframe && now - last_frame < 1s && video && video->SignalingConnected());
            next_health = now + 1s;
        }
        if ((!camera || ready) && now - last_frame > 3s) throw std::runtime_error("encoder stopped producing access units");
        if (!ready && now - start >= 80s) throw std::runtime_error("qualification startup exceeded 80 seconds");
        if (!ready && keyframes && pose_fresh && sitl.boot_ms && sitl.heartbeat != Clock::time_point{} &&
            now - sitl.heartbeat < 2s && now - sitl.attitude < 1s) {
            std::printf("QUAD_READY mode=%s camera=%s unix_ms=%lld media_elapsed_ms=%lld boot_ms=%u\n",
                local ? "local" : "kvs",
                camera ? "pose" : "pattern",
                UnixMilliseconds(),
                static_cast<long long>(std::chrono::duration_cast<std::chrono::milliseconds>(now - start).count()),
                sitl.boot_ms);
            ready = true;
            sample_start = now;
            last_boot = sitl.boot_ms;
            encoded = keyframes = 0;
            encoded_bytes = 0;
        }
        if (ready && (now - sitl.heartbeat > 3s || now - sitl.attitude > 3s)) {
            throw std::runtime_error("SITL heartbeat or attitude stopped");
        }
        if (ready && now - sample_start >= 30s) {
            const double wall = std::chrono::duration<double>(now - sample_start).count();
            const auto boot_delta = sitl.boot_ms - last_boot;
            std::printf(
                "QUAD_MEDIA_SAMPLE wall_seconds=%.3f boot_delta_ms=%u sim_rate=%.4f "
                "encoded_fps=%.2f encoded_kbps=%.1f keyframes=%u telemetry_frames_total=%llu "
                "unframed_datagrams_total=%llu pose_samples_total=%llu\n",
                wall, boot_delta, boot_delta / (1000.0 * wall), encoded / wall, encoded_bytes * 0.008 / wall, keyframes,
                static_cast<unsigned long long>(sitl.frames), static_cast<unsigned long long>(sitl.unframed),
                static_cast<unsigned long long>(sitl.pose_samples));
            sample_start = now;
            last_boot = sitl.boot_ms;
            encoded = keyframes = 0;
            encoded_bytes = 0;
        }
    }
}

}  // namespace

int main(int argc, char** argv) {
    std::setvbuf(stdout, nullptr, _IOLBF, 0);
    std::signal(SIGTERM, Stop);
    std::signal(SIGINT, Stop);
    try {
        bool local = false;
        bool camera = false;
        for (int i = 1; i < argc; ++i) {
            const std::string option(argv[i]);
            if (option == "--local") local = true;
            else if (option == "--camera") camera = true;
            else throw std::runtime_error("unknown simulator media option");
        }
        Run(local, camera);
    } catch (const std::exception& error) {
        std::fprintf(stderr, "QUAD_MEDIA_ERROR %s\n", error.what());
        return 1;
    }
}
