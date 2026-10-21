#pragma once
#include "agent/core.hpp"
#include <aws/core/auth/AWSCredentialsProvider.h>
#include <aws/core/client/ClientConfiguration.h>
#include <aws/iot/IoTClient.h>
#include <aws/iot-data/IoTDataPlaneClient.h>

namespace txing::agent {
Lifecycle parse_lifecycle(const std::string& json, const std::string& thing);
class AwsDevice {
public:
    AwsDevice(std::shared_ptr<Aws::Auth::AWSCredentialsProvider>, Aws::Client::ClientConfiguration);
    std::string registered_type(const std::string& thing);
    Lifecycle lifecycle(const std::string& thing);
private:
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
