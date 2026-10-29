#include "agent/aws.hpp"
#include <aws/core/utils/json/JsonSerializer.h>
#include <aws/iot/model/DescribeThingRequest.h>
#include <aws/iot/model/DescribeEndpointRequest.h>
#include <aws/iot/model/ListThingsRequest.h>
#include <aws/iot-data/model/GetThingShadowRequest.h>
#include <aws/iot-data/model/UpdateThingShadowRequest.h>
#include <sstream>
#include <set>
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
    if (redcon <= 2) {
        if (!view.ValueExists("capability") || !view.GetObject("capability").IsObject() ||
            !view.GetObject("capability").ValueExists("agent") ||
            !view.GetObject("capability").GetObject("agent").IsBool())
            throw std::runtime_error("sparkplug shadow: missing agent capability availability");
        if (!view.GetObject("capability").GetBool("agent")) return {false, 4};
    }
    return {true, static_cast<int>(redcon)};
}

ProjectionObservation parse_projection_observation(const std::string& json, const std::string& thing) {
    Aws::Utils::Json::JsonValue document(Aws::String(json.c_str()));
    if (!document.WasParseSuccessful()) throw std::runtime_error("sparkplug shadow: invalid JSON");
    const auto root = document.View();
    if (!root.ValueExists("version") || !root.GetObject("version").IsIntegerType() || root.GetInt64("version") <= 0)
        throw std::runtime_error("sparkplug shadow: missing version");
    auto view = root;
    for (const auto* field : {"state", "reported", "payload"}) {
        if (!view.ValueExists(field) || !view.GetObject(field).IsObject())
            throw std::runtime_error("sparkplug shadow: incomplete projection");
        view = view.GetObject(field);
    }
    if (!view.ValueExists("metrics") || !view.GetObject("metrics").IsObject() ||
        !view.ValueExists("timestamp") || !view.GetObject("timestamp").IsIntegerType() || view.GetInt64("timestamp") <= 0)
        throw std::runtime_error("sparkplug shadow: incomplete projection or missing source timestamp");
    const auto lifecycle = parse_lifecycle(json, thing);
    return {static_cast<std::uint64_t>(root.GetInt64("version")),
            lifecycle.born && lifecycle.redcon <= 2, view.GetInt64("timestamp")};
}

AwsDevice::AwsDevice(std::shared_ptr<Aws::Auth::AWSCredentialsProvider> credentials,
                     Aws::Client::ClientConfiguration config)
    : registry_(credentials, config), shadows_(credentials, config) {}

