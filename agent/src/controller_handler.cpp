#include "agent/controller_handler.hpp"
#include "agent/aws.hpp"
#include "agent/reconcile.hpp"
#include "agent/runtime_sample.hpp"
#include <aws/core/utils/UUID.h>
#include <aws/core/utils/json/JsonSerializer.h>
#include <chrono>
#include <exception>
#include <iostream>
#include <set>
#include <stdexcept>
#include <thread>
#include <curl/curl.h>

namespace txing::agent {
namespace {
std::int64_t now_seconds() {
    return std::chrono::duration_cast<std::chrono::seconds>(std::chrono::system_clock::now().time_since_epoch()).count();
}
std::string read_status(CloudMicrovms&, const CloudRun&);
class AwsBackend final : public ReconcileBackend {
public:
    AwsBackend(AwsDevice& device, CloudMicrovms& cloud, const ControllerConfig& config, std::string thing)
        : device_(device), cloud_(cloud), config_(config), thing_(std::move(thing)) {}
    ControllerSnapshot read() override { return parse_controller_shadow(device_.agent_shadow(thing_)); }
    bool save(const ControllerSnapshot& snapshot, std::int64_t now, std::int64_t verified) override {
        return device_.update_agent_shadow(thing_, controller_shadow_patch(snapshot, now, verified));
    }
    std::optional<bool> supported() override {
        try { return device_.has_capability(thing_, "agent"); }
        catch (...) { return {}; }
    }
    std::optional<ProjectionObservation> projection() override {
        try { return device_.projection(thing_); }
        catch (...) { return {}; }
    }
    std::optional<bool> runtime_verified(const ControllerSnapshot& snapshot) override {
        if (!snapshot.state.run || snapshot.state.run->microvm_id.empty()) return false;
        try {
            const auto started = std::chrono::steady_clock::now();
            const auto host = cloud_.get(snapshot.state.run->microvm_id);
            if (host.id != snapshot.state.run->microvm_id || host.state != "RUNNING") return false;
            const auto status = read_status(cloud_, host);
            const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now() - started).count() + 2;
            // Both the reported age and measured duration are rounded down;
            // two milliseconds conservatively cover both truncations.
            return runtime_verified_for(snapshot, thing_, status, elapsed);
        } catch (...) { return {}; }
    }
    std::string identity() override {
        const Aws::String id = Aws::Utils::UUID::RandomUUID(); return id.c_str();
    }
    std::string request(const std::string& run_id, const Activation& activation, std::int64_t now) override {
        return make_cloud_request(config_.cloud, thing_, run_id, activation.id, activation.deadline, now);
    }
    CloudRun launch(const RunReservation& run) override { return cloud_.launch(run.request, run.run_id); }
    CloudRun get(const std::string& id) override { return cloud_.get(id); }
    void terminate(const std::string& id) override { cloud_.terminate(id); }
private:
    AwsDevice& device_;
    CloudMicrovms& cloud_;
    const ControllerConfig& config_;
    const std::string thing_;
};
std::size_t status_body(char* data, std::size_t size, std::size_t count, void* opaque) {
    auto& body = *static_cast<std::string*>(opaque);
    const auto bytes = size * count;
    if (bytes > 16384 || body.size() > 16384 - bytes) return 0;
    body.append(data, bytes); return bytes;
}
std::string read_status(CloudMicrovms& cloud, const CloudRun& run) {
    const auto endpoint = microvm_https_endpoint(run.endpoint);
    auto token = cloud.token(run.id, 8081, 1);
    CURL* curl = curl_easy_init();
    if (!curl) throw std::runtime_error("could not initialize runtime status client");
    curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, ("X-aws-proxy-auth: " + token).c_str());
    if (!headers) { curl_easy_cleanup(curl); throw std::runtime_error("could not allocate status headers"); }
    auto* extended = curl_slist_append(headers, "X-aws-proxy-port: 8081");
    if (!extended) { curl_slist_free_all(headers); curl_easy_cleanup(curl); throw std::runtime_error("could not allocate status headers"); }
    headers = extended;
    std::string body;
    const auto url = endpoint + "/status";
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str()); curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, status_body); curl_easy_setopt(curl, CURLOPT_WRITEDATA, &body);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, 2000L); curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 4000L);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L); curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 0L);
    const auto status = curl_easy_perform(curl);
    long code = 0; curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &code);
    curl_slist_free_all(headers); curl_easy_cleanup(curl);
    if (status != CURLE_OK || code != 200) throw std::runtime_error("authenticated runtime status request failed");
    return body;
}
void sample_thing(AwsDevice& device, CloudMicrovms& cloud, const std::string& thing, bool stop_only = false) {
    auto snapshot = parse_controller_shadow(device.agent_shadow(thing));
    if (!snapshot.state.run || snapshot.state.run->phase != RunPhase::running) return;
    const auto run = *snapshot.state.run;
    const auto host = cloud.get(run.microvm_id);
    if (host.id != run.microvm_id || host.state != "RUNNING") return;
    const auto status = read_status(cloud, host);
    auto latest = parse_controller_shadow(device.agent_shadow(thing));
    if (!latest.state.run || latest.state.run->run_id != run.run_id || latest.state.run->microvm_id != run.microvm_id ||
        latest.state.run->phase != RunPhase::running) return;
    if (runtime_stopped_for(latest, thing, status)) {
        latest.state.run->phase = RunPhase::stopping;
        if (device.update_agent_shadow(thing, controller_shadow_patch(latest, now_seconds(), latest.verified_at)))
            cloud.terminate(run.microvm_id);
        return;
    }
    if (stop_only) return;
    // Only publishing a healthy endpoint requires current type and lifecycle.
    // A stopped report above cannot grant authority or refresh the budget.
    if (!activation_authorized(latest.state.activation, now_seconds()) || !device.has_capability(thing, "agent")) return;
    const auto fresh = device.projection(thing);
    if (!fresh.active || !*fresh.active || fresh.version != latest.state.activation.projection_version ||
        fresh.source_timestamp_ms != latest.state.activation.source_timestamp_ms) return;
    // The sample parser also checks both identities, the activation deadline,
    // running state and the runtime's fresh assignment verification.
    const auto patch = runtime_sample_patch(latest, host.endpoint, status, now_seconds());
    device.update_agent_shadow(thing, patch); // A conflict discards this sample.
}
void note_sample_error(AwsDevice& device, const std::string& thing) {
    try {
        auto snapshot = parse_controller_shadow(device.agent_shadow(thing));
        if (!snapshot.state.run || snapshot.state.run->phase != RunPhase::running) return;
        snapshot.last_error = "runtime status sampling failed; inspect controller logs";
        device.update_agent_shadow(thing, controller_shadow_patch(snapshot, now_seconds(), snapshot.verified_at));
    } catch (...) { /* Do not replace a healthy run for a diagnostic failure. */ }
}
void terminate_confirmed_orphan(AwsDevice& device, CloudMicrovms& cloud, const std::string& id) {
    // An inventory listing can omit a live assignment while registry contents
    // are changing. Do not kill an unreachable candidate on that evidence
    // alone: a later pass or the platform duration cap handles it.
    const auto host = cloud.get(id);
    if (host.id != id || host.state != "RUNNING") return;
    Aws::Utils::Json::JsonValue document(Aws::String(read_status(cloud, host).c_str()));
    const auto status = document.View();
    if (!document.WasParseSuccessful() || !status.IsObject() ||
        !status.ValueExists("thingId") || !status.GetObject("thingId").IsString() ||
        !status.ValueExists("runId") || !status.GetObject("runId").IsString() ||
        !status.ValueExists("microvmId") || !status.GetObject("microvmId").IsString() ||
        status.GetString("microvmId") != id.c_str()) return;
    const std::string thing = status.GetString("thingId").c_str(), run_id = status.GetString("runId").c_str();
    if (thing.empty() || thing.size() > 128 || run_id.empty() || run_id.size() > 128 ||
        thing.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-:") != std::string::npos) return;
    std::optional<bool> supported;
    std::optional<ControllerSnapshot> snapshot;
    bool missing = false;
    try {
        supported = device.has_capability(thing, "agent");
        try { snapshot = parse_controller_shadow(device.agent_shadow(thing)); }
        catch (const ShadowNotFound&) { missing = true; }
    } catch (const ThingNotFound&) { supported = false; missing = true; }
    const auto now = now_seconds();
    if (supported && *supported && snapshot && snapshot->state.run && snapshot->state.run->run_id == run_id &&
        (snapshot->state.run->microvm_id.empty() || snapshot->state.run->microvm_id == id)) {
        try { observe_orphan_inactive(*snapshot, device.projection(thing), now); }
        catch (const std::exception&) {
            // An unreadable projection is not inactivity. Other independent
            // stop evidence, such as the saved deadline, remains valid.
        }
    }
    const bool stopped = status.ValueExists("phase") && status.GetObject("phase").IsString() && status.GetString("phase") == "stopped";
    const auto action = orphan_action(supported, snapshot ? &*snapshot : nullptr, missing, run_id, id, stopped, now);
    if (action == OrphanAction::fence_then_terminate) {
        // An ambiguous launch can have no persisted MicroVM ID. Bind the
        // authenticated runtime identity before termination so normal repair
        // can observe the terminal state and clear the reservation.
        if (!bind_stopping_orphan(*snapshot, run_id, id)) return;
        if (!device.update_agent_shadow(thing, controller_shadow_patch(*snapshot, now_seconds(), snapshot->verified_at))) return;
    }
    if (action == OrphanAction::terminate || action == OrphanAction::fence_then_terminate) cloud.terminate(id);
}
void reconcile_thing(AwsDevice& device, CloudMicrovms& cloud, const ControllerConfig& config,
                     const std::string& thing, unsigned attempts) {
    AwsBackend backend(device, cloud, config, thing);
    try {
        for (unsigned attempt = 0; attempt < attempts; ++attempt) {
            const auto result = reconcile(backend, now_seconds(), config.release, now_seconds);
            if (result == ReconcileResult::settled) return;
            if (attempt + 1 < attempts) std::this_thread::sleep_for(std::chrono::seconds(1));
        }
    } catch (const std::exception& error) {
        try {
            auto snapshot = backend.read();
            const std::string detail(error.what());
            snapshot.last_error = "controller reconciliation failed; inspect logs";
            for (const std::string operation : {"lambda-microvms:RunMicrovm", "lambda-microvms:GetMicrovm",
                                                "lambda-microvms:TerminateMicrovm", "iot:GetThingShadow(agent)",
                                                "iot:UpdateThingShadow(agent)"}) {
                if (detail.rfind(operation + ": ", 0) != 0) continue;
                const auto at = detail.rfind(" HTTP ");
                if (at == std::string::npos) break;
                const auto status = detail.substr(at + 6);
                if (!status.empty() && status.size() <= 3 && status.find_first_not_of("0123456789") == std::string::npos)
                    snapshot.last_error = operation + " HTTP " + status;
                break;
            }
            backend.save(snapshot, now_seconds(), snapshot.verified_at);
        } catch (...) { /* Preserve the original failure for Lambda retry. */ }
        throw;
    }
}
class AwsDrain final : public DrainBackend {
public:
    AwsDrain(AwsDevice& device, CloudMicrovms& cloud, std::string image)
        : device_(device), cloud_(cloud), image_(std::move(image)) {}
    std::vector<std::string> things() override { return device_.registered_things(); }
    bool fence(const std::string& thing) override {
        try {
            auto snapshot = parse_controller_shadow(device_.agent_shadow(thing));
            if (!snapshot.state.run) return true;
            const auto& run = *snapshot.state.run;
            if (saved_launch_image(run.request, run.run_id, thing, run.activation_id) != image_) {
                mismatched_image_ = true;
                return false;
            }
            if (run.phase == RunPhase::stopping) return true;
            snapshot.state.run->phase = RunPhase::stopping;
            snapshot.last_error = "automation disabled";
            return device_.update_agent_shadow(thing, controller_shadow_patch(snapshot, now_seconds(), snapshot.verified_at));
        } catch (const ShadowNotFound&) { return true; }
    }
    void inventory(const std::function<void(const std::vector<CloudRun>&)>& visit) override {
        try { cloud_.for_each_page(image_, visit); }
        catch (...) { inventory_failed_ = true; throw; }
    }
    void terminate(const std::string& id) override { cloud_.terminate(id); }
    bool needs_known_fallback() const { return mismatched_image_ || inventory_failed_; }
private:
    AwsDevice& device_;
    CloudMicrovms& cloud_;
    const std::string image_;
    bool mismatched_image_ = false, inventory_failed_ = false;
};
class AwsKnownDrain final : public KnownDrainBackend {
public:
    AwsKnownDrain(AwsDevice& device, CloudMicrovms& cloud) : device_(device), cloud_(cloud) {}
    std::vector<std::string> things() override { return device_.registered_things(); }
    std::optional<ControllerSnapshot> read(const std::string& thing) override {
        try { return parse_controller_shadow(device_.agent_shadow(thing)); }
        catch (const ShadowNotFound&) { return {}; }
    }
    CloudRunDetails describe(const std::string& id) override { return cloud_.describe(id); }
    bool fence(const std::string& thing, ControllerSnapshot& snapshot) override {
        snapshot.state.run->phase = RunPhase::stopping;
        snapshot.last_error = "automation disabled; image inventory unavailable or mismatched";
        return device_.update_agent_shadow(thing, controller_shadow_patch(snapshot, now_seconds(), snapshot.verified_at));
    }
    void terminate(const std::string& id) override { cloud_.terminate(id); }
private:
    AwsDevice& device_;
    CloudMicrovms& cloud_;
};
}

