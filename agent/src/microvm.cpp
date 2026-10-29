#include "agent/microvm.hpp"
#include "agent/aws.hpp"
#include "agent/controller_shadow.hpp"
#include "agent/runtime_sample.hpp"
#include "agent/kvs.hpp"
#include <aws/core/Aws.h>
#include <aws/core/auth/AWSCredentialsProviderChain.h>
#include <aws/core/client/DefaultRetryStrategy.h>
#include <aws/core/utils/json/JsonSerializer.h>
#include <algorithm>
#include <csignal>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <com/amazonaws/kinesis/video/common/jsmn.h>

#ifndef TXING_AGENT_BUILD_ID
#define TXING_AGENT_BUILD_ID "development"
#endif

namespace txing::agent {
namespace {
using Json = Aws::Utils::Json::JsonValue;
using namespace std::chrono_literals;
bool identifier(const std::string& value, std::size_t limit) {
    return !value.empty() && value.size() <= limit &&
        value.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-:.") == std::string::npos;
}
std::string json(const Json& value) { return value.View().WriteCompact().c_str(); }
Json parse(const std::string& value) {
    Json result(Aws::String(value.c_str()));
    if (!result.WasParseSuccessful() || !result.View().IsObject()) throw std::invalid_argument("invalid JSON object");
    return result;
}
std::string field(Aws::Utils::Json::JsonView view, const char* name) {
    if (!view.ValueExists(name) || !view.GetObject(name).IsString()) throw std::invalid_argument("missing string field");
    return view.GetString(name).c_str();
}
// Build hooks must not initialize AWS globals (which load configuration and
// credential caches). The existing pinned SDK's small parser handles only the
// ASCII string envelope before /run; no AWS C++ API is used in that phase.
std::map<std::string, std::string> string_fields(const std::string& text) {
    jsmn_parser parser; jsmn_init(&parser);
    jsmntok_t tokens[16];
    const int count = jsmn_parse(&parser, text.data(), text.size(), tokens, 16);
    if (count < 3 || count % 2 != 1 || tokens[0].type != JSMN_OBJECT)
        throw std::invalid_argument("expected string object");
    auto delimiter = [&](int begin, int end, const char* expected) {
        if (end < begin) throw std::invalid_argument("invalid object");
        auto value = text.substr(begin, end - begin);
        value.erase(std::remove_if(value.begin(), value.end(), [](char c) {
            return c == ' ' || c == '\t' || c == '\r' || c == '\n';
        }), value.end());
        if (value != expected) throw std::invalid_argument("invalid object separator");
    };
    auto decode = [&](const jsmntok_t& token) {
        if (token.type != JSMN_STRING) throw std::invalid_argument("expected string");
        std::string value;
        for (int index = token.start; index < token.end; ++index) {
            char c = text[index];
            if (c == '\\') {
                if (++index >= token.end) throw std::invalid_argument("invalid escape");
                c = text[index];
                if (c != '"' && c != '\\' && c != '/') throw std::invalid_argument("unsupported escape");
            }
            value += c;
        }
        return value;
    };
    if (text.substr(0, tokens[0].start).find_first_not_of(" \t\r\n") != std::string::npos ||
        text.substr(tokens[0].end).find_first_not_of(" \t\r\n") != std::string::npos)
        throw std::invalid_argument("trailing JSON");
    std::map<std::string, std::string> fields;
    delimiter(tokens[0].start + 1, tokens[1].start - 1, "");
    for (int index = 1; index < count; index += 2) {
        delimiter(tokens[index].end + 1, tokens[index + 1].start - 1, ":");
        delimiter(tokens[index + 1].end + 1,
                  index + 2 < count ? tokens[index + 2].start - 1 : tokens[0].end - 1,
                  index + 2 < count ? "," : "");
        if (!fields.emplace(decode(tokens[index]), decode(tokens[index + 1])).second)
            throw std::invalid_argument("duplicate field");
    }
    return fields;
}
HookReply reply(unsigned code, const char* value) {
    // All callers supply fixed diagnostic literals, with no remote contents.
    return {code, "{\"result\":\"" + std::string(value) + "\"}"};
}
std::string safe_error(const char* error) {
    const std::string detail(error);
    for (const std::string operation : {"iot:DescribeThing", "iot:DescribeEndpoint(Data-ATS)", "iot:GetThingShadow(sparkplug)"}) {
        if (detail.rfind(operation + ": ", 0) != 0) continue;
        const auto at = detail.rfind(" HTTP ");
        if (at == std::string::npos) break;
        const auto status = detail.substr(at + 6);
        if (!status.empty() && status.size() <= 3 && status.find_first_not_of("0123456789") == std::string::npos)
            return operation + " HTTP " + status;
    }
    const std::string prefix = "initKvsWebRtc: KVS status 0x";
    if (detail.rfind(prefix, 0) == 0) {
        const auto status = detail.substr(prefix.size());
        if (!status.empty() && status.size() <= 8 && status.find_first_not_of("0123456789abcdefABCDEF") == std::string::npos)
            return prefix + status;
    }
    if (detail.rfind("unsupported registered Thing type", 0) == 0) return "unsupported registered Thing type";
    return "runtime initialization or execution failed; inspect connection operation/status diagnostics";
}
volatile std::sig_atomic_t interrupted = 0;
void interrupt(int) { interrupted = 1; }

void device_run(const MicrovmRun& run, MicrovmApplication& application, const std::string& ca) {
    // This function is never called by /ready or /validate. In particular, the
    // provider chain reads the restored environment rather than build-role state.
    const auto started_wall = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    const auto started_steady = std::chrono::steady_clock::now();
    std::optional<ExecutionDeadline> deadline;
    if (run.deadline) {
        try { deadline.emplace(run.deadline, started_wall, started_steady); }
        catch (const std::invalid_argument&) { application.stopped("activation deadline invalid or expired"); return; }
    }
    auto chain = Aws::MakeShared<Aws::Auth::DefaultAWSCredentialsProviderChain>("microvm-run");
    auto credentials = Aws::MakeShared<AuditedCredentials>("microvm-run", chain);
    Aws::Client::ClientConfiguration config;
    config.region = run.region.c_str(); config.caFile = ca.c_str();
    config.connectTimeoutMs = 2000; config.requestTimeoutMs = 2000;
    config.retryStrategy = Aws::MakeShared<Aws::Client::DefaultRetryStrategy>("microvm-run", 0);
    AwsDevice device(credentials, config);
    auto selected = profile(device.registered_type(run.thing), run.thing, run.region, ca);
    KvsRuntime sdk;
    LifecyclePoller lifecycle([&] {
        if (run.run_id.empty()) return device.lifecycle(run.thing);
        const auto projection = device.projection(run.thing);
        if (!run.run_id.empty()) {
            if (!device.has_capability(run.thing, "agent")) return Lifecycle{false, 4};
            const auto assignment = parse_controller_shadow(device.agent_shadow(run.thing)).state;
            if (!assignment.run || assignment.run->run_id != run.run_id || !assignment.activation.activation ||
                assignment.activation.activation->id != run.activation_id ||
                assignment.activation.activation->deadline != run.deadline ||
                assignment.run->activation_id != run.activation_id || assignment.run->phase == RunPhase::stopping)
                return Lifecycle{false, 4};
            if (assignment.run->phase == RunPhase::reserved && (assignment.run->microvm_id.empty() ||
                assignment.run->microvm_id == run.id)) throw std::runtime_error("agent assignment pending");
            if (assignment.run->phase != RunPhase::running || assignment.run->microvm_id != run.id)
                return Lifecycle{false, 4};
            if (!projection.active || !*projection.active) return Lifecycle{false, 4};
            if (!projection_matches_active(assignment.activation, projection))
                throw std::runtime_error("stale or inconsistent lifecycle projection");
        }
        return Lifecycle{true, 2};
    });
    Session session(std::move(selected), [credentials] { return make_kvs_transport(credentials); },
                    application, std::chrono::steady_clock::now());
    application.actions(&session);
    try {
        auto report_at = std::chrono::steady_clock::now();
        bool expired = false;
        while (!application.stopping()) {
            const auto now = std::chrono::steady_clock::now();
            const auto wall_seconds = std::chrono::duration_cast<std::chrono::seconds>(
                std::chrono::system_clock::now().time_since_epoch()).count();
            if (deadline && deadline->expired(wall_seconds, now)) { expired = true; break; }
            const auto state = lifecycle.latest();
            if (state) session.verified(state->first, state->second);
            if (!run.run_id.empty()) application.authorized(state && state->first.born && state->first.redcon <= 2 &&
                now >= state->second && now - state->second < 15s, state ? state->second : Time{});
            if (!session.tick(now)) break;
            if (now >= report_at) {
                // Lifecycle API signing and KVS consult the provider on their
                // own threads. Never refresh credentials on the control tick.
                // This snapshot takes only the audit mutex, without network IO.
                application.credential_status(credentials->status());
                std::cerr << "microvm status " << application.status() << '\n';
                const auto failure = lifecycle.error();
                if (!failure.empty()) std::cerr << failure << '\n';
                report_at = now + 5s;
            }
            std::this_thread::sleep_for(20ms);
        }
        application.authorized(false);
        session.shutdown(application.stopping() ? "hosting shutdown" : expired ? "activation deadline expired" : "lifecycle or assignment shutdown");
        application.actions(nullptr);
        application.stopped(session.stop_reason());
    } catch (...) { application.actions(nullptr); throw; }
}
}

AuditedCredentials::AuditedCredentials(std::shared_ptr<Aws::Auth::AWSCredentialsProvider> source)
    : source_(std::move(source)) {
    if (!source_) throw std::invalid_argument("credential source required");
}
Aws::Auth::AWSCredentials AuditedCredentials::GetAWSCredentials() {
    auto next = source_->GetAWSCredentials();
    std::lock_guard<std::mutex> lock(mutex_);
    ++calls_;
    if (!next.IsEmpty() && (generations_ == 0 ||
        next.GetAWSAccessKeyId() != previous_.GetAWSAccessKeyId() ||
        next.GetAWSSecretKey() != previous_.GetAWSSecretKey() ||
        next.GetSessionToken() != previous_.GetSessionToken())) ++generations_;
    if (!next.IsEmpty()) previous_ = next;
    return next;
}
std::string AuditedCredentials::status() const {
    std::lock_guard<std::mutex> lock(mutex_);
    Json result;
    result.WithInt64("providerCalls", calls_).WithInt64("generations", generations_)
        .WithBool("temporary", !previous_.GetSessionToken().empty());
    const auto expiry = previous_.GetExpiration();
    const bool finite = !previous_.IsEmpty() && expiry < Aws::Auth::AWSCredentials{}.GetExpiration();
    result.WithBool("finiteExpiration", finite);
    if (finite) result.WithInt64("expiresUnixMs", expiry.Millis());
    return json(result);
}

MicrovmApplication::MicrovmApplication(Runner runner, std::function<void()> prepare, bool require_assignment)
    : runner_(std::move(runner)), prepare_(std::move(prepare)), require_assignment_(require_assignment),
      authorized_(!require_assignment) {
    if (!runner_) throw std::invalid_argument("MicroVM runner required");
}
MicrovmApplication::~MicrovmApplication() { stop(); }
HookReply MicrovmApplication::hook(const std::string& path, const std::string& body) {
    if (path == "/ready" || path == "/validate") {
        std::lock_guard<std::mutex> lock(mutex_);
        return reply(phase_ == "waiting-for-run" ? 200 : 409,
                     phase_ == "waiting-for-run" ? "no runtime identity, credentials or device sessions initialized" : "runtime already initialized");
    }
    if (path == "/terminate" || path == "/suspend") {
        stop(); return reply(200, "stopped");
    }
    if (path == "/resume") return reply(409, "this probe requires suspension and automatic resumption to be disabled");
    if (path != "/run") return reply(404, "unknown hook");
    if (body.size() > 16384) return reply(413, "hook body too large");
    MicrovmRun next;
    try {
        auto envelope = string_fields(body);
        if (envelope.size() != 2) throw std::invalid_argument("unexpected envelope fields");
        next.id = envelope.at("microvmId");
        auto payload = string_fields(envelope.at("runHookPayload"));
        if (payload.size() != (require_assignment_ ? 5u : 2u)) throw std::invalid_argument("unexpected run fields");
        next.thing = payload.at("thingId");
        next.region = payload.at("region");
        if (require_assignment_) {
            next.run_id = payload.at("runId"); next.activation_id = payload.at("activationId");
            const auto deadline = payload.at("deadline");
            if (deadline.empty() || deadline.find_first_not_of("0123456789") != std::string::npos)
                throw std::invalid_argument("invalid deadline");
            std::size_t end = 0; next.deadline = std::stoll(deadline, &end);
            if (end != deadline.size() || next.deadline <= 0 || !identifier(next.run_id, 128) ||
                !identifier(next.activation_id, 128)) throw std::invalid_argument("invalid cloud assignment");
        }
        if (!identifier(next.id, 256) || !identifier(next.thing, 128) || next.region != "eu-central-1")
            throw std::invalid_argument("invalid probe identity or region");
    } catch (...) { return reply(400, "invalid MicroVM identity or run payload"); }
    const auto deadline_error = [&]() -> unsigned {
        if (!require_assignment_) return 0;
        const auto now = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        if (now < 0) return 400;
        if (now >= next.deadline) return 409;
        return next.deadline - now > 3000 ? 400 : 0;
    };
    if (const auto error = deadline_error()) {
        // A late or retried launch must not report a successful run hook when
        // its persisted activation has already expired. Lambda can treat the
        // failed hook as a failed start instead of accepting an idle host.
        return reply(error, error == 409 ? "activation deadline expired" : "activation deadline invalid");
    }
    std::lock_guard<std::mutex> lock(mutex_);
    if (phase_ != "waiting-for-run") {
        return reply(run_.id == next.id && run_.thing == next.thing && run_.region == next.region &&
                     run_.run_id == next.run_id && run_.activation_id == next.activation_id && run_.deadline == next.deadline &&
                     phase_ == "running" ? 200 : 409, "run already initialized");
    }
    try {
        if (prepare_) prepare_();
        prepared_ = true;
        if (const auto error = deadline_error()) {
            phase_ = "failed";
            return reply(error, error == 409 ? "activation deadline expired" : "activation deadline invalid");
        }
        run_ = std::move(next); started_ = std::chrono::steady_clock::now(); phase_ = "running";
        worker_ = std::thread([this] {
            try { runner_(run_, *this); }
            catch (const std::exception& error) { stopped(safe_error(error.what())); }
            catch (...) {
                // Do not serialize arbitrary exception payloads into ingress or
                // CloudWatch; an SDK exception can include remote secrets.
                stopped("unknown runtime failure");
            }
        });
    } catch (...) { phase_ = "failed"; return reply(503, "could not start runtime"); }
    return reply(200, "runtime initialized after restoration");
}
std::string MicrovmApplication::status() const {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!prepared_) return "{\"phase\":\"" + phase_ +
        "\",\"credentials\":{},\"telemetryMessages\":0,\"videoFrames\":0,\"microvmId\":\"\"}";
    Json result;
    result.WithString("buildId", TXING_AGENT_BUILD_ID).WithString("phase", phase_.c_str())
        .WithString("microvmId", run_.id.c_str()).WithString("thingId", run_.thing.c_str())
        .WithString("region", run_.region.c_str()).WithBool("attached", attached_)
        .WithBool("controlHeld", held_).WithString("stopReason", reason_.c_str())
        .WithInt64("telemetryMessages", telemetry_).WithInt64("videoFrames", video_)
        .WithInt64("attachmentDrops", outgoing_.dropped());
    const auto now = std::chrono::steady_clock::now();
    if (!run_.run_id.empty()) result.WithString("runId", run_.run_id.c_str())
        .WithString("activationId", run_.activation_id.c_str()).WithInt64("deadline", run_.deadline)
        .WithBool("assignmentVerified", assignment_fresh(now));
    if (!run_.run_id.empty() && assignment_verified_at_ != Time{} && now >= assignment_verified_at_)
        result.WithInt64("assignmentAgeMs", std::chrono::duration_cast<std::chrono::milliseconds>(now - assignment_verified_at_).count());
    if (started_ != Time{}) result.WithInt64("uptimeMs", std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - started_).count());
    Json frame; frame.WithString("codec", codec_.c_str()).WithInt64("bytes", frame_bytes_)
        .WithInt64("presentation100ns", presentation_).WithInt64("receiptUnixMs", receipt_);
    result.WithObject("lastVideo", std::move(frame)).WithObject("credentials", parse(credentials_));
    Json control; control.WithString("state", control_state_.c_str()).WithString("error", control_error_.c_str());
    result.WithObject("control", std::move(control));
    for (const auto index : {0, 1}) {
        const auto error = safe_connection_diagnostic(errors_[index]);
        Json link; link.WithInteger("state", static_cast<int>(connections_[index])).WithString("error", error.c_str());
        result.WithObject(index ? "video" : "telemetry", std::move(link));
    }
    return json(result);
}
bool MicrovmApplication::assignment_fresh(Time now) const {
    return authorized_ && (!require_assignment_ || (assignment_verified_at_ != Time{} &&
        now >= assignment_verified_at_ && now - assignment_verified_at_ < std::chrono::seconds(15)));
}
bool MicrovmApplication::attach() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (attached_ || phase_ != "running" || !assignment_fresh(std::chrono::steady_clock::now())) return false;
    while (outgoing_.pop()) {}
    attached_ = true; control_attempted_ = false; return true;
}
bool MicrovmApplication::attached() const { std::lock_guard<std::mutex> lock(mutex_); return attached_ && assignment_fresh(std::chrono::steady_clock::now()); }
void MicrovmApplication::detach() {
    std::lock_guard<std::mutex> lock(mutex_);
    attached_ = false;
    if (actions_) actions_->release();
    while (outgoing_.pop()) {}
}
void MicrovmApplication::message(Bytes bytes, bool binary) {
    if (bytes.size() > 4096) throw std::invalid_argument("attachment message exceeds 4096 bytes");
    Json response;
    bool status_requested = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!attached_) return;
        if (!assignment_fresh(std::chrono::steady_clock::now())) {
            if (actions_) actions_->release();
            attached_ = false;
            while (outgoing_.pop()) {}
            return;
        }
        if (binary) {
            const bool valid = valid_mavlink2(bytes);
            if (valid && actions_) actions_->client_activity();
            const bool accepted = actions_ && valid && actions_->send(std::move(bytes));
            response.WithString("type", "send.result").WithBool("accepted", accepted);
        } else {
            try {
                auto command = parse(std::string(bytes.begin(), bytes.end()));
                const auto type = field(command.View(), "type");
                if (type == "ping") response.WithString("type", "pong");
                else if (type == "status") status_requested = true;
                else if (type == "activity") {
                    if (actions_) actions_->client_activity();
                    response.WithString("type", "activity.queued");
                }
                else if (type == "acquire") {
                    const auto actor = field(command.View(), "actor");
                    const bool queued = actions_ && !control_attempted_ && actor.size() <= 128 && actions_->acquire(actor);
                    if (queued) { control_attempted_ = true; control_state_ = "acquiring"; control_error_.clear(); }
                    response.WithString("type", "acquire.queued").WithBool("queued", queued);
                } else if (type == "release") {
                    if (actions_) actions_->release();
                    response.WithString("type", "release.queued");
                } else throw std::invalid_argument("unknown attachment command");
            } catch (...) { response.WithString("type", "error").WithString("message", "invalid attachment command"); }
        }
    }
    publish(status_requested ? status() : json(response));
}
std::optional<WireMessage> MicrovmApplication::outgoing() { return outgoing_.pop(); }
void MicrovmApplication::wake_with(std::function<void()> wake) { std::lock_guard<std::mutex> lock(mutex_); wake_ = std::move(wake); }
void MicrovmApplication::stop() {
    stopping_ = true;
    if (worker_.joinable()) worker_.join();
    std::lock_guard<std::mutex> lock(mutex_);
    phase_ = "stopped"; attached_ = false;
}
void MicrovmApplication::actions(Actions* actions) { std::lock_guard<std::mutex> lock(mutex_); actions_ = actions; }
void MicrovmApplication::authorized(bool value, Time verified_at) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (authorized_ && !value) {
        if (actions_) actions_->release();
        attached_ = false;
        while (outgoing_.pop()) {}
    }
    authorized_ = value;
    assignment_verified_at_ = value ? verified_at : Time{};
}
void MicrovmApplication::credential_status(std::string status) { std::lock_guard<std::mutex> lock(mutex_); credentials_ = std::move(status); }
void MicrovmApplication::stopped(std::string reason) {
    std::lock_guard<std::mutex> lock(mutex_); reason_ = std::move(reason); phase_ = "stopped";
    authorized_ = false; attached_ = false; actions_ = nullptr;
    while (outgoing_.pop()) {}
}
void MicrovmApplication::publish(std::string text) { publish({Bytes(text.begin(), text.end()), false}); }
void MicrovmApplication::publish(WireMessage message) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!attached_ || !assignment_fresh(std::chrono::steady_clock::now())) return;
    const auto bytes = message.bytes.size(); outgoing_.push(std::move(message), bytes);
    if (wake_) wake_();
}
void MicrovmApplication::telemetry(const Bytes& bytes) {
    { std::lock_guard<std::mutex> lock(mutex_); ++telemetry_; }
    publish({bytes, true});
}
void MicrovmApplication::video(const EncodedVideo& frame) {
    std::lock_guard<std::mutex> lock(mutex_); ++video_;
    codec_ = frame.codec; frame_bytes_ = frame.bytes.size(); presentation_ = frame.presentation_100ns;
    receipt_ = std::chrono::duration_cast<std::chrono::milliseconds>(frame.received.time_since_epoch()).count();
}
void MicrovmApplication::connection(Stream stream, Connection state, const std::string& error) {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto index = stream == Stream::video ? 1 : 0;
    connections_[index] = state; errors_[index] = error;
}
void MicrovmApplication::control(bool held, const std::string& reason) {
    {
        std::lock_guard<std::mutex> lock(mutex_); held_ = held;
        control_state_ = held ? "held" : "lost";
        // Some reason text originates at the board; expose only known codes or
        // fixed local diagnostics, never arbitrary peer-supplied content.
        control_error_.clear();
        if (!held) {
            const std::vector<std::string> safe = {"control_busy", "stale_epoch", "invalid_request",
                "control error", "control unavailable", "control request send failed", "invalid lease state",
                "board control ownership changed", "unexpected control response", "telemetry stopped",
                "telemetry connection lost", "operator exception or control response overload",
                "client inactivity or lease expiry", "control request timed out", "operator released", "MAVLink send failed"};
            control_error_ = std::find(safe.begin(), safe.end(), reason) != safe.end() ? reason : "control operation failed";
        }
    }
    Json event; event.WithString("type", "control").WithBool("held", held); publish(json(event));
}

