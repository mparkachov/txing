#include "agent/runtime_sample.hpp"
#include <aws/core/utils/json/JsonSerializer.h>
#include <algorithm>
#include <stdexcept>

namespace txing::agent {
namespace {
using Aws::Utils::Json::JsonValue;
using Aws::Utils::Json::JsonView;
std::string field(JsonView view, const char* name) {
    if (!view.ValueExists(name) || !view.GetObject(name).IsString())
        throw std::runtime_error(std::string("invalid runtime sample: ") + name);
    return view.GetString(name).c_str();
}
std::int64_t number(JsonView view, const char* name) {
    if (!view.ValueExists(name) || !view.GetObject(name).IsIntegerType() || view.GetInt64(name) < 0)
        throw std::runtime_error(std::string("invalid runtime sample: ") + name);
    return view.GetInt64(name);
}
JsonView object(JsonView view, const char* name) {
    if (!view.ValueExists(name) || !view.GetObject(name).IsObject())
        throw std::runtime_error(std::string("invalid runtime sample: ") + name);
    return view.GetObject(name);
}
const char* connection_state(std::int64_t state) {
    switch (state) {
    case 0: return "disconnected";
    case 1: return "connecting";
    case 2: return "connected";
    case 3: return "error";
    default: throw std::runtime_error("invalid runtime connection state");
    }
}
std::string connection_error(const std::string& error) {
    // Keep only trusted operation names and numeric KVS status. Arbitrary
    // exception/peer text may contain tokens, SDP, addresses, or URLs.
    const std::vector<std::string> operations = {"dataChannelSend", "KVS signaling callback",
        "refusing signaling channel mutation", "WebRTC connection lost", "signalingClientConnectSync",
        "signalingClientFetchSync", "createSignalingClientSync", "createPeerConnection", "setRemoteDescription",
        "createOffer", "setLocalDescription", "addIceCandidate", "createDataChannel"};
    for (const auto* known : {"no MAVLink telemetry for 15 seconds", "transport failed",
                              "too many pending remote ICE candidates", "KVS signaling queue exceeded bounded capacity"})
        if (error == known) return error;
    if (error.rfind("peer negotiation exceeded 20 seconds", 0) == 0) return "peer negotiation exceeded 20 seconds";
    const auto marker = error.find(": KVS status 0x");
    if (marker != std::string::npos && std::find(operations.begin(), operations.end(), error.substr(0, marker)) != operations.end()) {
        const auto begin = marker + std::string(": KVS status 0x").size();
        const auto end = error.find_first_not_of("0123456789abcdefABCDEF", begin);
        const auto digits = error.substr(begin, end == std::string::npos ? end : end - begin);
        if (!digits.empty() && digits.size() <= 8) return error.substr(0, begin) + digits;
    }
    return error.empty() ? "" : "connection operation failed; inspect agent logs";
}
}
std::string safe_connection_diagnostic(const std::string& error) { return connection_error(error); }
bool runtime_stopped_for(const ControllerSnapshot& snapshot, const std::string& thing, const std::string& sample) {
    if (thing.empty() || !snapshot.state.run || snapshot.state.run->phase != RunPhase::running ||
        snapshot.state.run->microvm_id.empty()) return false;
    JsonValue document(Aws::String(sample.c_str()));
    if (!document.WasParseSuccessful() || !document.View().IsObject()) return false;
    const auto view = document.View();
    const auto equals = [&](const char* key, const std::string& expected) {
        return view.ValueExists(key) && view.GetObject(key).IsString() && view.GetString(key) == expected.c_str();
    };
    return equals("phase", "stopped") && equals("thingId", thing) &&
        equals("runId", snapshot.state.run->run_id) && equals("microvmId", snapshot.state.run->microvm_id) &&
        equals("activationId", snapshot.state.run->activation_id);
}
bool runtime_verified_for(const ControllerSnapshot& snapshot, const std::string& thing, const std::string& sample,
                          std::int64_t elapsed_ms) {
    if (thing.empty() || elapsed_ms < 0 || elapsed_ms >= 15000 || !snapshot.state.run ||
        snapshot.state.run->phase != RunPhase::running || snapshot.state.run->microvm_id.empty() ||
        !snapshot.state.activation.activation ||
        snapshot.state.run->activation_id != snapshot.state.activation.activation->id) return false;
    try {
        JsonValue document(Aws::String(sample.c_str()));
        const auto view = document.View();
        return document.WasParseSuccessful() && view.IsObject() && field(view, "phase") == "running" &&
            field(view, "thingId") == thing && field(view, "runId") == snapshot.state.run->run_id &&
            field(view, "microvmId") == snapshot.state.run->microvm_id &&
            field(view, "activationId") == snapshot.state.run->activation_id &&
            number(view, "deadline") == snapshot.state.activation.activation->deadline &&
            view.ValueExists("assignmentVerified") && view.GetObject("assignmentVerified").IsBool() &&
            view.GetBool("assignmentVerified") && number(view, "assignmentAgeMs") < 15000 - elapsed_ms;
    } catch (...) { return false; }
}
std::string microvm_https_endpoint(const std::string& endpoint) {
    auto host = endpoint;
    if (host.rfind("https://", 0) == 0) host.erase(0, 8);
    const std::string suffix = ".lambda-microvm.eu-central-1.on.aws";
    if (host.size() <= suffix.size() || host.size() > 253 ||
        host.compare(host.size() - suffix.size(), suffix.size(), suffix) != 0 ||
        host.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789.-") != std::string::npos ||
        host.front() == '.' || host.find("..") != std::string::npos)
        throw std::invalid_argument("invalid managed MicroVM endpoint");
    return "https://" + host;
}

std::string runtime_sample_patch(const ControllerSnapshot& snapshot, const std::string& endpoint,
                                 const std::string& sample, std::int64_t sampled_at) {
    const auto& state = snapshot.state;
    if (!state.run || state.run->phase != RunPhase::running || state.run->microvm_id.empty() ||
        !activation_authorized(state.activation, sampled_at) || !state.activation.activation ||
        state.run->activation_id != state.activation.activation->id)
        throw std::invalid_argument("sample has no current authorized assignment");
    JsonValue document(Aws::String(sample.c_str()));
    const auto view = document.View();
    if (!document.WasParseSuccessful() || !view.IsObject() || field(view, "phase") != "running" ||
        field(view, "runId") != state.run->run_id || field(view, "microvmId") != state.run->microvm_id ||
        field(view, "activationId") != state.run->activation_id ||
        number(view, "deadline") != state.activation.activation->deadline || !view.ValueExists("assignmentVerified") ||
        !view.GetObject("assignmentVerified").IsBool() || !view.GetBool("assignmentVerified"))
        throw std::runtime_error("runtime sample does not match current assignment");
    const auto telemetry = object(view, "telemetry"), video = object(view, "video"), control = object(view, "control");
    const auto telemetry_state = number(telemetry, "state"), video_state = number(video, "state");
    const auto control_state = field(control, "state");
    if (control_state != "observing" && control_state != "acquiring" && control_state != "held" && control_state != "lost")
        throw std::runtime_error("invalid runtime control state");
    JsonValue mavlink;
    mavlink.WithString("state", connection_state(telemetry_state));
    const auto mavlink_error = connection_error(field(telemetry, "error"));
    if (!mavlink_error.empty()) mavlink.WithString("lastError", mavlink_error.c_str());
    else mavlink.WithNull("lastError");
    JsonValue video_status;
    video_status.WithString("state", connection_state(video_state)).WithInt64("framesReceived", number(view, "videoFrames"));
    const auto video_error = connection_error(field(video, "error"));
    if (!video_error.empty()) video_status.WithString("lastError", video_error.c_str());
    else video_status.WithNull("lastError");
    const auto frame = object(view, "lastVideo");
    const auto receipt = number(frame, "receiptUnixMs");
    if (receipt) video_status.WithInt64("lastFrameAt", receipt / 1000);
    else video_status.WithNull("lastFrameAt");
    JsonValue control_status; control_status.WithString("state", control_state.c_str());
    const auto detail = field(control, "error");
    if (!detail.empty()) {
        const std::vector<std::string> safe = {"control_busy", "stale_epoch", "invalid_request", "control error",
            "control unavailable", "control request send failed", "invalid lease state", "board control ownership changed",
            "unexpected control response", "telemetry stopped", "telemetry connection lost",
            "operator exception or control response overload", "client inactivity or lease expiry",
            "control request timed out", "operator released", "MAVLink send failed", "control operation failed"};
        control_status.WithString("lastError", std::find(safe.begin(), safe.end(), detail) != safe.end()
            ? detail.c_str() : "control operation failed");
    }
    else control_status.WithNull("lastError");
    JsonValue runtime;
    runtime.WithString("runId", state.run->run_id.c_str()).WithInt64("sampledAt", sampled_at)
        .WithObject("mavlink", std::move(mavlink)).WithObject("video", std::move(video_status))
        .WithObject("control", std::move(control_status));
    JsonValue reported;
    reported.WithString("endpoint", microvm_https_endpoint(endpoint).c_str()).WithObject("runtime", std::move(runtime));
    JsonValue state_value; state_value.WithObject("reported", std::move(reported));
    JsonValue patch; patch.WithInt64("version", snapshot.shadow_version).WithObject("state", std::move(state_value));
    return patch.View().WriteCompact().c_str();
}
}