bool controller_configured(const ControllerConfig& config) {
    const auto& image = config.cloud.image;
    const bool placeholder = image.size() >= 9 && image.compare(image.size() - 9, 9, ":disabled") == 0;
    return config.cloud.region == "eu-central-1" && !image.empty() && !placeholder &&
        !config.cloud.image_version.empty() && config.cloud.image_version.find_first_of(" \t\r\n") == std::string::npos &&
        !config.cloud.execution_role.empty() && !config.cloud.log_group.empty() && valid_release(config.release);
}
void controller_dispatch_automation(const std::string& setting, bool configured,
                                    const std::function<void()>& reconcile,
                                    const std::function<void()>& drain) {
    if (setting == "enabled" && configured) { reconcile(); return; }
    drain();
    if (setting != "disabled")
        throw std::invalid_argument(setting == "enabled" ? "controller configuration is incomplete" : "invalid automation setting");
}

bool controller_sweep_each(const std::vector<std::string>& things, const char* stage,
                           const std::function<void(const std::string&)>& visit) {
    bool complete = true;
    for (const auto& thing : things) {
        try { visit(thing); }
        catch (const ShadowNotFound&) {
            // The missing agent shadow is not an activation. Candidates
            // must still be independently verified before orphan termination.
            std::cerr << "controller " << stage << ": agent shadow missing\n";
        } catch (const std::exception& error) {
            complete = false;
            std::cerr << "controller " << stage << ": " << error.what() << '\n';
        }
    }
    return complete;
}

