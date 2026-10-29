#pragma once
#include "agent/controller_shadow.hpp"

namespace txing::agent {
std::string microvm_https_endpoint(const std::string& endpoint);
std::string safe_connection_diagnostic(const std::string& error);
// A terminal runtime report can fence its current run even when device
// lifecycle cannot be verified; it must never authorize an endpoint.
bool runtime_stopped_for(const ControllerSnapshot&, const std::string& thing, const std::string& sample);
// This evidence can only defer a stop of the same existing assignment; it
// cannot authorize a launch, endpoint publication, or a new activation.
bool runtime_verified_for(const ControllerSnapshot&, const std::string& thing, const std::string& sample,
                          std::int64_t elapsed_ms);
// A sample is accepted only for the currently reserved running assignment.
// The returned update carries the agent shadow version for optimistic locking.
std::string runtime_sample_patch(const ControllerSnapshot&, const std::string& endpoint,
                                 const std::string& sample, std::int64_t sampled_at);
}
