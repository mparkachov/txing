#include "agent/attach.hpp"
#include "agent/aws.hpp"
#include "agent/cloud.hpp"
#include "agent/controller_shadow.hpp"
#include "agent/manual.hpp"
#include "agent/runtime_sample.hpp"
#include <aws/core/Aws.h>
#include <aws/core/auth/AWSCredentialsProviderChain.h>
#include <aws/core/client/DefaultRetryStrategy.h>
#include <aws/core/utils/json/JsonSerializer.h>
#include <libwebsockets.h>
#include <curl/curl.h>
#include <algorithm>
#include <csignal>
#include <cstdlib>
#include <deque>
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace txing::agent {
namespace {
using namespace std::chrono_literals;
volatile std::sig_atomic_t interrupted = 0;
void interrupt(int) { interrupted = 1; }
struct Message { Bytes data; bool binary = false; };
struct Attachment final : Actions {
    explicit Attachment(ManualOperator& manual) : manual(manual) { timer.owner = this; }
    ManualOperator& manual;
    lws_context* context = nullptr;
    lws* socket = nullptr;
    struct Timer { lws_sorted_usec_list_t sul{}; Attachment* owner = nullptr; } timer;
    std::string token, incoming;
    std::deque<Message> pending;
    Time deadline{}, next_status{}, last_activity{};
    bool incoming_binary = false, established = false, done = false, failed = false, released = false;
    std::atomic<bool> token_failed{false};
    int telemetry_state = -1;

    bool enqueue(Bytes bytes, bool binary) {
        if (done || pending.size() >= 128 || bytes.size() > 4096) return false;
        pending.push_back({std::move(bytes), binary});
        if (socket) lws_callback_on_writable(socket);
        return true;
    }
    bool text(const std::string& text) { return enqueue(Bytes(text.begin(), text.end()), false); }
    bool acquire(std::string actor) override {
        if (released) return false;
        Aws::Utils::Json::JsonValue command;
        command.WithString("type", "acquire").WithString("actor", actor.c_str());
        return text(command.View().WriteCompact().c_str());
    }
    bool send(Bytes frame) override { return !released && enqueue(std::move(frame), true); }
    void release() override {
        released = true; pending.clear();
        text(R"({"type":"release"})");
    }
    void client_activity() override {
        const auto now = std::chrono::steady_clock::now();
        if (last_activity == Time{} || now - last_activity >= 1s) {
            if (text(R"({"type":"activity"})")) last_activity = now;
        }
    }
    static Attachment& self(lws* socket) { return *static_cast<Attachment*>(lws_context_user(lws_get_context(socket))); }
    static void tick(lws_sorted_usec_list_t* timer) {
        auto* client = reinterpret_cast<Timer*>(timer)->owner;
        const auto now = std::chrono::steady_clock::now();
        if (interrupted || now >= client->deadline || client->token_failed.load()) {
            if (client->token_failed.load()) client->failed = true;
            client->release(); client->done = true; return;
        }
        if (client->established) {
            client->manual.poll(*client, now);
            if (now >= client->next_status) {
                client->text(R"({"type":"status"})"); client->next_status = now + 2s;
            }
        }
        lws_sul_schedule(client->context, 0, &client->timer.sul, tick, 20000);
    }
    static int callback(lws* socket, lws_callback_reasons reason, void*, void* data, std::size_t size) noexcept {
        try {
            auto& client = self(socket);
            switch (reason) {
            case LWS_CALLBACK_CLIENT_APPEND_HANDSHAKE_HEADER: {
                auto** cursor = static_cast<unsigned char**>(data); auto* end = *cursor + size;
                if (lws_add_http_header_by_name(socket, reinterpret_cast<const unsigned char*>("X-aws-proxy-auth:"),
                    reinterpret_cast<const unsigned char*>(client.token.data()), client.token.size(), cursor, end) ||
                    lws_add_http_header_by_name(socket, reinterpret_cast<const unsigned char*>("X-aws-proxy-port:"),
                    reinterpret_cast<const unsigned char*>("8081"), 4, cursor, end)) return -1;
                return 0;
            }
            case LWS_CALLBACK_CLIENT_ESTABLISHED:
                client.socket = socket; client.established = true; client.next_status = Time{}; return 0;
            case LWS_CALLBACK_CLIENT_WRITEABLE:
                if (!client.pending.empty()) {
                    auto message = std::move(client.pending.front()); client.pending.pop_front();
                    std::vector<unsigned char> buffer(LWS_PRE + message.data.size());
                    std::copy(message.data.begin(), message.data.end(), buffer.begin() + LWS_PRE);
                    const auto sent = lws_write(socket, buffer.data() + LWS_PRE, message.data.size(),
                        message.binary ? LWS_WRITE_BINARY : LWS_WRITE_TEXT);
                    if (sent < 0 || static_cast<std::size_t>(sent) != message.data.size()) return -1;
                    if (!client.pending.empty()) lws_callback_on_writable(socket);
                }
                return 0;
            case LWS_CALLBACK_CLIENT_RECEIVE:
                if (lws_is_first_fragment(socket) && client.incoming.empty()) client.incoming_binary = lws_frame_is_binary(socket);
                if (client.incoming.size() + size > 16384) return -1;
                client.incoming.append(static_cast<char*>(data), size);
                if (!lws_is_final_fragment(socket) || lws_remaining_packet_payload(socket)) return 0;
                if (client.incoming_binary) {
                    Bytes frame(client.incoming.begin(), client.incoming.end());
                    if (!valid_mavlink2(frame)) return -1;
                    client.manual.telemetry(frame);
                } else {
                    Aws::Utils::Json::JsonValue document(Aws::String(client.incoming.c_str()));
                    if (!document.WasParseSuccessful() || !document.View().IsObject()) return -1;
                    auto view = document.View();
                    if (view.ValueExists("type") && view.GetObject("type").IsString() && view.GetString("type") == "control" &&
                        view.ValueExists("held") && view.GetObject("held").IsBool())
                        client.manual.control(view.GetBool("held"), "cloud agent control state");
                    if (view.ValueExists("telemetry") && view.GetObject("telemetry").IsObject()) {
                        const auto telemetry = view.GetObject("telemetry");
                        if (!telemetry.ValueExists("state") || !telemetry.GetObject("state").IsIntegerType()) return -1;
                        const auto state = telemetry.GetInt64("state");
                        if (state < 0 || state > 3) return -1;
                        if (client.telemetry_state != state) {
                            client.telemetry_state = static_cast<int>(state);
                            client.manual.connection(Stream::telemetry, static_cast<Connection>(state), "cloud agent telemetry");
                        }
                    }
                }
                client.incoming.clear(); return 0;
            case LWS_CALLBACK_CLIENT_CONNECTION_ERROR:
                client.failed = client.done = true; return 0;
            case LWS_CALLBACK_CLIENT_CLOSED:
                client.socket = nullptr; client.manual.control(false, "attachment closed");
                if (!client.done) client.failed = client.done = true;
                return 0;
            default: return 0;
            }
        } catch (...) { return -1; }
    }
};

std::size_t discard_body(char*, std::size_t size, std::size_t count, void*) { return size * count; }
bool token_valid(const std::string& url, const std::string& token, const std::string& ca) {
    CURL* curl = curl_easy_init();
    if (!curl) return false;
    curl_slist* headers = curl_slist_append(nullptr, ("X-aws-proxy-auth: " + token).c_str());
    if (!headers) { curl_easy_cleanup(curl); return false; }
    auto* extended = curl_slist_append(headers, "X-aws-proxy-port: 8081");
    if (!extended) { curl_slist_free_all(headers); curl_easy_cleanup(curl); return false; }
    headers = extended;
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str()); curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, discard_body); curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, 1500L);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT_MS, 2000L); curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 0L);
    if (!ca.empty()) curl_easy_setopt(curl, CURLOPT_CAINFO, ca.c_str());
    const auto result = curl_easy_perform(curl);
    long code = 0; curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &code);
    curl_slist_free_all(headers); curl_easy_cleanup(curl);
    return result == CURLE_OK && code == 200;
}

