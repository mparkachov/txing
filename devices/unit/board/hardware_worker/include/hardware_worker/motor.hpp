#ifndef TXING_UNIT_HARDWARE_WORKER_MOTOR_HPP
#define TXING_UNIT_HARDWARE_WORKER_MOTOR_HPP

#include "hardware_worker/config.hpp"

#include <cstdint>
#include <memory>
#include <optional>
#include <utility>
#include <string>

namespace txing::unit::hardware_worker {

struct Vector3 {
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

struct Twist {
    Vector3 linear;
    Vector3 angular;
};

struct MotionState {
    std::int32_t left_speed = 0;
    std::int32_t right_speed = 0;
    std::uint64_t sequence = 0;
};

enum class HardwareState {
    Starting,
    Ready,
    Degraded,
    Error,
    Stopped,
};

struct HardwareStatus {
    HardwareState state = HardwareState::Starting;
    bool actuator_ready = false;
    std::string last_error;
    MotionState motion;
    std::optional<std::uint64_t> active_deadline_unix_ms;
};

class MotorDriver {
public:
    virtual ~MotorDriver() = default;
    virtual void SetSpeeds(std::int32_t left_percent, std::int32_t right_percent) = 0;
    virtual void Close();
};

class NoopMotorDriver final : public MotorDriver {
public:
    void SetSpeeds(std::int32_t left_percent, std::int32_t right_percent) override;
};

class SysfsMotorDriver final : public MotorDriver {
public:
    explicit SysfsMotorDriver(MotorConfig config);
    ~SysfsMotorDriver() override;

    void SetSpeeds(std::int32_t left_percent, std::int32_t right_percent) override;
    void Close() override;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

class MotorController {
public:
    MotorController(MotorConfig config, std::unique_ptr<MotorDriver> driver);
    static MotorController FromConfig(const MotorConfig& config);

    MotionState ApplyVelocity(const Twist& twist, std::uint64_t deadline_unix_ms, std::uint64_t now_unix_ms);
    MotionState Stop(bool force);
    bool Tick(std::uint64_t now_unix_ms);
    void Close();

    HardwareStatus Status() const;
    MotionState Motion() const;

private:
    void ApplySpeeds(std::int32_t left_speed, std::int32_t right_speed, bool force);
    void MarkError(const std::string& message);

    MotorConfig config_;
    std::unique_ptr<MotorDriver> driver_;
    MotionState motion_;
    std::optional<std::uint64_t> active_deadline_unix_ms_;
    HardwareState state_ = HardwareState::Ready;
    bool actuator_ready_ = true;
    std::string last_error_;
    bool closed_ = false;
};

void ValidateTwist(const Twist& twist);
std::pair<std::int32_t, std::int32_t> MixTwistToTankSpeeds(const Twist& twist, const MotorConfig& config);
std::int32_t ScalePercentToRaw(std::int32_t value, const MotorConfig& config);
std::uint64_t NowUnixMs();

}  // namespace txing::unit::hardware_worker

#endif