void controller_event_repair(const std::function<void()>& reconcile,
                             const std::function<void(bool stop_only)>& sample) {
    std::exception_ptr failure;
    try { reconcile(); } catch (...) { failure = std::current_exception(); }
    try { sample(bool(failure)); }
    catch (...) { if (!failure) throw; }
    if (failure) std::rethrow_exception(failure);
}

void handle_disabled_event(const std::string& event, const ControllerConfig& config,
                           std::shared_ptr<Aws::Auth::AWSCredentialsProvider> credentials,
                           Aws::Client::ClientConfiguration client_config) {
    Aws::Utils::Json::JsonValue body(Aws::String(event.c_str()));
    if (!body.WasParseSuccessful() || !body.View().IsObject()) throw std::invalid_argument("invalid controller event");
    const auto view = body.View();
    if (!view.ValueExists("source") || !view.GetObject("source").IsString() || view.GetString("source") != "aws.events") return;
    if (config.cloud.image.size() >= 9 &&
        config.cloud.image.compare(config.cloud.image.size() - 9, 9, ":disabled") == 0) return;
    if (config.cloud.region != "eu-central-1") throw std::invalid_argument("invalid drain region");
    AwsDevice device(credentials, client_config);
    CloudMicrovms cloud(credentials, client_config);
    if (config.cloud.image.empty()) {
        AwsKnownDrain drain(device, cloud);
        drain_known_assignments(drain);
        // Known assignments cannot prove that an unidentified VM is absent.
        throw std::runtime_error("image configuration missing; inspect and drain unidentified VMs manually");
    }
    AwsDrain drain(device, cloud, config.cloud.image);
    if (!drain_disabled(drain)) {
        if (drain.needs_known_fallback()) {
            AwsKnownDrain known(device, cloud);
            drain_known_assignments(known);
        }
        throw std::runtime_error("disabled agent drain incomplete; retry on next schedule");
    }
}

