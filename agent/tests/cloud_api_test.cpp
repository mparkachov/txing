#include "agent/cloud.hpp"
#include "agent/aws.hpp"
#include <aws/core/Aws.h>
#include <aws/core/auth/AWSCredentialsProvider.h>
#include <aws/core/client/DefaultRetryStrategy.h>
#include <aws/core/utils/json/JsonSerializer.h>
#include <arpa/inet.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
#include <cctype>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

using namespace txing::agent;
namespace {
void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
struct ApiFixture {
    int listener = -1;
    unsigned port = 0;
    std::thread worker;
    std::string request;
    ApiFixture(int code, std::string body) {
        listener = socket(AF_INET, SOCK_STREAM, 0); require(listener >= 0, "cannot create fixture listener");
        sockaddr_in address{}; address.sin_family = AF_INET; address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        require(bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0 && listen(listener, 1) == 0,
                "cannot bind fixture listener");
        socklen_t length = sizeof(address); require(getsockname(listener, reinterpret_cast<sockaddr*>(&address), &length) == 0,
                                                     "cannot read fixture port");
        port = ntohs(address.sin_port);
        worker = std::thread([this, code, body = std::move(body)] {
            pollfd event{listener, POLLIN, 0};
            if (poll(&event, 1, 5000) <= 0) return;
            const int peer = accept(listener, nullptr, nullptr); if (peer < 0) return;
            timeval timeout{3, 0}; setsockopt(peer, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
            char buffer[4096];
            std::size_t body_at = std::string::npos, content_length = 0;
            while (request.size() < 65536) {
                const auto count = recv(peer, buffer, sizeof(buffer), 0); if (count <= 0) break;
                request.append(buffer, static_cast<std::size_t>(count));
                if (body_at == std::string::npos) {
                    const auto separator = request.find("\r\n\r\n");
                    if (separator != std::string::npos) {
                        body_at = separator + 4;
                        auto headers = request.substr(0, separator);
                        for (auto& ch : headers) ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
                        const auto at = headers.find("content-length:");
                        if (at != std::string::npos) content_length = std::stoul(headers.substr(at + 15));
                    }
                }
                if (body_at != std::string::npos && request.size() >= body_at + content_length) break;
            }
            const std::string response = "HTTP/1.1 " + std::to_string(code) + (code == 200 ? " OK" : " Forbidden") +
                "\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: " + std::to_string(body.size()) + "\r\n\r\n" + body;
            send(peer, response.data(), response.size(), 0); close(peer);
        });
    }
    ~ApiFixture() { if (worker.joinable()) worker.join(); if (listener >= 0) close(listener); }
};
struct PaginationFixture {
    int listener = -1;
    unsigned port = 0;
    std::thread worker;
    std::vector<std::string> requests;
    explicit PaginationFixture(bool registry = false) {
        listener = socket(AF_INET, SOCK_STREAM, 0); require(listener >= 0, "cannot create pagination fixture");
        sockaddr_in address{}; address.sin_family = AF_INET; address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        require(bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0 && listen(listener, 3) == 0,
                "cannot bind pagination fixture");
        socklen_t length = sizeof(address);
        require(getsockname(listener, reinterpret_cast<sockaddr*>(&address), &length) == 0, "cannot read pagination fixture port");
        port = ntohs(address.sin_port);
        worker = std::thread([this, registry] {
            const std::vector<std::string> microvm_pages = {
                R"({"items":[{"microvmId":"first","state":"RUNNING"}],"nextToken":"A"})",
                R"({"items":[{"microvmId":"second","state":"RUNNING"}],"nextToken":"B"})",
                R"({"items":[{"microvmId":"third","state":"RUNNING"}],"nextToken":"A"})"};
            const std::vector<std::string> registry_pages = {
                R"({"things":[{"thingName":"first"}],"nextToken":"A"})",
                R"({"things":[{"thingName":"second"}],"nextToken":"B"})",
                R"({"things":[{"thingName":"third"}],"nextToken":"A"})"};
            const auto& pages = registry ? registry_pages : microvm_pages;
            for (const auto& body : pages) {
                pollfd event{listener, POLLIN, 0}; if (poll(&event, 1, 5000) <= 0) return;
                const int peer = accept(listener, nullptr, nullptr); if (peer < 0) return;
                timeval timeout{3, 0}; setsockopt(peer, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
                std::string request; char buffer[4096];
                while (request.size() < 65536 && request.find("\r\n\r\n") == std::string::npos) {
                    const auto count = recv(peer, buffer, sizeof(buffer), 0); if (count <= 0) break;
                    request.append(buffer, static_cast<std::size_t>(count));
                }
                requests.push_back(request.substr(0, request.find("\r\n")));
                const std::string response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: " +
                    std::to_string(body.size()) + "\r\n\r\n" + body;
                send(peer, response.data(), response.size(), 0); close(peer);
            }
        });
    }
    ~PaginationFixture() { if (worker.joinable()) worker.join(); if (listener >= 0) close(listener); }
};
void tests() {
    auto credentials = Aws::MakeShared<Aws::Auth::SimpleAWSCredentialsProvider>("fixture", "fixture-key", "fixture-secret");
    auto config_for = [](unsigned port) {
        Aws::Client::ClientConfiguration config;
        config.region = "eu-central-1"; config.scheme = Aws::Http::Scheme::HTTP;
        config.endpointOverride = ("http://127.0.0.1:" + std::to_string(port)).c_str();
        config.connectTimeoutMs = 2000; config.requestTimeoutMs = 3000;
        config.retryStrategy = Aws::MakeShared<Aws::Client::DefaultRetryStrategy>("fixture", 0);
        return config;
    };
    for (const auto& example : std::vector<std::pair<std::string, bool>>{
            {R"({"thingTypeName":"another-device","attributes":{"capabilities":"sparkplug,agent"}})", true},
            {R"({"thingTypeName":"tbot","attributes":{"capabilities":"sparkplug,video"}})", false},
            {R"({"thingTypeName":"tbot","attributes":{"capabilities":"sparkplug,agent-extra"}})", false},
            {R"({"thingTypeName":"tbot","attributes":{}})", false}}) {
        ApiFixture fixture(200, example.first);
        AwsDevice device(credentials, config_for(fixture.port));
        require(device.has_capability("registered-device", "agent") == example.second,
                "agent eligibility used device type or partial capability membership");
    }
    {
        ApiFixture fixture(200, R"({"attributes":{"capabilities":"sparkplug,agent,agent"}})");
        AwsDevice device(credentials, config_for(fixture.port));
        bool rejected = false;
        try { device.has_capability("registered-device", "agent"); }
        catch (const std::runtime_error&) { rejected = true; }
        require(rejected, "malformed registry capabilities authorized execution");
    }
    {
        PaginationFixture fixture;
        CloudMicrovms cloud(credentials, config_for(fixture.port));
        std::vector<std::string> visited;
        std::string error;
        try {
            cloud.for_each_page("image-identifier", [&](const auto& page) {
                for (const auto& run : page) visited.push_back(run.id);
            });
        } catch (const std::exception& failure) { error = failure.what(); }
        fixture.worker.join();
        require(visited == std::vector<std::string>({"first", "second", "third"}) &&
                error.find("pagination did not advance") != std::string::npos && fixture.requests.size() == 3 &&
                fixture.requests[1].find("nextToken=A") != std::string::npos &&
                fixture.requests[2].find("nextToken=B") != std::string::npos,
                "cyclic pagination did not preserve page actions and fail promptly");
    }
    {
        PaginationFixture fixture(true);
        AwsDevice device(credentials, config_for(fixture.port));
        std::string error;
        try { device.registered_things(); }
        catch (const std::exception& failure) { error = failure.what(); }
        fixture.worker.join();
        require(error.find("iot:ListThings: pagination did not advance") != std::string::npos &&
                fixture.requests.size() == 3 && fixture.requests[1].find("nextToken=A") != std::string::npos &&
                fixture.requests[2].find("nextToken=B") != std::string::npos,
                "cyclic Thing registry pagination returned a partial inventory or failed to stop promptly");
    }
    {
        ApiFixture fixture(200, R"({"microvmId":"mvm-fixture","state":"RUNNING","imageArn":"arn:aws:lambda:eu-central-1:123456789012:microvm-image:agent"})");
        CloudMicrovms cloud(credentials, config_for(fixture.port));
        const auto host = cloud.describe("mvm-fixture");
        require(host.run.id == "mvm-fixture" && host.run.state == "RUNNING" &&
                host.image == "arn:aws:lambda:eu-central-1:123456789012:microvm-image:agent",
                "GetMicrovm did not preserve the reported host and image identities");
        fixture.worker.join();
        require(fixture.request.rfind("GET /2025-09-09/microvms/mvm-fixture ", 0) == 0,
                "wrong MicroVM identity was queried");
    }
    {
        ApiFixture fixture(200, R"({"authToken":{"X-aws-proxy-auth":"fixture-token"}})");
        CloudMicrovms cloud(credentials, config_for(fixture.port));
        require(cloud.token("mvm-fixture", 8081, 5) == "fixture-token", "token response was not returned");
        fixture.worker.join();
        const auto start = fixture.request.find("\r\n\r\n"); require(start != std::string::npos, "missing token request body");
        Aws::Utils::Json::JsonValue body(Aws::String(fixture.request.substr(start + 4).c_str()));
        require(body.WasParseSuccessful() && body.View().GetInteger("expirationInMinutes") == 5, "wrong token expiry");
        const auto ports = body.View().GetArray("allowedPorts");
        require(ports.GetLength() == 1 && ports[0].GetInteger("port") == 8081, "token was not port scoped");
    }
    {
        ApiFixture fixture(403, R"({"__type":"AccessDeniedException","message":"private-secret"})");
        CloudMicrovms cloud(credentials, config_for(fixture.port));
        std::string error;
        try { cloud.token("mvm-fixture", 8081, 5); }
        catch (const std::exception& failure) { error = failure.what(); }
        require(error.find("CreateMicrovmAuthToken") != std::string::npos && error.find("403") != std::string::npos &&
                error.find("private-secret") == std::string::npos && error.find("fixture-secret") == std::string::npos,
                "token failure did not preserve safe operation/status diagnostics");
    }
    {
        ApiFixture fixture(200, R"({"authToken":{"X-aws-proxy-auth":"bad\r\nprivate-secret"}})");
        CloudMicrovms cloud(credentials, config_for(fixture.port));
        std::string error;
        try { cloud.token("mvm-fixture", 8081, 5); }
        catch (const std::exception& failure) { error = failure.what(); }
        require(error.find("invalid framing") != std::string::npos && error.find("private-secret") == std::string::npos,
                "malformed token was accepted or exposed");
    }
}
}
int main() {
    setenv("NO_PROXY", "127.0.0.1", 1);
    setenv("no_proxy", "127.0.0.1", 1);
    Aws::SDKOptions options; Aws::InitAPI(options);
    int result = 0;
    try { tests(); std::cout << "PASS port-scoped token and sanitized API failure\n"; }
    catch (const std::exception& error) { std::cerr << "FAIL " << error.what() << '\n'; result = 1; }
    Aws::ShutdownAPI(options); return result;
}
