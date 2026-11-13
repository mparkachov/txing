#include "flight.hpp"

#include <json-c/json.h>
#include <mavlink/v2.0/common/mavlink.h>

#include <array>
#include <cmath>
#include <cstdio>
#include <mutex>
#include <optional>
#include <string_view>
#include <unordered_set>
#include <utility>

namespace txing::virtual_quad {
namespace {

using namespace std::chrono_literals;
using Clock = FlightControl::Clock;
using Frame = FlightControl::Frame;
using Json = std::unique_ptr<json_object, decltype(&json_object_put)>;

constexpr auto lease_duration = 5s;
constexpr auto telemetry_timeout = 2s;
constexpr std::uint8_t autopilot_system = 1;
constexpr std::uint8_t autopilot_component = MAV_COMP_ID_AUTOPILOT1;
constexpr std::uint8_t gcs_system = 255;
constexpr std::uint8_t gcs_component = MAV_COMP_ID_MISSIONPLANNER;
constexpr std::uint32_t guided_mode = 4;
constexpr std::uint32_t land_mode = 9;
constexpr std::uint16_t velocity_yaw_rate_mask = POSITION_TARGET_TYPEMASK_X_IGNORE |
    POSITION_TARGET_TYPEMASK_Y_IGNORE | POSITION_TARGET_TYPEMASK_Z_IGNORE |
    POSITION_TARGET_TYPEMASK_AX_IGNORE | POSITION_TARGET_TYPEMASK_AY_IGNORE |
    POSITION_TARGET_TYPEMASK_AZ_IGNORE | POSITION_TARGET_TYPEMASK_YAW_IGNORE;
constexpr float yaw_rate_limit = 0.523599f;

std::optional<mavlink_message_t> ParseFrame(const Frame& frame) {
    if (frame.size() < 12 || frame[0] != MAVLINK_STX || frame[2] != 0 ||
        frame.size() != 12u + frame[1]) return std::nullopt;
    mavlink_message_t buffer{}, message{};
    mavlink_status_t parser{};
    for (const auto byte : frame) mavlink_frame_char_buffer(&buffer, &parser, byte, &message, nullptr);
    if (parser.msg_received != MAVLINK_FRAMING_OK) return std::nullopt;
    return message;
}

bool AutopilotMessage(const mavlink_message_t& message) {
    return message.sysid == autopilot_system && message.compid == autopilot_component;
}

json_object* Field(json_object* object, const char* name, json_type type) {
    json_object* field = nullptr;
    if (!json_object_object_get_ex(object, name, &field) || !json_object_is_type(field, type)) return nullptr;
    return field;
}

std::string StringField(json_object* object, const char* name) {
    auto* field = Field(object, name, json_type_string);
    if (!field) return {};
    return {json_object_get_string(field), static_cast<std::size_t>(json_object_get_string_len(field))};
}

bool ValidText(const std::string& value, std::size_t max_length) {
    return value.size() <= max_length && value.find('\0') == std::string::npos &&
        value.find_first_not_of(" \t\r\n") != std::string::npos;
}

std::string Error(const std::string& id, const char* code, const char* message) {
    Json response(json_object_new_object(), json_object_put);
    json_object_object_add(response.get(), "type", json_object_new_string("control.error"));
    json_object_object_add(response.get(), "requestId", json_object_new_string(id.c_str()));
    json_object_object_add(response.get(), "code", json_object_new_string(code));
    json_object_object_add(response.get(), "message", json_object_new_string(message));
    return json_object_to_json_string_ext(response.get(), JSON_C_TO_STRING_PLAIN);
}

}  // namespace

struct FlightControl::State {
    struct Lease {
        std::uint64_t peer;
        std::string actor;
        Clock::time_point expires;
    };

    State(Sender sender, Now clock) : send(std::move(sender)), now(std::move(clock)) {}