int connect_attachment(ManualOperator& manual, const std::string& endpoint, const std::string& ca,
                       std::string token, Time deadline, unsigned loopback_test_port = 0,
                       unsigned validation_test_port = 0) {
    if (token.empty() || token.size() > 8000 || token.find_first_not_of(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-") != std::string::npos)
        throw std::runtime_error("invalid MicroVM authentication response");
    const auto host = loopback_test_port ? std::string("127.0.0.1") : microvm_https_endpoint(endpoint).substr(8);
    Attachment client(manual); client.token = std::move(token); client.deadline = deadline;
    lws_protocols protocols[] = {{"txing.agent.probe.v1", Attachment::callback, 0, 16384, 0, nullptr, 0},
                                 {nullptr, nullptr, 0, 0, 0, nullptr, 0}};
    lws_context_creation_info info{}; info.port = CONTEXT_PORT_NO_LISTEN; info.protocols = protocols;
    info.user = &client; info.options = LWS_SERVER_OPTION_DO_SSL_GLOBAL_INIT;
    info.client_ssl_ca_filepath = loopback_test_port ? nullptr : ca.c_str();
    lws_set_log_level(LLL_ERR | LLL_WARN, nullptr);
    client.context = lws_create_context(&info);
    if (!client.context) throw std::runtime_error("could not initialize attachment TLS client");
    const auto status_url = loopback_test_port ? "http://127.0.0.1:" + std::to_string(validation_test_port ? validation_test_port : loopback_test_port) + "/status"
                                               : "https://" + host + "/status";
    std::mutex validator_mutex;
    std::condition_variable validator_wake;
    bool validator_stop = false;
    std::thread validator([&] {
        std::unique_lock<std::mutex> lock(validator_mutex);
        while (!validator_wake.wait_for(lock, 2s, [&] { return validator_stop; })) {
            lock.unlock();
            const bool valid = token_valid(status_url, client.token, ca);
            lock.lock();
            if (!valid && !validator_stop) {
                client.token_failed = true;
                lws_cancel_service(client.context);
                break;
            }
        }
    });
    lws_client_connect_info connect{}; connect.context = client.context; connect.address = host.c_str();
    connect.host = host.c_str(); connect.port = loopback_test_port ? loopback_test_port : 443; connect.path = "/stream";
    connect.protocol = "lambda-microvms,txing.agent.probe.v1"; connect.local_protocol_name = protocols[0].name;
    if (!loopback_test_port) connect.ssl_connection = LCCSCF_USE_SSL;
    if (!lws_client_connect_via_info(&connect)) client.failed = client.done = true;
    lws_sul_schedule(client.context, 0, &client.timer.sul, Attachment::tick, 20000);
    while (!client.done) if (lws_service(client.context, 0) < 0) { client.failed = true; break; }
    { std::lock_guard<std::mutex> lock(validator_mutex); validator_stop = true; }
    validator_wake.notify_all(); validator.join();
    lws_sul_cancel(&client.timer.sul); lws_context_destroy(client.context);
    if (client.failed) std::cerr << "attachment lost or authentication failed; control requires a new explicit attachment\n";
    else if (!interrupted) std::cerr << "attachment token lifetime ended; start a new explicit attachment\n";
    return client.failed ? 1 : 0;
}
}

#ifdef TXING_AGENT_TESTING
int test_attach_loopback(ManualOperator& manual, unsigned port, unsigned seconds, unsigned validation_port) {
    if (!port || port > 65535 || validation_port > 65535 || !seconds || seconds > 30)
        throw std::invalid_argument("invalid loopback fixture");
    return connect_attachment(manual, {}, {}, "loopback-test-token", std::chrono::steady_clock::now() + std::chrono::seconds(seconds), port, validation_port);
}
#endif

int attach_main(int argc, char** argv) {
    std::string thing, ca, region = "eu-central-1";
    ManualOptions manual;
    bool has_port = false;
    if (const auto* value = std::getenv("TXING_AGENT_CA_PATH")) ca = value;
    try {
        for (int index = 1; index < argc; ++index) {
            const std::string argument = argv[index];
            if (argument == "--control") manual.control = true;
            else if ((argument == "--region" || argument == "--ca" || argument == "--qgc-port") && index + 1 < argc) {
                const std::string value = argv[++index];
                if (argument == "--ca") ca = value;
                else if (argument == "--region") region = value;
                else manual.qgc = udp_port(value);
            } else if (thing.empty() && !argument.empty() && argument[0] != '-') thing = argument;
            else if (!thing.empty() && !has_port && !argument.empty() && argument[0] != '-') {
                manual.listener = udp_port(argument); has_port = true;
            } else throw std::invalid_argument("invalid attach argument");
        }
        if (thing.empty() || region != "eu-central-1" || ca.empty() || !std::ifstream(ca).good())
            throw std::invalid_argument("Thing ID, eu-central-1 and readable verified CA are required");
        ManualOperator observer(manual, std::cerr);
        std::signal(SIGINT, interrupt); std::signal(SIGTERM, interrupt); interrupted = 0;
        Aws::SDKOptions options; Aws::InitAPI(options);
        int result = 1;
        try {
            auto credentials = Aws::MakeShared<Aws::Auth::DefaultAWSCredentialsProviderChain>("agent-attach");
            Aws::Client::ClientConfiguration config; config.region = region.c_str(); config.caFile = ca.c_str();
            config.connectTimeoutMs = 2000; config.requestTimeoutMs = 5000;
            config.retryStrategy = Aws::MakeShared<Aws::Client::DefaultRetryStrategy>("agent-attach", 1);
            AwsDevice device(credentials, config);
            if (!device.has_capability(thing, "agent")) throw std::runtime_error("Thing does not declare the agent capability");
            const auto payload = device.agent_shadow(thing);
            const auto snapshot = parse_controller_shadow(payload);
            const auto now = std::chrono::duration_cast<std::chrono::seconds>(std::chrono::system_clock::now().time_since_epoch()).count();
            const auto projection = device.projection(thing);
            if (!snapshot.state.run || snapshot.state.run->phase != RunPhase::running ||
                !activation_authorized(snapshot.state.activation, now) || !projection.active || !*projection.active ||
                projection.version != snapshot.state.activation.projection_version ||
                projection.source_timestamp_ms != snapshot.state.activation.source_timestamp_ms)
                throw std::runtime_error("no verified current cloud assignment");
            Aws::Utils::Json::JsonValue document(Aws::String(payload.c_str()));
            const auto reported = document.View().GetObject("state").GetObject("reported");
            if (!reported.ValueExists("endpoint") || !reported.GetObject("endpoint").IsString())
                throw std::runtime_error("current cloud endpoint is unavailable");
            const std::string endpoint = microvm_https_endpoint(reported.GetString("endpoint").c_str());
            CloudMicrovms cloud(credentials, config);
            const auto host = cloud.get(snapshot.state.run->microvm_id);
            if (host.id != snapshot.state.run->microvm_id || host.state != "RUNNING" ||
                microvm_https_endpoint(host.endpoint) != endpoint) throw std::runtime_error("cloud endpoint no longer matches assignment");
            const auto token_started = std::chrono::steady_clock::now();
            auto token = cloud.token(host.id, 8081, 5);
            result = connect_attachment(observer, endpoint, ca, std::move(token), token_started + 4min);
        } catch (const std::exception& error) { std::cerr << "agent attach: " << error.what() << '\n'; }
        Aws::ShutdownAPI(options); return result;
    } catch (const std::exception& error) { std::cerr << "agent attach: " << error.what() << '\n'; return 2; }
}
}