int microvm_main(int argc, char** argv) {
    std::string ca;
    bool require_assignment = false;
    unsigned hook_port = 8080, attachment_port = 8081;
    try {
        for (int index = 1; index < argc; ++index) {
            const std::string argument = argv[index];
            if (argument == "--require-assignment") { require_assignment = true; continue; }
            if (index + 1 >= argc) throw std::invalid_argument("missing MicroVM option value");
            const std::string value = argv[++index];
            if (argument == "--ca") ca = value;
            else {
                std::size_t end = 0; const auto number = std::stoul(value, &end);
                if (end != value.size() || number < 1024 || number > 65535) throw std::invalid_argument("invalid listener port");
                if (argument == "--hook-port") hook_port = number;
                else if (argument == "--attachment-port") attachment_port = number;
                else throw std::invalid_argument("unknown MicroVM option");
            }
        }
        if (ca.empty() || !std::ifstream(ca).good() || hook_port == attachment_port)
            throw std::invalid_argument("verified CA and distinct hook/attachment ports required");
    } catch (const std::exception& error) { std::cerr << "txing-agent --microvm: " << error.what() << '\n'; return 2; }
    interrupted = 0; std::signal(SIGINT, interrupt); std::signal(SIGTERM, interrupt);
    Aws::SDKOptions options;
    bool initialized = false;
    int result = 0;
    try {
        MicrovmApplication application([ca](const MicrovmRun& run, MicrovmApplication& app) { device_run(run, app, ca); },
            [&] { Aws::InitAPI(options); initialized = true; }, require_assignment);
        result = serve_microvm(application, hook_port, attachment_port, [] { return interrupted != 0; });
    } catch (const std::exception& error) { std::cerr << "MicroVM host: " << error.what() << '\n'; result = 1; }
    if (initialized) Aws::ShutdownAPI(options);
    return result;
}
}
