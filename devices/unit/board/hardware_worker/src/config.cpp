#include "hardware_worker/config.hpp"

#include "hardware_worker/version.hpp"

#include <cstdlib>
#include <cmath>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

namespace txing::unit::hardware_worker {
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
    if (!env_name.empty()) {
        if (const auto value = lookup_env(env_name); value && !value->empty()) {
            return value;
        }
    }
    return std::nullopt;
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
    if (const auto value = LookupValue(options, key, lookup_env, env_name); value) {
        return ParseBoolValue(*value, options.find(key) != options.end() ? "--" + key : env_name);
    }
    return default_value;
}

std::int32_t ParseI32Value(const std::string& value, const std::string& name) {
    try {
        std::size_t position = 0;
        const auto parsed = std::stol(value, &position, 10);
        if (position != value.size()) {
            throw std::runtime_error("trailing characters");
        }
        return static_cast<std::int32_t>(parsed);
    } catch (const std::exception&) {
        throw std::runtime_error(name + " must be a signed integer");
    }
}

std::uint32_t ParseU32Value(const std::string& value, const std::string& name) {
    try {
        std::size_t position = 0;
        const auto parsed = std::stoul(value, &position, 10);
        if (position != value.size()) {
            throw std::runtime_error("trailing characters");
        }
        return static_cast<std::uint32_t>(parsed);
    } catch (const std::exception&) {
        throw std::runtime_error(name + " must be an unsigned integer");
    }
}

std::uint64_t ParseU64Value(const std::string& value, const std::string& name) {
    try {
        std::size_t position = 0;
        const auto parsed = std::stoull(value, &position, 10);
        if (position != value.size()) {
            throw std::runtime_error("trailing characters");
        }
        return static_cast<std::uint64_t>(parsed);
    } catch (const std::exception&) {
        throw std::runtime_error(name + " must be an unsigned integer");
    }
}

double ParseDoubleValue(const std::string& value, const std::string& name) {
    try {
        std::size_t position = 0;
        const auto parsed = std::stod(value, &position);
        if (position != value.size()) {
            throw std::runtime_error("trailing characters");
        }
        return parsed;
    } catch (const std::exception&) {
        throw std::runtime_error(name + " must be a number");
    }
}

template <typename T, typename ParseFn>
T ParseOptional(
    const std::unordered_map<std::string, std::string>& options,
    const std::string& key,
    const EnvLookup& lookup_env,
    const std::string& env_name,
    T default_value,
    ParseFn parse
) {
    if (const auto value = LookupValue(options, key, lookup_env, env_name); value) {
        return parse(*value, options.find(key) != options.end() ? "--" + key : env_name);
    }
    return default_value;
}

