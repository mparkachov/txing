#include "agent/reconcile.hpp"
#include <iostream>
#include <atomic>
#include <mutex>
#include <map>
#include <stdexcept>
#include <thread>

using namespace txing::agent;
namespace {
void require(bool condition, const char* message) { if (!condition) throw std::runtime_error(message); }
struct Fake : ReconcileBackend {
    ControllerSnapshot stored;
    std::optional<ProjectionObservation> observed = ProjectionObservation{1, false, 1000};
    std::optional<bool> type = true;
    std::optional<bool> runtime_fresh;
    bool conflict = false, ambiguous = false, conflict_after_launch = false, takeover_on_conflict = false;
    unsigned ids = 0, launches = 0, terminations = 0;
    CloudRun host{"vm-1", "PENDING", "endpoint"};
    std::map<std::string, std::string> launched_requests;
    std::function<void(ControllerSnapshot&)> during_launch;
    std::mutex mutex;
    ControllerSnapshot read() override { std::lock_guard<std::mutex> lock(mutex); return stored; }
    bool save(const ControllerSnapshot& value, std::int64_t, std::int64_t verified) override {
        std::lock_guard<std::mutex> lock(mutex);
        if (conflict) {
            conflict = false; ++stored.shadow_version;
            if (takeover_on_conflict && stored.state.run) {
                stored.state.run->run_id = "newer-run";
                stored.state.run->microvm_id = host.id;
                stored.state.run->phase = RunPhase::running;
            }
            return false;
        }
        if (value.shadow_version != stored.shadow_version) return false;
        stored = value; ++stored.shadow_version; stored.verified_at = verified; return true;
    }
    std::optional<bool> supported() override { return type; }
    std::optional<ProjectionObservation> projection() override { return observed; }
    std::optional<bool> runtime_verified(const ControllerSnapshot&) override { return runtime_fresh; }
    std::string identity() override { std::lock_guard<std::mutex> lock(mutex); return "identity-" + std::to_string(++ids); }
    std::string request(const std::string& run, const Activation& activation, std::int64_t) override {
        return run + ":" + activation.id + ":" + std::to_string(activation.deadline);
    }
    CloudRun launch(const RunReservation& run) override {
        std::lock_guard<std::mutex> lock(mutex);
        ++launches;
        const auto recorded = launched_requests.emplace(run.run_id, run.request);
        require(run.request == recorded.first->second, "retry changed launch request");
        if (ambiguous) { ambiguous = false; throw std::runtime_error("ambiguous test result"); }
        if (during_launch) during_launch(stored);
        if (conflict_after_launch) { conflict_after_launch = false; conflict = true; }
        return host;
    }
    CloudRun get(const std::string& id) override { std::lock_guard<std::mutex> lock(mutex); require(id == host.id, "wrong host lookup"); return host; }
    void terminate(const std::string& id) override { std::lock_guard<std::mutex> lock(mutex); require(id == host.id, "wrong host termination"); ++terminations; host.state = "TERMINATING"; }
};
struct FakeDrain : DrainBackend {
    bool registry_failure = false, inventory_failure = false, page_failure = false;
    bool fence_failure = false, terminate_failure = false, all_terminal = false;
    std::vector<std::string> fenced, terminated, operations;
    std::vector<std::string> things() override {
        operations.push_back("things");
        if (registry_failure) throw std::runtime_error("registry unavailable");
        return {"one", "two"};
    }
    bool fence(const std::string& thing) override {
        operations.push_back("fence"); fenced.push_back(thing); return !fence_failure || thing != "one";
    }
    void inventory(const std::function<void(const std::vector<CloudRun>&)>& visit) override {
        operations.push_back("inventory");
        if (inventory_failure) throw std::runtime_error("inventory unavailable");
        if (all_terminal) { visit({{"one", "TERMINATED", {}}, {"two", "TERMINATED", {}}}); return; }
        visit({{"one", "TERMINATED", {}}, {"one", "RUNNING", {}}, {"one", "RUNNING", {}}});
        operations.push_back("page2");
        if (page_failure) throw std::runtime_error("later page unavailable");
        visit({{"two", "TERMINATING", {}}, {"two", "PENDING", {}},
               {"three", "UNKNOWN", {}}, {"three", "SUSPENDED", {}},
               {"done", "TERMINATED", {}}, {"ending", "TERMINATING", {}}});
    }
    void terminate(const std::string& id) override {
        operations.push_back("terminate"); terminated.push_back(id);
        if (terminate_failure && id == "one") throw std::runtime_error("terminate unavailable");
    }
};
void tests() {
    FakeDrain drain;
    require(!drain_disabled(drain) && drain.fenced == std::vector<std::string>({"one", "two"}) &&
            drain.terminated == std::vector<std::string>({"one", "two", "three"}) &&
            drain.operations == std::vector<std::string>({"inventory", "terminate", "page2", "terminate", "terminate", "things", "fence", "fence"}),
            "disabled drain did not fence and terminate each nonterminal VM exactly once");
    drain.all_terminal = true;
    require(drain_disabled(drain), "disabled drain reported complete before terminal inventory or failed to complete after it");
    FakeDrain partial;
    partial.fence_failure = true; partial.terminate_failure = true;
    require(!drain_disabled(partial) && partial.fenced.size() == 2 && partial.terminated.size() == 3,
            "partial failure must request a retry while continuing other termination attempts");
    FakeDrain registry_down;
    registry_down.registry_failure = true;
    require(!drain_disabled(registry_down) && registry_down.terminated.size() == 3,
            "registry failure prevented termination of the dedicated image's VMs");
    FakeDrain inventory_down;
    inventory_down.inventory_failure = true;
    require(!drain_disabled(inventory_down) && inventory_down.fenced.size() == 2,
            "inventory failure did not fence assignments or request a retry");
    FakeDrain late_page;
    late_page.page_failure = true;
    require(!drain_disabled(late_page) && late_page.terminated == std::vector<std::string>({"one"}) &&
            late_page.fenced.size() == 2, "later inventory failure erased progress on the first page");
    Fake io;
    require(reconcile(io, 100, "1.0.0") == ReconcileResult::settled && !io.stored.state.run,
            "inactive device launched");
    io.observed = ProjectionObservation{2, true, 2000};
    io.ambiguous = true;
    bool failed = false;
    try { reconcile(io, 101, "1.0.0"); }
    catch (const std::runtime_error&) { failed = true; }
    require(failed, "ambiguous launch did not fail");
    require(io.stored.state.run && io.stored.state.run->phase == RunPhase::reserved && io.launches == 1,
            "launch identity was not persisted before call");
    const auto run = io.stored.state.run->run_id;
    const auto deadline = io.stored.state.activation.activation->deadline;
    reconcile(io, 102, "2.0.0");
    require(io.launches == 2 && io.stored.state.run->run_id == run && io.stored.state.run->release == "1.0.0" &&
            io.stored.state.activation.activation->deadline == deadline && io.stored.state.run->microvm_id == "vm-1",
            "ambiguous launch was not recovered using original reservation");
    io.host.state = "RUNNING";
    reconcile(io, 103, "2.0.0");
    require(io.stored.state.run->phase == RunPhase::running, "running host was not assigned");
    io.observed.reset();
    reconcile(io, 104, "2.0.0");
    require(io.terminations == 0 && io.stored.state.run->phase == RunPhase::running && !io.stored.last_error.empty(),
            "temporary verification failure replaced a healthy host");
    Fake verification_timeout;
    reconcile(verification_timeout, 100, "1.0.0");
    verification_timeout.observed = ProjectionObservation{2, true, 2000};
    reconcile(verification_timeout, 101, "1.0.0");
    verification_timeout.host.state = "RUNNING";
    reconcile(verification_timeout, 102, "1.0.0");
    verification_timeout.observed.reset();
    reconcile(verification_timeout, 116, "1.0.0");
    require(verification_timeout.terminations == 0 && verification_timeout.stored.state.run->phase == RunPhase::running &&
            verification_timeout.stored.unverified_since == 116,
            "temporary lifecycle read failure prematurely terminated a healthy host");
    reconcile(verification_timeout, 130, "1.0.0");
    require(verification_timeout.terminations == 0, "verification deadline fired before fifteen seconds");
    reconcile(verification_timeout, 131, "1.0.0");
    require(verification_timeout.terminations == 1 && verification_timeout.stored.state.run->phase == RunPhase::stopping &&
            verification_timeout.stored.state.activation.active &&
            verification_timeout.stored.state.activation.activation->deadline == 3100,
            "verification timeout did not fence the VM without inventing an inactive transition");
    Fake runtime_independent;
    reconcile(runtime_independent, 100, "1.0.0");
    runtime_independent.observed = ProjectionObservation{2, true, 2000};
    reconcile(runtime_independent, 101, "1.0.0");
    runtime_independent.host.state = "RUNNING";
    reconcile(runtime_independent, 102, "1.0.0");
    runtime_independent.observed.reset();
    reconcile(runtime_independent, 116, "1.0.0");
    runtime_independent.runtime_fresh = true;
    reconcile(runtime_independent, 131, "1.0.0");
    require(runtime_independent.terminations == 0 && runtime_independent.stored.unverified_since == 116 &&
            runtime_independent.stored.state.activation.activation->deadline == 3100,
            "fresh runtime evidence replaced a healthy VM or refreshed the activation");
    runtime_independent.runtime_fresh = false;
    reconcile(runtime_independent, 132, "1.0.0");
    require(runtime_independent.terminations == 1, "stale runtime evidence did not fence the VM");
    Fake slow_verification;
    reconcile(slow_verification, 100, "1.0.0");
    slow_verification.observed = ProjectionObservation{2, true, 2000};
    reconcile(slow_verification, 101, "1.0.0");
    slow_verification.host.state = "RUNNING";
    reconcile(slow_verification, 102, "1.0.0");
    slow_verification.observed = ProjectionObservation{3, false, 1500};
    reconcile(slow_verification, 116, "1.0.0", [] { return 117; });
    require(slow_verification.terminations == 0 && slow_verification.stored.unverified_since == 117,
            "stale lifecycle data did not start a new unverified interval");
    reconcile(slow_verification, 132, "1.0.0");
    require(slow_verification.terminations == 1 && slow_verification.stored.state.activation.active &&
            slow_verification.stored.state.activation.projection_version == 2,
            "slow stale verification did not stop the VM or incorrectly created an inactive edge");
    Fake recovered_verification;
    reconcile(recovered_verification, 100, "1.0.0");
    recovered_verification.observed = ProjectionObservation{2, true, 2000};
    reconcile(recovered_verification, 101, "1.0.0");
    recovered_verification.host.state = "RUNNING";
    reconcile(recovered_verification, 102, "1.0.0");
    recovered_verification.observed.reset();
    reconcile(recovered_verification, 116, "1.0.0");
    recovered_verification.observed = ProjectionObservation{3, true, 3000};
    reconcile(recovered_verification, 120, "1.0.0");
    require(recovered_verification.stored.unverified_since == 0 && recovered_verification.terminations == 0,
            "successful lifecycle verification did not clear the outage interval");
    recovered_verification.observed.reset();
    reconcile(recovered_verification, 121, "1.0.0");
    reconcile(recovered_verification, 135, "1.0.0");
    require(recovered_verification.terminations == 0, "a previous outage shortened the new verification window");
    reconcile(recovered_verification, 136, "1.0.0");
    require(recovered_verification.terminations == 1, "a second verification outage did not stop the VM");
    Fake verification_clock;
    reconcile(verification_clock, 100, "1.0.0");
    verification_clock.observed = ProjectionObservation{2, true, 2000};
    reconcile(verification_clock, 101, "1.0.0");
    verification_clock.host.state = "RUNNING";
    reconcile(verification_clock, 102, "1.0.0");
    verification_clock.observed.reset();
    reconcile(verification_clock, 116, "1.0.0");
    reconcile(verification_clock, 115, "1.0.0");
    require(verification_clock.terminations == 1 && verification_clock.stored.state.run->phase == RunPhase::stopping,
            "backward wall clock incorrectly extended a persisted unverified interval");
    io.observed = ProjectionObservation{3, true, 3000};
    reconcile(io, deadline, "2.0.0");
    require(io.terminations == 1 && io.stored.state.run->phase == RunPhase::stopping,
            "expiry did not fence before termination");
    io.host.state = "TERMINATED";
    reconcile(io, deadline + 1, "2.0.0");
    require(!io.stored.state.run, "terminal run was not cleared");
    reconcile(io, deadline + 2, "2.0.0");
    require(!io.stored.state.run && io.launches == 2, "continuous active expiry rolled over");
    io.observed = ProjectionObservation{4, false, 4000};
    reconcile(io, deadline + 3, "2.0.0");
    io.observed = ProjectionObservation{5, true, 3000};
    reconcile(io, deadline + 4, "2.0.0");
    require(!io.stored.state.run, "replayed source transition restarted expired activation");
    io.observed = ProjectionObservation{6, true, 6000};
    io.conflict = true;
    require(reconcile(io, deadline + 5, "2.0.0") == ReconcileResult::conflict && io.launches == 2,
            "conflicting conditional update performed a launch");
    const std::vector<CloudRun> inventory = {{"assigned", "RUNNING", {}}, {"orphan", "TERMINATED", {}},
        {"orphan", "UNKNOWN", {}}, {"orphan", "PENDING", {}},
        {"orphan", "PENDING", {}}, {"done", "TERMINATED", {}}, {"unknown", "UNKNOWN", {}}};
    const auto orphans = orphan_candidates(inventory, {"assigned"});
    require(orphans.size() == 1 && orphans.front() == "orphan", "orphan cleanup selected an assigned or terminal VM");
    ControllerSnapshot assigned;
    assigned.state.run = RunReservation{"run", "activation", "1.0.0", "request", "vm", RunPhase::running};
    assigned.state.activation.observed = true;
    assigned.state.activation.active = true;
    assigned.state.activation.projection_version = 2;
    assigned.state.activation.source_timestamp_ms = 2000;
    assigned.state.activation.activation = Activation{"activation", 100, 3100};
    require(orphan_action(true, &assigned, false, "run", "vm", false, 101) == OrphanAction::retain &&
            orphan_action(true, &assigned, false, "run", "vm", true, 101) == OrphanAction::fence_then_terminate &&
            orphan_action(false, &assigned, false, "run", "vm", false, 101) == OrphanAction::fence_then_terminate &&
            orphan_action(true, &assigned, false, "run", "vm", false, 3100) == OrphanAction::fence_then_terminate &&
            orphan_action(true, &assigned, false, "run", "vm", false, 0) == OrphanAction::defer &&
            orphan_action(true, &assigned, false, "different", "vm", false, 101) == OrphanAction::terminate &&
            orphan_action(true, nullptr, true, "run", "vm", false, 101) == OrphanAction::terminate &&
            orphan_action(true, nullptr, false, "run", "vm", false, 101) == OrphanAction::defer &&
            orphan_action({}, &assigned, false, "run", "vm", false, 101) == OrphanAction::defer,
            "orphan verification did not protect a current or uncertain assignment");
    auto observed_inactive = assigned;
    require(!observe_orphan_inactive(observed_inactive, {3, false, 1500}, 101) &&
            !observe_orphan_inactive(observed_inactive, {2, false, 2000}, 101) &&
            !observe_orphan_inactive(observed_inactive, {3, {}, 3000}, 101) &&
            !observe_orphan_inactive(observed_inactive, {3, true, 3000}, 101) &&
            observed_inactive.state.activation.active,
            "stale or unverified projection fenced an active assignment");
    require(observe_orphan_inactive(observed_inactive, {3, false, 3000}, 101) &&
            observed_inactive.state.activation.activation->deadline == 3100 &&
            observed_inactive.verified_at == 101 &&
            orphan_action(true, &observed_inactive, false, "run", "vm", false, 101) == OrphanAction::fence_then_terminate,
            "fresh inactive projection did not fence the matching host without resetting its budget");
    assigned.state.activation.active = false;
    require(orphan_action(true, &assigned, false, "run", "vm", false, 101) == OrphanAction::fence_then_terminate,
            "inactive saved activation did not fence the assigned host");
    assigned.state.activation.active = true;
    assigned.state.activation.activation->id = "new-activation";
    require(orphan_action(true, &assigned, false, "run", "vm", false, 101) == OrphanAction::fence_then_terminate,
            "superseded activation did not fence the assigned host");
    assigned.state.activation.activation->id = "activation";
    assigned.state.run->microvm_id.clear();
    assigned.state.run->phase = RunPhase::reserved;
    require(orphan_action(true, &assigned, false, "run", "vm", false, 101) == OrphanAction::retain,
            "orphan sweep would terminate an unidentified live reservation");
    assigned.state.run->phase = RunPhase::stopping;
    require(orphan_action(true, &assigned, false, "run", "vm", false, 101) == OrphanAction::fence_then_terminate &&
            orphan_action(true, &assigned, false, "different", "vm", false, 101) == OrphanAction::terminate,
            "fenced ambiguous launch was not identified for termination");
    require(!bind_stopping_orphan(assigned, "different", "vm") &&
            bind_stopping_orphan(assigned, "run", "vm") &&
            !bind_stopping_orphan(assigned, "run", "other-vm") &&
            confirm_run_stopped(assigned.state, "run", "vm") && !assigned.state.run,
            "fenced launch identity could not be safely bound and cleared after termination");

    for (const bool expires : {false, true}) {
        Fake uncertain;
        reconcile(uncertain, 100, "1.0.0");
        uncertain.observed = ProjectionObservation{2, true, 2000};
        uncertain.ambiguous = true;
        try { reconcile(uncertain, 101, "1.0.0"); }
        catch (const std::runtime_error&) {}
        const auto uncertain_deadline = uncertain.stored.state.activation.activation->deadline;
        uncertain.observed.reset();
        reconcile(uncertain, 102, "1.0.0");
        require(uncertain.launches == 1 && uncertain.stored.state.run->phase == RunPhase::reserved,
                "unverified lifecycle retried an ambiguous launch");
        uncertain.observed = expires ? std::optional<ProjectionObservation>(ProjectionObservation{3, true, 3000})
                                     : std::optional<ProjectionObservation>(ProjectionObservation{3, false, 3000});
        reconcile(uncertain, expires ? uncertain_deadline : 103, "1.0.0");
        require(uncertain.launches == 1 && uncertain.stored.state.run->phase == RunPhase::stopping &&
                uncertain.stored.state.run->microvm_id.empty(),
                "fenced ambiguous reservation started another VM");
        reconcile(uncertain, uncertain_deadline + 1, "1.0.0");
        require(uncertain.launches == 1, "fenced ambiguous reservation retried on repair");
    }
    for (const bool known_id : {false, true}) {
        Fake reactivated;
        reconcile(reactivated, 100, "1.0.0");
        reactivated.observed = ProjectionObservation{2, true, 2000};
        reactivated.ambiguous = !known_id;
        try { reconcile(reactivated, 101, "1.0.0"); }
        catch (const std::runtime_error&) {}
        const auto old_run = *reactivated.stored.state.run;
        reactivated.observed = ProjectionObservation{3, false, 3000};
        reconcile(reactivated, 103, "1.0.0");
        require(reactivated.stored.state.run->run_id == old_run.run_id &&
                reactivated.stored.state.run->phase == RunPhase::stopping,
                "inactive observation discarded a launch before a new activation");
        reactivated.observed = ProjectionObservation{4, true, 4000};
        if (known_id) {
            reconcile(reactivated, 104, "2.0.0");
            require(reactivated.launches == 1 && reactivated.stored.state.run->run_id == old_run.run_id,
                    "known VM identity was discarded before terminal confirmation");
            continue;
        }
        reactivated.conflict = true;
        require(reconcile(reactivated, 104, "2.0.0") == ReconcileResult::conflict &&
                reactivated.launches == 1 && reactivated.stored.state.run->run_id == old_run.run_id,
                "conflicting retirement launched or erased an unidentified reservation");
        reactivated.host = {"vm-2", "PENDING", "endpoint"};
        reconcile(reactivated, 104, "2.0.0");
        const auto replacement = *reactivated.stored.state.run;
        require(reactivated.launches == 2 && replacement.run_id != old_run.run_id &&
                replacement.activation_id != old_run.activation_id && replacement.release == "2.0.0" &&
                replacement.microvm_id == "vm-2" && reactivated.stored.state.activation.activation->deadline == 3103 &&
                reactivated.launched_requests.at(old_run.run_id) == old_run.request,
                "a superseded unidentified reservation blocked reactivation or reused the old launch/budget");
        auto late = reactivated.stored.state;
        require(accept_launch(late, old_run.run_id, "vm-1", true, CurrentLifecycle::active, 105) == LaunchResult::stop_unassigned &&
                late.run->run_id == replacement.run_id && late.run->microvm_id == "vm-2" &&
                late.activation.activation->deadline == 3103,
                "late old launch result altered the new reservation");
    }
    Fake late_superseded;
    reconcile(late_superseded, 100, "1.0.0");
    late_superseded.observed = ProjectionObservation{2, true, 2000};
    late_superseded.during_launch = [](ControllerSnapshot& value) {
        observe_activation(value.state.activation, {3, false, 3000}, 102, 3000, {});
        observe_activation(value.state.activation, {4, true, 4000}, 103, 3000, [] { return "new-activation"; });
        value.state.run.reset();
        reserve_run(value.state, CurrentLifecycle::active, 103, "new-run", "2.0.0", "new-request");
        accept_launch(value.state, "new-run", "vm-2", true, CurrentLifecycle::active, 103);
        ++value.shadow_version;
    };
    reconcile(late_superseded, 101, "1.0.0");
    require(late_superseded.terminations == 1 && late_superseded.stored.state.run->run_id == "new-run" &&
            late_superseded.stored.state.run->microvm_id == "vm-2" &&
            late_superseded.stored.state.activation.activation->deadline == 3102,
            "late launch response did not terminate the old VM while preserving the replacement");
    Fake expired_reactivation;
    reconcile(expired_reactivation, 100, "1.0.0");
    expired_reactivation.observed = ProjectionObservation{2, true, 2000};
    expired_reactivation.ambiguous = true;
    try { reconcile(expired_reactivation, 101, "1.0.0"); }
    catch (const std::runtime_error&) {}
    const auto unresolved_run = expired_reactivation.stored.state.run->run_id;
    expired_reactivation.observed = ProjectionObservation{3, false, 3000};
    reconcile(expired_reactivation, 103, "1.0.0");
    expired_reactivation.observed = ProjectionObservation{4, true, 4000};
    reconcile(expired_reactivation, 3200, "2.0.0");
    require(expired_reactivation.launches == 1 && expired_reactivation.stored.state.run->run_id == unresolved_run &&
            expired_reactivation.stored.state.activation.activation->deadline == 3103,
            "an expired later activation discarded the fence or created a new launch budget");
    Fake expires_before_launch;
    reconcile(expires_before_launch, 100, "1.0.0");
    expires_before_launch.observed = ProjectionObservation{2, true, 2000};
    reconcile(expires_before_launch, 101, "1.0.0", [] { return 3100; });
    require(expires_before_launch.launches == 0 && expires_before_launch.stored.state.run &&
            expires_before_launch.stored.state.run->phase == RunPhase::stopping,
            "a deadline crossed during reservation still issued a launch");
    Fake expires_during_launch;
    reconcile(expires_during_launch, 100, "1.0.0");
    expires_during_launch.observed = ProjectionObservation{2, true, 2000};
    unsigned clock_reads = 0;
    reconcile(expires_during_launch, 101, "1.0.0", [&] { return ++clock_reads == 1 ? 101 : 3100; });
    require(expires_during_launch.launches == 1 && expires_during_launch.terminations == 1 &&
            expires_during_launch.stored.state.run->phase == RunPhase::stopping &&
            expires_during_launch.stored.state.run->microvm_id == "vm-1",
            "a launch response after the deadline was accepted instead of being fenced and terminated");
    Fake conflict_after_expiry;
    reconcile(conflict_after_expiry, 100, "1.0.0");
    conflict_after_expiry.observed = ProjectionObservation{2, true, 2000};
    conflict_after_expiry.conflict_after_launch = true;
    unsigned conflict_clock = 0;
    reconcile(conflict_after_expiry, 101, "1.0.0", [&] { return ++conflict_clock == 1 ? 101 : 3100; });
    require(conflict_after_expiry.launches == 1 && conflict_after_expiry.terminations == 1 &&
            conflict_after_expiry.stored.state.run->phase == RunPhase::stopping &&
            conflict_after_expiry.stored.state.run->microvm_id == "vm-1",
            "a conditional-write conflict lost a late VM identity before termination");
    Fake takeover;
    reconcile(takeover, 100, "1.0.0");
    takeover.observed = ProjectionObservation{2, true, 2000};
    takeover.conflict_after_launch = true; takeover.takeover_on_conflict = true;
    reconcile(takeover, 101, "1.0.0");
    require(takeover.terminations == 0 && takeover.stored.state.run->run_id == "newer-run" &&
            takeover.stored.state.run->microvm_id == "vm-1",
            "a late launch response terminated a VM named by a newer reservation");
    Fake clock_reversal;
    reconcile(clock_reversal, 100, "1.0.0");
    clock_reversal.observed = ProjectionObservation{2, true, 2000};
    unsigned reversal_reads = 0;
    reconcile(clock_reversal, 101, "1.0.0", [&]() -> std::int64_t {
        if (++reversal_reads == 1) return 3099;
        std::this_thread::sleep_for(std::chrono::milliseconds(1100));
        return 100;
    });
    require(clock_reversal.terminations == 1 && clock_reversal.stored.state.run->phase == RunPhase::stopping,
            "wall-clock reversal extended the deadline across a delayed launch response");
    Fake expires_during_assignment;
    reconcile(expires_during_assignment, 100, "1.0.0");
    expires_during_assignment.observed = ProjectionObservation{2, true, 2000};
    reconcile(expires_during_assignment, 101, "1.0.0");
    expires_during_assignment.host.state = "RUNNING";
    reconcile(expires_during_assignment, 102, "1.0.0", [] { return 3100; });
    require(expires_during_assignment.terminations == 1 &&
            expires_during_assignment.stored.state.run->phase == RunPhase::stopping,
            "a VM was assigned after its activation deadline");
    Fake stale_verification;
    reconcile(stale_verification, 100, "1.0.0");
    stale_verification.observed = ProjectionObservation{2, true, 2000};
    reconcile(stale_verification, 101, "1.0.0");
    stale_verification.host.state = "RUNNING";
    unsigned stale_reads = 0;
    reconcile(stale_verification, 102, "1.0.0", [&]() -> std::int64_t { return ++stale_reads == 1 ? 102 : 118; });
    require(stale_verification.stored.state.run->phase == RunPhase::reserved && stale_verification.terminations == 0,
            "an old lifecycle observation was promoted to a freshly verified assignment");
    Fake concurrent;
    reconcile(concurrent, 100, "1.0.0");
    concurrent.observed = ProjectionObservation{2, true, 2000};
    std::atomic<bool> go{false}, failed_concurrent{false};
    auto delivery = [&] {
        while (!go.load()) std::this_thread::yield();
        try { reconcile(concurrent, 101, "1.0.0"); }
        catch (...) { failed_concurrent = true; }
    };
    std::thread first(delivery), second(delivery); go = true; first.join(); second.join();
    require(!failed_concurrent && concurrent.stored.state.run && concurrent.launches >= 1 && concurrent.launches <= 2 &&
            concurrent.stored.state.activation.activation->deadline == 3100,
            "concurrent deliveries escaped reservation or changed the deadline");
}
}
int main() {
    try { tests(); std::cout << "PASS reconciliation retries, expiry and fencing\n"; }
    catch (const std::exception& error) { std::cerr << "FAIL " << error.what() << '\n'; return 1; }
}
