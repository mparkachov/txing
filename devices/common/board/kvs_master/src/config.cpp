#include "kvs_master/config.hpp"

#include "kvs_master/version.hpp"

#include <cstdlib>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

namespace txing::board::kvs_master {
namespace {

std::optional<std::string> LookupValue(
    const std::unordered_map<std::string, std::string>& options,
    const std::string& key,
    const EnvLookup& lookup_env,
    const std::string& env_name,
    const std::string& fallback_env_name = ""
) {
    const auto option = options.find(key);
    if (option != options.end()) {
        return option->second;
    }
    if (!env_name.empty()) {
        if (const auto value = lookup_env(env_name); value && !value->empty()) {
            return value;
        }
    }
    if (!fallback_env_name.empty()) {
        return lookup_env(fallback_env_name);
    }
    return std::nullopt;
}

std::string RequireValue(
    const std::unordered_map<std::string, std::string>& options,
    const std::string& key,
    const EnvLookup& lookup_env,
    const std::string& env_name,
    const std::string& fallback_env_name = ""
) {
    auto value = LookupValue(options, key, lookup_env, env_name, fallback_env_name);
    if (!value || value->empty()) {
        throw std::runtime_error("--" + key + " or " + env_name + " is required");
    }
    return *value;
}

std::uint32_t ParseUnsigned(
    const std::unordered_map<std::string, std::string>& options,
    const std::string& key,
    std::uint32_t default_value
) {
    const auto option = options.find(key);
    if (option == options.end()) {
        return default_value;
    }

    try {
        std::size_t position = 0;
        const auto parsed = std::stoul(option->second, &position, 10);
        if (position != option->second.size()) {
            throw std::runtime_error("trailing characters");
        }
        return static_cast<std::uint32_t>(parsed);
    } catch (const std::exception&) {
        throw std::runtime_error("--" + key + " must be an unsigned integer");
    }
}

bool ParseBoolValue(const std::string& value, const std::string& name) {
    if (value == "1" || value == "true" || value == "TRUE" || value == "yes" || value == "YES" || value == "on" || value == "ON") {
        return true;
    }
    if (value == "0" || value == "false" || value == "FALSE" || value == "no" || value == "NO" || value == "off" || value == "OFF") {
        return false;
    }
    throw std::runtime_error(name + " must be a boolean");
}

bool ParseBool(
    const std::unordered_map<std::string, std::string>& options,
    const std::string& key,
    const EnvLookup& lookup_env,
    const std::string& env_name,
    bool default_value
) {
    if (const auto option = options.find(key); option != options.end()) {
        return ParseBoolValue(option->second, "--" + key);
    }
    if (const auto value = lookup_env(env_name); value && !value->empty()) {
        return ParseBoolValue(*value, env_name);
    }
    return default_value;
}

std::string Trim(std::string value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) {
        return "";
    }
    const auto last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
}

bool HasMavlinkCapability(const EnvLookup& lookup_env) {
    const auto capabilities = lookup_env("TXING_DAEMON_CAPABILITIES");
    if (!capabilities.has_value()) {
        return false;
    }
    std::istringstream input(*capabilities);
    std::string capability;
    while (std::getline(input, capability, ',')) {
        if (Trim(capability) == "mavlink") {
            return true;
        }
    }
    return false;
}

std::unordered_map<std::string, std::string> ParseOptions(
    const std::vector<std::string>& arguments,
    bool& show_help,
    bool& show_version,
    bool& camera_probe
) {
    std::unordered_map<std::string, std::string> options;

    for (std::size_t index = 1; index < arguments.size(); ++index) {
        const std::string& argument = arguments[index];
        if (argument == "--help" || argument == "-h") {
            show_help = true;
            continue;
        }
        if (argument == "--version") {
            show_version = true;
            continue;
        }
        if (argument == "--camera-probe") {
            camera_probe = true;
            continue;
        }
        if (argument.rfind("--", 0) != 0) {
            throw std::runtime_error("unexpected positional argument: " + argument);
        }

        std::string key;
        std::string value;
        const auto equals = argument.find('=');
        if (equals != std::string::npos) {
            key = argument.substr(2, equals - 2);
            value = argument.substr(equals + 1);
        } else {
            key = argument.substr(2);
            if (index + 1 >= arguments.size()) {
                throw std::runtime_error("missing value for --" + key);
            }
            value = arguments[++index];
        }

        if (key.empty()) {
            throw std::runtime_error("empty option name is not allowed");
        }
        options[key] = value;
    }

    return options;
}

}  // namespace

