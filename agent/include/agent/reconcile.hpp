#pragma once
#include "agent/cloud.hpp"
#include "agent/controller_shadow.hpp"
#include <set>

namespace txing::agent {
// Adapters supply authoritative current reads. Event payloads are only hints
// identifying the Thing; they never establish lifecycle state or ordering.
class ReconcileBackend {
public:
    virtual ~ReconcileBackend() = default;
    virtual ControllerSnapshot read() = 0;
    virtual bool save(const ControllerSnapshot&, std::int64_t now, std::int64_t verified_at) = 0;
    virtual std::optional<bool> supported() = 0;
    virtual std::optional<ProjectionObservation> projection() = 0;
    virtual std::optional<bool> runtime_verified(const ControllerSnapshot&) { return {}; }
    virtual std::string identity() = 0;
    virtual std::string request(const std::string& run_id, const Activation&, std::int64_t now) = 0;
    virtual CloudRun launch(const RunReservation&) = 0;
    virtual CloudRun get(const std::string& id) = 0;
    virtual void terminate(const std::string& id) = 0;
};
enum class ReconcileResult { settled, again, conflict };

// One bounded pass. All launch reservations and state transitions are saved
// conditionally before their side effects. Caller schedules another pass on
// `again` or conflict and limits per-invocation work. Production supplies a
// wall clock so deadlines are rechecked after blocking network operations;
// steady elapsed time prevents a backwards wall-clock jump extending a pass.
ReconcileResult reconcile(ReconcileBackend&, std::int64_t now, const std::string& release,
                          const std::function<std::int64_t()>& clock = {});
std::vector<std::string> orphan_candidates(const std::vector<CloudRun>& inventory,
                                           const std::set<std::string>& assigned);
enum class OrphanAction { defer, retain, terminate, fence_then_terminate };
// Accept only a verified inactive observation under the same ordering rules as
// normal reconciliation. This never creates an activation or resets a budget.
bool observe_orphan_inactive(ControllerSnapshot&, const ProjectionObservation&, std::int64_t now);
OrphanAction orphan_action(std::optional<bool> supported, const ControllerSnapshot* shadow,
                           bool shadow_missing, const std::string& run_id,
                           const std::string& microvm_id, bool runtime_stopped, std::int64_t now);
// Bind an authenticated candidate to the same reservation before its
// conditional shadow write and termination; reject changed identities.
bool bind_stopping_orphan(ControllerSnapshot&, const std::string& run_id, const std::string& microvm_id);

// Termination-only repair for a globally disabled controller. The backend is
// scoped to its dedicated image; failures on one Thing or host must not stop
// the remaining hosts from being drained. False requests a later retry.
class DrainBackend {
public:
    virtual ~DrainBackend() = default;
    virtual std::vector<std::string> things() = 0;
    virtual bool fence(const std::string& thing) = 0;
    virtual void inventory(const std::function<void(const std::vector<CloudRun>&)>& visit) = 0;
    virtual void terminate(const std::string& id) = 0;
};
bool drain_disabled(DrainBackend&);

// Fallback when the configured image is missing: use only current, verifiable
// per-Thing assignments. It cannot discover unidentified orphans.
class KnownDrainBackend {
public:
    virtual ~KnownDrainBackend() = default;
    virtual std::vector<std::string> things() = 0;
    virtual std::optional<ControllerSnapshot> read(const std::string& thing) = 0;
    virtual CloudRunDetails describe(const std::string& id) = 0;
    virtual bool fence(const std::string& thing, ControllerSnapshot&) = 0;
    virtual void terminate(const std::string& id) = 0;
};
bool drain_known_assignments(KnownDrainBackend&);
}