    bool Send(const mavlink_message_t& message) const {
        std::array<std::uint8_t, MAVLINK_MAX_PACKET_LEN> bytes{};
        const auto length = mavlink_msg_to_send_buffer(bytes.data(), &message);
        return send(Frame(bytes.begin(), bytes.begin() + length));
    }

    bool Command(std::uint16_t command, float p1 = 0, float p2 = 0, float p7 = 0) {
        mavlink_message_t message{};
        mavlink_msg_command_long_pack_status(gcs_system, gcs_component, &tx, &message,
            autopilot_system, autopilot_component, command, 0, p1, p2, 0, 0, 0, 0, p7);
        return Send(message);
    }

    bool Velocity(float forward, float right, float down, float yaw_rate) {
        mavlink_message_t message{};
        mavlink_msg_set_position_target_local_ned_pack_status(gcs_system, gcs_component, &tx, &message,
            0, autopilot_system, autopilot_component, MAV_FRAME_BODY_OFFSET_NED, velocity_yaw_rate_mask,
            0, 0, 0, forward, right, down, 0, 0, 0, 0, yaw_rate);
        return Send(message);
    }

    bool Heartbeat(Clock::time_point now) {
        mavlink_message_t message{};
        mavlink_msg_heartbeat_pack_status(gcs_system, gcs_component, &tx, &message,
            MAV_TYPE_GCS, MAV_AUTOPILOT_INVALID, 0, 0, MAV_STATE_ACTIVE);
        if (!Send(message)) return false;
        next_heartbeat = now + 1s;
        return true;
    }

    bool Grounded(Clock::time_point now) const {
        return now - landed_at < telemetry_timeout && landed == MAV_LANDED_STATE_ON_GROUND;
    }

    bool Healthy(Clock::time_point now) const {
        return !stopping && now - media_ready_at < 500ms && now - heartbeat_at < telemetry_timeout &&
            now - landed_at < telemetry_timeout && now - position_at < telemetry_timeout;
    }

    void LandIfNeeded(Clock::time_point now) {
        if (!landing_at || now < next_landing_attempt) return;
        if (!armed && now >= arm_wait_until && heartbeat_at > *landing_at &&
            landed_at > *landing_at && now - heartbeat_at < telemetry_timeout && Grounded(now)) {
            takeoff_pending = false;
            landing_at.reset();
            return;
        }
        if (!armed && !takeoff_pending) return;
        next_landing_attempt = now + 500ms;
        if (armed && Grounded(now) && !takeoff_pending) {
            Command(MAV_CMD_COMPONENT_ARM_DISARM);
        } else if (mode != land_mode || now - heartbeat_at >= telemetry_timeout) {
            Command(MAV_CMD_DO_SET_MODE, MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, land_mode);
        }
    }

    void Revoke(Clock::time_point now, const char* reason) {
        if (!lease) return;
        std::printf("QUAD_FLIGHT_LEASE_REVOKED epoch=%llu reason=%s\n",
            static_cast<unsigned long long>(epoch), reason);
        lease.reset();
        movement_at.reset();
        if (armed || now < arm_wait_until || takeoff_pending) {
            landing_at = now;
            next_landing_attempt = now;
            LandIfNeeded(now);
        }
    }

    void Expire(Clock::time_point now) {
        if (!lease) return;
        if (now >= lease->expires) Revoke(now, "expired");
        else if (!Healthy(now)) Revoke(now, "worker health lost");
    }

    bool Owns(std::uint64_t peer, std::uint64_t candidate_epoch) const {
        return lease && lease->peer == peer && epoch == candidate_epoch;
    }

