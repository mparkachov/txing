#include "agent/attach.hpp"
#include "agent/manual.hpp"
#include "agent/microvm.hpp"
#include <aws/core/Aws.h>
#include <arpa/inet.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#include <atomic>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <stdexcept>

using namespace txing::agent;
using namespace std::chrono_literals;
namespace {
void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
unsigned bound_port(int socket) {
    sockaddr_in address{}; address.sin_family = AF_INET; address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    require(bind(socket, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0, "cannot bind fixture port");
    socklen_t size = sizeof(address);
    require(getsockname(socket, reinterpret_cast<sockaddr*>(&address), &size) == 0, "cannot read fixture port");
    return ntohs(address.sin_port);
}
unsigned unused_port() {
    const auto socket = ::socket(AF_INET, SOCK_STREAM, 0); require(socket >= 0, "cannot create fixture socket");
    const auto port = bound_port(socket); close(socket); return port;
}
template<class F> void eventually(F condition, std::chrono::seconds timeout = 6s) {
    const auto end = std::chrono::steady_clock::now() + timeout;
    while (!condition()) {
        if (std::chrono::steady_clock::now() >= end) throw std::runtime_error("attachment fixture timed out");
        std::this_thread::sleep_for(20ms);
    }
}
struct FakeActions : Actions {
    std::atomic<unsigned> acquisitions{0}, activities{0}, sent{0}, releases{0};
    std::atomic<bool> grant{false};
    bool acquire(std::string actor) override { if (actor != "QGroundControl") return false; ++acquisitions; grant = true; return true; }
    bool send(Bytes bytes) override { if (!valid_mavlink2(bytes)) return false; ++sent; return true; }
    void release() override { ++releases; }
    void client_activity() override { ++activities; }
};
struct RejectedAuth {
    int listener = -1;
    unsigned port = 0;
    std::thread worker;
    RejectedAuth() {
        listener = ::socket(AF_INET, SOCK_STREAM, 0); require(listener >= 0, "cannot create auth fixture");
        port = bound_port(listener); require(listen(listener, 1) == 0, "cannot listen for auth fixture");
        worker = std::thread([this] {
            pollfd ready{listener, POLLIN, 0};
            if (poll(&ready, 1, 7000) <= 0) return;
            const auto peer = accept(listener, nullptr, nullptr); if (peer < 0) return;
            char request[2048]; recv(peer, request, sizeof(request), 0);
            const std::string response = "HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
            send(peer, response.data(), response.size(), 0); close(peer);
        });
    }
    ~RejectedAuth() { if (worker.joinable()) worker.join(); if (listener >= 0) close(listener); }
};
void tests(bool rejected_token) {
    const Bytes frame{0xfd, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0};
    const int qgc = ::socket(AF_INET, SOCK_DGRAM, 0); require(qgc >= 0, "cannot create QGC fixture socket");
    const auto qgc_port = bound_port(qgc);
    auto hook_port = unused_port(), ingress_port = unused_port();
    while (hook_port == ingress_port) ingress_port = unused_port();
    FakeActions actions;
    MicrovmApplication app([&](const MicrovmRun&, MicrovmApplication& host) {
        host.connection(Stream::telemetry, Connection::connected, "");
        while (!host.stopping()) {
            if (actions.grant.exchange(false)) host.control(true, "acquired");
            host.telemetry(frame);
            std::this_thread::sleep_for(30ms);
        }
    });
    app.actions(&actions);
    const std::string hook = R"({"microvmId":"mvm-test","runHookPayload":"{\"thingId\":\"tbot-test\",\"region\":\"eu-central-1\"}"})";
    require(app.hook("/run", hook).status == 200, "fixture run hook failed");
    ManualOptions options; options.listener = 0; options.qgc = qgc_port; options.control = true;
    std::ostringstream diagnostics;
    ManualOperator manual(options, diagnostics);
    std::atomic<bool> stop{false};
    std::atomic<bool> server_failed{false};
    std::thread server([&] { try { serve_microvm(app, hook_port, ingress_port, [&] { return stop.load(); }); }
                             catch (...) { server_failed = true; } });
    std::atomic<int> result{-9};
    std::thread client;
    std::unique_ptr<RejectedAuth> rejection;
    try {
        if (rejected_token) rejection = std::make_unique<RejectedAuth>();
        // Listener setup completes on the server thread before attempting the
        // WebSocket. No AWS calls or external network are involved.
        std::this_thread::sleep_for(200ms);
        client = std::thread([&] { try { result = test_attach_loopback(manual, ingress_port, rejected_token ? 8 : 3,
                                                                       rejection ? rejection->port : 0); }
                                   catch (...) { result = -1; } });
        eventually([&] { return app.attached() || server_failed.load(); });
        require(!server_failed && app.attached(), "loopback attachment failed");
        eventually([&] { return manual.status().telemetry > 0; });
        sockaddr_in destination{}; destination.sin_family = AF_INET; destination.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        destination.sin_port = htons(manual.port());
        auto send_frame = [&] {
            require(sendto(qgc, frame.data(), frame.size(), 0, reinterpret_cast<sockaddr*>(&destination), sizeof(destination)) ==
                    static_cast<ssize_t>(frame.size()), "QGC fixture send failed");
        };
        send_frame();
        eventually([&] { return actions.acquisitions.load() == 1 && manual.status().held; });
        send_frame();
        eventually([&] { return actions.sent.load() > 0 && actions.activities.load() > 0; });
        eventually([&] { return result.load() != -9; });
        client.join();
        eventually([&] { return actions.releases.load() > 0 && !app.attached(); });
        require(result == (rejected_token ? 1 : 0), "attachment did not close on token loss or lifetime");
        send_frame();
        std::this_thread::sleep_for(100ms);
        require(actions.acquisitions.load() == 1, "attachment reacquired control");
        stop = true; server.join();
    } catch (...) {
        stop = true;
        if (server.joinable()) server.join();
        if (client.joinable()) client.join();
        close(qgc); throw;
    }
    close(qgc);
}
}
int main() {
    setenv("NO_PROXY", "127.0.0.1", 1);
    setenv("no_proxy", "127.0.0.1", 1);
    Aws::SDKOptions options; Aws::InitAPI(options);
    int result = 0;
    try { tests(false); tests(true); std::cout << "PASS loopback attachment, token cutoff and rejection\n"; }
    catch (const std::exception& error) { std::cerr << "FAIL " << error.what() << '\n'; result = 1; }
    Aws::ShutdownAPI(options); return result;
}
