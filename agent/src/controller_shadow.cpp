#include "agent/controller_shadow.hpp"
#include <aws/core/utils/json/JsonSerializer.h>
#include <limits>
#include <stdexcept>

namespace txing::agent {
namespace {
using Aws::Utils::Json::JsonValue;
using Aws::Utils::Json::JsonView;
std::string str(JsonView value, const char* name) {
    if (!value.ValueExists(name) || !value.GetObject(name).IsString() || value.GetString(name).empty())
        throw std::runtime_error(std::string("agent shadow: invalid ") + name);
    return value.GetString(name).c_str();
}
std::int64_t number(JsonView value, const char* name) {
    if (!value.ValueExists(name) || !value.GetObject(name).IsIntegerType() || value.GetInt64(name) < 0)
        throw std::runtime_error(std::string("agent shadow: invalid ") + name);
    return value.GetInt64(name);
}
JsonView object(JsonView value, const char* name) {
    if (!value.ValueExists(name) || !value.GetObject(name).IsObject())
        throw std::runtime_error(std::string("agent shadow: missing ") + name);
    return value.GetObject(name);
}
RunPhase phase(const std::string& value) {
    if (value == "reserved") return RunPhase::reserved;
    if (value == "running") return RunPhase::running;
    if (value == "stopping") return RunPhase::stopping;
    throw std::runtime_error("agent shadow: invalid run phase");
}
const char* phase_name(RunPhase value) {
    switch (value) {
    case RunPhase::reserved: return "reserved";
    case RunPhase::running: return "running";
    case RunPhase::stopping: return "stopping";
    }
    throw std::logic_error("invalid run phase");
}
}

ControllerSnapshot parse_controller_shadow(const std::string& text) {
    JsonValue document(Aws::String(text.c_str()));
    if (!document.WasParseSuccessful() || !document.View().IsObject())
        throw std::runtime_error("agent shadow: invalid JSON");
    auto root = document.View();
    ControllerSnapshot snapshot;
    snapshot.shadow_version = number(root, "version");
    auto reported = object(object(root, "state"), "reported");
    const auto lifecycle = object(reported, "lifecycle");
    if (lifecycle.ValueExists("verifiedAt")) snapshot.verified_at = number(lifecycle, "verifiedAt");
    if (reported.ValueExists("lastError")) snapshot.last_error = str(reported, "lastError");
    auto& state = snapshot.state;
    const bool has_activation = reported.ValueExists("activation") && reported.GetObject("activation").IsObject();
    const bool has_run = reported.ValueExists("run") && reported.GetObject("run").IsObject();
    if (!reported.ValueExists("controller")) {
        if (has_activation || has_run) throw std::runtime_error("agent shadow: missing controller state");
        return snapshot;
    }
    auto controller = object(reported, "controller");
    if (controller.ValueExists("unverifiedSince")) snapshot.unverified_since = number(controller, "unverifiedSince");
    if (controller.ValueExists("stopRequestedAt")) snapshot.stop_requested_at = number(controller, "stopRequestedAt");
    const auto version = number(controller, "projectionVersion");
    const auto source_timestamp = number(controller, "sourceTimestampMs");
    const auto inactive_observed_at = number(controller, "inactiveObservedAt");
    if (!controller.ValueExists("observed") || !controller.GetObject("observed").IsBool() ||
        !controller.ValueExists("active") || !controller.GetObject("active").IsBool())
        throw std::runtime_error("agent shadow: invalid observation flags");
    state.activation.projection_version = static_cast<std::uint64_t>(version);
    state.activation.source_timestamp_ms = source_timestamp;
    state.activation.inactive_observed_at = inactive_observed_at;
    state.activation.observed = controller.GetBool("observed");
    state.activation.active = controller.GetBool("active");
    if (state.activation.observed != (version > 0) || state.activation.observed != (source_timestamp > 0) ||
        (!state.activation.observed && (state.activation.active || inactive_observed_at)) ||
        (state.activation.observed && !state.activation.active && !inactive_observed_at))
        throw std::runtime_error("agent shadow: inconsistent observation");
    if (has_activation) {
        auto value = object(reported, "activation");
        Activation activation{str(value, "id"), number(value, "startedAt"), number(value, "deadline")};
        if (!state.activation.observed || activation.deadline <= activation.started_at ||
            activation.deadline - activation.started_at > 3000)
            throw std::runtime_error("agent shadow: invalid activation deadline");
        state.activation.activation = std::move(activation);
    }
    if (has_run) {
        if (!state.activation.activation) throw std::runtime_error("agent shadow: run without activation");
        auto value = object(reported, "run");
        RunReservation run;
        run.run_id = str(value, "id"); run.release = str(value, "release");
        run.activation_id = str(controller, "runActivationId");
        run.request = str(controller, "launchRequest");
        run.phase = phase(str(controller, "runPhase"));
        if (run.request.size() > 2048) throw std::runtime_error("agent shadow: launch request too large");
        if (value.ValueExists("microvmId")) run.microvm_id = str(value, "microvmId");
        if (run.phase == RunPhase::running && run.microvm_id.empty())
            throw std::runtime_error("agent shadow: running without MicroVM identity");
        state.run = std::move(run);
    } else if (controller.ValueExists("runActivationId") || controller.ValueExists("runPhase") ||
               controller.ValueExists("launchRequest")) {
        throw std::runtime_error("agent shadow: orphan run metadata");
    }
    return snapshot;
}

std::string controller_shadow_patch(const ControllerSnapshot& snapshot, std::int64_t now,
                                    std::int64_t verified_at) {
    if (snapshot.shadow_version < 0 || snapshot.unverified_since < 0 || snapshot.stop_requested_at < 0 || now < 0 || verified_at < 0 || verified_at > now ||
        snapshot.state.activation.projection_version > static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()))
        throw std::invalid_argument("invalid controller shadow times or version");
    const auto& state = snapshot.state;
    JsonValue controller;
    controller.WithInt64("projectionVersion", state.activation.projection_version)
        .WithInt64("sourceTimestampMs", state.activation.source_timestamp_ms)
        .WithInt64("inactiveObservedAt", state.activation.inactive_observed_at)
        .WithInt64("unverifiedSince", snapshot.unverified_since)
        .WithBool("observed", state.activation.observed).WithBool("active", state.activation.active);
    JsonValue reported;
    if (snapshot.last_error.empty()) reported.WithNull("lastError");
    else reported.WithString("lastError", snapshot.last_error.c_str());
    if (state.activation.activation) {
        const auto& a = *state.activation.activation;
        JsonValue activation;
        activation.WithString("id", a.id.c_str()).WithInt64("startedAt", a.started_at).WithInt64("deadline", a.deadline);
        reported.WithObject("activation", std::move(activation));
    } else reported.WithNull("activation");
    JsonValue lifecycle;
    if (state.run) {
        const auto& r = *state.run;
        if (r.phase == RunPhase::stopping)
            controller.WithInt64("stopRequestedAt", snapshot.stop_requested_at ? snapshot.stop_requested_at : now);
        else controller.WithNull("stopRequestedAt");
        if (r.request.empty() || r.request.size() > 2048) throw std::invalid_argument("invalid launch request length");
        JsonValue run;
        run.WithString("id", r.run_id.c_str()).WithString("release", r.release.c_str());
        if (r.microvm_id.empty()) run.WithNull("microvmId");
        else run.WithString("microvmId", r.microvm_id.c_str());
        controller.WithString("runActivationId", r.activation_id.c_str()).WithString("runPhase", phase_name(r.phase))
            .WithString("launchRequest", r.request.c_str());
        reported.WithObject("run", std::move(run));
        const auto life = r.phase == RunPhase::reserved ? "starting" : r.phase == RunPhase::running ? "running" : "stopping";
        lifecycle.WithString("state", life);
        if (r.phase != RunPhase::stopping) lifecycle.WithInt64("verifiedAt", verified_at);
        if (r.phase != RunPhase::running) reported.WithNull("endpoint").WithNull("runtime");
    } else {
        controller.WithNull("stopRequestedAt");
        controller.WithNull("runActivationId").WithNull("runPhase").WithNull("launchRequest");
        reported.WithNull("run").WithNull("endpoint").WithNull("runtime");
        const bool expired = state.activation.activation && now >= state.activation.activation->deadline && state.activation.active;
        lifecycle.WithString("state", expired ? "expired" : "stopped");
    }
    reported.WithObject("controller", std::move(controller)).WithObject("lifecycle", std::move(lifecycle));
    JsonValue state_value; state_value.WithObject("reported", std::move(reported));
    JsonValue update; update.WithInt64("version", snapshot.shadow_version).WithObject("state", std::move(state_value));
    return update.View().WriteCompact().c_str();
}
}
