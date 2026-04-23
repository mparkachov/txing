#ifndef TXING_BOARD_KVS_MASTER_CONFIG_HPP
#define TXING_BOARD_KVS_MASTER_CONFIG_HPP

#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace txing::board::kvs_master {

using EnvLookup = std::function<std::optional<std::string>(const std::string&)>;

struct CameraConfig {
    std::uint32_t camera = 0;
    std::uint32_t width = 1920;
    std::uint32_t height = 1080;
    std::uint32_t framerate = 30;
    std::uint32_t bitrate = 8'000'000;
    std::uint32_t intra = 30;
};

struct RuntimeConfig {
    std::string region;
    std::string channel_name;
    std::string client_id = "txing-board-kvs-master";
    std::optional<std::string> mcp_webrtc_socket_path;
    CameraConfig camera;
};

struct ParsedCli {
    bool show_help = false;
    RuntimeConfig config;
};

ParsedCli ParseCli(const std::vector<std::string>& arguments, const EnvLookup& lookup_env);
ParsedCli ParseCli(int argc, char** argv, const EnvLookup& lookup_env);
std::string UsageText();
EnvLookup ProcessEnvironmentLookup();

}  // namespace txing::board::kvs_master

#endif
