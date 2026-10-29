#pragma once
#include "agent/core.hpp"
#include "agent/activation.hpp"
#include <aws/core/auth/AWSCredentialsProvider.h>
#include <aws/core/client/ClientConfiguration.h>
#include <aws/iot/IoTClient.h>
#include <aws/iot-data/IoTDataPlaneClient.h>
#include <stdexcept>

namespace txing::agent {
class ShadowNotFound : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};
class ThingNotFound : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};
Lifecycle parse_lifecycle(const std::string& json, const std::string& thing);
// A complete current projection and its IoT shadow version, for the
// controller's fail-closed activation bookkeeping.
ProjectionObservation parse_projection_observation(const std::string& json, const std::string& thing);
class AwsDevice {
public:
    AwsDevice(std::shared_ptr<Aws::Auth::AWSCredentialsProvider>, Aws::Client::ClientConfiguration);
    std::string registered_type(const std::string& thing);
    bool has_capability(const std::string& thing, const std::string& capability);
    // Include Things whose capability was removed, so existing assignments
    // remain discoverable for shutdown. Missing agent shadows are skipped.
    std::vector<std::string> registered_things();
    Lifecycle lifecycle(const std::string& thing);
    ProjectionObservation projection(const std::string& thing);
    std::string agent_shadow(const std::string& thing);
    // False is a version conflict: discard the snapshot and read again.
    bool update_agent_shadow(const std::string& thing, const std::string& conditional_patch);
private:
    void resolve_shadow_endpoint();
    std::string shadow(const std::string& thing, const char* name);
    Aws::IoT::IoTClient registry_;
    Aws::IoTDataPlane::IoTDataPlaneClient shadows_;
    bool shadow_endpoint_resolved_ = false;
};
// Network reads run outside the lifecycle/control tick. A hung/failed read cannot
// postpone the session's fifteen-second monotonic deadline.
class LifecyclePoller {
public:
    explicit LifecyclePoller(std::function<Lifecycle()>);
    ~LifecyclePoller();
    std::optional<std::pair<Lifecycle, Time>> latest();
    std::string error();
private:
    std::mutex mutex_;
    std::condition_variable wake_;
    std::optional<std::pair<Lifecycle, Time>> latest_;
    std::string error_;
    bool stop_ = false;
    std::thread worker_;
};
}
