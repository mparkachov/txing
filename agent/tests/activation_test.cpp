#include "agent/activation.hpp"
#include "agent/controller.hpp"

#include <iostream>
#include <stdexcept>

using namespace txing::agent;
namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
void test_activation() {
    ActivationState state;
    unsigned ids = 0;
    auto id = [&] { return "activation-" + std::to_string(++ids); };
    auto observe = [&](std::uint64_t version, std::optional<bool> active, std::int64_t now) {
        return observe_activation(state, {version, active, static_cast<std::int64_t>(version * 1000)}, now, 3000, id);
    };
    require(observe(1, std::nullopt, 100) == ActivationChange::unverified && !state.observed,
            "incomplete projection became an observation");
    require(observe(2, true, 90) == ActivationChange::unchanged && !state.activation,
            "unbounded initial active state was authorized");
    require(observe(3, false, 100) == ActivationChange::inactive, "verified inactive state missing");
    require(observe(4, true, 101) == ActivationChange::activated, "observed activation missing");
    require(state.activation->deadline == 3100 && activation_authorized(state, 3099), "wrong activation budget");
    require(projection_matches_active(state, {4, true, 4000}) &&
            projection_matches_active(state, {5, true, 5000}) &&
            !projection_matches_active(state, {3, true, 3000}) &&
            !projection_matches_active(state, {4, true, 5000}) &&
            !projection_matches_active(state, {5, true, 3000}) &&
            !projection_matches_active(state, {5, false, 5000}),
            "runtime projection ordering admitted stale or inconsistent authority");
    require(observe(5, true, 3100) == ActivationChange::unchanged && ids == 1 &&
            !activation_authorized(state, 3100), "continuous active device rolled over");
    require(observe(6, std::nullopt, 3110) == ActivationChange::unverified, "invalid projection rearmed");
    require(observe(7, true, 3120) == ActivationChange::unchanged && ids == 1 &&
            state.activation->deadline == 3100, "missed inactivity reset the deadline");
    require(observe(8, false, 3130) == ActivationChange::inactive && !activation_authorized(state, 3130),
            "verified inactivity did not fence operation");
    require(observe(7, true, 3140) == ActivationChange::stale && ids == 1, "older active observation reactivated");
    require(observe(8, true, 3140) == ActivationChange::stale && ids == 1, "conflicting duplicate version reactivated");
    require(observe_activation(state, {9, true, 7000}, 3140, 3000, id) == ActivationChange::stale && ids == 1,
            "replayed source event on newer shadow version reactivated");
    require(observe(10, true, 3150) == ActivationChange::activated && ids == 2 &&
            state.activation->deadline == 6130 && activation_authorized(state, 3150), "observed transition did not reactivate");

    auto saved = state;
    bool failed = false;
    try { observe_activation(state, {11, false, 11000}, 3151, 3000, id);
          observe_activation(state, {12, true, 12000}, 3152, 3001, id); }
    catch (const std::invalid_argument&) { failed = true; }
    require(failed && state.projection_version == 11 && state.activation->id == saved.activation->id,
            "invalid budget changed persisted activation");
    ActivationState delayed;
    observe_activation(delayed, {1, false, 1000}, 100, 3000, id);
    require(observe_activation(delayed, {1, false, 1000}, 200, 3000, id) == ActivationChange::unchanged &&
            delayed.inactive_observed_at == 200, "fresh inactive verification was not retained");
    observe_activation(delayed, {2, true, 2000}, 3500, 3000, id);
    require(delayed.activation && delayed.activation->deadline == 3200 && !activation_authorized(delayed, 3500),
            "long observation gap silently extended activation budget");
    const auto start = std::chrono::steady_clock::time_point{};
    ExecutionDeadline deadline(3100, 100, start);
    require(!deadline.expired(99, start + std::chrono::seconds(2999)) &&
            deadline.expired(99, start + std::chrono::seconds(3000)) &&
            deadline.expired(3100, start + std::chrono::seconds(1)),
            "wall-clock change extended the persisted duration");
    bool too_long = false;
    try { ExecutionDeadline invalid(3101, 100, start); }
    catch (const std::invalid_argument&) { too_long = true; }
    require(too_long, "runtime accepted a deadline beyond the stage maximum");
}
void test_run_fencing() {
    constexpr auto active = CurrentLifecycle::active;
    constexpr auto inactive = CurrentLifecycle::inactive;
    constexpr auto unavailable = CurrentLifecycle::unavailable;
    ControllerState state;
    auto id = [] { return "activation-one"; };
    observe_activation(state.activation, {1, false, 1000}, 100, 3000, id);
    observe_activation(state.activation, {2, true, 2000}, 101, 3000, id);
    require(reserve_run(state, active, 101, "run-one", "1.0.0", "immutable-request"), "reservation failed");
    const auto saved = *state.run;
    require(!reserve_run(state, active, 102, "run-two", "2.0.0", "another-request") &&
            state.run->run_id == saved.run_id && state.run->request == saved.request,
            "ambiguous launch reservation was replaced");
    require(accept_launch(state, "run-one", "vm-one", false, unavailable, 102) == LaunchResult::pending_verification &&
            state.run->phase == RunPhase::reserved, "unverified launch became running");
    require(accept_launch(state, "run-one", "vm-one", true, active, 103) == LaunchResult::accepted &&
            state.run->phase == RunPhase::running,
            "current launch rejected");
    require(accept_launch(state, "run-one", "vm-two", true, active, 103) == LaunchResult::stop_unassigned,
            "duplicate VM was authorized");
    fence_run(state, active, 3100);
    require(state.run->phase == RunPhase::stopping &&
            !reserve_run(state, active, 3100, "run-two", "2.0.0", "another-request"), "expiry did not fence run");
    require(accept_launch(state, "run-one", "vm-one", true, active, 3101) == LaunchResult::stop_unassigned,
            "duplicate result restored expired run");
    require(!confirm_run_stopped(state, "run-one", "vm-two") &&
            confirm_run_stopped(state, "run-one", "vm-one"), "wrong terminal run accepted");
    require(!reserve_run(state, active, 3101, "run-two", "2.0.0", "another-request"), "expired activation restarted");
    observe_activation(state.activation, {3, false, 3000}, 3102, 3000, id);
    auto next = [] { return "activation-two"; };
    observe_activation(state.activation, {4, true, 4000}, 3103, 3000, next);
    require(reserve_run(state, active, 3103, "run-two", "2.0.0", "new-request"), "replacement activation blocked");
    require(accept_launch(state, "run-one", "vm-one", true, active, 3104) == LaunchResult::stop_unassigned &&
            state.run->run_id == "run-two", "stale launch result changed current run");
    fence_run(state, unavailable, 3104);
    require(state.run->phase == RunPhase::reserved, "transient verification error stopped the run");
    fence_run(state, inactive, 3105);
    require(accept_launch(state, "run-two", "vm-late", true, active, 3106) == LaunchResult::stop_unassigned &&
            state.run->phase == RunPhase::stopping, "late ambiguous launch restored authority");
}
}
int main() {
    try { test_activation(); test_run_fencing(); std::cout << "PASS activation expiry, launch identity and fencing\n"; }
    catch (const std::exception& error) { std::cerr << "FAIL " << error.what() << '\n'; return 1; }
}
