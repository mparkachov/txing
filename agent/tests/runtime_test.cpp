#include "agent/core.hpp"
#include "agent/aws.hpp"
#include "agent/controller_shadow.hpp"
#include "agent/cloud.hpp"
#include "agent/runtime_sample.hpp"
#include "agent/reconcile.hpp"
#include "agent/kvs.hpp"
#include <aws/core/Aws.h>
#include <aws/core/auth/AWSCredentialsProviderChain.h>
#include <aws/core/utils/json/JsonSerializer.h>
#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <filesystem>
#include <fstream>
#include <map>
using namespace txing::agent;
using namespace std::chrono_literals;
using Aws::Utils::Json::JsonValue;
#define REQUIRE(...) do { if (!(__VA_ARGS__)) throw std::runtime_error(std::string(__func__) + ": " + #__VA_ARGS__); } while (false)
template<class F> void eventually(F f, std::chrono::milliseconds timeout = 3s) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (!f()) {
        if (std::chrono::steady_clock::now() >= deadline) throw std::runtime_error("event deadline exceeded");
        std::this_thread::sleep_for(5ms);
    }
}
Bytes frame(bool signed_frame = false) {
    Bytes b(12 + 2 + (signed_frame ? 13 : 0), 0);
    b[0] = 0xfd; b[1] = 2; b[2] = signed_frame ? 1 : 0;
    b[7] = 0xfe; b[8] = 0xee; b[9] = 0x7f;
    b.back() = 0x7a; return b;
}
struct RecordingOperator : Operator {
    std::atomic<int> telemetry_count{0}, video_count{0}, granted{0}, lost{0};
    std::atomic<bool> block_video{false}, in_video{false};
    std::string loss_reason;
    Actions* actions = nullptr;
    void telemetry(const Bytes&) override { ++telemetry_count; }
    void video(const EncodedVideo& f) override {
        REQUIRE(f.codec == "h264"); REQUIRE(!f.bytes.empty()); in_video = true;
        while (block_video) std::this_thread::sleep_for(1ms);
        ++video_count;
    }
    void connection(Stream, Connection, const std::string&) override {}
    void control(bool held, const std::string& reason) override {
        if (held) { ++granted; if (actions) actions->send(frame(true)); }
        else { loss_reason = reason; ++lost; }
    }
};
struct FakeState {
    TransportConfig config; TransportEvents events;
    std::atomic<Connection> state{Connection::connected}; std::atomic<int> stops{0};
    bool renew = true, busy = false;
    int epoch = 7;
    std::atomic<bool> cleanup_complete{true};
    std::string error = "test connection failure after long healthy operation";
    std::vector<Bytes> binary; std::vector<std::string> text;
};
std::string reply(const std::string& id, const std::string& type, int epoch = 7) {
    return "{\"type\":\"" + type + "\",\"requestId\":\"" + id +
        "\",\"state\":{\"epoch\":" + std::to_string(epoch) +
        ",\"leaseTtlMs\":5000,\"activeControl\":{\"epoch\":" + std::to_string(epoch) +
        ",\"sessionId\":\"peer-1\",\"actor\":\"test\"}}}";
}
void receive(const std::shared_ptr<FakeState>& s, const std::string& json) {
    s->events.data(Bytes(json.begin(), json.end()), false);
}
struct FakeTransport : Transport {
    std::shared_ptr<FakeState> s;
    explicit FakeTransport(std::shared_ptr<FakeState> state) : s(std::move(state)) {}
    void start(const TransportConfig& c, TransportEvents e) override { s->config = c; s->events = std::move(e); }
    void stop() noexcept override { ++s->stops; }
    bool finished() const override { return s->cleanup_complete; }
    Connection state() const override { return s->state; }
    std::string error() const override { return s->error; }
    bool send(const Bytes& b, bool binary) override {
        if (binary) { s->binary.push_back(b); return true; }
        std::string json(b.begin(), b.end()); s->text.push_back(json);
        JsonValue parsed(json.c_str()); auto v = parsed.View();
        auto type = v.GetString("type"), id = v.GetString("requestId");
        if (type == "control.activate") {
            REQUIRE(!v.GetBool("takeover"));
            if (s->busy) receive(s, "{\"type\":\"control.error\",\"requestId\":\"" + std::string(id.c_str()) + "\",\"code\":\"control_busy\"}");
            else receive(s, reply(id.c_str(), "control.activated", s->epoch));
        } else if (type == "control.renew_active" && s->renew) receive(s, reply(id.c_str(), "control.renewed", s->epoch));
        return true;
    }
};
struct Fixture {
    RecordingOperator op; std::vector<std::shared_ptr<FakeState>> links;
    const Time now = Time{} + 100s;
    Session session{profile("tbot", "id", "region", "ca"), [this] {
        auto s = std::make_shared<FakeState>(); links.push_back(s); return std::make_unique<FakeTransport>(s);
    }, op, now};
    Fixture() { op.actions = &session; }
    void active(int redcon = 1) { session.verified({true, redcon}, now); REQUIRE(session.tick(now)); }
    void acquire() {
        REQUIRE(session.acquire("test")); session.tick(now); session.tick(now);
        eventually([&] { return op.granted == 1; });
        eventually([&] { session.tick(now); return !links[0]->binary.empty(); });
    }
};
void profile_and_framing() {
    auto p = profile("tbot", "unrelated-name", "region", "ca");
    REQUIRE(p.telemetry.channel == "unrelated-name-mavlink");
    REQUIRE(p.video.channel == "unrelated-name-board-video");
    REQUIRE(p.telemetry.region == "region" && p.telemetry.label == "txing.mavlink.v1");
    bool rejected = false;
    try { profile("unit", "tbot-name", "region", "ca"); } catch (...) { rejected = true; }
    REQUIRE(rejected); REQUIRE(valid_mavlink2(frame())); REQUIRE(valid_mavlink2(frame(true)));
    auto bad = frame(); bad.push_back(0); REQUIRE(!valid_mavlink2(bad));
    bad = frame(); bad[2] = 2; REQUIRE(!valid_mavlink2(bad));
}
void lifecycle_and_recovery() {
    Fixture f; REQUIRE(f.session.tick(f.now)); REQUIRE(f.links.empty());
    f.active(2); REQUIRE(f.links.size() == 1);
    f.session.verified({true, 1}, f.now); f.session.tick(f.now); REQUIRE(f.links.size() == 2);
    auto telemetry = f.links[0], video = f.links[1];
    video->state = Connection::failed; f.session.tick(f.now + 1s);
    REQUIRE(video->stops == 1 && telemetry->stops == 0);
    f.session.tick(f.now + 2s); REQUIRE(f.links.size() == 3);
    f.session.verified({true, 2}, f.now + 3s); f.session.tick(f.now + 3s);
    REQUIRE(f.links[2]->stops == 1 && telemetry->stops == 0);
    REQUIRE(f.session.tick(f.now + 17s));
    REQUIRE(!f.session.tick(f.now + 18s)); REQUIRE(telemetry->stops == 1);
    for (auto lifecycle : {Lifecycle{false, 1}, Lifecycle{true, 3}, Lifecycle{true, 4}}) {
        Fixture stopped; stopped.session.verified(lifecycle, stopped.now);
        REQUIRE(!stopped.session.tick(stopped.now)); REQUIRE(stopped.links.empty());
    }
    Fixture late; late.active(2); const auto hours = late.now + std::chrono::hours(24);
    late.links[0]->events.data(frame(), true);
    late.session.verified({true, 2}, hours); late.session.tick(hours);
    late.links[0]->state = Connection::failed; late.session.tick(hours + 1s);
    REQUIRE(late.links[0]->stops == 1); late.session.tick(hours + 2s); REQUIRE(late.links.size() == 2);
    Fixture slow; slow.active(); slow.acquire();
    slow.links[1]->cleanup_complete = false; slow.links[1]->state = Connection::failed;
    slow.session.tick(slow.now + 1s); slow.session.tick(slow.now + 2s);
    REQUIRE(slow.links.size() == 2 && slow.links[0]->stops == 0);
    slow.session.send(frame(true)); slow.session.tick(slow.now + 2s);
    REQUIRE(slow.links[0]->binary.size() == 2);
    slow.links[1]->cleanup_complete = true; slow.session.tick(slow.now + 3s);
    REQUIRE(slow.links.size() == 3);
}
void silent_telemetry_recovery() {
    Fixture f; f.active(); f.acquire();
    auto telemetry = f.links[0], video = f.links[1];
    telemetry->cleanup_complete = false;
    for (int second = 1; second <= 18; ++second) {
        if (second == 4) telemetry->events.data(frame(), true);
        // Control replies and lifecycle success must not hide missing MAVLink.
        f.session.client_activity();
        f.session.verified({true, 1}, f.now + std::chrono::seconds(second));
        REQUIRE(f.session.tick(f.now + std::chrono::seconds(second)));
        REQUIRE(telemetry->stops == 0 && video->stops == 0);
    }
    eventually([&] { return f.op.telemetry_count == 1; });
    telemetry->events.data({0}, true); // Invalid frames do not refresh receipt.
    const auto sent = telemetry->binary.size();
    REQUIRE(f.session.send(frame(true)));
    f.session.verified({true, 1}, f.now + 19s);
    REQUIRE(f.session.tick(f.now + 19s));
    eventually([&] { return f.op.lost == 1; });
    REQUIRE(telemetry->stops == 1 && video->stops == 0);
    REQUIRE(telemetry->binary.size() == sent); // Queued authority is fenced.
    REQUIRE(!f.session.send(frame(true)));
    telemetry->events.data(frame(), true); // Retired generation is ignored.
    f.session.verified({true, 1}, f.now + 20s); f.session.tick(f.now + 20s);
    REQUIRE(f.links.size() == 2); // Teardown never blocks or overlaps peers.
    telemetry->cleanup_complete = true;
    f.session.tick(f.now + 21s);
    REQUIRE(f.links.size() == 3 && video->stops == 0);
    auto replacement = f.links[2];
    replacement->events.data(frame(), true); f.session.tick(f.now + 22s);
    eventually([&] { return f.op.telemetry_count == 2; });
    REQUIRE(f.op.granted == 1 && replacement->binary.empty());
    telemetry->events.data(frame(), true);
    f.session.verified({true, 1}, f.now + 36s); f.session.tick(f.now + 36s);
    REQUIRE(replacement->stops == 0);
    f.session.verified({true, 1}, f.now + 37s); f.session.tick(f.now + 37s);
    REQUIRE(replacement->stops == 1 && video->stops == 0);

    Fixture negotiation; negotiation.active(2);
    negotiation.links[0]->state = Connection::connecting;
    negotiation.session.verified({true, 2}, negotiation.now + 14s);
    negotiation.session.tick(negotiation.now + 14s);
    negotiation.links[0]->state = Connection::connected;
    negotiation.session.verified({true, 2}, negotiation.now + 19s);
    negotiation.session.tick(negotiation.now + 19s);
    negotiation.session.verified({true, 2}, negotiation.now + 33s);
    negotiation.session.tick(negotiation.now + 33s);
    REQUIRE(negotiation.links[0]->stops == 0);
    negotiation.session.verified({true, 2}, negotiation.now + 34s);
    negotiation.session.tick(negotiation.now + 34s);
    REQUIRE(negotiation.links[0]->stops == 1);
}
void operator_and_authority() {
    Fixture f; f.active(); f.links[0]->events.data(frame(), true);
    f.links[1]->events.video({{0,0,0,1,0x65,1}, "h264", 7654, std::chrono::system_clock::now()});
    eventually([&] { return f.op.telemetry_count == 1 && f.op.video_count == 1; });
    REQUIRE(!f.session.send(frame())); f.session.tick(f.now); REQUIRE(f.links[0]->binary.empty());
    f.acquire(); REQUIRE(f.links[0]->binary.size() == 1 && f.links[0]->binary[0] == frame(true));
    REQUIRE(f.session.send(frame(true))); f.session.tick(f.now + 1s); f.session.tick(f.now + 1s);
    REQUIRE(f.links[0]->binary.size() == 2 && f.op.lost == 0);
    f.session.tick(f.now + 6s); eventually([&] { return f.op.lost == 1; });
    REQUIRE(f.links[0]->text.back().find("control.release_active") != std::string::npos);
    f.session.tick(f.now + 7s); REQUIRE(f.op.granted == 1);
    Fixture busy; busy.active(2); busy.links[0]->busy = true;
    busy.session.acquire("other"); busy.session.tick(busy.now); busy.session.tick(busy.now);
    eventually([&] { return busy.op.lost == 1; }); REQUIRE(busy.op.granted == 0);
}
void loss_and_shutdown() {
    Fixture f; f.active(); f.acquire();
    receive(f.links[0], reply("unrelated", "control.state", 8)); f.session.tick(f.now + 1s);
    eventually([&] { return f.op.lost == 1; });
    f.session.send(frame()); f.session.tick(f.now + 1s); REQUIRE(f.links[0]->binary.size() == 1);
    Fixture disconnect; disconnect.active(2); disconnect.acquire();
    disconnect.links[0]->state = Connection::failed; disconnect.session.tick(disconnect.now + 1s);
    eventually([&] { return disconnect.op.lost == 1; });
    disconnect.session.tick(disconnect.now + 2s); REQUIRE(disconnect.op.granted == 1);
    Fixture shutdown; shutdown.active(2); shutdown.acquire(); shutdown.session.shutdown("test shutdown");
    REQUIRE(shutdown.links[0]->text.back().find("control.release_active") != std::string::npos);
    REQUIRE(shutdown.links[0]->stops == 1);
    Fixture expiry; expiry.active(2); expiry.acquire(); expiry.links[0]->renew = false;
    expiry.session.client_activity(); expiry.session.tick(expiry.now + 1s);
    expiry.session.client_activity(); expiry.session.tick(expiry.now + 4s);
    eventually([&] { return expiry.op.lost == 1; });
}
void queued_authority() {
    Fixture f; f.active(2); f.op.actions = nullptr;
    REQUIRE(f.session.acquire("test")); f.session.tick(f.now);
    // The board reply is queued, but the operator has not been granted control.
    // A frame submitted now must never become authorized by that later reply.
    REQUIRE(!f.session.send(frame(true))); f.session.tick(f.now);
    eventually([&] { return f.op.granted == 1; });
    REQUIRE(f.links[0]->binary.empty());
    // A frame queued with authority must also be dropped if a takeover is
    // observed before dispatch. Explicit reacquisition permits only new work.
    REQUIRE(f.session.send(frame(true)));
    receive(f.links[0], reply("takeover", "control.state", 8)); f.session.tick(f.now);
    REQUIRE(f.links[0]->binary.empty());
    REQUIRE(!f.session.send(frame(true)));
    f.links[0]->epoch = 9;
    REQUIRE(f.session.acquire("test")); f.session.tick(f.now); f.session.tick(f.now);
    eventually([&] { return f.op.granted == 2; });
    REQUIRE(f.links[0]->binary.empty());
    REQUIRE(f.session.send(frame(true))); f.session.tick(f.now);
    REQUIRE(f.links[0]->binary == std::vector<Bytes>{frame(true)});
}
void malformed_control_diagnostics() {
    const std::string marker = "private-control-marker";
    for (const auto& payload : std::vector<std::string>{
            "", marker, "{\"" + marker + "\":",
            "{\"" + marker + "\":\"" + std::string(1, '\0') + "\"}"}) {
        Fixture f; f.active(); f.acquire();
        auto telemetry = f.links[0], video = f.links[1];
        telemetry->renew = false;
        f.session.client_activity(); f.session.tick(f.now + 1s);
        const auto sent = telemetry->binary.size();
        REQUIRE(f.session.send(frame(true)));
        receive(telemetry, payload); f.session.tick(f.now + 2s);
        eventually([&] { return f.op.lost == 1; });
        REQUIRE(telemetry->binary.size() == sent); // Fence queued authority.
        REQUIRE(!f.session.send(frame(true)));
        REQUIRE(telemetry->text.back().find("control.release_active") != std::string::npos);
        REQUIRE(f.op.loss_reason.find("invalid control JSON") == 0);
        REQUIRE(f.op.loss_reason.find("bytes=" + std::to_string(payload.size())) != std::string::npos);
        REQUIRE(f.op.loss_reason.find(marker) == std::string::npos);
        REQUIRE(f.op.loss_reason.size() < 180);
        telemetry->events.data(frame(), true);
        f.session.client_activity(); f.session.tick(f.now + 3s);
        eventually([&] { return f.op.telemetry_count == 1; });
        REQUIRE(telemetry->stops == 0 && video->stops == 0);
        REQUIRE(f.op.granted == 1); // Healthy traffic does not reacquire.
    }
}
void bounded_video() {
    Queue<Bytes> q(2, 3); REQUIRE(q.push({1,2}, 2)); REQUIRE(q.push({3,4}, 2)); REQUIRE(q.dropped() == 1);
    REQUIRE(!q.push({1,2,3,4}, 4)); REQUIRE(q.pop().value() == Bytes({3,4}));
    Fixture f; f.active(); f.op.block_video = true;
    struct Unblock { RecordingOperator& op; ~Unblock() { op.block_video = false; } } unblock{f.op};
    f.links[1]->events.video({{1}, "h264", 1, std::chrono::system_clock::now()});
    eventually([&] { return f.op.in_video.load(); });
    for (int i=0; i<100; ++i) f.links[1]->events.video({Bytes(1024*1024, 1), "h264", 42, std::chrono::system_clock::now()});
    REQUIRE(f.session.video_dropped() >= 96);
    f.links[0]->events.data(frame(), true); f.acquire();
    eventually([&] { return f.op.telemetry_count == 1; });
    f.session.release(); f.session.tick(f.now); eventually([&] { return f.op.lost == 1; });
}
struct RotatingCredentials : Aws::Auth::AWSCredentialsProvider {
    int generation = 1; bool expired = false, throwing = false;
    Aws::Auth::AWSCredentials GetAWSCredentials() override {
        if (throwing) throw std::runtime_error("secret should never appear");
        return {("key" + std::to_string(generation)).c_str(), "test-secret", "test-token",
            Aws::Utils::DateTime(Aws::Utils::DateTime::Now().Millis() + (expired ? -1000 : 60000))};
    }
};
void credentials_and_errors() {
    auto source = std::make_shared<RotatingCredentials>(); Credentials adapter(source); PAwsCredentials output = nullptr;
    REQUIRE(STATUS_SUCCEEDED(adapter.getCredentialsFn(&adapter, &output)));
    REQUIRE(std::string(output->accessKeyId) == "key1" && std::string(output->sessionToken) == "test-token");
    source->generation = 2; REQUIRE(STATUS_SUCCEEDED(adapter.getCredentialsFn(&adapter, &output)));
    REQUIRE(std::string(output->accessKeyId) == "key2"); source->expired = true;
    REQUIRE(STATUS_FAILED(adapter.getCredentialsFn(&adapter, &output)) && !output);
    REQUIRE(!adapter.error().empty()); source->throwing = true;
    REQUIRE(STATUS_FAILED(adapter.getCredentialsFn(&adapter, &output)));
    REQUIRE(adapter.error().find("secret") == std::string::npos);
    auto transport = make_kvs_transport(source);
    transport->start({"explicit-channel", "us-west-2", "custom-label", "ca", Media::data, Role::viewer}, {});
    eventually([&] { return transport->state() == Connection::failed; });
    REQUIRE(transport->error().find("KVS status 0x") != std::string::npos);
    REQUIRE(transport->error().find("credential") != std::string::npos); transport->stop();
    auto static_source = std::make_shared<Aws::Auth::SimpleAWSCredentialsProvider>("static-key", "static-secret");
    Credentials static_adapter(static_source);
    REQUIRE(STATUS_SUCCEEDED(static_adapter.getCredentialsFn(&static_adapter, &output)));
}
void sdk_credential_chain() {
    Aws::Auth::DefaultAWSCredentialsProviderChain chain;
    auto credentials = chain.GetAWSCredentials();
    REQUIRE(credentials.GetAWSAccessKeyId() == "profile-key");
    REQUIRE(credentials.GetSessionToken() == "profile-token");
    Aws::Client::ClientConfiguration config;
    REQUIRE(config.region == "eu-central-1");
    setenv("AWS_ACCESS_KEY_ID", "env-key", 1);
    setenv("AWS_SECRET_ACCESS_KEY", "env-secret", 1);
    setenv("AWS_SESSION_TOKEN", "env-token", 1);
    Aws::Auth::DefaultAWSCredentialsProviderChain environment;
    REQUIRE(environment.GetAWSCredentials().GetSessionToken() == "env-token");
    unsetenv("AWS_SESSION_TOKEN");
    Aws::Auth::DefaultAWSCredentialsProviderChain static_environment;
    REQUIRE(static_environment.GetAWSCredentials().GetAWSAccessKeyId() == "env-key");
    REQUIRE(static_environment.GetAWSCredentials().GetSessionToken().empty());
    unsetenv("AWS_ACCESS_KEY_ID"); unsetenv("AWS_SECRET_ACCESS_KEY");
}
void projected_lifecycle() {
    const std::string start = "{\"state\":{\"reported\":{\"topic\":{\"deviceId\":\"id\",\"namespace\":\"spBv1.0\",\"messageType\":\"";
    auto born = parse_lifecycle(start + "DDATA\"},\"payload\":{\"metrics\":{\"redcon\":2,\"capability\":{\"agent\":true}}}}}}", "id");
    REQUIRE(born.born && born.redcon == 2);
    REQUIRE(!parse_lifecycle(start + "DDEATH\"}}}}", "id").born);
    bool rejected = false;
    try { parse_lifecycle(start + "DDATA\"},\"payload\":{\"metrics\":{\"redcon\":2,\"capability\":{\"agent\":true}}}}}}", "wrong"); }
    catch (...) { rejected = true; } REQUIRE(rejected);
    const std::string versioned = "{\"version\":9,\"state\":{\"reported\":{\"topic\":{\"deviceId\":\"id\",\"namespace\":\"spBv1.0\",\"messageType\":\"";
    auto active = parse_projection_observation(versioned + "DDATA\"},\"payload\":{\"timestamp\":1000,\"metrics\":{\"redcon\":1,\"capability\":{\"agent\":true}}}}}}", "id");
    REQUIRE(active.version == 9 && active.active && *active.active && active.source_timestamp_ms == 1000);
    const auto disabled = parse_projection_observation(versioned + "DDATA\"},\"payload\":{\"timestamp\":1001,\"metrics\":{\"redcon\":1,\"capability\":{\"agent\":false}}}}}}", "id");
    REQUIRE(disabled.active && !*disabled.active);
    rejected = false;
    try { parse_projection_observation(versioned + "DDATA\"},\"payload\":{\"timestamp\":1001,\"metrics\":{\"redcon\":1}}}}}", "id"); }
    catch (...) { rejected = true; } REQUIRE(rejected);
    auto inactive = parse_projection_observation(versioned + "DDEATH\"},\"payload\":{\"timestamp\":1001,\"metrics\":{}}}}}", "id");
    REQUIRE(inactive.active && !*inactive.active);
    rejected = false;
    try { parse_projection_observation(versioned + "DDEATH\"},\"payload\":{}}}}", "id"); }
    catch (...) { rejected = true; } REQUIRE(rejected);
    rejected = false;
    try { parse_projection_observation(start + "DDATA\"},\"payload\":{\"metrics\":{\"redcon\":2,\"capability\":{\"agent\":true}}}}}}", "id"); }
    catch (...) { rejected = true; } REQUIRE(rejected);
    std::mutex mutex; std::vector<Time> calls;
    LifecyclePoller poller([&] {
        std::lock_guard<std::mutex> lock(mutex); calls.push_back(std::chrono::steady_clock::now()); return Lifecycle{true, 1};
    });
    eventually([&] { std::lock_guard<std::mutex> lock(mutex); return calls.size() >= 2; }, 2500ms);
    std::lock_guard<std::mutex> lock(mutex); REQUIRE(calls[1] - calls[0] >= 1900ms);
}
void controller_shadow() {
    auto snapshot = parse_controller_shadow(R"({"version":4,"state":{"reported":{"lifecycle":{"state":"stopped"}}}})");
    auto id = [] { return "activation-1"; };
    observe_activation(snapshot.state.activation, {9, false, 9000}, 100, 3000, id);
    observe_activation(snapshot.state.activation, {10, true, 10000}, 101, 3000, id);
    REQUIRE(reserve_run(snapshot.state, CurrentLifecycle::active, 101, "run-1", "1.0.0", "request"));
    snapshot.unverified_since = 100;
    const auto patch = controller_shadow_patch(snapshot, 101, 101);
    auto restored = parse_controller_shadow(patch);
    REQUIRE(restored.shadow_version == 4 && restored.unverified_since == 100 && restored.state.activation.projection_version == 10 &&
            restored.state.activation.activation->deadline == 3100 && restored.state.run->run_id == "run-1" &&
            restored.state.run->request == "request" && restored.state.run->phase == RunPhase::reserved);
    REQUIRE(accept_launch(restored.state, "run-1", "vm-1", true, CurrentLifecycle::active, 102) == LaunchResult::accepted);
    auto running = parse_controller_shadow(controller_shadow_patch(restored, 102, 102));
    REQUIRE(running.state.run->microvm_id == "vm-1" && running.state.run->phase == RunPhase::running);
    fence_run(running.state, CurrentLifecycle::inactive, 103);
    running = parse_controller_shadow(controller_shadow_patch(running, 103, 102));
    REQUIRE(running.stop_requested_at == 103);
    running = parse_controller_shadow(controller_shadow_patch(running, 170, 102));
    REQUIRE(running.stop_requested_at == 103); // Repeated writes cannot postpone witness's grace period.
    REQUIRE(confirm_run_stopped(running.state, "run-1", "vm-1"));
    const auto stopped = parse_controller_shadow(controller_shadow_patch(running, 103, 102));
    REQUIRE(!stopped.state.run && stopped.stop_requested_at == 0 && stopped.state.activation.activation->deadline == 3100);
    bool rejected = false;
    try { parse_controller_shadow(R"({"version":5,"state":{"reported":{"lifecycle":{"state":"expired"},"activation":{"id":"old","startedAt":1,"deadline":3001}}}})"); }
    catch (...) { rejected = true; } REQUIRE(rejected);
}
void cloud_launch_request() {
    const CloudConfig config{"image-arn", "7", "execution-role", "log-group", "eu-central-1"};
    const auto first = make_cloud_request(config, "tbot-test", "run-1", "activation-1", 3100, 100);
    const auto retry = make_cloud_request(config, "tbot-test", "run-1", "activation-1", 3100, 100);
    REQUIRE(first == retry);
    JsonValue request(Aws::String(first.c_str()));
    auto view = request.View();
    REQUIRE(request.WasParseSuccessful() && view.GetInt64("maximumDurationInSeconds") == 3000 &&
            view.GetString("clientToken") == "run-1" && !view.ValueExists("idlePolicy"));
    JsonValue hook(view.GetString("runHookPayload"));
    REQUIRE(hook.WasParseSuccessful() && hook.View().GetString("runId") == "run-1" &&
            hook.View().GetString("activationId") == "activation-1" && hook.View().GetString("deadline") == "3100");
    auto replacement = make_cloud_request(config, "tbot-test", "run-2", "activation-1", 3100, 3090);
    JsonValue next(Aws::String(replacement.c_str()));
    REQUIRE(next.View().GetInt64("maximumDurationInSeconds") == 10);
    bool rejected = false;
    try { make_cloud_request(config, "tbot-test", "run-2", "activation-1", 3100, 3100); }
    catch (...) { rejected = true; } REQUIRE(rejected);
}
void known_assignment_drain() {
    struct Fake : KnownDrainBackend {
        std::vector<std::string> names, described, fenced, terminated;
        std::map<std::string, ControllerSnapshot> shadows;
        std::string image;
        std::vector<std::string> things() override { return names; }
        std::optional<ControllerSnapshot> read(const std::string& thing) override {
            const auto it = shadows.find(thing); return it == shadows.end() ? std::nullopt : std::optional(it->second);
        }
        CloudRunDetails describe(const std::string& id) override {
            described.push_back(id);
            return {{id, id == "vm-terminal" ? "TERMINATED" : "RUNNING", {}},
                    id == "vm-mismatch" ? "arn:aws:lambda:eu-central-1:123456789012:microvm-image:other" : image};
        }
        bool fence(const std::string& thing, ControllerSnapshot&) override {
            fenced.push_back(thing); return thing != "conflict";
        }
        void terminate(const std::string& id) override { terminated.push_back(id); }
    } io;
    io.image = "arn:aws:lambda:eu-central-1:123456789012:microvm-image:agent";
    const CloudConfig config{io.image, "1", "execution-role", "log-group", "eu-central-1"};
    auto add = [&](const std::string& thing, const std::string& id, const std::string& request_thing) {
        ControllerSnapshot snapshot;
        snapshot.state.run = RunReservation{"run-1", "activation-1", "1.0.0",
            make_cloud_request(config, request_thing, "run-1", "activation-1", 3100, 100), id, RunPhase::running};
        io.shadows.emplace(thing, snapshot);
    };
    add("good", "vm-good", "good");
    add("mismatch", "vm-mismatch", "mismatch");
    add("conflict", "vm-conflict", "conflict");
    add("wrong-thing", "vm-wrong", "someone-else");
    add("wrong-activation", "vm-wrong-activation", "wrong-activation");
    io.shadows.at("wrong-activation").state.run->activation_id = "other-activation";
    add("wrong-token", "vm-wrong-token", "wrong-token");
    io.shadows.at("wrong-token").state.run->run_id = "other-run";
    add("unidentified", "", "unidentified");
    add("terminal", "vm-terminal", "terminal");
    io.names = {"good", "missing", "mismatch", "conflict", "wrong-thing", "wrong-activation",
                "wrong-token", "unidentified", "terminal"};
    REQUIRE(!drain_known_assignments(io));
    REQUIRE(io.terminated == std::vector<std::string>{"vm-good"});
    REQUIRE(io.fenced == std::vector<std::string>({"good", "conflict", "terminal"}));
    for (const std::string invalid : {"vm-wrong", "vm-wrong-activation", "vm-wrong-token"})
        REQUIRE(std::find(io.described.begin(), io.described.end(), invalid) == io.described.end());
    io.names = {"terminal"};
    REQUIRE(drain_known_assignments(io));
}
void runtime_sampling() {
    ControllerSnapshot snapshot; snapshot.shadow_version = 7;
    observe_activation(snapshot.state.activation, {1, false, 1000}, 100, 3000, [] { return "a"; });
    observe_activation(snapshot.state.activation, {2, true, 2000}, 101, 3000, [] { return "a"; });
    REQUIRE(reserve_run(snapshot.state, CurrentLifecycle::active, 101, "run", "1.0.0", "request"));
    REQUIRE(accept_launch(snapshot.state, "run", "vm", true, CurrentLifecycle::active, 101) == LaunchResult::accepted);
    const std::string stopped = R"({"phase":"stopped","thingId":"tbot-test","runId":"run","activationId":"a","microvmId":"vm","assignmentVerified":false})";
    REQUIRE(runtime_stopped_for(snapshot, "tbot-test", stopped));
    REQUIRE(!runtime_stopped_for(snapshot, "other-thing", stopped));
    REQUIRE(!runtime_stopped_for(snapshot, "tbot-test", "{"));
    REQUIRE(!runtime_stopped_for(snapshot, "tbot-test", R"({"phase":"stopped","thingId":"tbot-test","runId":"run","activationId":"old","microvmId":"vm"})"));
    REQUIRE(!runtime_stopped_for(snapshot, "tbot-test", R"({"phase":"running","thingId":"tbot-test","runId":"run","activationId":"a","microvmId":"vm"})"));
    auto superseded = snapshot; superseded.state.run->microvm_id = "new-vm";
    REQUIRE(!runtime_stopped_for(superseded, "tbot-test", stopped));
    superseded = snapshot; superseded.state.run->phase = RunPhase::stopping;
    REQUIRE(!runtime_stopped_for(superseded, "tbot-test", stopped));
    const std::string fresh = R"({"phase":"running","thingId":"tbot-test","runId":"run","activationId":"a","microvmId":"vm","deadline":3100,"assignmentVerified":true,"assignmentAgeMs":500})";
    REQUIRE(runtime_verified_for(snapshot, "tbot-test", fresh, 1000));
    REQUIRE(!runtime_verified_for(snapshot, "other", fresh, 1000));
    REQUIRE(!runtime_verified_for(snapshot, "tbot-test", fresh, 14500));
    REQUIRE(!runtime_verified_for(snapshot, "tbot-test", fresh, -1));
    REQUIRE(!runtime_verified_for(snapshot, "tbot-test", stopped, 0));
    REQUIRE(!runtime_verified_for(superseded, "tbot-test", fresh, 0));
    REQUIRE(!runtime_verified_for(snapshot, "tbot-test", R"({"phase":"running","thingId":"tbot-test","runId":"run","activationId":"a","microvmId":"vm","deadline":3100,"assignmentVerified":true})", 0));
    const std::string sample = R"({"phase":"running","runId":"run","activationId":"a","microvmId":"vm","deadline":3100,"assignmentVerified":true,"telemetry":{"state":2,"error":""},"video":{"state":3,"error":"KVS signaling callback: KVS status 0xbeef; private-token"},"control":{"state":"lost","error":"stale_epoch"},"videoFrames":42,"lastVideo":{"receiptUnixMs":105000}})";
    const auto patch = runtime_sample_patch(snapshot, "vm.lambda-microvm.eu-central-1.on.aws", sample, 105);
    JsonValue result(Aws::String(patch.c_str()));
    const auto reported = result.View().GetObject("state").GetObject("reported");
    const auto runtime = reported.GetObject("runtime");
    REQUIRE(result.View().GetInt64("version") == 7 && runtime.GetString("runId") == "run" &&
            runtime.GetObject("mavlink").GetString("state") == "connected" &&
            runtime.GetObject("video").GetString("state") == "error" &&
            runtime.GetObject("video").GetString("lastError") == "KVS signaling callback: KVS status 0xbeef" &&
            runtime.GetObject("control").GetString("lastError") == "stale_epoch" && patch.find("private-token") == std::string::npos);
    bool rejected = false;
    try { runtime_sample_patch(snapshot, "example.com", sample, 105); }
    catch (...) { rejected = true; } REQUIRE(rejected);
    snapshot.state.run->run_id = "new-run"; rejected = false;
    try { runtime_sample_patch(snapshot, "vm.lambda-microvm.eu-central-1.on.aws", sample, 105); }
    catch (...) { rejected = true; } REQUIRE(rejected);
}
void sdk_peers();
void sdk_manual();
void sdk_concurrent_data_channel();
int main() {
    // Every SDK configuration read in tests stays inside repository scratch.
    const auto scratch = std::filesystem::path(__FILE__).parent_path().parent_path().parent_path() / "tmp/agent-test";
    std::filesystem::create_directories(scratch);
    const auto config_path = (scratch / "config").string(), credentials_path = (scratch / "credentials").string();
    std::ofstream(config_path) << "[profile fixture]\nregion = eu-central-1\n";
    std::ofstream(credentials_path) << "[fixture]\naws_access_key_id = profile-key\naws_secret_access_key = profile-secret\naws_session_token = profile-token\n";
    setenv("AWS_CONFIG_FILE", config_path.c_str(), 1); setenv("AWS_SHARED_CREDENTIALS_FILE", credentials_path.c_str(), 1);
    setenv("AWS_PROFILE", "fixture", 1); setenv("AWS_EC2_METADATA_DISABLED", "true", 1);
    for (const char* key : {"AWS_DEFAULT_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_REGION", "AWS_DEFAULT_REGION"}) unsetenv(key);
    Aws::SDKOptions options; Aws::InitAPI(options); int result = 0;
    try {
        KvsRuntime runtime;
        for (const auto& test : std::vector<std::pair<const char*, void(*)()>>{
            {"profile and framing", profile_and_framing}, {"lifecycle and recovery", lifecycle_and_recovery},
            {"silent telemetry recovery", silent_telemetry_recovery},
            {"operator and authority", operator_and_authority}, {"loss and shutdown", loss_and_shutdown},
            {"queued authority", queued_authority},
            {"malformed control diagnostics", malformed_control_diagnostics},
            {"bounded video", bounded_video}, {"credentials and errors", credentials_and_errors},
            {"SDK credential chain", sdk_credential_chain}, {"projected lifecycle", projected_lifecycle}, {"controller shadow", controller_shadow}, {"cloud launch request", cloud_launch_request}, {"known assignment drain", known_assignment_drain}, {"runtime sampling", runtime_sampling},
            {"real SDK peers", sdk_peers}, {"real SDK manual UDP", sdk_manual},
            {"real SDK concurrent data channel", sdk_concurrent_data_channel}}) {
            test.second(); std::cout << "PASS " << test.first << std::endl;
        }
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; result = 1; }
    Aws::ShutdownAPI(options); return result;
}
