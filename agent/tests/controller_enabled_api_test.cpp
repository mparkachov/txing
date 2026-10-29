#include "agent/controller_handler.hpp"
#include "agent/controller_shadow.hpp"
#include <aws/core/Aws.h>
#include <aws/core/auth/AWSCredentialsProvider.h>
#include <aws/core/client/DefaultRetryStrategy.h>
#include <aws/core/http/HttpClient.h>
#include <aws/core/http/standard/StandardHttpRequest.h>
#include <aws/core/http/standard/StandardHttpResponse.h>
#include <aws/core/utils/json/JsonSerializer.h>
#include <chrono>
#include <map>
#include <sstream>
#include <stdexcept>

using namespace txing::agent;
namespace {
using Json = Aws::Utils::Json::JsonValue;
using View = Aws::Utils::Json::JsonView;
using namespace Aws::Http;
void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }

// Model IoT's recursive object merge and null deletion, not a whole-document
// replacement that could accidentally conceal stale endpoint/runtime fields.
Json merge(View current, View patch) {
    if (!patch.IsObject()) return patch.Materialize();
    Aws::Map<Aws::String, Json> fields;
    if (current.IsObject()) for (const auto& item : current.GetAllObjects()) fields.emplace(item.first, item.second.Materialize());
    for (const auto& item : patch.GetAllObjects()) {
        if (item.second.IsNull()) { fields.erase(item.first); continue; }
        const auto found = fields.find(item.first);
        fields[item.first] = merge(found == fields.end() ? Json{}.View() : found->second.View(), item.second);
    }
    Json result;
    for (auto& item : fields) result.WithObject(item.first, std::move(item.second));
    return result;
}