namespace {
Aws::IoT::Model::DescribeThingResult describe_thing(Aws::IoT::IoTClient& registry, const std::string& thing) {
    Aws::IoT::Model::DescribeThingRequest request;
    request.SetThingName(thing.c_str());
    auto result = registry.DescribeThing(request);
    if (!result.IsSuccess()) {
        const auto message = "iot:DescribeThing: " + std::string(result.GetError().GetExceptionName().c_str()) + " HTTP " +
            std::to_string(static_cast<int>(result.GetError().GetResponseCode()));
        if (static_cast<int>(result.GetError().GetResponseCode()) == 404) throw ThingNotFound(message);
        throw std::runtime_error(message);
    }
    return result.GetResult();
}
}
std::string AwsDevice::registered_type(const std::string& thing) {
    return describe_thing(registry_, thing).GetThingTypeName().c_str();
}
bool AwsDevice::has_capability(const std::string& thing, const std::string& capability) {
    const auto result = describe_thing(registry_, thing);
    const auto& attributes = result.GetAttributes();
    const auto entry = attributes.find("capabilities");
    if (entry == attributes.end()) return false;
    std::istringstream values(entry->second.c_str());
    std::set<std::string> declared;
    std::string value;
    while (std::getline(values, value, ',')) {
        if (value.empty() || value.find_first_of(" \t\r\n") != std::string::npos || !declared.insert(value).second)
            throw std::runtime_error("iot:DescribeThing: malformed capabilities");
    }
    if (declared.empty() || entry->second.back() == ',' || !declared.count("sparkplug"))
        throw std::runtime_error("iot:DescribeThing: malformed capabilities");
    return declared.count(capability) != 0;
}
std::vector<std::string> AwsDevice::registered_things() {
    Aws::IoT::Model::ListThingsRequest request;
    std::vector<std::string> things;
    unsigned pages = 0;
    std::set<Aws::String> seen_tokens;
    do {
        if (++pages > 1000) throw std::runtime_error("iot:ListThings: pagination limit exceeded");
        const auto result = registry_.ListThings(request);
        if (!result.IsSuccess()) throw std::runtime_error("iot:ListThings: " +
            std::string(result.GetError().GetExceptionName().c_str()) + " HTTP " +
            std::to_string(static_cast<int>(result.GetError().GetResponseCode())));
        for (const auto& thing : result.GetResult().GetThings()) things.emplace_back(thing.GetThingName().c_str());
        const auto next = result.GetResult().GetNextToken();
        if (!next.empty() && !seen_tokens.insert(next).second)
            throw std::runtime_error("iot:ListThings: pagination did not advance");
        request.SetNextToken(next);
    } while (!request.GetNextToken().empty());
    return things;
}
void AwsDevice::resolve_shadow_endpoint() {
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
}
std::string AwsDevice::shadow(const std::string& thing, const char* name) {
    resolve_shadow_endpoint();
    Aws::IoTDataPlane::Model::GetThingShadowRequest request;
    request.SetThingName(thing.c_str()); request.SetShadowName(name);
    auto result = shadows_.GetThingShadow(request);
    if (!result.IsSuccess()) {
        const auto message = std::string("iot:GetThingShadow(") + name + "): " +
            std::string(result.GetError().GetExceptionName().c_str()) + " HTTP " +
            std::to_string(static_cast<int>(result.GetError().GetResponseCode()));
        if (static_cast<int>(result.GetError().GetResponseCode()) == 404) throw ShadowNotFound(message);
        throw std::runtime_error(message);
    }
    std::ostringstream payload; payload << result.GetResult().GetPayload().rdbuf();
    return payload.str();
}
Lifecycle AwsDevice::lifecycle(const std::string& thing) { return parse_lifecycle(shadow(thing, "sparkplug"), thing); }
ProjectionObservation AwsDevice::projection(const std::string& thing) {
    return parse_projection_observation(shadow(thing, "sparkplug"), thing);
}
std::string AwsDevice::agent_shadow(const std::string& thing) { return shadow(thing, "agent"); }
bool AwsDevice::update_agent_shadow(const std::string& thing, const std::string& patch) {
    Aws::Utils::Json::JsonValue document(Aws::String(patch.c_str()));
    auto root = document.View();
    if (!document.WasParseSuccessful() || !root.IsObject() || !root.ValueExists("version") ||
        !root.GetObject("version").IsIntegerType() || root.GetInt64("version") < 0)
        throw std::invalid_argument("agent shadow update requires an expected version");
    resolve_shadow_endpoint();
    Aws::IoTDataPlane::Model::UpdateThingShadowRequest request;
    request.SetThingName(thing.c_str()); request.SetShadowName("agent");
    auto body = Aws::MakeShared<Aws::StringStream>("agent-shadow-update");
    *body << patch;
    request.SetBody(body);
    const auto result = shadows_.UpdateThingShadow(request);
    if (result.IsSuccess()) return true;
    if (static_cast<int>(result.GetError().GetResponseCode()) == 409) return false;
    throw std::runtime_error("iot:UpdateThingShadow(agent): " +
        std::string(result.GetError().GetExceptionName().c_str()) + " HTTP " +
        std::to_string(static_cast<int>(result.GetError().GetResponseCode())));
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
