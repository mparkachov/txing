#include "agent/controller_handler.hpp"
#include <aws/core/Aws.h>
#include <aws/core/auth/AWSCredentialsProvider.h>
#include <aws/core/client/DefaultRetryStrategy.h>
#include <arpa/inet.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using namespace txing::agent;
namespace {
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
struct Fixture {
    int listener = -1;
    unsigned port = 0;
    std::thread worker;
    std::vector<std::string> requests;
    bool terminated_one = false, terminated_two = false;
    explicit Fixture(unsigned expected_requests = 7) {
        listener = socket(AF_INET, SOCK_STREAM, 0);
        require(listener >= 0, "cannot create drain API fixture");
        sockaddr_in address{}; address.sin_family = AF_INET; address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        require(bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0 && listen(listener, 5) == 0,
                "cannot bind drain API fixture");
        socklen_t length = sizeof(address);
        require(getsockname(listener, reinterpret_cast<sockaddr*>(&address), &length) == 0, "cannot obtain fixture port");
        port = ntohs(address.sin_port);
        worker = std::thread([this, expected_requests] {
            for (unsigned n = 0; n < expected_requests; ++n) {
                pollfd event{listener, POLLIN, 0};
                if (poll(&event, 1, 5000) <= 0) break;
                const int peer = accept(listener, nullptr, nullptr);
                if (peer < 0) break;
                timeval timeout{3, 0}; setsockopt(peer, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
                std::string request; char buffer[4096];
                while (request.size() < 65536 && request.find("\r\n\r\n") == std::string::npos) {
                    const auto count = recv(peer, buffer, sizeof(buffer), 0);
                    if (count <= 0) break;
                    request.append(buffer, static_cast<std::size_t>(count));
                }
                const auto end = request.find("\r\n");
                const auto line = request.substr(0, end);
                requests.push_back(line);
                std::string body;
                if (line.rfind("GET /2025-09-09/microvms?", 0) == 0) {
                    if (terminated_one && terminated_two)
                        body = R"({"items":[{"microvmId":"mvm-one","state":"TERMINATED"},{"microvmId":"mvm-two","state":"TERMINATED"}]})";
                    else if (line.find("nextToken=page2") != std::string::npos)
                        body = R"({"items":[{"microvmId":"mvm-two","state":"TERMINATING"},{"microvmId":"mvm-two","state":"RUNNING"}]})";
                    else body = R"({"items":[{"microvmId":"mvm-one","state":"TERMINATED"},{"microvmId":"mvm-one","state":"RUNNING"}],"nextToken":"page2"})";
                } else if (line.rfind("DELETE /2025-09-09/microvms/mvm-one ", 0) == 0) {
                    terminated_one = true; body = R"({"microvmId":"mvm-one","state":"TERMINATING"})";
                } else if (line.rfind("DELETE /2025-09-09/microvms/mvm-two ", 0) == 0) {
                    terminated_two = true; body = R"({"microvmId":"mvm-two","state":"TERMINATING"})";
                } else if (line.rfind("GET /things ", 0) == 0) body = R"({"things":[]})";
                else body = R"({"unexpected":true})";
                const std::string response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: " +
                    std::to_string(body.size()) + "\r\n\r\n" + body;
                send(peer, response.data(), response.size(), 0); close(peer);
            }
        });
    }
    ~Fixture() { if (worker.joinable()) worker.join(); if (listener >= 0) close(listener); }
};
void run() {
    Fixture fixture;
    auto credentials = Aws::MakeShared<Aws::Auth::SimpleAWSCredentialsProvider>("fixture", "fixture-key", "fixture-secret");
    Aws::Client::ClientConfiguration client(Aws::Client::ClientConfigurationInitValues{true});
    client.region = "eu-central-1"; client.scheme = Aws::Http::Scheme::HTTP;
    client.endpointOverride = ("http://127.0.0.1:" + std::to_string(fixture.port)).c_str();
    client.connectTimeoutMs = 2000; client.requestTimeoutMs = 3000;
    client.retryStrategy = Aws::MakeShared<Aws::Client::DefaultRetryStrategy>("fixture", 0);
    ControllerConfig config{{"arn:aws:lambda:eu-central-1:123456789012:microvm-image:agent", {}, {}, {}, "eu-central-1"}, {}};
    bool incomplete = false, completed = false, configuration_error = false;
    unsigned reconciliations = 0;
    const auto reconcile = [&] { ++reconciliations; };
    const auto drain = [&] { handle_disabled_event(R"({"source":"aws.events"})", config, credentials, client); completed = true; };
    try { controller_dispatch_automation("invalid", true, reconcile, drain); }
    catch (const std::runtime_error&) { incomplete = true; }
    require(incomplete && !completed && reconciliations == 0,
            "invalid mode did not drain or acknowledged completion before termination was observed");
    try { controller_dispatch_automation("enabled", false, reconcile, drain); }
    catch (const std::invalid_argument&) { configuration_error = true; }
    require(completed && configuration_error && reconciliations == 0,
            "incomplete enabled configuration did not drain or reported successful activation");
    fixture.worker.join();
    require(fixture.requests.size() == 7 && fixture.requests[0].rfind("GET /2025-09-09/microvms?", 0) == 0 &&
            fixture.requests[1].rfind("DELETE /2025-09-09/microvms/mvm-one ", 0) == 0 &&
            fixture.requests[2].rfind("GET /2025-09-09/microvms?", 0) == 0 &&
            fixture.requests[2].find("nextToken=page2") != std::string::npos &&
            fixture.requests[3].rfind("DELETE /2025-09-09/microvms/mvm-two ", 0) == 0 &&
            fixture.requests[4].rfind("GET /things ", 0) == 0 &&
            fixture.requests[5].rfind("GET /2025-09-09/microvms?", 0) == 0 &&
            fixture.requests[6].rfind("GET /things ", 0) == 0,
            "disabled drain did not terminate each page before fetching the next and confirm terminal inventory on retry");
    Fixture missing(1);
    client.endpointOverride = ("http://127.0.0.1:" + std::to_string(missing.port)).c_str();
    config.cloud.image.clear();
    bool needs_manual_inventory = false;
    try { handle_disabled_event(R"({"source":"aws.events"})", config, credentials, client); }
    catch (const std::runtime_error& error) {
        needs_manual_inventory = std::string(error.what()).find("image configuration missing") != std::string::npos;
    }
    missing.worker.join();
    require(needs_manual_inventory && missing.requests.size() == 1 && missing.requests[0].rfind("GET /things ", 0) == 0,
            "missing image skipped known-assignment discovery or incorrectly reported a complete drain");
}
}
void test_controller_drain_api() {
    setenv("NO_PROXY", "127.0.0.1", 1); setenv("no_proxy", "127.0.0.1", 1);
    Aws::SDKOptions options; Aws::InitAPI(options);
    try { run(); } catch (...) { Aws::ShutdownAPI(options); throw; }
    Aws::ShutdownAPI(options);
}
