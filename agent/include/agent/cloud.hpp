#pragma once

#include <aws/core/auth/AWSCredentialsProvider.h>
#include <aws/core/client/ClientConfiguration.h>
#include <aws/lambda-microvms/LambdaMicrovmsClient.h>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace txing::agent {
struct CloudConfig {
    std::string image, image_version, execution_role, log_group, region;
};
struct CloudRun {
    std::string id, state, endpoint;
};
struct CloudRunDetails {
    CloudRun run;
    std::string image;
};

// This non-secret JSON request is stored before launching and is reused
// unchanged after an interrupted or ambiguous RunMicrovm call.
std::string make_cloud_request(const CloudConfig&, const std::string& thing,
                               const std::string& run_id, const std::string& activation_id,
                               std::int64_t deadline, std::int64_t now);
// Validate the persisted request and its assignment before using its image
// as evidence for a known-run shutdown.
std::string saved_launch_image(const std::string& request, const std::string& run_id,
                               const std::string& thing, const std::string& activation_id);
class CloudMicrovms {
public:
    CloudMicrovms(std::shared_ptr<Aws::Auth::AWSCredentialsProvider>, Aws::Client::ClientConfiguration);
    CloudRun launch(const std::string& exact_request, const std::string& expected_run_id);
    CloudRun get(const std::string& id);
    CloudRunDetails describe(const std::string& id);
    void terminate(const std::string& id);
    std::vector<CloudRun> list(const std::string& image);
    void for_each_page(const std::string& image, const std::function<void(const std::vector<CloudRun>&)>& visit);
    // The caller keeps this value in memory only; never log or persist it.
    std::string token(const std::string& id, unsigned port, unsigned minutes);
private:
    Aws::LambdaMicrovms::LambdaMicrovmsClient client_;
};
}
