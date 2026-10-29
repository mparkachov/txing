#include "agent/activation.hpp"

#include <limits>
#include <stdexcept>

namespace txing::agent {
ActivationChange observe_activation(ActivationState& state, const ProjectionObservation& observation,
                                    std::int64_t now, std::int64_t budget_seconds,
                                    const std::function<std::string()>& new_id) {
    if (!observation.active || !observation.version || observation.source_timestamp_ms <= 0 || now < 0)
        return ActivationChange::unverified;
    if (state.observed && observation.version <= state.projection_version) {
        if (observation.version != state.projection_version || *observation.active != state.active ||
            observation.source_timestamp_ms != state.source_timestamp_ms) return ActivationChange::stale;
        if (!state.active && now > state.inactive_observed_at) state.inactive_observed_at = now;
        return ActivationChange::unchanged;
    }
    if (state.observed && observation.source_timestamp_ms <= state.source_timestamp_ms)
        return ActivationChange::stale;

    const bool active = *observation.active;
    const bool allocate = active && state.observed && !state.active;
    std::optional<Activation> next;
    if (allocate) {
        const auto started = state.inactive_observed_at;
        if (started <= 0 || started > now || budget_seconds <= 0 || budget_seconds > 3000 ||
            started > std::numeric_limits<std::int64_t>::max() - budget_seconds || !new_id)
            throw std::invalid_argument("invalid activation time, budget or identity source");
        auto id = new_id();
        if (id.empty() || id.size() > 128 ||
            id.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-:.") != std::string::npos ||
            (state.activation && id == state.activation->id))
            throw std::invalid_argument("activation identity must be new and nonempty");
        next = Activation{std::move(id), started, started + budget_seconds};
    }
    state.projection_version = observation.version;
    state.source_timestamp_ms = observation.source_timestamp_ms;
    state.observed = true;
    state.active = active;
    if (!active) state.inactive_observed_at = now;
    if (next) {
        state.activation = std::move(next);
        return ActivationChange::activated;
    }
    return active ? ActivationChange::unchanged : ActivationChange::inactive;
}

bool activation_authorized(const ActivationState& state, std::int64_t now) {
    return state.observed && state.active && state.activation && now >= state.activation->started_at &&
           now < state.activation->deadline;
}
bool projection_matches_active(const ActivationState& state, const ProjectionObservation& observation) {
    if (!state.observed || !state.active || !state.activation || !observation.active || !*observation.active ||
        !observation.version || observation.source_timestamp_ms <= 0) return false;
    if (observation.version == state.projection_version)
        return observation.source_timestamp_ms == state.source_timestamp_ms;
    return observation.version > state.projection_version && observation.source_timestamp_ms > state.source_timestamp_ms;
}
ExecutionDeadline::ExecutionDeadline(std::int64_t absolute, std::int64_t now,
                                     std::chrono::steady_clock::time_point steady_now)
    : absolute_(absolute) {
    if (now < 0 || absolute <= now || absolute - now > 3000)
        throw std::invalid_argument("activation deadline invalid or expired");
    steady_deadline_ = steady_now + std::chrono::seconds(absolute - now);
}
bool ExecutionDeadline::expired(std::int64_t now, std::chrono::steady_clock::time_point steady_now) const {
    return now >= absolute_ || steady_now >= steady_deadline_;
}
}
