#include "agent/controller.hpp"

#include <stdexcept>

namespace txing::agent {
bool valid_release(const std::string& value) {
    unsigned parts = 0;
    std::size_t start = 0;
    while (start < value.size()) {
        const auto end = value.find('.', start);
        const auto part = value.substr(start, end == std::string::npos ? end : end - start);
        if (part.empty() || (part.size() > 1 && part.front() == '0') || part.find_first_not_of("0123456789") != std::string::npos)
            return false;
        ++parts;
        if (end == std::string::npos) return parts == 3;
        start = end + 1;
    }
    return false;
}
bool reserve_run(ControllerState& state, CurrentLifecycle current, std::int64_t now,
                 std::string run_id, std::string release, std::string exact_request) {
    if (state.run || current != CurrentLifecycle::active || !activation_authorized(state.activation, now)) return false;
    if (run_id.empty() || run_id.size() > 128 ||
        run_id.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-:.") != std::string::npos ||
        !valid_release(release) || exact_request.empty() || exact_request.size() > 2048)
        throw std::invalid_argument("valid run identity, semver release and bounded launch request are required");
    state.run = RunReservation{std::move(run_id), state.activation.activation->id,
                               std::move(release), std::move(exact_request), {}, RunPhase::reserved};
    return true;
}

LaunchResult accept_launch(ControllerState& state, const std::string& run_id,
                           const std::string& microvm_id, bool host_running, CurrentLifecycle current,
                           std::int64_t now) {
    if (microvm_id.empty()) throw std::invalid_argument("MicroVM identity required");
    if (!state.run || state.run->run_id != run_id ||
        (!state.run->microvm_id.empty() && state.run->microvm_id != microvm_id))
        return LaunchResult::stop_unassigned;
    const bool already_known = state.run->microvm_id == microvm_id;
    state.run->microvm_id = microvm_id;
    if (current == CurrentLifecycle::inactive || !activation_authorized(state.activation, now) ||
        state.run->activation_id != state.activation.activation->id || state.run->phase == RunPhase::stopping) {
        state.run->phase = RunPhase::stopping;
        return LaunchResult::stop_unassigned;
    }
    if (current == CurrentLifecycle::unavailable || !host_running) return LaunchResult::pending_verification;
    if (already_known && state.run->phase == RunPhase::running) return LaunchResult::already_known;
    state.run->phase = RunPhase::running;
    return LaunchResult::accepted;
}

void fence_run(ControllerState& state, CurrentLifecycle current, std::int64_t now) {
    if (state.run && (current == CurrentLifecycle::inactive || !activation_authorized(state.activation, now) ||
                      state.run->activation_id != state.activation.activation->id))
        state.run->phase = RunPhase::stopping;
}

bool confirm_run_stopped(ControllerState& state, const std::string& run_id, const std::string& microvm_id) {
    if (!state.run || state.run->run_id != run_id || state.run->phase != RunPhase::stopping ||
        state.run->microvm_id.empty() || state.run->microvm_id != microvm_id) return false;
    state.run.reset();
    return true;
}
}
