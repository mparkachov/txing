#pragma once
#include "agent/controller.hpp"

namespace txing::agent {
struct ControllerSnapshot {
    std::int64_t shadow_version = 0;
    std::int64_t verified_at = 0;
    std::int64_t unverified_since = 0;
    std::int64_t stop_requested_at = 0;
    std::string last_error;
    ControllerState state;
};

// Read only complete, internally consistent controller records. An existing
// activation without its reconciliation metadata is an error, never a new
// activation. The version belongs to the agent shadow, not Sparkplug.
ControllerSnapshot parse_controller_shadow(const std::string& document);

// Produce a version-conditional IoT shadow update. Callers must retry from a
// fresh GET after a conflict, before performing external side effects.
std::string controller_shadow_patch(const ControllerSnapshot&, std::int64_t now,
                                    std::int64_t verified_at);
}
