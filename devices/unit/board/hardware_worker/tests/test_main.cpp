#include "hardware_worker/config.hpp"
#include "hardware_worker/motor.hpp"

#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace hw = txing::unit::hardware_worker;

namespace {

void Expect(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

hw::MotorConfig TestConfig() {
    hw::MotorConfig config;
    config.enabled = false;
    config.raw_max_speed = 480;
    config.cmd_raw_min_speed = 50;
    config.cmd_raw_max_speed = 250;
    config.track_width_m = 0.28;
    config.max_wheel_linear_speed_mps = 0.50;
    config.watchdog_timeout_ms = 1'000;
    return config;
}

class RecordingDriver final : public hw::MotorDriver {
public:
    void SetSpeeds(std::int32_t left_raw, std::int32_t right_raw) override {
        if (fail_writes) {
            throw std::runtime_error("injected hardware write failure");
        }
        calls.emplace_back(left_raw, right_raw);
    }

    std::vector<std::pair<std::int32_t, std::int32_t>> calls;
    bool fail_writes = false;
};

void TestTwistValidationAndMixing() {
    auto config = TestConfig();
    hw::Twist forward;
    forward.linear.x = 0.50;
    Expect(hw::MixTwistToTankSpeeds(forward, config) == std::make_pair(100, 100), "forward cmd_vel should saturate both sides");

    config.right_track_power_percent = 98.0;
    Expect(hw::MixTwistToTankSpeeds(forward, config) == std::make_pair(100, 100), "track power trim should not affect logical straight-line output");
    config.right_track_power_percent = 100.0;

    hw::Twist turn;
    turn.angular.z = 1.0;
    Expect(hw::MixTwistToTankSpeeds(turn, config) == std::make_pair(-28, 28), "yaw cmd_vel should mix differential speeds");

    hw::Twist unsupported;
    unsupported.linear.y = 0.1;
    bool rejected = false;
    try {
        hw::ValidateTwist(unsupported);
    } catch (const std::exception& err) {
        rejected = std::string(err.what()).find("unsupported cmd_vel axes") != std::string::npos;
    }
    Expect(rejected, "unsupported cmd_vel axes should be rejected");
}

void TestRawScaling() {
    auto config = TestConfig();
    Expect(hw::ScalePercentToRaw(0, config) == 0, "zero percent should map to zero raw speed");
    Expect(hw::ScalePercentToRaw(1, config) == 50, "one percent should map to configured minimum raw speed");
    Expect(hw::ScalePercentToRaw(100, config) == 250, "full percent should map to configured max command raw speed");
    Expect(hw::ScalePercentToRaw(-100, config) == -250, "negative full percent should map to negative max command raw speed");
}

void TestTrackPowerValidation() {
    auto config = TestConfig();
    config.left_track_power_percent = 0.0;
    bool rejected = false;
    try {
        hw::ValidateMotorConfig(config);
    } catch (const std::exception& err) {
        rejected = std::string(err.what()).find("motor-left-track-power-percent") != std::string::npos;
    }
    Expect(rejected, "zero left track power percent should be rejected");

    config = TestConfig();
    config.right_track_power_percent = 101.0;
    rejected = false;
    try {
        hw::ValidateMotorConfig(config);
    } catch (const std::exception& err) {
        rejected = std::string(err.what()).find("motor-right-track-power-percent") != std::string::npos;
    }
    Expect(rejected, "right track power percent above 100 should be rejected");
}

void TestWatchdogNeutralizesOnDeadline() {
    auto driver = std::make_unique<RecordingDriver>();
    auto* recorder = driver.get();
    hw::MotorController controller(TestConfig(), std::move(driver));
    hw::Twist twist;
    twist.linear.x = 0.25;

    const auto drive = controller.ApplyVelocity(twist, 2'000, 1'000);
    Expect(drive.left_speed == 50 && drive.right_speed == 50, "controller should apply mixed speed");
    Expect(!controller.Tick(1'500), "controller should not stop before deadline");
    Expect(controller.Tick(2'000), "controller should stop at deadline");
    const auto motion = controller.Motion();
    Expect(motion.left_speed == 0 && motion.right_speed == 0, "deadline stop should neutralize motion");
    Expect(
        recorder->calls == std::vector<std::pair<std::int32_t, std::int32_t>>({{149, 149}, {0, 0}}),
        "driver calls should include drive and stop"
    );
}

void TestTrackPowerTrimAppliesOnlyToDriverOutput() {
    auto config = TestConfig();
    config.cmd_raw_min_speed = 100;
    config.cmd_raw_max_speed = 200;
    config.right_track_power_percent = 50.0;
    auto driver = std::make_unique<RecordingDriver>();
    auto* recorder = driver.get();
    hw::MotorController controller(config, std::move(driver));
    hw::Twist twist;
    twist.linear.x = 0.25;

    const auto drive = controller.ApplyVelocity(twist, 2'000, 1'000);
    Expect(drive.left_speed == 50 && drive.right_speed == 50, "track trim should not change reported logical motion");
    Expect(
        recorder->calls == std::vector<std::pair<std::int32_t, std::int32_t>>({{149, 100}}),
        "track trim should reduce physical output without going below the configured raw minimum"
    );

    twist.linear.x = -0.25;
    const auto reverse = controller.ApplyVelocity(twist, 2'500, 1'500);
    Expect(reverse.left_speed == -50 && reverse.right_speed == -50, "track trim should not change reported logical reverse motion");
    Expect(
        recorder->calls == std::vector<std::pair<std::int32_t, std::int32_t>>({{149, 100}, {-149, -100}}),
        "track trim should apply symmetrically to reverse physical output without going below the configured raw minimum"
    );
}

void TestDeadlineIsClampedToWatchdogTimeout() {
    auto driver = std::make_unique<RecordingDriver>();
    hw::MotorController controller(TestConfig(), std::move(driver));
    hw::Twist twist;
    twist.linear.x = 0.25;

    controller.ApplyVelocity(twist, 20'000, 1'000);
    const auto status = controller.Status();
    Expect(status.active_deadline_unix_ms.has_value(), "status should report active deadline");
    Expect(*status.active_deadline_unix_ms == 2'000, "deadline should be clamped to watchdog timeout");
}

void TestHardwareErrorNeutralizesMotion() {
    auto driver = std::make_unique<RecordingDriver>();
    auto* recorder = driver.get();
    hw::MotorController controller(TestConfig(), std::move(driver));
    hw::Twist twist;
    twist.linear.x = 0.25;

    controller.ApplyVelocity(twist, 2'000, 1'000);
    recorder->fail_writes = true;
    twist.linear.x = 0.10;
    bool rejected = false;
    try {
        controller.ApplyVelocity(twist, 2'500, 1'500);
    } catch (const std::exception& err) {
        rejected = std::string(err.what()).find("injected hardware write failure") != std::string::npos;
    }

    const auto status = controller.Status();
    Expect(rejected, "hardware write failure should reject command");
    Expect(!status.actuator_ready, "hardware write failure should mark actuator unavailable");
    Expect(status.state == hw::HardwareState::Error, "hardware write failure should mark error state");
    Expect(status.motion.left_speed == 0 && status.motion.right_speed == 0, "hardware write failure should neutralize cached motion");
    Expect(!status.last_error.empty(), "hardware write failure should be reported in status");
}

void TestCliParsesMotorEnvironment() {
    const std::unordered_map<std::string, std::string> values = {
        {"TXING_HARDWARE_WORKER_SOCKET_PATH", "/tmp/unit-hardware.sock"},
        {"TXING_MOTOR_ENABLED", "false"},
        {"TXING_MOTOR_CMD_RAW_MIN_SPEED", "100"},
        {"TXING_MOTOR_CMD_RAW_MAX_SPEED", "200"},
        {"TXING_MOTOR_LEFT_TRACK_POWER_PERCENT", "99.5"},
        {"TXING_MOTOR_RIGHT_TRACK_POWER_PERCENT", "98"},
    };
    auto parsed = hw::ParseCli({"txing-unit-hardware-worker"}, [&](const std::string& name) -> std::optional<std::string> {
        const auto found = values.find(name);
        if (found == values.end()) {
            return std::nullopt;
        }
        return found->second;
    });
    Expect(parsed.config.socket_path == "/tmp/unit-hardware.sock", "CLI should parse socket path from env");
    Expect(!parsed.config.motor.enabled, "CLI should parse motor-enabled from env");
    Expect(parsed.config.motor.cmd_raw_min_speed == 100, "CLI should parse min speed from env");
    Expect(parsed.config.motor.cmd_raw_max_speed == 200, "CLI should parse max speed from env");
    Expect(parsed.config.motor.left_track_power_percent == 99.5, "CLI should parse left track power percent from env");
    Expect(parsed.config.motor.right_track_power_percent == 98.0, "CLI should parse right track power percent from env");
}

}  // namespace

int main() {
    try {
        TestTwistValidationAndMixing();
        TestRawScaling();
        TestTrackPowerValidation();
        TestWatchdogNeutralizesOnDeadline();
        TestTrackPowerTrimAppliesOnlyToDriverOutput();
        TestDeadlineIsClampedToWatchdogTimeout();
        TestHardwareErrorNeutralizesMotion();
        TestCliParsesMotorEnvironment();
        std::cout << "txing-unit-hardware-worker tests passed\n";
        return 0;
    } catch (const std::exception& err) {
        std::cerr << "test failed: " << err.what() << "\n";
        return 1;
    }
}
