#include "agent/controller_handler.hpp"
#include <aws/core/Aws.h>
#include <aws/core/auth/AWSCredentialsProviderChain.h>
#include <aws/core/client/DefaultRetryStrategy.h>
#include <curl/curl.h>
#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
struct Response { std::string body, request_id; };
std::size_t receive(char* data, std::size_t size, std::size_t count, void* opaque) {
    auto& output = *static_cast<Response*>(opaque);
    const auto bytes = size * count;
    if (bytes > 256 * 1024 || output.body.size() > 256 * 1024 - bytes) return 0;
    output.body.append(data, bytes); return bytes;
}
std::size_t header(char* data, std::size_t size, std::size_t count, void* opaque) {
    const auto bytes = size * count;
    const std::string line(data, bytes);
    constexpr const char name[] = "lambda-runtime-aws-request-id:";
    if (line.size() >= sizeof(name) - 1) {
        auto prefix = line.substr(0, sizeof(name) - 1);
        std::transform(prefix.begin(), prefix.end(), prefix.begin(), [](unsigned char c) { return std::tolower(c); });
        if (prefix == name) {
            auto value = line.substr(sizeof(name) - 1);
            const auto first = value.find_first_not_of(" \t"), last = value.find_last_not_of(" \t\r\n");
            if (first != std::string::npos) static_cast<Response*>(opaque)->request_id = value.substr(first, last - first + 1);
        }
    }
    return bytes;
}
Response http(const std::string& url, const std::string* payload) {
    CURL* raw = curl_easy_init();
    if (!raw) throw std::runtime_error("could not initialize Lambda runtime HTTP client");
    Response response;
    curl_easy_setopt(raw, CURLOPT_URL, url.c_str());
    curl_easy_setopt(raw, CURLOPT_WRITEFUNCTION, receive); curl_easy_setopt(raw, CURLOPT_WRITEDATA, &response);
    curl_easy_setopt(raw, CURLOPT_HEADERFUNCTION, header); curl_easy_setopt(raw, CURLOPT_HEADERDATA, &response);
    curl_easy_setopt(raw, CURLOPT_CONNECTTIMEOUT_MS, 2000L); curl_easy_setopt(raw, CURLOPT_NOSIGNAL, 1L);
    curl_slist* headers = nullptr;
    if (payload) {
        headers = curl_slist_append(nullptr, "Content-Type: application/json");
        if (!headers) { curl_easy_cleanup(raw); throw std::runtime_error("could not allocate runtime HTTP headers"); }
        curl_easy_setopt(raw, CURLOPT_HTTPHEADER, headers);
        curl_easy_setopt(raw, CURLOPT_POST, 1L); curl_easy_setopt(raw, CURLOPT_POSTFIELDS, payload->c_str());
        curl_easy_setopt(raw, CURLOPT_POSTFIELDSIZE, static_cast<long>(payload->size()));
        curl_easy_setopt(raw, CURLOPT_TIMEOUT_MS, 5000L);
    }
    const auto status = curl_easy_perform(raw);
    long code = 0; curl_easy_getinfo(raw, CURLINFO_RESPONSE_CODE, &code);
    curl_slist_free_all(headers);
    curl_easy_cleanup(raw);
    if (status != CURLE_OK || code < 200 || code >= 300) throw std::runtime_error("Lambda runtime API request failed");
    return response;
}
std::string env(const char* name) { const auto* value = std::getenv(name); return value ? value : ""; }
}
int main() {
    const auto runtime = env("AWS_LAMBDA_RUNTIME_API");
    if (runtime.empty() || runtime.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.:_-") != std::string::npos) {
        std::cerr << "Lambda runtime API address is invalid\n"; return 1;
    }
    Aws::SDKOptions options; Aws::InitAPI(options);
    int exit_code = 0;
    try {
        if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) throw std::runtime_error("could not initialize curl");
        auto credentials = Aws::MakeShared<Aws::Auth::DefaultAWSCredentialsProviderChain>("agent-controller");
        Aws::Client::ClientConfiguration client_config;
        client_config.region = "eu-central-1"; client_config.connectTimeoutMs = 2000; client_config.requestTimeoutMs = 5000;
        client_config.retryStrategy = Aws::MakeShared<Aws::Client::DefaultRetryStrategy>("agent-controller", 1);
        txing::agent::ControllerConfig config{{env("TXING_AGENT_IMAGE"), env("TXING_AGENT_IMAGE_VERSION"),
            env("TXING_AGENT_EXECUTION_ROLE"), env("TXING_AGENT_LOG_GROUP"), "eu-central-1"}, env("TXING_AGENT_RELEASE")};
        const auto base = "http://" + runtime + "/2018-06-01/runtime/invocation/";
        while (true) {
            const auto event = http(base + "next", nullptr);
            if (event.request_id.empty() || event.request_id.size() > 128 ||
                event.request_id.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") != std::string::npos)
                throw std::runtime_error("Lambda invocation identity is invalid");
            bool success = true;
            try {
                txing::agent::controller_dispatch_automation(env("TXING_AGENT_AUTOMATION"),
                    txing::agent::controller_configured(config),
                    [&] { txing::agent::handle_controller_event(event.body, config, credentials, client_config); },
                    [&] { txing::agent::handle_disabled_event(event.body, config, credentials, client_config); });
            } catch (const std::exception& error) {
                success = false; std::cerr << "agent controller: " << error.what() << '\n';
            }
            const std::string body = success ? R"({"ok":true})" : R"({"errorType":"AgentControllerError","errorMessage":"Controller reconciliation failed; inspect logs"})";
            http(base + event.request_id + (success ? "/response" : "/error"), &body);
        }
    } catch (const std::exception& error) { std::cerr << "agent controller runtime: " << error.what() << '\n'; exit_code = 1; }
    curl_global_cleanup(); Aws::ShutdownAPI(options); return exit_code;
}
