#ifndef TXING_UNIT_HARDWARE_WORKER_CONFIG_HPP
#define TXING_UNIT_HARDWARE_WORKER_CONFIG_HPP

#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace txing::unit::hardware_worker {

using EnvLookup = std::function<std::optional<std::string>(const std::string&)>;

struct MotorConfig {
    bool enabled = true;
    std::string pwm_sysfs_root = "/sys/class/pwm";
    std::int32_t raw_max_speed = 480;
    std::int32_t cmd_raw_min_speed = 50;
    std::int32_t cmd_raw_max_speed = 250;
    std::uint64_t pwm_hz = 20'000;
    std::uint32_t pwm_chip = 0;
    std::uint32_t gpio_chip = 0;
    std::uint32_t left_pwm_channel = 0;
    std::uint32_t right_pwm_channel = 1;
    std::uint32_t left_dir_gpio = 5;
    std::uint32_t right_dir_gpio = 6;
    bool left_inverted = false;
    bool right_inverted = false;
    double track_width_m = 0.28;
    double max_wheel_linear_speed_mps = 0.50;
    std::uint64_t watchdog_timeout_ms = 5'000;
};

struct RuntimeConfig {
    std::string socket_path = "/run/txing-unit-hardware-worker/unit-hardware.sock";
    MotorConfig motor;
};

struct ParsedCli {
    bool show_help = false;
    bool show_version = false;
    RuntimeConfig config;
};

ParsedCli ParseCli(const std::vector<std::string>& arguments, const EnvLookup& lookup_env);
ParsedCli ParseCli(int argc, char** argv, const EnvLookup& lookup_env);
std::string UsageText();
EnvLookup ProcessEnvironmentLookup();
void ValidateMotorConfig(const MotorConfig& config);

}  // namespace txing::unit::hardware_worker

#endif