ParsedCli ParseCli(const std::vector<std::string>& arguments, const EnvLookup& lookup_env) {
    if (arguments.empty()) {
        throw std::runtime_error("argv[0] must be present");
    }

    ParsedCli parsed;
    const auto options =
        ParseOptions(arguments, parsed.show_help, parsed.show_version, parsed.camera_probe);
    if (parsed.show_help || parsed.show_version) {
        return parsed;
    }

    parsed.config.worker_name = LookupValue(
        options,
        "worker-name",
        lookup_env,
        "TXING_KVS_WORKER_NAME"
    ).value_or(parsed.config.worker_name);
    if (parsed.config.worker_name.empty()) {
        throw std::runtime_error("--worker-name or TXING_KVS_WORKER_NAME must not be empty");
    }
    parsed.config.client_id = LookupValue(
        options,
        "client-id",
        lookup_env,
        "TXING_KVS_CLIENT_ID"
    ).value_or(parsed.config.worker_name);

    if (const auto socket_path = LookupValue(
            options,
            "board-video-bridge-socket-path",
            lookup_env,
            "TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH"
        );
        socket_path && !socket_path->empty()) {
        parsed.config.board_video_bridge_socket_path = *socket_path;
    }
    if (const auto socket_path = LookupValue(
            options,
            "mavlink-bridge-socket-path",
            lookup_env,
            "TXING_MAVLINK_BRIDGE_SOCKET_PATH"
        );
        socket_path && !socket_path->empty()) {
        parsed.config.mavlink_bridge_socket_path = *socket_path;
    } else if (HasMavlinkCapability(lookup_env)) {
        throw std::runtime_error(
            "--mavlink-bridge-socket-path or TXING_MAVLINK_BRIDGE_SOCKET_PATH "
            "is required when the mavlink capability is enabled"
        );
    }
    if (parsed.config.board_video_bridge_socket_path.has_value() || parsed.camera_probe) {
        parsed.config.region = LookupValue(
            options,
            "region",
            lookup_env,
            "BOARD_VIDEO_REGION",
            "TXING_BOARD_VIDEO_REGION"
        ).value_or("");
        parsed.config.channel_name = LookupValue(
            options,
            "channel-name",
            lookup_env,
            "BOARD_VIDEO_CHANNEL_NAME",
            "TXING_BOARD_VIDEO_CHANNEL_NAME"
        ).value_or("");
    } else {
        parsed.config.region = RequireValue(
            options,
            "region",
            lookup_env,
            "BOARD_VIDEO_REGION",
            "TXING_BOARD_VIDEO_REGION"
        );
        parsed.config.channel_name = RequireValue(
            options,
            "channel-name",
            lookup_env,
            "BOARD_VIDEO_CHANNEL_NAME",
            "TXING_BOARD_VIDEO_CHANNEL_NAME"
        );
    }

    if (const auto socket_path = LookupValue(
            options,
            "mcp-webrtc-socket-path",
            lookup_env,
            "BOARD_MCP_WEBRTC_SOCKET_PATH"
        );
        socket_path && !socket_path->empty()) {
        parsed.config.mcp_webrtc_socket_path = *socket_path;
    }
    // Static worker configuration predates capability-aware bridge config.
    // Preserve its explicit opt-in behavior without enabling MCP for profiles
    // that do not provide an MCP socket.
    parsed.config.mcp_data_channel_enabled = parsed.config.mcp_webrtc_socket_path.has_value();
    parsed.config.prefer_ipv6 = ParseBool(
        options,
        "prefer-ipv6",
        lookup_env,
        "KVS_DUALSTACK_ENDPOINTS",
        parsed.config.prefer_ipv6
    );
    parsed.config.disable_ipv4_turn = ParseBool(
        options,
        "disable-ipv4-turn",
        lookup_env,
        "KVS_DISABLE_IPV4_TURN",
        parsed.config.disable_ipv4_turn
    );

    parsed.config.camera.camera = ParseUnsigned(options, "camera", parsed.config.camera.camera);
    parsed.config.camera.width = ParseUnsigned(options, "width", parsed.config.camera.width);
    parsed.config.camera.height = ParseUnsigned(options, "height", parsed.config.camera.height);
    parsed.config.camera.framerate = ParseUnsigned(options, "framerate", parsed.config.camera.framerate);
    parsed.config.camera.bitrate = ParseUnsigned(options, "bitrate", parsed.config.camera.bitrate);
    parsed.config.camera.intra = ParseUnsigned(options, "intra", parsed.config.camera.intra);

    return parsed;
}

ParsedCli ParseCli(int argc, char** argv, const EnvLookup& lookup_env) {
    std::vector<std::string> arguments;
    arguments.reserve(static_cast<std::size_t>(argc));
    for (int index = 0; index < argc; ++index) {
        arguments.emplace_back(argv[index]);
    }
    return ParseCli(arguments, lookup_env);
}

std::string UsageText() {
    std::ostringstream usage;
    usage
        << TXING_BOARD_KVS_MASTER_BINARY_NAME " [options]\n\n"
        << "Options:\n"
        << "  --region <aws-region>                  or BOARD_VIDEO_REGION\n"
        << "  --channel-name <channel-name>          or BOARD_VIDEO_CHANNEL_NAME\n"
        << "  --worker-name <name>                   or TXING_KVS_WORKER_NAME\n"
        << "  --client-id <id>                       or TXING_KVS_CLIENT_ID; default: worker name\n"
        << "  --mcp-webrtc-socket-path <path>        or BOARD_MCP_WEBRTC_SOCKET_PATH\n"
        << "  --board-video-bridge-socket-path <path> or TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH\n"
        << "  --mavlink-bridge-socket-path <path>   or TXING_MAVLINK_BRIDGE_SOCKET_PATH\n"
        << "  --prefer-ipv6 <bool>                   default: true\n"
        << "  --disable-ipv4-turn <bool>             default: false\n"
        << "  --camera-probe                         capture-only probe: no KVS session,\n"
        << "                                         exercises camera access and encoding\n"
        << "  --camera <index>                       default: 0\n"
        << "  --width <pixels>                       default: 1920\n"
        << "  --height <pixels>                      default: 1080\n"
        << "  --framerate <fps>                      default: 30\n"
        << "  --bitrate <bps>                        default: 8000000\n"
        << "  --intra <frames>                       default: 30\n"
        << "  --version\n"
        << "  --help\n";
    return usage.str();
}

EnvLookup ProcessEnvironmentLookup() {
    return [](const std::string& key) -> std::optional<std::string> {
        if (key.empty()) {
            return std::nullopt;
        }
        const char* value = std::getenv(key.c_str());
        if (value == nullptr) {
            return std::nullopt;
        }
        return std::string(value);
    };
}

}  // namespace txing::board::kvs_master
