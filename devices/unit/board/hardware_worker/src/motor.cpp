#include "hardware_worker/motor.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <thread>

#if defined(__linux__)
#include <fcntl.h>
#include <linux/gpio.h>
#include <sys/ioctl.h>
#include <unistd.h>
#endif

namespace txing::unit::hardware_worker {
namespace {

std::int32_t ClampI32(std::int32_t value, std::int32_t low, std::int32_t high) {
    return std::max(low, std::min(value, high));
}

std::int32_t ApplyTrackPowerPercent(double speed, double track_power_percent) {
    return static_cast<std::int32_t>(std::llround(speed * track_power_percent));
}

void WriteText(const std::filesystem::path& path, const std::string& value) {
    std::ofstream stream(path);
    if (!stream) {
        throw std::runtime_error("open " + path.string());
    }
    stream << value;
    if (!stream) {
        throw std::runtime_error("write " + path.string());
    }
}

template <typename T>
void WriteInt(const std::filesystem::path& path, T value) {
    WriteText(path, std::to_string(value) + "\n");
}

void WaitForDirectory(const std::filesystem::path& path, std::chrono::milliseconds timeout) {
    const auto started = std::chrono::steady_clock::now();
    while (std::chrono::steady_clock::now() - started < timeout) {
        if (std::filesystem::is_directory(path)) {
            return;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    throw std::runtime_error("path did not appear after export: " + path.string());
}

std::uint32_t ChannelNumberFromPath(const std::filesystem::path& path) {
    const auto name = path.filename().string();
    constexpr const char* prefix = "pwm";
    if (name.rfind(prefix, 0) != 0) {
        throw std::runtime_error("invalid PWM channel path " + path.string());
    }
    return static_cast<std::uint32_t>(std::stoul(name.substr(3)));
}

class SysfsPwmChannel {
public:
    SysfsPwmChannel(const std::string& root, std::uint32_t chip, std::uint32_t channel, std::uint64_t frequency_hz)
        : chip_path_(std::filesystem::path(root) / ("pwmchip" + std::to_string(chip))),
          channel_path_(chip_path_ / ("pwm" + std::to_string(channel))),
          period_ns_(static_cast<std::uint64_t>(std::llround(1'000'000'000.0 / static_cast<double>(frequency_hz)))) {
        if (!std::filesystem::is_directory(chip_path_)) {
            throw std::runtime_error("PWM chip path does not exist: " + chip_path_.string());
        }
        if (!std::filesystem::is_directory(channel_path_)) {
            WriteInt(chip_path_ / "export", channel);
            owns_channel_ = true;
            WaitForDirectory(channel_path_, std::chrono::seconds(1));
        }
        DisableNoThrow();
        SetPeriodNs(period_ns_);
        SetDutyCycleNs(0);
        Enable();
    }

    ~SysfsPwmChannel() {
        CloseNoThrow();
    }

    void SetDutyCycleNs(std::uint64_t value) {
        WriteInt(channel_path_ / "duty_cycle", std::min(value, period_ns_));
    }

    std::uint64_t PeriodNs() const {
        return period_ns_;
    }

    void Close() {
        if (closed_) {
            return;
        }
        closed_ = true;
        SetDutyCycleNs(0);
        DisableNoThrow();
        if (owns_channel_) {
            WriteInt(chip_path_ / "unexport", ChannelNumberFromPath(channel_path_));
        }
    }

private:
    void SetPeriodNs(std::uint64_t value) {
        WriteInt(channel_path_ / "period", value);
    }

    void Enable() {
        WriteInt(channel_path_ / "enable", 1);
    }

    void DisableNoThrow() {
        try {
            WriteInt(channel_path_ / "enable", 0);
        } catch (const std::exception&) {
        }
    }

    void CloseNoThrow() {
        try {
            Close();
        } catch (const std::exception&) {
        }
    }

    std::filesystem::path chip_path_;
    std::filesystem::path channel_path_;
    std::uint64_t period_ns_;
    bool owns_channel_ = false;
    bool closed_ = false;
};

class GpioOutputPin {
public:
    GpioOutputPin(std::uint32_t chip, std::uint32_t pin) : chip_(chip), pin_(pin) {
#if defined(__linux__)
        const auto chip_path = "/dev/gpiochip" + std::to_string(chip);
        chip_fd_ = open(chip_path.c_str(), O_RDONLY | O_CLOEXEC);
        if (chip_fd_ < 0) {
            throw std::runtime_error("open " + chip_path);
        }

        gpiohandle_request request{};
        request.lineoffsets[0] = pin;
        request.flags = GPIOHANDLE_REQUEST_OUTPUT;
        request.default_values[0] = 0;
        request.lines = 1;
        const std::string consumer = "txing-unit-hardware-worker";
        std::copy(consumer.begin(), consumer.end(), request.consumer_label);
        if (ioctl(chip_fd_, GPIO_GET_LINEHANDLE_IOCTL, &request) < 0) {
            close(chip_fd_);
            chip_fd_ = -1;
            throw std::runtime_error("request GPIO direction pin " + std::to_string(pin) + " on gpiochip" + std::to_string(chip));
        }
        line_fd_ = request.fd;
#else
        (void)chip_;
        (void)pin_;
        throw std::runtime_error("GPIO direction pins require Linux GPIO character devices");
#endif
    }

    ~GpioOutputPin() {
        CloseNoThrow();
    }

    void SetValue(bool high) {
#if defined(__linux__)
        gpiohandle_data data{};
        data.values[0] = high ? 1 : 0;
        if (ioctl(line_fd_, GPIOHANDLE_SET_LINE_VALUES_IOCTL, &data) < 0) {
            throw std::runtime_error("set GPIO direction pin " + std::to_string(pin_) + " on gpiochip" + std::to_string(chip_));
        }
#else
        (void)high;
#endif
    }

private:
    void CloseNoThrow() {
#if defined(__linux__)
        if (line_fd_ >= 0) {
            try {
                SetValue(false);
            } catch (const std::exception&) {
            }
            close(line_fd_);
            line_fd_ = -1;
        }
        if (chip_fd_ >= 0) {
            close(chip_fd_);
            chip_fd_ = -1;
        }
#endif
    }

    std::uint32_t chip_;
    std::uint32_t pin_;
#if defined(__linux__)
    int chip_fd_ = -1;
    int line_fd_ = -1;
#endif
};

void ApplyMotorSide(
    std::int32_t raw_speed,
    std::int32_t raw_max_speed,
    bool inverted,
    SysfsPwmChannel& pwm,
    GpioOutputPin& direction
) {
    const auto clamped = ClampI32(raw_speed, -raw_max_speed, raw_max_speed);
    const auto effective = inverted ? -clamped : clamped;
    direction.SetValue(effective < 0);
    const auto duty = static_cast<std::uint64_t>(
        std::llround((static_cast<double>(std::abs(effective)) / static_cast<double>(raw_max_speed)) * static_cast<double>(pwm.PeriodNs()))
    );
    pwm.SetDutyCycleNs(duty);
}

}  // namespace

void MotorDriver::Close() {
    SetSpeeds(0, 0);
}

void NoopMotorDriver::SetSpeeds(std::int32_t, std::int32_t) {}

class SysfsMotorDriver::Impl {
public:
    explicit Impl(MotorConfig config)
        : config_(std::move(config)),
          left_pwm_(config_.pwm_sysfs_root, config_.pwm_chip, config_.left_pwm_channel, config_.pwm_hz),
          right_pwm_(config_.pwm_sysfs_root, config_.pwm_chip, config_.right_pwm_channel, config_.pwm_hz),
          left_dir_(config_.gpio_chip, config_.left_dir_gpio),
          right_dir_(config_.gpio_chip, config_.right_dir_gpio) {
        SetRawSpeeds(0, 0);
    }

    void SetSpeeds(std::int32_t left_percent, std::int32_t right_percent) {
        const auto left_raw = ScalePercentToRaw(left_percent, config_);
        const auto right_raw = ScalePercentToRaw(right_percent, config_);
        try {
            SetRawSpeeds(left_raw, right_raw);
        } catch (const std::exception&) {
            try {
                SetRawSpeeds(0, 0);
            } catch (const std::exception&) {
            }
            throw;
        }
    }

    void Close() {
        SetRawSpeeds(0, 0);
        left_pwm_.Close();
        right_pwm_.Close();
    }

private:
    void SetRawSpeeds(std::int32_t left_raw, std::int32_t right_raw) {
        ApplyMotorSide(left_raw, config_.raw_max_speed, config_.left_inverted, left_pwm_, left_dir_);
        ApplyMotorSide(right_raw, config_.raw_max_speed, config_.right_inverted, right_pwm_, right_dir_);
    }

    MotorConfig config_;
    SysfsPwmChannel left_pwm_;
    SysfsPwmChannel right_pwm_;
    GpioOutputPin left_dir_;
    GpioOutputPin right_dir_;
};

SysfsMotorDriver::SysfsMotorDriver(MotorConfig config) : impl_(std::make_unique<Impl>(std::move(config))) {}

SysfsMotorDriver::~SysfsMotorDriver() = default;

void SysfsMotorDriver::SetSpeeds(std::int32_t left_percent, std::int32_t right_percent) {
    impl_->SetSpeeds(left_percent, right_percent);
}

void SysfsMotorDriver::Close() {
    impl_->Close();
}

MotorController::MotorController(MotorConfig config, std::unique_ptr<MotorDriver> driver)
    : config_(std::move(config)), driver_(std::move(driver)) {
    ValidateMotorConfig(config_);
}

MotorController MotorController::FromConfig(const MotorConfig& config) {
    if (config.enabled) {
        return MotorController(config, std::make_unique<SysfsMotorDriver>(config));
    }
    return MotorController(config, std::make_unique<NoopMotorDriver>());
}

MotionState MotorController::ApplyVelocity(const Twist& twist, std::uint64_t deadline_unix_ms, std::uint64_t now_unix_ms) {
    if (!actuator_ready_) {
        throw std::runtime_error("hardware actuator unavailable");
    }
    if (deadline_unix_ms <= now_unix_ms) {
        Stop(true);
        throw std::runtime_error("cmd_vel deadline is not in the future");
    }
    if (deadline_unix_ms - now_unix_ms > config_.watchdog_timeout_ms) {
        deadline_unix_ms = now_unix_ms + config_.watchdog_timeout_ms;
    }

    ValidateTwist(twist);
    const auto [left_speed, right_speed] = MixTwistToTankSpeeds(twist, config_);
    active_deadline_unix_ms_ = deadline_unix_ms;
    ApplySpeeds(left_speed, right_speed, false);
    return motion_;
}

MotionState MotorController::Stop(bool force) {
    active_deadline_unix_ms_.reset();
    ApplySpeeds(0, 0, force);
    if (state_ != HardwareState::Error) {
        state_ = HardwareState::Ready;
    }
    return motion_;
}

bool MotorController::Tick(std::uint64_t now_unix_ms) {
    if (active_deadline_unix_ms_.has_value() && now_unix_ms >= *active_deadline_unix_ms_) {
        Stop(false);
        return true;
    }
    return false;
}

void MotorController::Close() {
    if (closed_) {
        return;
    }
    closed_ = true;
    try {
        Stop(true);
    } catch (const std::exception&) {
    }
    try {
        driver_->Close();
    } catch (const std::exception& err) {
        MarkError(err.what());
    }
    if (state_ != HardwareState::Error) {
        state_ = HardwareState::Stopped;
        actuator_ready_ = false;
    }
}

HardwareStatus MotorController::Status() const {
    HardwareStatus status;
    status.state = state_;
    status.actuator_ready = actuator_ready_;
    status.last_error = last_error_;
    status.motion = motion_;
    status.active_deadline_unix_ms = active_deadline_unix_ms_;
    return status;
}

MotionState MotorController::Motion() const {
    return motion_;
}

void MotorController::ApplySpeeds(std::int32_t left_speed, std::int32_t right_speed, bool force) {
    if (!force && motion_.left_speed == left_speed && motion_.right_speed == right_speed) {
        return;
    }
    try {
        driver_->SetSpeeds(left_speed, right_speed);
    } catch (const std::exception& err) {
        MarkError(err.what());
        throw;
    }
    motion_.left_speed = left_speed;
    motion_.right_speed = right_speed;
    motion_.sequence += 1;
}

void MotorController::MarkError(const std::string& message) {
    last_error_ = message;
    state_ = HardwareState::Error;
    actuator_ready_ = false;
    active_deadline_unix_ms_.reset();
    try {
        driver_->SetSpeeds(0, 0);
    } catch (const std::exception&) {
    }
    if (motion_.left_speed != 0 || motion_.right_speed != 0) {
        motion_.left_speed = 0;
        motion_.right_speed = 0;
        motion_.sequence += 1;
    }
}

void ValidateTwist(const Twist& twist) {
    const std::pair<const char*, double> values[] = {
        {"linear.x", twist.linear.x},
        {"linear.y", twist.linear.y},
        {"linear.z", twist.linear.z},
        {"angular.x", twist.angular.x},
        {"angular.y", twist.angular.y},
        {"angular.z", twist.angular.z},
    };
    for (const auto& [name, value] : values) {
        if (!std::isfinite(value)) {
            throw std::runtime_error(std::string("cmd_vel ") + name + " must be finite");
        }
    }

    std::string unsupported;
    const std::pair<const char*, double> unsupported_values[] = {
        {"linear.y", twist.linear.y},
        {"linear.z", twist.linear.z},
        {"angular.x", twist.angular.x},
        {"angular.y", twist.angular.y},
    };
    for (const auto& [name, value] : unsupported_values) {
        if (value != 0.0) {
            if (!unsupported.empty()) {
                unsupported += ", ";
            }
            unsupported += name;
            unsupported += "=";
            unsupported += std::to_string(value);
        }
    }
    if (!unsupported.empty()) {
        throw std::runtime_error("unsupported cmd_vel axes: " + unsupported);
    }
}

std::pair<std::int32_t, std::int32_t> MixTwistToTankSpeeds(const Twist& twist, const MotorConfig& config) {
    ValidateMotorConfig(config);
    const auto half_track_width_m = config.track_width_m / 2.0;
    const auto left_wheel_linear_speed = twist.linear.x - (twist.angular.z * half_track_width_m);
    const auto right_wheel_linear_speed = twist.linear.x + (twist.angular.z * half_track_width_m);
    const auto left = std::clamp(left_wheel_linear_speed / config.max_wheel_linear_speed_mps, -1.0, 1.0);
    const auto right = std::clamp(right_wheel_linear_speed / config.max_wheel_linear_speed_mps, -1.0, 1.0);
    return {
        ApplyTrackPowerPercent(left, config.left_track_power_percent),
        ApplyTrackPowerPercent(right, config.right_track_power_percent),
    };
}

std::int32_t ScalePercentToRaw(std::int32_t value, const MotorConfig& config) {
    const auto clamped = ClampI32(value, -100, 100);
    if (clamped == 0) {
        return 0;
    }
    const auto magnitude = std::abs(clamped);
    std::int32_t scaled = 0;
    if (config.cmd_raw_min_speed == 0) {
        scaled = static_cast<std::int32_t>(std::llround((static_cast<double>(magnitude) / 100.0) * config.cmd_raw_max_speed));
    } else {
        const auto position = magnitude == 1 ? 0.0 : static_cast<double>(magnitude - 1) / 99.0;
        scaled = static_cast<std::int32_t>(
            std::llround(static_cast<double>(config.cmd_raw_min_speed) + position * static_cast<double>(config.cmd_raw_max_speed - config.cmd_raw_min_speed))
        );
    }
    return clamped < 0 ? -scaled : scaled;
}

std::uint64_t NowUnixMs() {
    return static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()
        ).count()
    );
}

}  // namespace txing::unit::hardware_worker
