#include "kvs_master/runtime.hpp"

#include "kvs_master/aws_env.hpp"
#include "kvs_master/kvs_session.hpp"
#include "kvs_master/markers.hpp"
#include "kvs_master/video_capturer.hpp"

#include <algorithm>
#include <atomic>
#include <csignal>
#include <cstdlib>
#include <cstdint>
#include <filesystem>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>

namespace txing::board::kvs_master {
namespace {

std::atomic_bool g_stop_requested = false;
constexpr char kSslCertFileEnvVar[] = "SSL_CERT_FILE";
constexpr char kKvsCaCertPathEnvVar[] = "AWS_KVS_CACERT_PATH";

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

std::optional<std::string> NonEmptyEnv(const char* name) {
    const char* value = std::getenv(name);
    if (value == nullptr || *value == '\0') {
        return std::nullopt;
    }
    return std::string(value);
}

std::optional<std::string> ExistingFile(const char* path) {
    if (path == nullptr || *path == '\0') {
        return std::nullopt;
    }

    std::error_code error;
    const auto file_path = std::filesystem::path(path);
    if (std::filesystem::exists(file_path, error) && !error) {
        return file_path.string();
    }
    return std::nullopt;
}

std::optional<std::string> DiscoverCaCertPath() {
    if (const auto from_kvs_env = NonEmptyEnv(kKvsCaCertPathEnvVar); from_kvs_env) {
        return from_kvs_env;
    }
    if (const auto from_ssl_env = NonEmptyEnv(kSslCertFileEnvVar); from_ssl_env) {
        return from_ssl_env;
    }

    static constexpr const char* kCandidatePaths[] = {
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/ssl/cert.pem",
    };

    for (const auto* candidate : kCandidatePaths) {
        if (const auto discovered = ExistingFile(candidate); discovered) {
            return discovered;
        }
    }

    return std::nullopt;
}

void SetEnvIfAbsent(const char* name, const std::string& value) {
    if (NonEmptyEnv(name)) {
        return;
    }
#if defined(_WIN32)
    _putenv_s(name, value.c_str());
#else
    setenv(name, value.c_str(), 0);
#endif
}

void ConfigureTlsCaEnvironment() {
    if (const auto ca_cert_path = DiscoverCaCertPath(); ca_cert_path) {
        SetEnvIfAbsent(kSslCertFileEnvVar, *ca_cert_path);
        SetEnvIfAbsent(kKvsCaCertPathEnvVar, *ca_cert_path);
    }
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
    ConfigureTlsCaEnvironment();

    const auto credentials = hooks.resolve_aws_credentials();
    auto kvs_session = hooks.create_kvs_session(config, credentials);
    auto capturer = hooks.create_video_capturer();

    if (kvs_session == nullptr || capturer == nullptr) {
        throw std::runtime_error("runtime dependencies are not initialized");
    }

    std::optional<std::string> first_error;
    bool ready_emitted = false;
    std::uint64_t previous_timestamp_us = 0;
    std::uint64_t presentation_timestamp_100ns = 0;
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
                presentation_timestamp_100ns = SaturatingAdd(presentation_timestamp_100ns, duration_100ns);
            } else if (previous_timestamp_us != 0) {
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