struct Fixture {
    Json shadow{R"({"version":1,"state":{"reported":{"lifecycle":{"state":"stopped"}}}})"};
    std::int64_t projection_version = 1, source_time = 1000;
    bool active = false, agent_declared = true, agent_available = true, ambiguous = true, binding_conflict = true;
    unsigned launch_calls = 0, conflicts = 0, terminations = 0, conditional_writes = 0;
    std::map<std::string, std::pair<std::string, std::string>> launches;
    std::map<std::string, std::string> hosts;
    std::string failure;
    ControllerSnapshot snapshot() const { return parse_controller_shadow(shadow.View().WriteCompact().c_str()); }
    std::string projection() const {
        Json topic; topic.WithString("namespace", "spBv1.0").WithString("deviceId", "tbot-test").WithString("messageType", "DDATA");
        Json capabilities; capabilities.WithBool("agent", agent_available);
        Json metrics; metrics.WithInteger("redcon", active ? 1 : 4).WithObject("capability", std::move(capabilities));
        Json payload; payload.WithInt64("timestamp", source_time).WithObject("metrics", std::move(metrics));
        Json reported; reported.WithObject("topic", std::move(topic)).WithObject("payload", std::move(payload));
        Json state; state.WithObject("reported", std::move(reported));
        Json result; result.WithInt64("version", projection_version).WithObject("state", std::move(state));
        return result.View().WriteCompact().c_str();
    }
    void observe(bool value) { active = value; ++projection_version; source_time += 1000; }
    Json host(const std::string& id) const {
        require(hosts.count(id), "unknown VM lookup");
        Json result; result.WithString("microvmId", id.c_str()).WithString("state", hosts.at(id).c_str());
        return result;
    }
    std::pair<HttpResponseCode, std::string> respond(const HttpRequest& request) {
        const std::string path = request.GetUri().GetPath().c_str();
        require(request.HasHeader("authorization"), ("SDK request was unsigned for " + path).c_str());
        const auto method = request.GetMethod();
        if (path == "/things" && method == HttpMethod::HTTP_GET)
            return {HttpResponseCode::OK, R"({"things":[{"thingName":"tbot-test","thingTypeName":"tbot"}]})"};
        if (path == "/things/tbot-test" && method == HttpMethod::HTTP_GET)
            return {HttpResponseCode::OK, agent_declared
                ? R"({"thingName":"tbot-test","thingTypeName":"tbot","attributes":{"capabilities":"sparkplug,mavlink,video,agent"}})"
                : R"({"thingName":"tbot-test","thingTypeName":"tbot","attributes":{"capabilities":"sparkplug,mavlink,video"}})"};
        if (path == "/endpoint" && method == HttpMethod::HTTP_GET)
            return {HttpResponseCode::OK, R"({"endpointAddress":"fixture-ats.iot.eu-central-1.amazonaws.com"})"};
        std::string body;
        if (request.GetContentBody()) {
            request.GetContentBody()->clear(); request.GetContentBody()->seekg(0);
            std::ostringstream stream; stream << request.GetContentBody()->rdbuf(); body = stream.str();
        }
        if (path == "/things/tbot-test/shadow") {
            const auto parameters = request.GetQueryStringParameters();
            require(parameters.count("name"), "shadow name missing");
            const auto name = parameters.find("name")->second;
            if (method == HttpMethod::HTTP_GET)
                return {HttpResponseCode::OK, name == "sparkplug" ? projection() : std::string(shadow.View().WriteCompact().c_str())};
            require(name == "agent" && method == HttpMethod::HTTP_POST, "handler wrote a device-owned shadow");
            Json patch(Aws::String(body.c_str()));
            require(patch.WasParseSuccessful() && patch.View().ValueExists("version"), "unconditional shadow write");
            ++conditional_writes;
            if (patch.View().GetInt64("version") != shadow.View().GetInt64("version"))
                return {HttpResponseCode::CONFLICT, R"({"message":"version conflict"})"};
            const auto candidate = parse_controller_shadow(body);
            if (binding_conflict && candidate.state.run && !candidate.state.run->microvm_id.empty()) {
                binding_conflict = false; ++conflicts;
                shadow.WithInt64("version", shadow.View().GetInt64("version") + 1);
                return {HttpResponseCode::CONFLICT, R"({"message":"binding conflict"})"};
            }
            const auto next_version = shadow.View().GetInt64("version") + 1;
            shadow = merge(shadow.View(), patch.View());
            shadow.WithInt64("version", next_version);
            return {HttpResponseCode::OK, shadow.View().WriteCompact().c_str()};
        }
        const std::string vms = "/2025-09-09/microvms";
        if (path == vms && method == HttpMethod::HTTP_POST) {
            ++launch_calls;
            Json wire(Aws::String(body.c_str())); const auto view = wire.View();
            const std::string token = view.GetString("clientToken").c_str();
            const auto reserved = snapshot();
            require(reserved.state.run && reserved.state.run->run_id == token &&
                    reserved.state.run->phase == RunPhase::reserved, "launch preceded its conditional reservation");
            Json hook(view.GetString("runHookPayload"));
            require(hook.View().GetString("thingId") == "tbot-test" &&
                    hook.View().GetString("activationId") == reserved.state.run->activation_id.c_str() &&
                    hook.View().GetString("deadline") == std::to_string(reserved.state.activation.activation->deadline).c_str(),
                    "launch lost the persisted assignment or deadline");
            auto existing = launches.find(token);
            if (existing == launches.end()) {
                const auto id = "vm-" + std::to_string(launches.size() + 1);
                existing = launches.emplace(token, std::make_pair(id, body)).first;
                hosts[id] = "RUNNING";
            } else require(existing->second.second == body, "ambiguous retry changed its wire request");
            if (ambiguous) {
                ambiguous = false;
                return {HttpResponseCode::INTERNAL_SERVER_ERROR, R"({"message":"ambiguous result"})"};
            }
            return {HttpResponseCode::OK, host(existing->second.first).View().WriteCompact().c_str()};
        }
        if (path == vms && method == HttpMethod::HTTP_GET) {
            Aws::Utils::Array<Json> items(hosts.size());
            std::size_t index = 0; for (const auto& item : hosts) items[index++] = host(item.first);
            Json result; result.WithArray("items", std::move(items));
            return {HttpResponseCode::OK, result.View().WriteCompact().c_str()};
        }
        if (path.rfind(vms + "/", 0) == 0) {
            const auto id = path.substr(vms.size() + 1);
            if (method == HttpMethod::HTTP_DELETE) { ++terminations; hosts[id] = "TERMINATED"; }
            else require(method == HttpMethod::HTTP_GET, "unexpected VM action");
            return {HttpResponseCode::OK, host(id).View().WriteCompact().c_str()};
        }
        throw std::runtime_error("unexpected SDK API path: " + path);
    }
};

