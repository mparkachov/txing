#pragma once
#include "agent/cloud.hpp"
#include <aws/core/auth/AWSCredentialsProvider.h>
#include <aws/core/client/ClientConfiguration.h>
#include <functional>
#include <vector>

namespace txing::agent {
struct ControllerConfig {
    CloudConfig cloud;
    std::string release;
};
bool controller_configured(const ControllerConfig&);
// Only an explicitly enabled controller with complete configuration may
// reconcile/launch. All other states attempt termination-only repair first.
void controller_dispatch_automation(const std::string& setting, bool configured,
                                    const std::function<void()>& reconcile,
                                    const std::function<void()>& drain);
// Run one registry sweep stage independently for each Thing. A confirmed
// missing agent capability shadow is skipped; other failures make the stage
// incomplete. Orphan candidates always require independent verification.
bool controller_sweep_each(const std::vector<std::string>& things, const char* stage,
                           const std::function<void(const std::string&)>& visit);
// Always check for an already-stopped runtime, even after reconciliation
// fails. In that case the sample must be stop-only and the original failure
// must still be returned to the event source for retry.
void controller_event_repair(const std::function<void()>& reconcile,
                             const std::function<void(bool stop_only)>& sample);
// Invoked only by the Lambda bootstrap. The function reads current registry and
// shadow state; it never trusts lifecycle state in an event notification.
void handle_controller_event(const std::string& event, const ControllerConfig&,
                             std::shared_ptr<Aws::Auth::AWSCredentialsProvider>,
                             Aws::Client::ClientConfiguration);
// A disabled schedule performs termination only; it never starts a VM.
void handle_disabled_event(const std::string& event, const ControllerConfig&,
                           std::shared_ptr<Aws::Auth::AWSCredentialsProvider>,
                           Aws::Client::ClientConfiguration);
}
