#include "flight.hpp"

#include <mavlink/v2.0/common/mavlink.h>

#include <array>
#include <cstdio>
#include <stdexcept>
#include <string_view>

namespace {

using txing::virtual_quad::FlightControl;
using Frame = FlightControl::Frame;
using namespace std::chrono_literals;

void Check(bool passed, const char* reason) {
    if (!passed) throw std::runtime_error(reason);
}

Frame Encode(const mavlink_message_t& message) {
    std::array<std::uint8_t, MAVLINK_MAX_PACKET_LEN> bytes{};
    const auto length = mavlink_msg_to_send_buffer(bytes.data(), &message);
    return {bytes.begin(), bytes.begin() + length};
}

mavlink_message_t Decode(const Frame& frame) {
    mavlink_message_t message{}, buffer{};
    mavlink_status_t parser{};
    for (auto byte : frame) mavlink_frame_char_buffer(&buffer, &parser, byte, &message, nullptr);
    Check(parser.msg_received == MAVLINK_FRAMING_OK, "invalid bridge output CRC");
    return message;
}

class Scenario {
  public:
    FlightControl::Clock::time_point now = FlightControl::Clock::time_point{} + 1h;
    std::vector<Frame> writes;
    FlightControl flight{[this](const Frame& frame) { writes.push_back(frame); return true; }, [this] { return now; }};
    mavlink_status_t tx{};
    const std::uint64_t owner = flight.OpenPeer();
    const std::uint64_t observer = flight.OpenPeer();

    void Report(bool armed, unsigned landed, int altitude_mm = 0, unsigned mode = 4) {
        mavlink_message_t message{};
        mavlink_msg_heartbeat_pack_status(1, 1, &tx, &message, MAV_TYPE_QUADROTOR,
            MAV_AUTOPILOT_ARDUPILOTMEGA, armed ? MAV_MODE_FLAG_SAFETY_ARMED : 0, mode, MAV_STATE_ACTIVE);
        flight.Observe(Encode(message));
        mavlink_msg_extended_sys_state_pack_status(1, 1, &tx, &message, MAV_VTOL_STATE_UNDEFINED, landed);
        flight.Observe(Encode(message));
        mavlink_msg_global_position_int_pack_status(1, 1, &tx, &message, 0, -353632610, 1491652300,
            584000 + altitude_mm, altitude_mm, 0, 0, 0, 0);
        flight.Observe(Encode(message));
        flight.Tick(true);
    }

    bool Reply(std::uint64_t peer, const char* request, std::string_view expected) {
        return flight.HandleControl(peer, request).find(expected) != std::string::npos;
    }

    Frame Command(std::uint16_t id, float p1 = 0, float p2 = 0, float p7 = 0) {
        mavlink_message_t message{};
        mavlink_msg_command_long_pack_status(255, 190, &tx, &message, 1, 1, id, 0, p1, p2, 0, 0, 0, 0, p7);
        return Encode(message);
    }

    Frame Move(float forward) {
        mavlink_message_t message{};
        mavlink_msg_set_position_target_local_ned_pack_status(255, 190, &tx, &message,
            0, 1, 1, MAV_FRAME_BODY_OFFSET_NED, 1479, 0, 0, 0, forward, 0, 0, 0, 0, 0, 0, 0);
        return Encode(message);
    }

