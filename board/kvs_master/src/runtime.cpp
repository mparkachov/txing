#include "kvs_master/runtime.hpp"

#include "kvs_master/aws_env.hpp"
#include "kvs_master/kvs_session.hpp"
#include "kvs_master/markers.hpp"
#include "kvs_master/video_capturer.hpp"

#include <algorithm>
#include <atomic>
#include <csignal>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>

namespace txing::board::kvs_master {
namespace {

std::atomic_bool g_stop_requested = false;

extern "C" void OnSignal(int) {
    g_stop_requested.store(true);
}

void InstallSignalHandlers() {
    struct sigaction action {};
    action.sa_handler = OnSignal;
    sigemptyset(&action.sa_mask);
    action.sa_flags = 0;

    if (sigaction(SIGINT, &action, nullptr) != 0) {
        throw std::runtime_error("failed to register SIGINT handler");
    }
    if (sigaction(SIGTERM, &action, nullptr) != 0) {
        throw std::runtime_error("failed to register SIGTERM handler");
    }
}

std::uint64_t SaturatingMultiply(std::uint64_t value, std::uint64_t multiplier) {
    if (value == 0 || multiplier == 0) {
        return 0;
    }
    if (value > std::numeric_limits<std::uint64_t>::max() / multiplier) {
        return std::numeric_limits<std::uint64_t>::max();
    }
    return value * multiplier;
}

std::uint64_t TimestampUsTo100ns(std::uint64_t timestamp_us) {
    return SaturatingMultiply(timestamp_us, 10);
}

std::uint64_t DefaultFrameDuration100ns(const CameraConfig& config) {
    const auto framerate = std::max<std::uint32_t>(1, config.framerate);
    return std::uint64_t(10'000'000) / framerate;
}

}  // namespace

RuntimeHooks DefaultRuntimeHooks() {
    RuntimeHooks hooks;
    hooks.resolve_aws_credentials = []() { return ResolveAwsCredentials(); };
    hooks.create_kvs_session = [](
                                   const RuntimeConfig& config,
                                   const AwsCredentials& credentials
                               ) { return CreateKvsSession(config, credentials); };
    hooks.create_video_capturer = []() { return CreateVideoCapturer(); };
    return hooks;
}

void Run(const RuntimeConfig& config) {
    Run(config, DefaultRuntimeHooks());
}

void Run(const RuntimeConfig& config, const RuntimeHooks& hooks) {
    if (!hooks.resolve_aws_credentials || !hooks.create_kvs_session || !hooks.create_video_capturer) {
        throw std::runtime_error("runtime hooks are incomplete");
    }

    g_stop_requested.store(false);
    InstallSignalHandlers();

    const auto credentials = hooks.resolve_aws_credentials();
    auto kvs_session = hooks.create_kvs_session(config, credentials);
    auto capturer = hooks.create_video_capturer();

    if (kvs_session == nullptr || capturer == nullptr) {
        throw std::runtime_error("runtime dependencies are not initialized");
    }

    std::optional<std::string> first_error;
    bool ready_emitted = false;
    std::uint64_t previous_timestamp_us = 0;
    const auto default_duration_100ns = DefaultFrameDuration100ns(config.camera);

    try {
        kvs_session->Start();
        capturer->Configure(config.camera);
        capturer->Start();

        while (!g_stop_requested.load()) {
            if (const auto fatal_error = kvs_session->TakeFatalError()) {
                first_error = *fatal_error;
                break;
            }

            auto maybe_frame = capturer->GetFrame(100);
            if (!maybe_frame) {
                if (capturer->GetStatus() == VideoCapturerStatus::kStopped) {
                    break;
                }
                continue;
            }

            auto& frame = *maybe_frame;
            if (frame.bytes.empty()) {
                continue;
            }

            std::uint64_t duration_100ns = default_duration_100ns;
            if (previous_timestamp_us != 0 && frame.timestamp_us > previous_timestamp_us) {
                duration_100ns = TimestampUsTo100ns(frame.timestamp_us - previous_timestamp_us);
            }

            kvs_session->PushH264AccessUnit(
                frame.bytes.data(),
                frame.bytes.size(),
                TimestampUsTo100ns(frame.timestamp_us),
                duration_100ns,
                frame.is_keyframe
            );
            previous_timestamp_us = frame.timestamp_us;

            if (!ready_emitted && frame.is_keyframe) {
                EmitMarker("TXING_KVS_READY", {});
                ready_emitted = true;
            }
        }
    } catch (const std::exception& error) {
        first_error = error.what();
    }

    capturer->Stop();
    kvs_session->Stop();

    if (first_error) {
        throw std::runtime_error(*first_error);
    }
}

}  // namespace txing::board::kvs_master