class Transport final : public HttpClient {
public:
    explicit Transport(std::shared_ptr<Fixture> fixture) : fixture_(std::move(fixture)) {}
    std::shared_ptr<HttpResponse> MakeRequest(const std::shared_ptr<HttpRequest>& request,
        Aws::Utils::RateLimits::RateLimiterInterface*, Aws::Utils::RateLimits::RateLimiterInterface*) const override {
        auto response = Aws::MakeShared<Aws::Http::Standard::StandardHttpResponse>("enabled-fixture", request);
        std::pair<HttpResponseCode, std::string> reply;
        try { reply = fixture_->respond(*request); }
        catch (const std::exception& error) {
            fixture_->failure = error.what();
            reply = {HttpResponseCode::INTERNAL_SERVER_ERROR, R"({"message":"fixture rejected request"})"};
        }
        response->SetResponseCode(reply.first); response->AddHeader("content-type", "application/json");
        response->GetResponseBody() << reply.second;
        return response;
    }
private:
    std::shared_ptr<Fixture> fixture_;
};
class Factory final : public HttpClientFactory {
public:
    explicit Factory(std::shared_ptr<Fixture> fixture) : fixture_(std::move(fixture)) {}
    std::shared_ptr<HttpClient> CreateHttpClient(const Aws::Client::ClientConfiguration&) const override {
        return Aws::MakeShared<Transport>("enabled-fixture", fixture_);
    }
    std::shared_ptr<HttpRequest> CreateHttpRequest(const Aws::String& uri, HttpMethod method,
                                                   const Aws::IOStreamFactory& stream) const override {
        return CreateHttpRequest(URI(uri), method, stream);
    }
    std::shared_ptr<HttpRequest> CreateHttpRequest(const URI& uri, HttpMethod method,
                                                   const Aws::IOStreamFactory& stream) const override {
        auto request = Aws::MakeShared<Aws::Http::Standard::StandardHttpRequest>("enabled-fixture", uri, method);
        request->SetResponseStreamFactory(stream); return request;
    }
private:
    std::shared_ptr<Fixture> fixture_;
};

