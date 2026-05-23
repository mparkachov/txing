#include "kvs_master/runtime.hpp"

#include "kvs_master/aws_env.hpp"
#include "kvs_master/kvs_session.hpp"
#include "kvs_master/markers.hpp"
#include "kvs_master/version.hpp"
#include "kvs_master/video_capturer.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <thread>

namespace txing::board::kvs_master {
namespace {

std::atomic_bool g_stop_requested = false;
constexpr auto kCredentialRefreshMargin = std::chrono::minutes(5);
constexpr auto kCredentialRefreshMinDelay = std::chrono::seconds(30);
constexpr auto kBridgeRetryInitialDelay = std::chrono::seconds(1);
constexpr auto kBridgeRetryMaxDelay = std::chrono::seconds(30);

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

std::uint64_t SaturatingAdd(std::uint64_t left, std::uint64_t right) {
    if (left > std::numeric_limits<std::uint64_t>::max() - right) {
        return std::numeric_limits<std::uint64_t>::max();
    }
    return left + right;
}

std::uint64_t DefaultFrameDuration100ns(const CameraConfig& config) {
    const auto framerate = std::max<std::uint32_t>(1, config.framerate);
    return std::uint64_t(10'000'000) / framerate;
}

std::chrono::system_clock::time_point CredentialRefreshAt(
    std::chrono::system_clock::time_point expires_at
) {
    const auto now = std::chrono::system_clock::now();
    if (expires_at > now + kCredentialRefreshMargin + kCredentialRefreshMinDelay) {
        return expires_at - kCredentialRefreshMargin;
    }
    return now + kCredentialRefreshMinDelay;
}

void TryReportVideoState(
    BoardVideoBridgeClient* bridge_client,
    BridgeVideoState state,
    std::uint32_t viewer_count,
    const std::string& error
) noexcept {
    if (bridge_client == nullptr) {
        return;
    }
    try {
        bridge_client->ReportVideoState(state, viewer_count, error);
    } catch (const std::exception& report_error) {
        std::fprintf(
            stderr,
            "WARN runtime: failed to report video state to board video bridge: %s\n",
            report_error.what()
        );
    }
}

void SleepUntilStopped(std::chrono::milliseconds duration) {
    const auto deadline = std::chrono::steady_clock::now() + duration;
    while (!g_stop_requested.load() && std::chrono::steady_clock::now() < deadline) {
        const auto remaining = deadline - std::chrono::steady_clock::now();
        std::this_thread::sleep_for(std::min<std::chrono::milliseconds>(
            std::chrono::duration_cast<std::chrono::milliseconds>(remaining),
            std::chrono::milliseconds(200)
        ));
    }
}

BridgeWorkerConfig GetWorkerConfigWithRetry(BoardVideoBridgeClient& bridge_client) {
    auto delay = kBridgeRetryInitialDelay;
    while (!g_stop_requested.load()) {
        try {
            return bridge_client.GetWorkerConfig(
                "txing-unit-kvs-master",
                std::string(kTxingUnitKvsMasterVersion)
            );
        } catch (const std::exception& error) {
            std::fprintf(
                stderr,
                "WARN runtime: board video bridge config unavailable: %s\n",
                error.what()
            );
            SleepUntilStopped(std::chrono::duration_cast<std::chrono::milliseconds>(delay));
            delay = std::min(delay * 2, kBridgeRetryMaxDelay);
        }
    }
    throw std::runtime_error("stopped before board video bridge config was available");
}

void SetEnvironmentFlag(const char* name, bool enabled, const char* enabled_value) {
#if defined(_WIN32)
    _putenv_s(name, enabled ? enabled_value : "");
#else
    if (enabled) {
        setenv(name, enabled_value, 1);
    } else {
        unsetenv(name);
    }
#endif
}

void ConfigureKvsNetworkEnvironment(const RuntimeConfig& config) {
    SetEnvironmentFlag("KVS_DUALSTACK_ENDPOINTS", config.prefer_ipv6, "ON");
    SetEnvironmentFlag("AWS_USE_DUALSTACK_ENDPOINT", config.prefer_ipv6, "true");
    SetEnvironmentFlag("KVS_DISABLE_IPV4_TURN", config.disable_ipv4_turn, "ON");
}

}  // namespace

RuntimeHooks DefaultRuntimeHooks() {
    RuntimeHooks hooks;
    hooks.resolve_aws_credentials = []() { return ResolveAwsCredentials(); };
    hooks.create_bridge_client = [](const std::string& socket_path) {
        return CreateBoardVideoBridgeClient(socket_path);
    };
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
    if (!hooks.resolve_aws_credentials || !hooks.create_bridge_client || !hooks.create_kvs_session || !hooks.create_video_capturer) {
        throw std::runtime_error("runtime hooks are incomplete");
    }

    g_stop_requested.store(false);
    InstallSignalHandlers();

    RuntimeConfig effective_config = config;
    std::unique_ptr<BoardVideoBridgeClient> bridge_client;
    AwsCredentials credentials;
    std::optional<std::chrono::system_clock::time_point> credential_refresh_at;
    if (config.board_video_bridge_socket_path.has_value()) {
        bridge_client = hooks.create_bridge_client(*config.board_video_bridge_socket_path);
        if (bridge_client == nullptr) {
            throw std::runtime_error("board video bridge client is not initialized");
        }
        auto worker_config = GetWorkerConfigWithRetry(*bridge_client);
        worker_config.runtime_config.camera = config.camera;
        worker_config.runtime_config.board_video_bridge_socket_path = config.board_video_bridge_socket_path;
        effective_config = worker_config.runtime_config;
        credentials = worker_config.credentials.credentials;
        credential_refresh_at = CredentialRefreshAt(worker_config.credentials.expires_at);
    } else {
        credentials = hooks.resolve_aws_credentials();
    }

    ConfigureKvsNetworkEnvironment(effective_config);
    auto kvs_session = hooks.create_kvs_session(effective_config, credentials);
    auto capturer = hooks.create_video_capturer();

    if (kvs_session == nullptr || capturer == nullptr) {
        throw std::runtime_error("runtime dependencies are not initialized");
    }

    std::optional<std::string> first_error;
    bool ready_emitted = false;
    std::uint64_t previous_timestamp_us = 0;
    bool have_previous_timestamp = false;
    std::uint64_t presentation_timestamp_100ns = 0;
    const auto default_duration_100ns = DefaultFrameDuration100ns(config.camera);

    try {
        TryReportVideoState(bridge_client.get(), BridgeVideoState::kStarting, 0, "");
        kvs_session->Start();
        capturer->Configure(effective_config.camera);
        capturer->Start();

        while (!g_stop_requested.load()) {
            if (const auto fatal_error = kvs_session->TakeFatalError()) {
                first_error = *fatal_error;
                break;
            }
            if (
                bridge_client != nullptr &&
                credential_refresh_at.has_value() &&
                std::chrono::system_clock::now() >= *credential_refresh_at
            ) {
                try {
                    const auto refreshed = bridge_client->RefreshCredentials();
                    credentials = refreshed.credentials;
                    credential_refresh_at = CredentialRefreshAt(refreshed.expires_at);
                    kvs_session->Stop();
                    kvs_session = hooks.create_kvs_session(effective_config, credentials);
                    if (kvs_session == nullptr) {
                        throw std::runtime_error("KVS session is not initialized after credential refresh");
                    }
                    kvs_session->Start();
                    ready_emitted = false;
                    TryReportVideoState(bridge_client.get(), BridgeVideoState::kStarting, 0, "");
                } catch (const std::exception& refresh_error) {
                    std::fprintf(
                        stderr,
                        "WARN runtime: failed to refresh board video bridge credentials: %s\n",
                        refresh_error.what()
                    );
                    credential_refresh_at = std::chrono::system_clock::now() + kCredentialRefreshMinDelay;
                }
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
            if (have_previous_timestamp && frame.timestamp_us > previous_timestamp_us) {
                duration_100ns = TimestampUsTo100ns(frame.timestamp_us - previous_timestamp_us);
                presentation_timestamp_100ns = SaturatingAdd(presentation_timestamp_100ns, duration_100ns);
            } else if (have_previous_timestamp) {
                presentation_timestamp_100ns = SaturatingAdd(presentation_timestamp_100ns, duration_100ns);
            }

            kvs_session->PushH264AccessUnit(
                frame.bytes.data(),
                frame.bytes.size(),
                presentation_timestamp_100ns,
                duration_100ns,
                frame.is_keyframe
            );
            previous_timestamp_us = frame.timestamp_us;
            have_previous_timestamp = true;

            if (!ready_emitted && frame.is_keyframe) {
                EmitMarker(
                    "TXING_KVS_READY",
                    {{"version", std::string(kTxingUnitKvsMasterVersion)}}
                );
                TryReportVideoState(bridge_client.get(), BridgeVideoState::kReady, 0, "");
                ready_emitted = true;
            }
        }
    } catch (const std::exception& error) {
        first_error = error.what();
    }

    capturer->Stop();
    kvs_session->Stop();

    if (first_error) {
        TryReportVideoState(bridge_client.get(), BridgeVideoState::kError, 0, *first_error);
        throw std::runtime_error(*first_error);
    }
}

}  // namespace txing::board::kvs_master