    std::string Reply(const std::string& id, const char* type) const {
        Json response(json_object_new_object(), json_object_put);
        auto* state = json_object_new_object();
        json_object* active = nullptr;
        if (lease) {
            active = json_object_new_object();
            const auto session = "mavlink-" + std::to_string(lease->peer);
            json_object_object_add(active, "sessionId", json_object_new_string(session.c_str()));
            json_object_object_add(active, "actor", json_object_new_string(lease->actor.c_str()));
            json_object_object_add(active, "epoch", json_object_new_uint64(epoch));
        }
        json_object_object_add(state, "epoch", json_object_new_uint64(epoch));
        json_object_object_add(state, "leaseTtlMs", json_object_new_int(5000));
        json_object_object_add(state, "activeControl", active);
        json_object_object_add(response.get(), "type", json_object_new_string(type));
        json_object_object_add(response.get(), "requestId", json_object_new_string(id.c_str()));
        json_object_object_add(response.get(), "state", state);
        return json_object_to_json_string_ext(response.get(), JSON_C_TO_STRING_PLAIN);
    }

    void OperatorCommand(const mavlink_message_t& message, Clock::time_point now) {
        mavlink_command_long_t command{};
        mavlink_msg_command_long_decode(&message, &command);
        if (command.target_system != autopilot_system || command.target_component != autopilot_component ||
            command.param3 != 0 || command.param4 != 0 || command.param5 != 0 || command.param6 != 0) return;
        switch (command.command) {
        case MAV_CMD_DO_SET_MODE:
            if (command.param1 != MAV_MODE_FLAG_CUSTOM_MODE_ENABLED || command.param7 != 0) return;
            if (command.param2 == guided_mode && !armed && Grounded(now) && now >= arm_wait_until) {
                Command(command.command, command.param1, guided_mode);
            } else if (command.param2 == land_mode && armed) {
                if (Command(command.command, command.param1, land_mode)) {
                    movement_at.reset();
                    landing_at = now;
                    next_landing_attempt = now + 500ms;
                }
            }
            break;
        case MAV_CMD_COMPONENT_ARM_DISARM:
            if (command.param2 != 0 || command.param7 != 0 || !Grounded(now) || takeoff_pending) return;
            if (command.param1 == 1 && !armed && mode == guided_mode && now >= arm_wait_until && Heartbeat(now)) {
                if (Command(command.command, 1)) arm_wait_until = now + 2s;
            } else if (command.param1 == 0 && armed) {
                Command(command.command);
            }
            break;
        case MAV_CMD_NAV_TAKEOFF:
            if (command.param1 == 0 && command.param2 == 0 && command.param7 == 2 &&
                armed && mode == guided_mode && Grounded(now) && !takeoff_pending &&
                Command(command.command, 0, 0, 2)) takeoff_pending = true;
            break;
        }
    }

    void OperatorVelocity(const mavlink_message_t& message, Clock::time_point now) {
        if (!armed || mode != guided_mode || takeoff_pending || landed != MAV_LANDED_STATE_IN_AIR) return;
        mavlink_set_position_target_local_ned_t target{};
        mavlink_msg_set_position_target_local_ned_decode(&message, &target);
        if (target.target_system != autopilot_system || target.target_component != autopilot_component ||
            target.coordinate_frame != MAV_FRAME_BODY_OFFSET_NED || target.type_mask != velocity_yaw_rate_mask ||
            !std::isfinite(target.vx) || !std::isfinite(target.vy) || !std::isfinite(target.vz) ||
            !std::isfinite(target.yaw_rate) || std::hypot(target.vx, target.vy) > 1.00001f ||
            std::abs(target.vz) > 0.5f || std::abs(target.yaw_rate) > yaw_rate_limit) return;
        if (target.vz < 0 && altitude_m >= 3.8f) target.vz = 0;
        if (Velocity(target.vx, target.vy, target.vz, target.yaw_rate)) movement_at = now;
    }