std::unordered_map<std::string, std::string> ParseOptions(
    const std::vector<std::string>& arguments,
    bool& show_help,
    bool& show_version
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
    const auto options = ParseOptions(arguments, parsed.show_help, parsed.show_version);
    if (parsed.show_help || parsed.show_version) {
        return parsed;
    }

    if (const auto socket_path = LookupValue(
            options,
            "socket-path",
            lookup_env,
            "TXING_HARDWARE_WORKER_SOCKET_PATH"
        );
        socket_path && !socket_path->empty()) {
        parsed.config.socket_path = *socket_path;
    }

    auto& motor = parsed.config.motor;
    motor.enabled = ParseBool(options, "motor-enabled", lookup_env, "TXING_MOTOR_ENABLED", motor.enabled);
    motor.left_inverted = ParseBool(options, "motor-left-inverted", lookup_env, "TXING_MOTOR_LEFT_INVERTED", motor.left_inverted);
    motor.right_inverted = ParseBool(options, "motor-right-inverted", lookup_env, "TXING_MOTOR_RIGHT_INVERTED", motor.right_inverted);
    motor.pwm_sysfs_root = LookupValue(options, "motor-pwm-sysfs-root", lookup_env, "TXING_MOTOR_PWM_SYSFS_ROOT").value_or(motor.pwm_sysfs_root);
    motor.raw_max_speed = ParseOptional(options, "motor-raw-max-speed", lookup_env, "TXING_MOTOR_RAW_MAX_SPEED", motor.raw_max_speed, ParseI32Value);
    motor.cmd_raw_min_speed = ParseOptional(options, "motor-cmd-raw-min-speed", lookup_env, "TXING_MOTOR_CMD_RAW_MIN_SPEED", motor.cmd_raw_min_speed, ParseI32Value);
    motor.cmd_raw_max_speed = ParseOptional(options, "motor-cmd-raw-max-speed", lookup_env, "TXING_MOTOR_CMD_RAW_MAX_SPEED", motor.cmd_raw_max_speed, ParseI32Value);
    motor.pwm_hz = ParseOptional(options, "motor-pwm-hz", lookup_env, "TXING_MOTOR_PWM_HZ", motor.pwm_hz, ParseU64Value);
    motor.pwm_chip = ParseOptional(options, "motor-pwm-chip", lookup_env, "TXING_MOTOR_PWM_CHIP", motor.pwm_chip, ParseU32Value);
    motor.gpio_chip = ParseOptional(options, "motor-gpio-chip", lookup_env, "TXING_MOTOR_GPIO_CHIP", motor.gpio_chip, ParseU32Value);
    motor.left_pwm_channel = ParseOptional(options, "motor-left-pwm-channel", lookup_env, "TXING_MOTOR_LEFT_PWM_CHANNEL", motor.left_pwm_channel, ParseU32Value);
    motor.right_pwm_channel = ParseOptional(options, "motor-right-pwm-channel", lookup_env, "TXING_MOTOR_RIGHT_PWM_CHANNEL", motor.right_pwm_channel, ParseU32Value);
    motor.left_dir_gpio = ParseOptional(options, "motor-left-dir-gpio", lookup_env, "TXING_MOTOR_LEFT_DIR_GPIO", motor.left_dir_gpio, ParseU32Value);
    motor.right_dir_gpio = ParseOptional(options, "motor-right-dir-gpio", lookup_env, "TXING_MOTOR_RIGHT_DIR_GPIO", motor.right_dir_gpio, ParseU32Value);
    motor.track_width_m = ParseOptional(options, "motor-track-width-m", lookup_env, "TXING_MOTOR_TRACK_WIDTH_M", motor.track_width_m, ParseDoubleValue);
    motor.max_wheel_linear_speed_mps = ParseOptional(options, "motor-max-wheel-linear-speed-mps", lookup_env, "TXING_MOTOR_MAX_WHEEL_LINEAR_SPEED_MPS", motor.max_wheel_linear_speed_mps, ParseDoubleValue);
    motor.left_track_power_percent = ParseOptional(options, "motor-left-track-power-percent", lookup_env, "TXING_MOTOR_LEFT_TRACK_POWER_PERCENT", motor.left_track_power_percent, ParseDoubleValue);
    motor.right_track_power_percent = ParseOptional(options, "motor-right-track-power-percent", lookup_env, "TXING_MOTOR_RIGHT_TRACK_POWER_PERCENT", motor.right_track_power_percent, ParseDoubleValue);
    motor.watchdog_timeout_ms = ParseOptional(options, "motor-watchdog-timeout-ms", lookup_env, "TXING_MOTOR_WATCHDOG_TIMEOUT_MS", motor.watchdog_timeout_ms, ParseU64Value);
    ValidateMotorConfig(motor);
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
        << "Usage: txing-unit-hardware-worker [options]\n\n"
        << "Options:\n"
        << "  --socket-path <path>                  or TXING_HARDWARE_WORKER_SOCKET_PATH\n"
        << "  --motor-enabled <bool>                or TXING_MOTOR_ENABLED\n"
        << "  --motor-pwm-sysfs-root <path>         or TXING_MOTOR_PWM_SYSFS_ROOT\n"
        << "  --motor-raw-max-speed <value>         or TXING_MOTOR_RAW_MAX_SPEED\n"
        << "  --motor-cmd-raw-min-speed <value>     or TXING_MOTOR_CMD_RAW_MIN_SPEED\n"
        << "  --motor-cmd-raw-max-speed <value>     or TXING_MOTOR_CMD_RAW_MAX_SPEED\n"
        << "  --motor-pwm-hz <hz>                   or TXING_MOTOR_PWM_HZ\n"
        << "  --motor-pwm-chip <chip>               or TXING_MOTOR_PWM_CHIP\n"
        << "  --motor-left-pwm-channel <channel>    or TXING_MOTOR_LEFT_PWM_CHANNEL\n"
        << "  --motor-right-pwm-channel <channel>   or TXING_MOTOR_RIGHT_PWM_CHANNEL\n"
        << "  --motor-gpio-chip <chip>              or TXING_MOTOR_GPIO_CHIP\n"
        << "  --motor-left-dir-gpio <line>          or TXING_MOTOR_LEFT_DIR_GPIO\n"
        << "  --motor-right-dir-gpio <line>         or TXING_MOTOR_RIGHT_DIR_GPIO\n"
        << "  --motor-left-inverted <bool>          or TXING_MOTOR_LEFT_INVERTED\n"
        << "  --motor-right-inverted <bool>         or TXING_MOTOR_RIGHT_INVERTED\n"
        << "  --motor-track-width-m <meters>        or TXING_MOTOR_TRACK_WIDTH_M\n"
        << "  --motor-max-wheel-linear-speed-mps <m/s> or TXING_MOTOR_MAX_WHEEL_LINEAR_SPEED_MPS\n"
        << "  --motor-left-track-power-percent <percent> or TXING_MOTOR_LEFT_TRACK_POWER_PERCENT\n"
        << "  --motor-right-track-power-percent <percent> or TXING_MOTOR_RIGHT_TRACK_POWER_PERCENT\n"
        << "  --motor-watchdog-timeout-ms <ms>      or TXING_MOTOR_WATCHDOG_TIMEOUT_MS\n"
        << "  --version\n"
        << "  --help\n";
    return usage.str();
}

