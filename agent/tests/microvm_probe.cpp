// Explicit operator-run ingress probe. No discovery, token creation or control
// acquisition: supply an existing endpoint and a token on stdin.
#include "agent/core.hpp"
#include <aws/core/Aws.h>
#include <aws/core/utils/json/JsonSerializer.h>
#include <libwebsockets.h>
#include <cstring>
#include <deque>
#include <iostream>
#include <stdexcept>

using namespace txing::agent;
namespace {
struct Client {
    lws_context* context = nullptr;
    lws* socket = nullptr;
    struct Timer { lws_sorted_usec_list_t sul{}; Client* owner = nullptr; } timer;
    std::string token, incoming;
    std::deque<std::pair<Bytes, bool>> pending;
    std::uint64_t telemetry = 0;
    bool pong = false, rejected = false, media = false, started = false, done = false, failed = false;
    Time deadline;
    void text(const char* data) { pending.emplace_back(Bytes(data, data + std::strlen(data)), false); }
    static Client& self(lws* socket) { return *static_cast<Client*>(lws_context_user(lws_get_context(socket))); }
    static void tick(lws_sorted_usec_list_t* timer) {
        auto* client = reinterpret_cast<Timer*>(timer)->owner;
        if (std::chrono::steady_clock::now() >= client->deadline) { client->done = true; return; }
        if (client->socket && client->pending.empty()) {
            client->text("{\"type\":\"status\"}");
            lws_callback_on_writable(client->socket);
        }
        lws_sul_schedule(client->context, 0, &client->timer.sul, tick, 1000000);
    }
    static int callback(lws* socket, lws_callback_reasons reason, void*, void* data, std::size_t size) noexcept {
        try {
            auto& client = self(socket);
            switch (reason) {
            case LWS_CALLBACK_CLIENT_APPEND_HANDSHAKE_HEADER: {
                auto** cursor = static_cast<unsigned char**>(data);
                auto* end = *cursor + size;
                const auto* value = reinterpret_cast<const unsigned char*>(client.token.data());
                if (lws_add_http_header_by_name(socket, reinterpret_cast<const unsigned char*>("X-aws-proxy-auth:"),
                    value, client.token.size(), cursor, end) ||
                    lws_add_http_header_by_name(socket, reinterpret_cast<const unsigned char*>("X-aws-proxy-port:"),
                    reinterpret_cast<const unsigned char*>("8081"), 4, cursor, end)) return -1;
                return 0;
            }
            case LWS_CALLBACK_CLIENT_ESTABLISHED:
                client.socket = socket; client.text("{\"type\":\"status\"}");
                lws_callback_on_writable(socket); return 0;
            case LWS_CALLBACK_CLIENT_WRITEABLE:
                if (!client.pending.empty()) {
                    auto message = std::move(client.pending.front()); client.pending.pop_front();
                    std::vector<unsigned char> buffer(LWS_PRE + message.first.size());
                    std::copy(message.first.begin(), message.first.end(), buffer.begin() + LWS_PRE);
                    const auto written = lws_write(socket, buffer.data() + LWS_PRE, message.first.size(),
                        message.second ? LWS_WRITE_BINARY : LWS_WRITE_TEXT);
                    if (written < 0 || static_cast<std::size_t>(written) != message.first.size()) return -1;
                    if (!client.pending.empty()) lws_callback_on_writable(socket);
                }
                return 0;
            case LWS_CALLBACK_CLIENT_RECEIVE:
                if (client.incoming.size() + size > 16384) return -1;
                client.incoming.append(static_cast<char*>(data), size);
                if (!lws_is_final_fragment(socket) || lws_remaining_packet_payload(socket)) return 0;
                if (lws_frame_is_binary(socket)) {
                    if (!valid_mavlink2(Bytes(client.incoming.begin(), client.incoming.end()))) return -1;
                    ++client.telemetry;
                } else {
                    Aws::Utils::Json::JsonValue document(Aws::String(client.incoming.c_str()));
                    if (!document.WasParseSuccessful()) return -1;
                    auto view = document.View();
                    if (view.ValueExists("phase")) {
                        if (view.GetBool("controlHeld")) { client.failed = client.done = true; return -1; }
                        auto video = view.GetObject("lastVideo");
                        client.media = view.GetInt64("videoFrames") > 0 && video.GetString("codec") == "h264" &&
                                       video.GetInt64("bytes") > 0 && video.GetInt64("receiptUnixMs") > 0;
                        std::cout << "PROBE status " << client.incoming << std::endl;
                        if (!client.started) {
                            client.started = true;
                            client.text("{\"type\":\"ping\"}");
                            client.pending.emplace_back(Bytes{0xfd, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0}, true);
                            lws_callback_on_writable(socket);
                        }
                    } else if (view.ValueExists("type")) {
                        const auto type = view.GetString("type");
                        if (type == "pong") client.pong = true;
                        else if (type == "send.result") client.rejected = !view.GetBool("accepted");
                    }
                }
                client.incoming.clear(); return 0;
            case LWS_CALLBACK_CLIENT_CONNECTION_ERROR:
                std::cerr << "PROBE connection/TLS/authentication failed\n";
                client.failed = client.done = true; return 0;
            case LWS_CALLBACK_CLIENT_CLOSED:
                client.socket = nullptr;
                if (!client.done) client.failed = client.done = true;
                return 0;
            default: return 0;
            }
        } catch (...) { return -1; }
    }
};
int probe(const std::string& endpoint, const std::string& ca, unsigned seconds) {
    Client client;
    client.timer.owner = &client;
    std::getline(std::cin, client.token);
    if (client.token.empty() || client.token.find_first_of("\r\n") != std::string::npos)
        throw std::invalid_argument("supply one authentication token on stdin");
    std::string host = endpoint;
    if (host.rfind("https://", 0) == 0) host.erase(0, 8);
    if (!host.empty() && host.back() == '/') host.pop_back();
    const std::string suffix = ".lambda-microvm.eu-central-1.on.aws";
    if (host.size() <= suffix.size() || host.compare(host.size() - suffix.size(), suffix.size(), suffix) ||
        host.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789.-") != std::string::npos)
        throw std::invalid_argument("expected an eu-central-1 Lambda MicroVM endpoint hostname");
    lws_protocols protocols[] = {
        {"txing.agent.probe.v1", Client::callback, 0, 16384, 0, nullptr, 0},
        {nullptr, nullptr, 0, 0, 0, nullptr, 0}
    };
    lws_context_creation_info info{};
    info.port = CONTEXT_PORT_NO_LISTEN; info.protocols = protocols; info.user = &client;
    info.options = LWS_SERVER_OPTION_DO_SSL_GLOBAL_INIT; info.client_ssl_ca_filepath = ca.c_str();
    client.context = lws_create_context(&info);
    if (!client.context) throw std::runtime_error("could not initialize verified TLS client");
    lws_client_connect_info connect{};
    connect.context = client.context; connect.address = host.c_str(); connect.host = host.c_str();
    connect.port = 443; connect.path = "/stream";
    connect.protocol = "lambda-microvms,txing.agent.probe.v1";
    connect.local_protocol_name = protocols[0].name;
    connect.ssl_connection = LCCSCF_USE_SSL;
    client.deadline = std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
    if (!lws_client_connect_via_info(&connect)) client.failed = client.done = true;
    lws_sul_schedule(client.context, 0, &client.timer.sul, Client::tick, 1000000);
    while (!client.done) if (lws_service(client.context, 0) < 0) { client.failed = true; break; }
    lws_sul_cancel(&client.timer.sul);
    lws_context_destroy(client.context);
    const bool passed = !client.failed && client.telemetry > 0 && client.media && client.pong && client.rejected;
    std::cout << "PROBE " << (passed ? "PASS" : "FAIL") << " telemetry=" << client.telemetry
              << " videoMetadata=" << client.media << " pong=" << client.pong
              << " unauthorizedFrameRejected=" << client.rejected << '\n';
    return passed ? 0 : 1;
}
}
int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "agent-microvm-probe <eu-central-1-endpoint> <verified-ca-pem> <seconds> < token-file\n"; return 2;
    }
    Aws::SDKOptions options; Aws::InitAPI(options);
    int result = 1;
    try {
        std::size_t end = 0; auto seconds = std::stoul(argv[3], &end);
        if (end != std::strlen(argv[3]) || seconds < 5 || seconds > 120) throw std::invalid_argument("duration must be 5..120 seconds");
        lws_set_log_level(LLL_ERR | LLL_WARN, nullptr);
        result = probe(argv[1], argv[2], seconds);
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; }
    Aws::ShutdownAPI(options); return result;
}
