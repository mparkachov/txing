#pragma once

#include "agent/activation.hpp"

namespace txing::agent {
enum class RunPhase { reserved, running, stopping };

// The exact request is persisted before the first RunMicrovm call and reused
// byte-for-byte with run_id as its idempotency token after ambiguous outcomes.
struct RunReservation {
    std::string run_id, activation_id, release, request;
    std::string microvm_id;
    RunPhase phase = RunPhase::reserved;
};
struct ControllerState {
    ActivationState activation;
    std::optional<RunReservation> run;
};
enum class CurrentLifecycle { active, inactive, unavailable };
enum class LaunchResult { accepted, already_known, pending_verification, stop_unassigned };
bool valid_release(const std::string& value);

// All changes must be durably saved by a version-conditional write before
// network effects. This model does not itself serialize writers or call AWS.
bool reserve_run(ControllerState&, CurrentLifecycle current, std::int64_t now,
                 std::string run_id, std::string release, std::string exact_request);
LaunchResult accept_launch(ControllerState&, const std::string& run_id,
                           const std::string& microvm_id, bool host_running, CurrentLifecycle current,
                           std::int64_t now);
void fence_run(ControllerState&, CurrentLifecycle current, std::int64_t now);
bool confirm_run_stopped(ControllerState&, const std::string& run_id, const std::string& microvm_id);
}