    std::mutex mutex;
    Sender send;
    Now now;
    mavlink_status_t tx{};
    std::unordered_set<std::uint64_t> peers;
    std::uint64_t next_peer = 0;
    std::uint64_t epoch = 0;
    std::optional<Lease> lease;
    std::optional<Clock::time_point> movement_at, landing_at;
    Clock::time_point heartbeat_at{}, landed_at{}, position_at{};
    Clock::time_point arm_wait_until{}, next_heartbeat{}, next_landing_attempt{}, media_ready_at{};
    float altitude_m = 0;
    std::uint32_t mode = 0;
    std::uint8_t landed = MAV_LANDED_STATE_UNDEFINED;
    bool armed = false;
    bool takeoff_pending = false;
    bool stopping = false;
};

FlightControl::FlightControl(Sender send, Now now) : state_(std::make_unique<State>(std::move(send), std::move(now))) {}
FlightControl::~FlightControl() = default;

std::uint64_t FlightControl::OpenPeer() {
    std::lock_guard lock(state_->mutex);
    const auto peer = ++state_->next_peer;
    state_->peers.insert(peer);
    return peer;
}

void FlightControl::ClosePeer(std::uint64_t peer) {
    std::lock_guard lock(state_->mutex);
    state_->peers.erase(peer);
    if (state_->Owns(peer, state_->epoch)) state_->Revoke(state_->now(), "peer closed");
}

std::string FlightControl::HandleControl(std::uint64_t peer, const std::string& encoded) {
    const auto invalid = [](const std::string& id) {
        return Error(id, "invalid_request", "invalid virtual quad control request");
    };
    if (encoded.empty() || encoded.size() > 4096) return invalid("");
    const std::unique_ptr<json_tokener, decltype(&json_tokener_free)> parser(json_tokener_new_ex(4), json_tokener_free);
    if (!parser) throw std::bad_alloc();
    json_tokener_set_flags(parser.get(), JSON_TOKENER_STRICT | JSON_TOKENER_VALIDATE_UTF8);
    Json request(json_tokener_parse_ex(parser.get(), encoded.data(), static_cast<int>(encoded.size())), json_object_put);
    if (json_tokener_get_error(parser.get()) != json_tokener_success ||
        json_tokener_get_parse_end(parser.get()) != encoded.size() ||
        !json_object_is_type(request.get(), json_type_object)) return invalid("");
    const auto id = StringField(request.get(), "requestId");
    if (!ValidText(id, 128)) return invalid("");
    const auto type = StringField(request.get(), "type");
    const auto fields = json_object_object_length(request.get());

    std::lock_guard lock(state_->mutex);
    const auto now = state_->now();
    state_->Expire(now);
    if (!state_->peers.count(peer)) return Error(id, "stale_epoch", "MAVLink peer has closed");
    if (type == "control.get_state" && fields == 2) return state_->Reply(id, "control.state");
    if (type == "control.activate" && fields == 4) {
        const auto actor = StringField(request.get(), "actor");
        auto* takeover = Field(request.get(), "takeover", json_type_boolean);
        if (!ValidText(actor, 256) || !takeover || json_object_get_boolean(takeover)) return invalid(id);
        if (!state_->Healthy(now) || state_->landing_at) {
            return Error(id, "control_busy", "simulator is not ready for flight control");
        }
        if (state_->lease && state_->lease->peer != peer) {
            return Error(id, "control_busy", "another viewer holds flight control");
        }
        if (!state_->lease) {
            ++state_->epoch;
            state_->lease = State::Lease{peer, actor, now + lease_duration};
        } else {
            state_->lease->expires = now + lease_duration;
        }
        return state_->Reply(id, "control.activated");
    }
    if ((type == "control.renew_active" || type == "control.release_active") && fields == 3) {
        auto* epoch = Field(request.get(), "epoch", json_type_int);
        if (!epoch || json_object_get_int64(epoch) < 0) return invalid(id);
        if (!state_->Owns(peer, json_object_get_uint64(epoch))) {
            return Error(id, "stale_epoch", "flight control lease is no longer active");
        }
        if (type == "control.renew_active") {
            state_->lease->expires = now + lease_duration;
            return state_->Reply(id, "control.renewed");
        }
        state_->Revoke(now, "released");
        return state_->Reply(id, "control.released");
    }
    return invalid(id);
}

void FlightControl::SendFrame(std::uint64_t peer, std::uint64_t epoch, const Frame& frame) {
    const auto message = ParseFrame(frame);
    if (!message || message->sysid != gcs_system || message->compid != gcs_component) return;
    std::lock_guard lock(state_->mutex);
    const auto now = state_->now();
    state_->Expire(now);
    if (!state_->Owns(peer, epoch) || state_->landing_at) return;
    if (message->msgid == MAVLINK_MSG_ID_COMMAND_LONG) state_->OperatorCommand(*message, now);
    if (message->msgid == MAVLINK_MSG_ID_SET_POSITION_TARGET_LOCAL_NED) state_->OperatorVelocity(*message, now);
}

bool FlightControl::IsAutopilotHeartbeat(const Frame& frame) {
    const auto message = ParseFrame(frame);
    return message && AutopilotMessage(*message) && message->msgid == MAVLINK_MSG_ID_HEARTBEAT;
}

void FlightControl::Observe(const Frame& frame) {
    if (frame.size() < 12 || frame[8] != 0 || frame[9] != 0) return;
    if (frame[7] != MAVLINK_MSG_ID_HEARTBEAT && frame[7] != MAVLINK_MSG_ID_EXTENDED_SYS_STATE &&
        frame[7] != MAVLINK_MSG_ID_GLOBAL_POSITION_INT) return;
    const auto message = ParseFrame(frame);
    if (!message || !AutopilotMessage(*message)) return;
    std::lock_guard lock(state_->mutex);
    const auto now = state_->now();
    switch (message->msgid) {
    case MAVLINK_MSG_ID_HEARTBEAT: {
        mavlink_heartbeat_t heartbeat{};
        mavlink_msg_heartbeat_decode(&*message, &heartbeat);
        state_->heartbeat_at = now;
        state_->mode = heartbeat.custom_mode;
        state_->armed = (heartbeat.base_mode & MAV_MODE_FLAG_SAFETY_ARMED) != 0;
        if (state_->armed) state_->arm_wait_until = {};
        break;
    }
    case MAVLINK_MSG_ID_EXTENDED_SYS_STATE: {
        mavlink_extended_sys_state_t extended{};
        mavlink_msg_extended_sys_state_decode(&*message, &extended);
        state_->landed_at = now;
        state_->landed = extended.landed_state;
        break;
    }
    case MAVLINK_MSG_ID_GLOBAL_POSITION_INT: {
        mavlink_global_position_int_t position{};
        mavlink_msg_global_position_int_decode(&*message, &position);
        state_->position_at = now;
        state_->altitude_m = position.relative_alt / 1000.0f;
        break;
    }
    }
    if (state_->takeoff_pending && state_->landed == MAV_LANDED_STATE_IN_AIR && state_->altitude_m >= 1.5f) {
        state_->takeoff_pending = false;
    }
}

void FlightControl::Tick(bool media_ready) {
    std::lock_guard lock(state_->mutex);
    const auto now = state_->now();
    state_->media_ready_at = media_ready ? now : Clock::time_point{};
    state_->Expire(now);
    if (now >= state_->next_heartbeat && now - state_->heartbeat_at < telemetry_timeout) state_->Heartbeat(now);
    state_->LandIfNeeded(now);
    if (state_->movement_at && now - *state_->movement_at >= 500ms && state_->armed && state_->mode == guided_mode) {
        if (state_->Velocity(0, 0, 0, 0)) state_->movement_at.reset();
    }
}

void FlightControl::Stop() {
    std::lock_guard lock(state_->mutex);
    state_->stopping = true;
    state_->Revoke(state_->now(), "workload stopping");
}

bool FlightControl::SafeToExit() {
    std::lock_guard lock(state_->mutex);
    return !state_->landing_at;
}

}  // namespace txing::virtual_quad