void handle_controller_event(const std::string& event, const ControllerConfig& config,
                             std::shared_ptr<Aws::Auth::AWSCredentialsProvider> credentials,
                             Aws::Client::ClientConfiguration client_config) {
    if (!controller_configured(config))
        throw std::invalid_argument("controller release and hosting configuration is incomplete");
    Aws::Utils::Json::JsonValue body(Aws::String(event.c_str()));
    if (!body.WasParseSuccessful() || !body.View().IsObject()) throw std::invalid_argument("invalid controller event");
    const auto view = body.View();
    AwsDevice device(credentials, client_config);
    CloudMicrovms cloud(credentials, client_config);
    if (view.ValueExists("thingName") && view.GetObject("thingName").IsString()) {
        const std::string thing = view.GetString("thingName").c_str();
        if (thing.empty() || thing.size() > 128 || thing.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-:") != std::string::npos)
            throw std::invalid_argument("invalid Thing identity in controller event");
        bool skip = false;
        controller_event_repair([&] {
            if (!device.has_capability(thing, "agent")) {
                try { device.agent_shadow(thing); }
                catch (const ShadowNotFound&) { skip = true; return; }
            }
            reconcile_thing(device, cloud, config, thing, 12);
        }, [&](bool stop_only) {
            if (skip) return;
            try { sample_thing(device, cloud, thing, stop_only); }
            catch (const std::exception& error) {
                std::cerr << "controller status: " << error.what() << '\n';
                if (!stop_only) note_sample_error(device, thing);
            }
        });
        return;
    }
    if (!view.ValueExists("source") || !view.GetObject("source").IsString() || view.GetString("source") != "aws.events")
        throw std::invalid_argument("unknown controller event source");

    // This image is dedicated to the controller. The assignment inventory is
    // an optimization, not proof that an unlisted VM is orphaned. Every
    // candidate is independently verified against current state before being
    // terminated. CloudFormation keeps controller concurrency at one so a
    // concurrent invocation cannot launch after the inventory snapshot.
    const auto things = device.registered_things();
    bool complete = controller_sweep_each(things, "repair", [&](const auto& thing) {
        reconcile_thing(device, cloud, config, thing, 1);
    });
    // A VM restored by the repair pass must be assigned promptly, not left
    // waiting for the next minute while its verification deadline expires.
    // Poll all pending devices in rounds so multiple starts share the wait.
    for (unsigned round = 0; round < 12; ++round) {
        bool pending = false;
        complete = controller_sweep_each(things, "startup", [&](const auto& thing) {
            const auto snapshot = parse_controller_shadow(device.agent_shadow(thing));
            if (snapshot.state.run && snapshot.state.run->phase == RunPhase::reserved) {
                pending = true; reconcile_thing(device, cloud, config, thing, 1);
            }
        }) && complete;
        if (!pending) break;
        if (round + 1 < 12) std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    for (const auto& thing : things) {
        try { sample_thing(device, cloud, thing); }
        catch (const ShadowNotFound&) { /* Missing agent shadow has no sample. */ }
        catch (const std::exception& error) { std::cerr << "controller status: " << error.what() << '\n'; note_sample_error(device, thing); }
    }
    std::set<std::string> assigned;
    complete = controller_sweep_each(things, "inventory", [&](const auto& thing) {
        const auto snapshot = parse_controller_shadow(device.agent_shadow(thing));
        if (snapshot.state.run) {
            if (snapshot.state.run->microvm_id.empty()) {
                if (snapshot.state.run->phase != RunPhase::stopping) complete = false;
            } else assigned.insert(snapshot.state.run->microvm_id);
        }
    }) && complete;
    if (!complete) std::cerr << "controller inventory incomplete; verifying orphan candidates independently\n";
    // An incomplete pass may have failed to fence even a known assignment.
    // Recheck all hosts individually in that case, including assigned ones.
    const std::set<std::string> no_exclusions;
    const auto& exclusions = complete ? assigned : no_exclusions;
    for (const auto& id : orphan_candidates(cloud.list(config.cloud.image), exclusions)) {
        try { terminate_confirmed_orphan(device, cloud, id); }
        catch (const std::exception& error) { std::cerr << "controller orphan verification: " << error.what() << '\n'; }
    }
}
}
