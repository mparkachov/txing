#include "agent/reconcile.hpp"
#include <algorithm>
#include <limits>
#include <stdexcept>

namespace txing::agent {
ReconcileResult reconcile(ReconcileBackend& io, std::int64_t now, const std::string& release,
                          const std::function<std::int64_t()>& clock) {
    if (now <= 0 || release.empty()) throw std::invalid_argument("reconciliation requires time and release");
    auto anchor_wall = now;
    auto anchor_steady = std::chrono::steady_clock::now();
    const auto current_time = [&]() -> std::int64_t {
        const auto sampled = clock ? clock() : now;
        if (sampled <= 0) throw std::runtime_error("controller clock unavailable");
        const auto steady_now = std::chrono::steady_clock::now();
        const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(steady_now - anchor_steady).count();
        if (elapsed < 0 || anchor_wall > std::numeric_limits<std::int64_t>::max() - elapsed)
            throw std::runtime_error("controller clock overflow");
        const auto projected = anchor_wall + elapsed;
        if (sampled > projected) { anchor_wall = sampled; anchor_steady = steady_now; return sampled; }
        return projected;
    };
    auto snapshot = io.read();
    auto current = CurrentLifecycle::unavailable;
    const auto supported = io.supported();
    if (supported && !*supported) current = CurrentLifecycle::inactive;
    if (supported && *supported) {
        const auto projection = io.projection();
        if (projection && projection->active) {
            const auto change = observe_activation(snapshot.state.activation, *projection, now, 3000, [&] { return io.identity(); });
            if (change != ActivationChange::unverified && change != ActivationChange::stale) {
                current = *projection->active ? CurrentLifecycle::active : CurrentLifecycle::inactive;
                snapshot.verified_at = now;
            }
        }
    }
    if (current == CurrentLifecycle::unavailable) snapshot.last_error = "registry or lifecycle verification unavailable or stale";
    else if (supported && !*supported) snapshot.last_error = "agent capability is not declared";
    else snapshot.last_error.clear();
    auto decision_time = now;
    if (current == CurrentLifecycle::unavailable && snapshot.state.run) {
        // Match the runtime's fifteen-second verification limit without
        // treating missing or stale projection data as an inactive edge.
        // The controller may poll less often than the runtime, so start the
        // interval at its first failed verification, not its last sweep.
        decision_time = current_time();
        if (!snapshot.unverified_since) snapshot.unverified_since = decision_time;
        else if (decision_time < snapshot.unverified_since) snapshot.state.run->phase = RunPhase::stopping;
        else if (decision_time - snapshot.unverified_since >= 15) {
            const bool may_defer = snapshot.state.run->phase == RunPhase::running &&
                activation_authorized(snapshot.state.activation, decision_time) &&
                io.runtime_verified(snapshot).value_or(false);
            decision_time = current_time();
            if (!may_defer) snapshot.state.run->phase = RunPhase::stopping;
        }
    } else snapshot.unverified_since = 0;
    if (snapshot.verified_at > decision_time) {
        if (snapshot.state.run) snapshot.state.run->phase = RunPhase::stopping;
        snapshot.verified_at = 0;
    }
    fence_run(snapshot.state, current, decision_time);
    if (snapshot.state.run && snapshot.state.run->phase == RunPhase::stopping &&
        snapshot.state.run->microvm_id.empty() && current == CurrentLifecycle::active &&
        activation_authorized(snapshot.state.activation, decision_time) &&
        snapshot.state.run->activation_id != snapshot.state.activation.activation->id) {
        // A directly observed new activation supersedes this unidentified
        // launch. Never retry it or let it block the new activation forever.
        // The next conditional write revokes its assignment; late results
        // and any leftover compute are handled as unassigned/orphaned VMs.
        snapshot.state.run.reset();
        snapshot.stop_requested_at = 0;
    }
    if (!snapshot.state.run && current == CurrentLifecycle::active && activation_authorized(snapshot.state.activation, decision_time)) {
        const auto run_id = io.identity();
        auto exact = io.request(run_id, *snapshot.state.activation.activation, decision_time);
        reserve_run(snapshot.state, current, decision_time, run_id, release, std::move(exact));
    }
    if (!io.save(snapshot, decision_time, snapshot.verified_at)) return ReconcileResult::conflict;
    if (!snapshot.state.run) return ReconcileResult::settled;

    const auto saved_run = *snapshot.state.run;
    if (saved_run.microvm_id.empty()) {
        // A retry can create a VM if the previous request never arrived. Do
        // not make one after fencing or while lifecycle cannot be verified.
        // The inventory sweep can identify a VM that actually started by its
        // authenticated runtime identity and attach it to this reservation.
        if (saved_run.phase == RunPhase::stopping || current != CurrentLifecycle::active)
            return ReconcileResult::settled;
        const auto before_launch = current_time();
        if (!activation_authorized(snapshot.state.activation, before_launch)) {
            auto latest = io.read();
            if (!latest.state.run || latest.state.run->run_id != saved_run.run_id) return ReconcileResult::again;
            latest.state.run->phase = RunPhase::stopping;
            if (!io.save(latest, before_launch, latest.verified_at)) return ReconcileResult::conflict;
            return ReconcileResult::again;
        }
        // Reuse the identical request while the activation remains authorized.
        const auto launched = io.launch(saved_run);
        if (launched.id.empty()) throw std::runtime_error("RunMicrovm returned no identity");
        for (unsigned attempt = 0; attempt < 3; ++attempt) {
            auto latest = io.read();
            const auto after_launch = current_time();
            const auto result = accept_launch(latest.state, saved_run.run_id, launched.id, false,
                                              CurrentLifecycle::unavailable, after_launch);
            // Never terminate a VM that a newer reservation already names.
            if (result == LaunchResult::stop_unassigned && latest.state.run &&
                latest.state.run->run_id != saved_run.run_id && latest.state.run->microvm_id == launched.id)
                return ReconcileResult::again;
            if (!io.save(latest, after_launch, latest.verified_at)) continue;
            if (result == LaunchResult::stop_unassigned) io.terminate(launched.id);
            return ReconcileResult::again;
        }
        return ReconcileResult::conflict;
    }

    const auto host = io.get(saved_run.microvm_id);
    if (host.id != saved_run.microvm_id) throw std::runtime_error("MicroVM lookup returned wrong identity");
    if (host.state == "TERMINATED") {
        snapshot.state.run->phase = RunPhase::stopping;
        if (!confirm_run_stopped(snapshot.state, saved_run.run_id, saved_run.microvm_id))
            throw std::logic_error("could not clear terminal run");
        // The earlier write advanced the version. Resample and compare before
        // clearing so a late terminal response cannot erase a replacement.
        auto latest = io.read();
        if (!latest.state.run || latest.state.run->run_id != saved_run.run_id ||
            latest.state.run->microvm_id != saved_run.microvm_id) return ReconcileResult::again;
        latest.state.run->phase = RunPhase::stopping;
        confirm_run_stopped(latest.state, saved_run.run_id, saved_run.microvm_id);
        if (!io.save(latest, now, latest.verified_at)) return ReconcileResult::conflict;
        return ReconcileResult::again;
    }
    if (saved_run.phase != RunPhase::stopping &&
        (host.state == "SUSPENDED" || host.state == "SUSPENDING" || host.state == "TERMINATING")) {
        auto latest = io.read();
        if (!latest.state.run || latest.state.run->run_id != saved_run.run_id ||
            latest.state.run->microvm_id != saved_run.microvm_id) return ReconcileResult::again;
        latest.state.run->phase = RunPhase::stopping;
        if (!io.save(latest, now, latest.verified_at)) return ReconcileResult::conflict;
        if (host.state != "TERMINATING") io.terminate(saved_run.microvm_id);
        return ReconcileResult::again;
    }
    if (saved_run.phase == RunPhase::stopping) {
        if (host.state != "TERMINATING") io.terminate(saved_run.microvm_id);
        return ReconcileResult::again;
    }
    if (saved_run.phase == RunPhase::reserved && host.state == "RUNNING" && current == CurrentLifecycle::active) {
        const auto still_supported = io.supported();
        const auto fresh = io.projection();
        if (!still_supported || !*still_supported || !fresh || !fresh->active || !*fresh->active ||
            fresh->version != snapshot.state.activation.projection_version ||
            fresh->source_timestamp_ms != snapshot.state.activation.source_timestamp_ms)
            return ReconcileResult::again;
        const auto verified_at = current_time();
        auto latest = io.read();
        // Verify the same persisted observation still belongs to this run.
        if (!latest.state.run || latest.state.run->run_id != saved_run.run_id ||
            latest.state.activation.projection_version != snapshot.state.activation.projection_version)
            return ReconcileResult::again;
        const auto assigned_at = current_time();
        // Do not turn an old lifecycle read into a freshly authorized run
        // after a slow shadow read. An expired budget is still fenced below.
        if (assigned_at - verified_at >= 15 && activation_authorized(latest.state.activation, assigned_at))
            return ReconcileResult::again;
        const auto result = accept_launch(latest.state, saved_run.run_id, saved_run.microvm_id, true, current, assigned_at);
        if (!io.save(latest, assigned_at, verified_at)) return ReconcileResult::conflict;
        if (result == LaunchResult::stop_unassigned) io.terminate(saved_run.microvm_id);
        return ReconcileResult::again;
    }
    return saved_run.phase == RunPhase::reserved ? ReconcileResult::again : ReconcileResult::settled;
}

std::vector<std::string> orphan_candidates(const std::vector<CloudRun>& inventory,
                                           const std::set<std::string>& assigned) {
    std::vector<std::string> orphans;
    std::set<std::string> seen;
    for (const auto& run : inventory) {
        if (run.id.empty() || assigned.count(run.id)) continue;
        if ((run.state == "PENDING" || run.state == "RUNNING" || run.state == "SUSPENDING" || run.state == "SUSPENDED") &&
            seen.insert(run.id).second)
            orphans.push_back(run.id);
    }
    return orphans;
}
bool observe_orphan_inactive(ControllerSnapshot& snapshot, const ProjectionObservation& observation, std::int64_t now) {
    if (!snapshot.state.run || !observation.active || *observation.active || now <= 0) return false;
    const auto change = observe_activation(snapshot.state.activation, observation, now, 3000, {});
    if (change == ActivationChange::unverified || change == ActivationChange::stale) return false;
    snapshot.verified_at = now;
    return true;
}
OrphanAction orphan_action(std::optional<bool> supported, const ControllerSnapshot* shadow,
                           bool shadow_missing, const std::string& run_id,
                           const std::string& microvm_id, bool runtime_stopped, std::int64_t now) {
    if (!supported || run_id.empty() || microvm_id.empty() || now <= 0 || (!shadow && !shadow_missing))
        return OrphanAction::defer;
    const bool assigned = shadow && shadow->state.run && shadow->state.run->run_id == run_id &&
                          (shadow->state.run->microvm_id.empty() || shadow->state.run->microvm_id == microvm_id);
    if (assigned) return !*supported || runtime_stopped || shadow->state.run->phase == RunPhase::stopping ||
        !activation_authorized(shadow->state.activation, now) ||
        shadow->state.run->activation_id != shadow->state.activation.activation->id
        ? OrphanAction::fence_then_terminate : OrphanAction::retain;
    return OrphanAction::terminate;
}
bool bind_stopping_orphan(ControllerSnapshot& snapshot, const std::string& run_id, const std::string& microvm_id) {
    if (run_id.empty() || microvm_id.empty() || !snapshot.state.run || snapshot.state.run->run_id != run_id ||
        (!snapshot.state.run->microvm_id.empty() && snapshot.state.run->microvm_id != microvm_id)) return false;
    snapshot.state.run->microvm_id = microvm_id;
    snapshot.state.run->phase = RunPhase::stopping;
    return true;
}
bool drain_disabled(DrainBackend& io) {
    bool complete = true;
    // Termination comes first: a large or failing Thing registry must not use
    // the invocation's entire time budget before any VM can be stopped.
    try {
        std::set<std::string> seen;
        io.inventory([&](const std::vector<CloudRun>& page) {
            for (const auto& run : page) {
                if (run.id.empty()) { complete = false; continue; }
                if (run.state == "TERMINATED") continue;
                // A successful API response only starts termination; a later
                // inventory must confirm that no nonterminal host remains.
                complete = false;
                if (run.state == "TERMINATING") continue;
                if (run.state != "PENDING" && run.state != "RUNNING" &&
                    run.state != "SUSPENDING" && run.state != "SUSPENDED") continue;
                if (!seen.insert(run.id).second) continue;
                try { io.terminate(run.id); }
                catch (const std::exception&) { complete = false; }
            }
        });
    } catch (const std::exception&) { complete = false; }
    try {
        for (const auto& thing : io.things()) {
            try { if (!io.fence(thing)) complete = false; }
            catch (const std::exception&) { complete = false; }
        }
    } catch (const std::exception&) { complete = false; }
    return complete;
}
bool drain_known_assignments(KnownDrainBackend& io) {
    bool complete = true;
    try {
        for (const auto& thing : io.things()) {
            try {
                auto snapshot = io.read(thing);
                if (!snapshot || !snapshot->state.run) continue;
                const auto run = *snapshot->state.run;
                if (run.microvm_id.empty()) { complete = false; continue; }
                const auto expected_image = saved_launch_image(run.request, run.run_id, thing, run.activation_id);
                const auto host = io.describe(run.microvm_id);
                if (host.run.id != run.microvm_id || host.image != expected_image) { complete = false; continue; }
                if (!io.fence(thing, *snapshot)) { complete = false; continue; }
                if (host.run.state == "TERMINATED") continue;
                complete = false;
                if (host.run.state == "PENDING" || host.run.state == "RUNNING" ||
                    host.run.state == "SUSPENDING" || host.run.state == "SUSPENDED") io.terminate(run.microvm_id);
            } catch (const std::exception&) { complete = false; }
        }
    } catch (const std::exception&) { complete = false; }
    return complete;
}
}
