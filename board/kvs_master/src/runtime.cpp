#include "txing_board_kvs_master/runtime.hpp"

#include "txing_board_kvs_master/aws_env.hpp"
#include "txing_board_kvs_master/h264.hpp"
#include "txing_board_kvs_master/kvs_session.hpp"
#include "txing_board_kvs_master/rpicam.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <csignal>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
#include <unistd.h>

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

std::uint64_t SaturatingAdd(std::uint64_t left, std::uint64_t right) {
    if (left > std::numeric_limits<std::uint64_t>::max() - right) {
        return std::numeric_limits<std::uint64_t>::max();
    }
    return left + right;
}

}  // namespace

void Run(const RuntimeConfig& config) {
    g_stop_requested.store(false);
    InstallSignalHandlers();

    const auto credentials = ResolveAwsCredentials();
    auto kvs_session = CreateKvsSession(config, credentials);
    kvs_session->Start();

    auto camera = RpicamProcess::Spawn(config.camera);
    AnnexBAccessUnitParser parser;
    const auto frame_duration = std::uint64_t(10'000'000) / std::max<std::uint32_t>(1, config.camera.framerate);
    std::uint64_t presentation_ts = 0;
    std::optional<std::string> first_error;
    std::array<std::uint8_t, 64 * 1024> buffer{};

    while (!g_stop_requested.load()) {
        if (const auto fatal_error = kvs_session->TakeFatalError()) {
            first_error = *fatal_error;
            break;
        }

        const auto bytes_read = read(camera.stdout_fd(), buffer.data(), buffer.size());
        if (bytes_read == 0) {
            const auto exit_status = camera.TryWait();
            if (exit_status && *exit_status == 0) {
                break;
            }
            if (exit_status) {
                first_error = "rpicam-vid exited with status " + std::to_string(*exit_status);
            } else {
                first_error = "rpicam-vid stdout closed unexpectedly";
            }
            break;
        }

        if (bytes_read < 0) {
            if (errno == EINTR) {
                continue;
            }
            first_error = "failed to read rpicam-vid output";
            break;
        }

        const auto access_units = parser.Push(buffer.data(), static_cast<std::size_t>(bytes_read));
        for (const auto& access_unit : access_units) {
            kvs_session->PushH264AccessUnit(
                access_unit.bytes.data(),
                access_unit.bytes.size(),
                presentation_ts,
                frame_duration,
                access_unit.is_keyframe
            );
            presentation_ts = SaturatingAdd(presentation_ts, frame_duration);
        }
    }

    if (!first_error) {
        for (const auto& access_unit : parser.Finish()) {
            kvs_session->PushH264AccessUnit(
                access_unit.bytes.data(),
                access_unit.bytes.size(),
                presentation_ts,
                frame_duration,
                access_unit.is_keyframe
            );
            presentation_ts = SaturatingAdd(presentation_ts, frame_duration);
        }
    }

    try {
        camera.Terminate();
    } catch (const std::exception& error) {
        if (!first_error) {
            first_error = error.what();
        }
    }
    kvs_session->Stop();

    if (first_error) {
        throw std::runtime_error(*first_error);
    }
}

}  // namespace txing::board::kvs_master
