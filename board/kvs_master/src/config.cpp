#include "txing_board_kvs_master/config.hpp"

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
    const std::string& env_name
) {
    const auto option = options.find(key);
    if (option != options.end()) {
        return option->second;
    }
    return lookup_env(env_name);
}

std::string RequireValue(
    const std::unordered_map<std::string, std::string>& options,
    const std::string& key,
    const EnvLookup& lookup_env,
    const std::string& env_name
) {
    auto value = LookupValue(options, key, lookup_env, env_name);
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

std::unordered_map<std::string, std::string> ParseOptions(const std::vector<std::string>& arguments, bool& show_help) {
    std::unordered_map<std::string, std::string> options;

    for (std::size_t index = 1; index < arguments.size(); ++index) {
        const std::string& argument = arguments[index];
        if (argument == "--help" || argument == "-h") {
            show_help = true;
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
    const auto options = ParseOptions(arguments, parsed.show_help);
    if (parsed.show_help) {
        return parsed;
    }

    parsed.config.region = RequireValue(options, "region", lookup_env, "TXING_BOARD_VIDEO_REGION");
    parsed.config.channel_name = RequireValue(
        options,
        "channel-name",
        lookup_env,
        "TXING_BOARD_VIDEO_CHANNEL_NAME"
    );

    if (const auto client_id = LookupValue(options, "client-id", lookup_env, ""); client_id && !client_id->empty()) {
        parsed.config.client_id = *client_id;
    }

    if (const auto path = LookupValue(options, "rpicam-vid-path", lookup_env, ""); path && !path->empty()) {
        parsed.config.camera.path = *path;
    }

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
        << "Usage: txing-board-kvs-master [options]\n\n"
        << "Options:\n"
        << "  --region <aws-region>                  or TXING_BOARD_VIDEO_REGION\n"
        << "  --channel-name <channel-name>          or TXING_BOARD_VIDEO_CHANNEL_NAME\n"
        << "  --client-id <id>                       default: txing-board-kvs-master\n"
        << "  --rpicam-vid-path <path>               default: /usr/bin/rpicam-vid\n"
        << "  --camera <index>                       default: 0\n"
        << "  --width <pixels>                       default: 1920\n"
        << "  --height <pixels>                      default: 1080\n"
        << "  --framerate <fps>                      default: 30\n"
        << "  --bitrate <bps>                        default: 8000000\n"
        << "  --intra <frames>                       default: 30\n"
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
