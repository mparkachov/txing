#pragma once

#include <cstdint>
#include <chrono>
#include <functional>
#include <optional>
#include <string>

namespace txing::agent {

// Persist this record using a conditional write before taking launch actions.
// A projection version is the IoT shadow version returned by the current GET,
// never the version or payload of the event which triggered reconciliation.
struct Activation {
    std::string id;
    std::int64_t started_at = 0;
    std::int64_t deadline = 0;
};
struct ActivationState {
    std::uint64_t projection_version = 0;
    std::int64_t source_timestamp_ms = 0;
    std::int64_t inactive_observed_at = 0;
    bool observed = false;
    bool active = false;
    std::optional<Activation> activation;
};
struct ProjectionObservation {
    std::uint64_t version = 0;
    // Missing means that the current projection could not be verified. In
    // particular, missing metrics must not be interpreted as inactivity.
    std::optional<bool> active;
    // Original Sparkplug payload timestamp; used only to reject replayed or
    // out-of-order projections, never as a trusted activation clock.
    std::int64_t source_timestamp_ms = 0;
    // Runtime stream selection uses this same verified shadow read. This is
    // transient device state, not part of the persisted activation record.
    int redcon = 4;
};
enum class ActivationChange { unverified, stale, unchanged, inactive, activated };

// Transition only on newer verified current shadow versions. IDs are allocated
// only for an observed inactive->active edge. A first observation that is
// already active has no provable activation boundary and fails closed.
// Duplicate/out-of-order deliveries and a continuously active expired device
// cannot allocate a new activation. A missed inactive interval fails closed.
ActivationChange observe_activation(ActivationState&, const ProjectionObservation&,
                                    std::int64_t now, std::int64_t budget_seconds,
                                    const std::function<std::string()>& new_id);
bool activation_authorized(const ActivationState&, std::int64_t now);
// Check a current active projection against the persisted assignment without
// creating a transition or changing the activation's budget.
bool projection_matches_active(const ActivationState&, const ProjectionObservation&);

// Enforce the persisted wall-clock limit even if the local wall clock later
// moves backwards. The steady-clock limit can only shorten execution.
class ExecutionDeadline {
public:
    ExecutionDeadline(std::int64_t absolute, std::int64_t now,
                      std::chrono::steady_clock::time_point steady_now);
    bool expired(std::int64_t now, std::chrono::steady_clock::time_point steady_now) const;
private:
    std::int64_t absolute_;
    std::chrono::steady_clock::time_point steady_deadline_;
};

}
