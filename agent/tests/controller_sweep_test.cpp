#include "agent/aws.hpp"
#include "agent/controller_handler.hpp"
#include "agent/reconcile.hpp"
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace txing::agent;
void test_controller_drain_api();
void test_controller_enabled_api();
namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
void tests() {
    const ControllerConfig configured{{"arn:aws:lambda:eu-central-1:123456789012:microvm-image:agent",
                                        "1", "role", "logs", "eu-central-1"}, "1.0.0"};
    auto incomplete = configured; incomplete.cloud.image_version.clear();
    auto placeholder = configured; placeholder.cloud.image = "arn:aws:lambda:eu-central-1:123456789012:microvm-image:disabled";
    auto invalid_release = configured; invalid_release.release = "01.0.0";
    auto invalid_version = configured; invalid_version.cloud.image_version = "version 1";
    require(controller_configured(configured) && !controller_configured(incomplete) && !controller_configured(placeholder) &&
            !controller_configured(invalid_release) && !controller_configured(invalid_version),
            "controller accepted incomplete or placeholder hosting configuration");
    unsigned reconciled = 0, drained = 0;
    const auto reconcile = [&] { ++reconciled; };
    const auto drain = [&] { ++drained; };
    controller_dispatch_automation("enabled", true, reconcile, drain);
    controller_dispatch_automation("disabled", true, reconcile, drain);
    require(reconciled == 1 && drained == 1, "enabled or disabled mode dispatched incorrectly");
    for (const auto& setting : {std::string(""), std::string("invalid"), std::string("enabled")}) {
        bool rejected = false;
        try { controller_dispatch_automation(setting, false, reconcile, drain); }
        catch (const std::invalid_argument&) { rejected = true; }
        require(rejected && reconciled == 1, "invalid controller state launched or failed to report its configuration error");
    }
    require(drained == 4, "invalid or incomplete controller state skipped termination-only repair");
    bool sampled = false, stop_only = true;
    controller_event_repair([] {}, [&](bool value) { sampled = true; stop_only = value; });
    require(sampled && !stop_only, "successful event did not permit ordinary status sampling");
    sampled = false;
    std::string failure;
    try {
        controller_event_repair([] { throw std::runtime_error("reconcile failed"); }, [&](bool value) {
            sampled = true; stop_only = value;
            throw std::runtime_error("sampling failed");
        });
    } catch (const std::runtime_error& error) { failure = error.what(); }
    require(sampled && stop_only && failure == "reconcile failed",
            "failed event did not check stopped runtime or preserve the reconciliation error for retry");
    const std::vector<std::string> things{"missing", "healthy", "failed", "last"};
    std::vector<std::string> visited;
    const auto visit = [&](const std::string& thing) {
        visited.push_back(thing);
        if (thing == "missing") throw ShadowNotFound("missing agent capability shadow");
        if (thing == "failed") throw std::runtime_error("temporary AWS failure");
    };
    require(!controller_sweep_each(things, "test", visit) && visited == things,
            "unavailable AWS state must mark inventory incomplete without blocking other devices");
    // An incomplete registry pass does not itself authorize termination: each
    // candidate is checked against current identity and assignment separately.
    const std::vector<CloudRun> inventory{{"unknown", "RUNNING", {}}, {"orphan", "RUNNING", {}}};
    const auto candidates = orphan_candidates(inventory, {});
    require(candidates.size() == 2 &&
            orphan_action({}, nullptr, false, "unknown-run", "unknown", false, 101) == OrphanAction::defer &&
            orphan_action(true, nullptr, true, "orphan-run", "orphan", false, 101) == OrphanAction::terminate,
            "incomplete inventory must defer uncertain candidates but permit individually verified cleanup");
    ControllerSnapshot pending;
    pending.state.run = RunReservation{"pending-run", "activation", "1.0.0", "request", {}, RunPhase::reserved};
    pending.state.activation.observed = true;
    pending.state.activation.active = true;
    pending.state.activation.activation = Activation{"activation", 100, 3100};
    require(orphan_action(true, &pending, false, "pending-run", "unknown", false, 101) == OrphanAction::retain,
            "unidentified live launch must remain protected during an incomplete sweep");
    pending.state.run->microvm_id = "unknown";
    pending.state.run->phase = RunPhase::running;
    require(orphan_action(true, &pending, false, "pending-run", "unknown", false, 101) == OrphanAction::retain &&
            orphan_action(true, &pending, false, "pending-run", "unknown", false, 3100) == OrphanAction::fence_then_terminate,
            "incomplete sweep must preserve a healthy assignment and fence the same VM at its deadline");
    visited.clear();
    const std::vector<std::string> with_missing{"missing", "healthy", "last"};
    require(controller_sweep_each(with_missing, "test", visit) && visited == with_missing,
            "missing agent shadow must not block independent devices or orphan verification");
}
}
int main() {
    try { tests(); test_controller_drain_api(); test_controller_enabled_api(); std::cout << "PASS enabled reconciliation, independent repair and disabled AWS API drain\n"; }
    catch (const std::exception& error) { std::cerr << "FAIL " << error.what() << '\n'; return 1; }
}