void run(Fixture& fixture) {
    auto credentials = Aws::MakeShared<Aws::Auth::SimpleAWSCredentialsProvider>("enabled-fixture", "test-key", "test-secret");
    // Prevent a machine without an AWS profile from probing unsigned EC2
    // metadata before the explicit fixture region is assigned.
    Aws::Client::ClientConfiguration client(Aws::Client::ClientConfigurationInitValues{true});
    client.region = "eu-central-1";
    client.retryStrategy = Aws::MakeShared<Aws::Client::DefaultRetryStrategy>("enabled-fixture", 0);
    ControllerConfig config{{"arn:aws:lambda:eu-central-1:123456789012:microvm-image:agent", "1", "role", "logs", "eu-central-1"}, "1.0.0"};
    const auto invoke = [&](const char* event) {
        handle_controller_event(event, config, credentials, client);
        require(fixture.failure.empty(), fixture.failure.c_str());
    };
    constexpr const char* repair = R"({"source":"aws.events"})";
    constexpr const char* event = R"({"thingName":"tbot-test","active":true})";
    invoke(event);
    require(fixture.launch_calls == 0, "event payload overrode current inactive projection");
    fixture.observe(true);
    bool interrupted = false;
    try { invoke(event); } catch (const std::runtime_error&) { interrupted = true; }
    require(interrupted && fixture.failure.empty() && fixture.launches.size() == 1 &&
            fixture.snapshot().state.run->microvm_id.empty(), "ambiguous launch did not preserve its reservation");
    const auto first = *fixture.snapshot().state.run;
    const auto first_deadline = fixture.snapshot().state.activation.activation->deadline;
    invoke(repair); // No new lifecycle notification is delivered.
    require(fixture.launch_calls == 2 && fixture.launches.size() == 1 && fixture.conflicts == 1 &&
            fixture.snapshot().state.run->phase == RunPhase::running && fixture.snapshot().state.run->run_id == first.run_id,
            "minute repair failed to recover ambiguous launch and binding conflict");
    config.release = "2.0.0"; config.cloud.image_version = "2";
    invoke(event);
    require(fixture.launch_calls == 2 && fixture.terminations == 0 &&
            fixture.snapshot().state.run->release == "1.0.0" &&
            fixture.snapshot().state.activation.activation->deadline == first_deadline,
            "duplicate delivery, release change or failed runtime sample replaced the healthy VM");
    fixture.observe(false);
    invoke(repair); invoke(repair);
    require(fixture.terminations == 1 && !fixture.snapshot().state.run, "eventless inactivity failed to drain the current VM");
    fixture.observe(true);
    invoke(repair);
    require(fixture.launches.size() == 2 && fixture.snapshot().state.run->run_id != first.run_id &&
            fixture.snapshot().state.run->release == "2.0.0", "verified reactivation failed to launch a new release");
    auto expired = fixture.snapshot();
    const auto now = std::chrono::duration_cast<std::chrono::seconds>(std::chrono::system_clock::now().time_since_epoch()).count();
    expired.state.activation.activation->started_at = now - 3000;
    expired.state.activation.activation->deadline = now;
    fixture.shadow = Json(Aws::String(controller_shadow_patch(expired, now, expired.verified_at).c_str()));
    invoke(repair); invoke(repair); invoke(event);
    require(fixture.launches.size() == 2 && fixture.terminations == 2 && !fixture.snapshot().state.run &&
            fixture.shadow.View().GetObject("state").GetObject("reported").GetObject("lifecycle").GetString("state") == "expired" &&
            fixture.conditional_writes > 0, "expiry rolled the budget over or failed to confirm termination");
    fixture.observe(false); invoke(repair);
    fixture.observe(true); invoke(repair);
    require(fixture.launches.size() == 3 && fixture.snapshot().state.run, "test reactivation failed");
    fixture.agent_available = false; ++fixture.projection_version; ++fixture.source_time;
    invoke(repair); invoke(repair);
    require(fixture.launches.size() == 3 && fixture.terminations == 3 && !fixture.snapshot().state.run,
            "agent availability false did not drain while device REDCON stayed active");
    fixture.agent_available = true; ++fixture.projection_version; ++fixture.source_time;
    invoke(repair);
    require(fixture.launches.size() == 4 && fixture.snapshot().state.run, "agent availability reactivation failed");
    fixture.agent_declared = false;
    invoke(repair); invoke(repair);
    require(fixture.launches.size() == 4 && fixture.terminations == 4 && !fixture.snapshot().state.run,
            "removing the declared capability did not drain the assigned VM");
}
}

void test_controller_enabled_api() {
    auto fixture = std::make_shared<Fixture>();
    Aws::SDKOptions options;
    options.httpOptions.httpClientFactory_create_fn = [fixture] { return Aws::MakeShared<Factory>("enabled-fixture", fixture); };
    Aws::InitAPI(options);
    try { run(*fixture); } catch (...) { Aws::ShutdownAPI(options); throw; }
    Aws::ShutdownAPI(options);
}
