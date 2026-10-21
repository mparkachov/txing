#include "agent/aws.hpp"
#include <aws/core/utils/json/JsonSerializer.h>
#include <aws/iot/model/DescribeThingRequest.h>
#include <aws/iot/model/DescribeEndpointRequest.h>
#include <aws/iot-data/model/GetThingShadowRequest.h>
#include <sstream>
#include <stdexcept>

namespace txing::agent {
Lifecycle parse_lifecycle(const std::string& json, const std::string& thing) {
    Aws::Utils::Json::JsonValue document(Aws::String(json.c_str()));
    if (!document.WasParseSuccessful()) throw std::runtime_error("sparkplug shadow: invalid JSON");
    auto view = document.View();
    for (const auto* field : {"state", "reported"}) {
        if (!view.ValueExists(field) || !view.GetObject(field).IsObject())
            throw std::runtime_error("sparkplug shadow: missing reported state");
        view = view.GetObject(field);
    }
    if (!view.ValueExists("topic") || !view.GetObject("topic").IsObject())
        throw std::runtime_error("sparkplug shadow: missing topic");
    auto topic = view.GetObject("topic");
    if (!topic.ValueExists("deviceId") || !topic.GetObject("deviceId").IsString() ||
        topic.GetString("deviceId") != thing.c_str() || !topic.ValueExists("namespace") ||
        !topic.GetObject("namespace").IsString() || topic.GetString("namespace") != "spBv1.0" ||
        !topic.ValueExists("messageType") || !topic.GetObject("messageType").IsString())
        throw std::runtime_error("sparkplug shadow: invalid device topic");
    const auto type = topic.GetString("messageType");
    if (type == "DDEATH") return {false, 4};
    if (type != "DBIRTH" && type != "DDATA") throw std::runtime_error("sparkplug shadow: unexpected message type");
    for (const auto* field : {"payload", "metrics"}) {
        if (!view.ValueExists(field) || !view.GetObject(field).IsObject())
            throw std::runtime_error("sparkplug shadow: missing metrics");
        view = view.GetObject(field);
    }
    if (!view.ValueExists("redcon") || !view.GetObject("redcon").IsIntegerType())
        throw std::runtime_error("sparkplug shadow: invalid redcon");
    const auto redcon = view.GetInt64("redcon");
    if (redcon < 1 || redcon > 4) throw std::runtime_error("sparkplug shadow: redcon outside 1..4");
    return {true, static_cast<int>(redcon)};
}

AwsDevice::AwsDevice(std::shared_ptr<Aws::Auth::AWSCredentialsProvider> credentials,
                     Aws::Client::ClientConfiguration config)
    : registry_(credentials, config), shadows_(credentials, config) {}

std::string AwsDevice::registered_type(const std::string& thing) {
    Aws::IoT::Model::DescribeThingRequest request;
    request.SetThingName(thing.c_str());
    auto result = registry_.DescribeThing(request);
    if (!result.IsSuccess()) throw std::runtime_error("iot:DescribeThing: " +
        std::string(result.GetError().GetExceptionName().c_str()) + " HTTP " +
        std::to_string(static_cast<int>(result.GetError().GetResponseCode())));
    return result.GetResult().GetThingTypeName().c_str();
}
Lifecycle AwsDevice::lifecycle(const std::string& thing) {
    if (!shadow_endpoint_resolved_) {
        Aws::IoT::Model::DescribeEndpointRequest endpoint;
        endpoint.SetEndpointType("iot:Data-ATS");
        const auto result = registry_.DescribeEndpoint(endpoint);
        if (!result.IsSuccess()) throw std::runtime_error("iot:DescribeEndpoint(Data-ATS): " +
            std::string(result.GetError().GetExceptionName().c_str()) + " HTTP " +
            std::to_string(static_cast<int>(result.GetError().GetResponseCode())));
        const auto address = result.GetResult().GetEndpointAddress();
        if (address.empty() || address.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789.-") != Aws::String::npos)
            throw std::runtime_error("iot:DescribeEndpoint returned an invalid hostname");
        shadows_.OverrideEndpoint("https://" + address);
        shadow_endpoint_resolved_ = true;
    }
    Aws::IoTDataPlane::Model::GetThingShadowRequest request;
    request.SetThingName(thing.c_str()); request.SetShadowName("sparkplug");
    auto result = shadows_.GetThingShadow(request);
    if (!result.IsSuccess()) throw std::runtime_error("iot:GetThingShadow(sparkplug): " +
        std::string(result.GetError().GetExceptionName().c_str()) + " HTTP " +
        std::to_string(static_cast<int>(result.GetError().GetResponseCode())));
    std::ostringstream payload; payload << result.GetResult().GetPayload().rdbuf();
    return parse_lifecycle(payload.str(), thing);
}

LifecyclePoller::LifecyclePoller(std::function<Lifecycle()> source) {
    worker_ = std::thread([this, source = std::move(source)] {
        std::unique_lock<std::mutex> lock(mutex_);
        while (!stop_) {
            const auto started = std::chrono::steady_clock::now();
            lock.unlock();
            std::optional<std::pair<Lifecycle, Time>> next;
            std::string failure;
            try { auto state = source(); next = std::make_pair(state, std::chrono::steady_clock::now()); }
            catch (const std::exception& e) { failure = e.what(); }
            lock.lock();
            if (next) latest_ = next;
            error_ = std::move(failure);
            wake_.wait_until(lock, started + std::chrono::seconds(2), [this] { return stop_; });
        }
    });
}
LifecyclePoller::~LifecyclePoller() {
    { std::lock_guard<std::mutex> lock(mutex_); stop_ = true; wake_.notify_all(); }
    worker_.join();
}
std::optional<std::pair<Lifecycle, Time>> LifecyclePoller::latest() {
    std::lock_guard<std::mutex> lock(mutex_); return latest_;
}
std::string LifecyclePoller::error() { std::lock_guard<std::mutex> lock(mutex_); return error_; }
}
