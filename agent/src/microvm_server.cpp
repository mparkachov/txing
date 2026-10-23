#include "agent/microvm.hpp"
#include <libwebsockets.h>
#include <algorithm>
#include <cstring>
#include <iostream>
#include <stdexcept>

namespace txing::agent {
namespace {
constexpr const char* hook_prefix = "/aws/lambda-microvms/runtime/v1";
struct Request {
    char path[128];
    unsigned char body[16385];
    std::size_t size;
    unsigned char response[LWS_PRE + 8192];
    std::size_t response_size;
    bool binary, post, rejected;
};
struct Server {
    Server(MicrovmApplication& application, unsigned hooks, unsigned ingress)
        : app(application), hook_port(hooks), attachment_port(ingress) {}
    MicrovmApplication& app;
    unsigned hook_port, attachment_port;
    lws_context* context = nullptr;
    lws* attachment = nullptr;
    struct Timer { lws_sorted_usec_list_t sul{}; Server* owner = nullptr; } timer;

    static Server& self(lws* socket) {
        return *static_cast<Server*>(lws_context_user(lws_get_context(socket)));
    }
    static void timer_callback(lws_sorted_usec_list_t* timer) {
        auto* server = reinterpret_cast<Timer*>(timer)->owner;
        if (server->attachment) lws_callback_on_writable(server->attachment);
        lws_sul_schedule(server->context, 0, &server->timer.sul, timer_callback, 100000);
    }
    int respond(lws* socket, Request& request, HookReply reply) {
        if (reply.body.size() > sizeof(request.response) - LWS_PRE) return -1;
        unsigned char headers[LWS_PRE + 512];
        auto* begin = headers + LWS_PRE;
        auto* next = begin;
        if (lws_add_http_common_headers(socket, reply.status, "application/json", reply.body.size(), &next, headers + sizeof(headers)) ||
            lws_finalize_write_http_header(socket, begin, &next, headers + sizeof(headers))) return -1;
        std::memcpy(request.response + LWS_PRE, reply.body.data(), reply.body.size());
        request.response_size = reply.body.size();
        lws_callback_on_writable(socket); return 0;
    }
    int complete(lws* socket, Request& request) {
        const bool hooks = static_cast<unsigned>(lws_get_vhost_listen_port(lws_get_vhost(socket))) == hook_port;
        if (hooks) {
            if (!request.post || std::strncmp(request.path, hook_prefix, std::strlen(hook_prefix)))
                return respond(socket, request, {404, "{\"error\":\"unknown hook\"}"});
            return respond(socket, request, app.hook(request.path + std::strlen(hook_prefix),
                std::string(reinterpret_cast<char*>(request.body), request.size)));
        }
        if (request.post || std::strcmp(request.path, "/status"))
            return respond(socket, request, {404, "{\"error\":\"unknown attachment endpoint\"}"});
        return respond(socket, request, {200, app.status()});
    }
    static int callback(lws* socket, lws_callback_reasons reason, void* user, void* data, std::size_t size) noexcept {
        if (reason == LWS_CALLBACK_PROTOCOL_INIT || reason == LWS_CALLBACK_PROTOCOL_DESTROY ||
            reason == LWS_CALLBACK_WSI_CREATE || reason == LWS_CALLBACK_WSI_DESTROY) return 0;
        try {
            auto& server = self(socket);
            auto* request = static_cast<Request*>(user);
            switch (reason) {
            case LWS_CALLBACK_EVENT_WAIT_CANCELLED:
                if (server.attachment) lws_callback_on_writable(server.attachment);
                return 0;
            case LWS_CALLBACK_FILTER_PROTOCOL_CONNECTION: {
                char path[128];
                if (lws_hdr_copy(socket, path, sizeof(path), WSI_TOKEN_GET_URI) <= 0) return 1;
                return static_cast<unsigned>(lws_get_vhost_listen_port(lws_get_vhost(socket))) != server.attachment_port ||
                       server.attachment != nullptr || std::strcmp(path, "/stream");
            }
            case LWS_CALLBACK_ESTABLISHED:
                if (!server.app.attach()) return -1;
                server.attachment = socket;
                request->size = 0;
                lws_callback_on_writable(socket); return 0;
            case LWS_CALLBACK_CLOSED:
                if (server.attachment == socket) { server.attachment = nullptr; server.app.detach(); }
                return 0;
            case LWS_CALLBACK_RECEIVE:
                if (lws_is_first_fragment(socket) && request->size == 0) request->binary = lws_frame_is_binary(socket);
                if (request->size + size > 4096) return -1;
                std::memcpy(request->body + request->size, data, size); request->size += size;
                if (lws_is_final_fragment(socket) && lws_remaining_packet_payload(socket) == 0) {
                    server.app.message(Bytes(request->body, request->body + request->size), request->binary);
                    request->size = 0;
                }
                return 0;
            case LWS_CALLBACK_SERVER_WRITEABLE: {
                auto message = server.app.outgoing();
                if (!message) return 0;
                std::vector<unsigned char> buffer(LWS_PRE + message->bytes.size());
                std::copy(message->bytes.begin(), message->bytes.end(), buffer.begin() + LWS_PRE);
                const auto written = lws_write(socket, buffer.data() + LWS_PRE, message->bytes.size(),
                    message->binary ? LWS_WRITE_BINARY : LWS_WRITE_TEXT);
                if (written < 0 || static_cast<std::size_t>(written) != message->bytes.size()) return -1;
                lws_callback_on_writable(socket); return 0;
            }
            case LWS_CALLBACK_HTTP:
                if (!data || size >= sizeof(request->path)) return -1;
                std::memcpy(request->path, data, size); request->path[size] = 0;
                request->size = 0; request->response_size = 0; request->rejected = false;
                request->post = lws_hdr_total_length(socket, WSI_TOKEN_POST_URI) != 0;
                if (!request->post || lws_hdr_total_length(socket, WSI_TOKEN_HTTP_CONTENT_LENGTH) == 0)
                    return server.complete(socket, *request);
                return 0;
            case LWS_CALLBACK_HTTP_BODY:
                if (request->rejected) return 0;
                if (request->size + size > 16384) {
                    request->rejected = true;
                    return server.respond(socket, *request, {413, "{\"error\":\"body too large\"}"});
                }
                std::memcpy(request->body + request->size, data, size); request->size += size;
                return 0;
            case LWS_CALLBACK_HTTP_BODY_COMPLETION:
                return request->rejected ? 0 : server.complete(socket, *request);
            case LWS_CALLBACK_HTTP_WRITEABLE: {
                const auto written = lws_write(socket, request->response + LWS_PRE, request->response_size, LWS_WRITE_HTTP_FINAL);
                if (written < 0 || static_cast<std::size_t>(written) != request->response_size) return -1;
                if (request->rejected) return -1;
                return lws_http_transaction_completed(socket) ? -1 : 0;
            }
            default: return 0;
            }
        } catch (...) { return -1; }
    }
};
}
int serve_microvm(MicrovmApplication& app, unsigned hook_port, unsigned attachment_port,
                  const std::function<bool()>& interrupted) {
    if (hook_port == attachment_port) throw std::invalid_argument("hook and attachment ports must differ");
    lws_set_log_level(LLL_ERR | LLL_WARN, nullptr);
    const lws_protocols protocols[] = {
        {"http", Server::callback, sizeof(Request), 16384, 0, nullptr, 0},
        {"txing.agent.probe.v1", Server::callback, sizeof(Request), 4096, 0, nullptr, 0},
        {nullptr, nullptr, 0, 0, 0, nullptr, 0}
    };
    Server server{app, hook_port, attachment_port};
    server.timer.owner = &server;
    lws_context_creation_info info{};
    info.options = LWS_SERVER_OPTION_EXPLICIT_VHOSTS;
    info.port = CONTEXT_PORT_NO_LISTEN; info.protocols = protocols; info.user = &server;
    info.gid = -1; info.uid = -1; info.fd_limit_per_thread = 64;
    server.context = lws_create_context(&info);
    if (!server.context) throw std::runtime_error("could not create MicroVM HTTP context");
    info.port = hook_port;
    auto* hooks = lws_create_vhost(server.context, &info);
    info.port = attachment_port;
    auto* ingress = lws_create_vhost(server.context, &info);
    if (!hooks || !ingress) {
        lws_context_destroy(server.context);
        throw std::runtime_error("could not bind MicroVM hook/attachment listeners");
    }
    app.wake_with([&] { lws_cancel_service(server.context); });
    lws_sul_schedule(server.context, 0, &server.timer.sul, Server::timer_callback, 100000);
    std::cerr << "MicroVM host waiting for /run; hooks=" << hook_port << " attachment=" << attachment_port << '\n';
    while (!interrupted()) {
        if (lws_service(server.context, 0) < 0) break;
    }
    app.stop();
    app.wake_with({});
    lws_sul_cancel(&server.timer.sul);
    lws_context_destroy(server.context); return 0;
}
}