    mavlink_command_long_t LastCommand() const {
        for (auto frame = writes.rbegin(); frame != writes.rend(); ++frame) {
            const auto message = Decode(*frame);
            if (message.msgid == MAVLINK_MSG_ID_COMMAND_LONG) {
                mavlink_command_long_t command{};
                mavlink_msg_command_long_decode(&message, &command);
                return command;
            }
        }
        throw std::runtime_error("expected an autopilot command");
    }
};

constexpr auto acquire = R"({"type":"control.activate","requestId":"a","actor":"Office","takeover":false})";
constexpr auto renew = R"({"type":"control.renew_active","requestId":"n","epoch":1})";
constexpr auto release = R"({"type":"control.release_active","requestId":"r","epoch":1})";

void LeaseAndLanding() {
    Scenario test;
    Check(test.Reply(test.owner, acquire, "control_busy"), "granted authority before telemetry was ready");
    test.Report(false, MAV_LANDED_STATE_ON_GROUND);
    Check(test.Reply(test.owner, acquire, "control.activated"), "owner could not acquire");
    Check(test.writes.size() == 1 && Decode(test.writes.back()).msgid == MAVLINK_MSG_ID_HEARTBEAT,
        "acquisition changed flight state");
    Check(test.Reply(test.observer, acquire, "control_busy"), "observer acquired an occupied lease");
    Check(test.Reply(test.observer, renew, "stale_epoch"), "observer renewed an occupied lease");
    Check(test.Reply(test.owner, renew, "control.renewed"), "owner could not renew");

    const auto arm = test.Command(MAV_CMD_COMPONENT_ARM_DISARM, 1);
    auto corrupt = arm;
    corrupt.back() ^= 1;
    test.flight.SendFrame(test.owner, 1, corrupt);
    test.flight.SendFrame(test.observer, 1, arm);
    test.flight.SendFrame(test.owner, 2, arm);
    test.flight.SendFrame(test.owner, 1, test.Command(MAV_CMD_COMPONENT_ARM_DISARM, 1, 21196));
    Check(test.writes.size() == 1, "rejected arm reached SITL");
    test.flight.SendFrame(test.owner, 1, arm);
    Check(test.LastCommand().command == MAV_CMD_COMPONENT_ARM_DISARM, "normal arm failed");

    test.Report(true, MAV_LANDED_STATE_ON_GROUND);
    test.flight.SendFrame(test.owner, 1, test.Command(MAV_CMD_NAV_TAKEOFF, 0, 0, 2));
    Check(test.LastCommand().command == MAV_CMD_NAV_TAKEOFF, "takeoff did not reach SITL");
    const auto before_move = test.writes.size();
    test.flight.SendFrame(test.owner, 1, test.Move(0.5f));
    Check(test.writes.size() == before_move, "movement interrupted takeoff");

    test.Report(true, MAV_LANDED_STATE_IN_AIR, 2000);
    test.flight.SendFrame(test.owner, 1, test.Move(2));
    Check(test.writes.size() == before_move, "overspeed setpoint reached SITL");
    test.flight.SendFrame(test.owner, 1, test.Move(0.5f));
    Check(test.writes.size() == before_move + 1, "valid movement did not reach SITL");
    test.now += 500ms;
    test.flight.Tick(true);
    const auto message = Decode(test.writes.back());
    mavlink_set_position_target_local_ned_t neutral{};
    mavlink_msg_set_position_target_local_ned_decode(&message, &neutral);
    Check(test.writes.size() == before_move + 2 && message.msgid == MAVLINK_MSG_ID_SET_POSITION_TARGET_LOCAL_NED &&
        neutral.vx == 0 && neutral.vy == 0 && neutral.vz == 0 && neutral.yaw_rate == 0,
        "missing neutral setpoint after movement gap");

    Check(test.Reply(test.owner, release, "control.released"), "owner could not release");
    const auto land = test.LastCommand();
    Check(land.command == MAV_CMD_DO_SET_MODE && land.param2 == 9, "release did not request LAND immediately");
    Check(!test.flight.SafeToExit(), "airborne cleanup reported complete");
    Check(test.Reply(test.observer, acquire, "control_busy"), "acquisition during autonomous landing");
    test.now += 1s;
    test.Report(false, MAV_LANDED_STATE_ON_GROUND, 0, 9);
    Check(test.flight.SafeToExit(), "landed and disarmed flight remained active");
    Check(test.Reply(test.observer, acquire, "\"epoch\":2"), "new acquisition did not advance epoch");
    test.flight.ClosePeer(test.owner);
    Check(test.Reply(test.owner, acquire, "stale_epoch"), "closed peer reacquired");
}

void ExpiryAndStop() {
    Scenario test;
    test.Report(false, MAV_LANDED_STATE_ON_GROUND);
    Check(test.Reply(test.owner, acquire, "control.activated"), "acquisition failed");
    for (int tick = 0; tick < 5; ++tick) {
        test.now += 1s;
        test.Report(tick > 0, tick > 0 ? MAV_LANDED_STATE_IN_AIR : MAV_LANDED_STATE_ON_GROUND, 2000);
    }
    Check(test.LastCommand().param2 == 9 && test.Reply(test.owner, renew, "stale_epoch"),
        "expired lease retained authority or failed to request LAND");
    test.flight.Stop();
    test.now += 1s;
    test.Report(false, MAV_LANDED_STATE_ON_GROUND, 0, 9);
    Check(test.flight.SafeToExit() && test.Reply(test.observer, acquire, "control_busy"),
        "shutdown did not close the write gate permanently");
}

void PeerClosureFencesReconnect() {
    Scenario test;
    test.Report(false, MAV_LANDED_STATE_ON_GROUND);
    Check(test.Reply(test.owner, acquire, "control.activated"), "acquisition failed");
    test.Report(true, MAV_LANDED_STATE_IN_AIR, 2000);

    test.flight.ClosePeer(test.owner);
    const auto land = test.LastCommand();
    Check(land.command == MAV_CMD_DO_SET_MODE && land.param2 == 9, "closing an airborne peer did not request LAND immediately");
    const auto replacement = test.flight.OpenPeer();
    Check(test.Reply(replacement, acquire, "control_busy"), "replacement peer acquired during landing");
    const auto writes_before_reconnect = test.writes.size();
    test.flight.SendFrame(test.owner, 1, test.Move(0.5f));
    test.flight.SendFrame(replacement, 1, test.Move(0.5f));
    Check(test.writes.size() == writes_before_reconnect, "retired lease forwarded a movement command");

    test.now += 1s;
    test.Report(false, MAV_LANDED_STATE_ON_GROUND, 0, 9);
    const auto writes_after_landing = test.writes.size();
    Check(test.Reply(replacement, acquire, "\"epoch\":2"), "replacement peer did not receive a fresh lease");
    const auto guided = test.Command(MAV_CMD_DO_SET_MODE, MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, 4);
    test.flight.SendFrame(test.owner, 2, guided);
    test.flight.SendFrame(replacement, 1, guided);
    Check(test.writes.size() == writes_after_landing, "closed peer or stale epoch forwarded a command");
    test.flight.SendFrame(replacement, 2, guided);
    Check(test.writes.size() == writes_after_landing + 1, "replacement peer could not use its fresh lease");
}

}  // namespace

int main() {
    try {
        LeaseAndLanding();
        ExpiryAndStop();
        PeerClosureFencesReconnect();
    } catch (const std::exception& error) {
        std::fprintf(stderr, "%s\n", error.what());
        return 1;
    }
}