EnvLookup ProcessEnvironmentLookup() {
    return [](const std::string& name) -> std::optional<std::string> {
        const char* value = std::getenv(name.c_str());
        if (value == nullptr) {
            return std::nullopt;
        }
        return std::string(value);
    };
}

void ValidateMotorConfig(const MotorConfig& config) {
    if (config.raw_max_speed <= 0) {
        throw std::runtime_error("motor-raw-max-speed must be positive");
    }
    if (config.cmd_raw_min_speed < 0) {
        throw std::runtime_error("motor-cmd-raw-min-speed must be non-negative");
    }
    if (config.cmd_raw_max_speed <= 0) {
        throw std::runtime_error("motor-cmd-raw-max-speed must be positive");
    }
    if (config.cmd_raw_min_speed >= config.cmd_raw_max_speed) {
        throw std::runtime_error("motor-cmd-raw-min-speed must be less than motor-cmd-raw-max-speed");
    }
    if (config.cmd_raw_max_speed > config.raw_max_speed) {
        throw std::runtime_error("motor-cmd-raw-max-speed must be less than or equal to motor-raw-max-speed");
    }
    if (config.pwm_hz == 0) {
        throw std::runtime_error("motor-pwm-hz must be positive");
    }
    if (config.left_pwm_channel == config.right_pwm_channel) {
        throw std::runtime_error("left and right motor PWM channels must differ");
    }
    if (config.left_dir_gpio == config.right_dir_gpio) {
        throw std::runtime_error("left and right motor direction GPIOs must differ");
    }
    if (config.track_width_m <= 0.0 || !std::isfinite(config.track_width_m)) {
        throw std::runtime_error("motor-track-width-m must be a positive finite number");
    }
    if (config.max_wheel_linear_speed_mps <= 0.0 || !std::isfinite(config.max_wheel_linear_speed_mps)) {
        throw std::runtime_error("motor-max-wheel-linear-speed-mps must be a positive finite number");
    }
    if (config.left_track_power_percent <= 0.0 || config.left_track_power_percent > 100.0 || !std::isfinite(config.left_track_power_percent)) {
        throw std::runtime_error("motor-left-track-power-percent must be a finite percentage in (0, 100]");
    }
    if (config.right_track_power_percent <= 0.0 || config.right_track_power_percent > 100.0 || !std::isfinite(config.right_track_power_percent)) {
        throw std::runtime_error("motor-right-track-power-percent must be a finite percentage in (0, 100]");
    }
    if (config.watchdog_timeout_ms == 0) {
        throw std::runtime_error("motor-watchdog-timeout-ms must be positive");
    }
}

}  // namespace txing::unit::hardware_worker
