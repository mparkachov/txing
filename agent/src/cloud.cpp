#include "agent/cloud.hpp"
#include <aws/core/utils/json/JsonSerializer.h>
#include <aws/lambda-microvms/model/RunMicrovmRequest.h>
#include <aws/lambda-microvms/model/GetMicrovmRequest.h>
#include <aws/lambda-microvms/model/TerminateMicrovmRequest.h>
#include <aws/lambda-microvms/model/ListMicrovmsRequest.h>
#include <aws/lambda-microvms/model/CreateMicrovmAuthTokenRequest.h>
#include <aws/lambda-microvms/model/PortSpecification.h>
#include <aws/lambda-microvms/model/Logging.h>
#include <aws/lambda-microvms/model/CloudWatchLogging.h>
#include <algorithm>
#include <set>
#include <stdexcept>

namespace txing::agent {
namespace {
using Json = Aws::Utils::Json::JsonValue;
namespace vm = Aws::LambdaMicrovms::Model;
bool identifier(const std::string& value) {
    return !value.empty() && value.size() <= 128 &&
        value.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-:.") == std::string::npos;
}
std::string field(Aws::Utils::Json::JsonView value, const char* name) {
    if (!value.ValueExists(name) || !value.GetObject(name).IsString() || value.GetString(name).empty())
        throw std::runtime_error(std::string("invalid launch request field: ") + name);
    return value.GetString(name).c_str();
}
std::string state_name(vm::MicrovmState state) { return vm::MicrovmStateMapper::GetNameForMicrovmState(state).c_str(); }
template<class Error> std::runtime_error api_error(const char* operation, const Error& error) {
    return std::runtime_error(std::string("lambda-microvms:") + operation + ": " +
        error.GetExceptionName().c_str() + " HTTP " + std::to_string(static_cast<int>(error.GetResponseCode())));
}
vm::RunMicrovmRequest parse_request(const std::string& text, const std::string& expected_run_id) {
    if (text.empty() || text.size() > 2048 || !identifier(expected_run_id)) throw std::invalid_argument("invalid stored launch request");
    Json json(Aws::String(text.c_str()));
    auto value = json.View();
    if (!json.WasParseSuccessful() || !value.IsObject() || value.GetAllObjects().size() != 9)
        throw std::invalid_argument("invalid stored launch request");
    const auto token = field(value, "clientToken");
    if (token != expected_run_id) throw std::invalid_argument("launch token does not match reservation");
    if (field(value, "format") != "txing.agent.launch.v1") throw std::invalid_argument("unsupported launch request format");
    const auto region = field(value, "region");
    if (region != "eu-central-1") throw std::invalid_argument("invalid MicroVM region");
    if (!value.ValueExists("maximumDurationInSeconds") || !value.GetObject("maximumDurationInSeconds").IsIntegerType())
        throw std::invalid_argument("missing MicroVM duration");
    const auto duration = value.GetInt64("maximumDurationInSeconds");
    if (duration < 1 || duration > 3000) throw std::invalid_argument("invalid MicroVM duration");
    const auto image = field(value, "imageIdentifier"), version = field(value, "imageVersion");
    const auto role = field(value, "executionRoleArn"), log_group = field(value, "logGroup");
    const auto hook = field(value, "runHookPayload");
    Json hook_json(Aws::String(hook.c_str()));
    const auto hook_value = hook_json.View();
    if (!hook_json.WasParseSuccessful() || !hook_value.IsObject() || hook_value.GetAllObjects().size() != 5 ||
        field(hook_value, "runId") != token || field(hook_value, "region") != region ||
        !identifier(field(hook_value, "thingId")) || !identifier(field(hook_value, "activationId")))
        throw std::invalid_argument("invalid run hook assignment");
    const auto hook_deadline = field(hook_value, "deadline");
    if (hook_deadline.find_first_not_of("0123456789") != std::string::npos || hook_deadline.size() > 18)
        throw std::invalid_argument("invalid run hook deadline");
    // Managed connectors and absent idle policy are fixed by the approved
    // deployment; neither can be overridden by a stored shadow payload.
    const auto prefix = "arn:aws:lambda:" + region + ":aws:network-connector:aws-network-connector:";
    vm::RunMicrovmRequest request;
    request.SetClientToken(token.c_str()); request.SetImageIdentifier(image.c_str());
    request.SetImageVersion(version.c_str()); request.SetExecutionRoleArn(role.c_str());
    request.SetRunHookPayload(hook.c_str()); request.SetMaximumDurationInSeconds(static_cast<int>(duration));
    request.AddIngressNetworkConnectors((prefix + "ALL_INGRESS").c_str());
    request.AddEgressNetworkConnectors((prefix + "INTERNET_EGRESS").c_str());
    vm::CloudWatchLogging cloudwatch; cloudwatch.SetLogGroup(log_group.c_str());
    vm::Logging logging; logging.SetCloudWatch(std::move(cloudwatch)); request.SetLogging(std::move(logging));
    return request;
}
}

std::string make_cloud_request(const CloudConfig& config, const std::string& thing,
                               const std::string& run_id, const std::string& activation_id,
                               std::int64_t deadline, std::int64_t now) {
    if (config.region != "eu-central-1" || config.image.empty() || config.image_version.empty() ||
        config.execution_role.empty() || config.log_group.empty() || !identifier(thing) ||
        !identifier(run_id) || !identifier(activation_id) || now < 0 || deadline <= now)
        throw std::invalid_argument("invalid MicroVM launch configuration or expired activation");
    Json hook; hook.WithString("thingId", thing.c_str()).WithString("region", config.region.c_str())
        .WithString("runId", run_id.c_str()).WithString("activationId", activation_id.c_str())
        .WithString("deadline", std::to_string(deadline).c_str());
    Json request;
    request.WithString("clientToken", run_id.c_str()).WithString("region", config.region.c_str())
        .WithString("imageIdentifier", config.image.c_str()).WithString("imageVersion", config.image_version.c_str())
        .WithString("executionRoleArn", config.execution_role.c_str()).WithString("logGroup", config.log_group.c_str())
        .WithString("runHookPayload", hook.View().WriteCompact())
        .WithInt64("maximumDurationInSeconds", std::min<std::int64_t>(3000, deadline - now));
    // Include an explicit schema marker to reject accidental alternate inputs.
    request.WithString("format", "txing.agent.launch.v1");
    const std::string result = request.View().WriteCompact().c_str();
    parse_request(result, run_id);
    return result;
}

std::string saved_launch_image(const std::string& text, const std::string& run_id,
                               const std::string& thing, const std::string& activation_id) {
    if (!identifier(thing) || !identifier(activation_id)) throw std::invalid_argument("invalid saved assignment identity");
    const auto request = parse_request(text, run_id);
    Json hook(request.GetRunHookPayload());
    const auto view = hook.View();
    if (!hook.WasParseSuccessful() || field(view, "thingId") != thing || field(view, "activationId") != activation_id)
        throw std::invalid_argument("saved launch does not match assignment");
    const std::string image = request.GetImageIdentifier().c_str();
    const std::string prefix = "arn:aws:lambda:eu-central-1:";
    const std::string marker = ":microvm-image:";
    if (image.rfind(prefix, 0) != 0 || image.size() <= prefix.size() + 12 + marker.size() ||
        image.substr(prefix.size(), 12).find_first_not_of("0123456789") != std::string::npos ||
        image.compare(prefix.size() + 12, marker.size(), marker) != 0 ||
        image.substr(prefix.size() + 12 + marker.size()).find_first_not_of(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") != std::string::npos)
        throw std::invalid_argument("saved launch image is not a scoped Frankfurt image ARN");
    return image;
}

CloudMicrovms::CloudMicrovms(std::shared_ptr<Aws::Auth::AWSCredentialsProvider> credentials,
                             Aws::Client::ClientConfiguration config)
    : client_(credentials, config) {}
CloudRun CloudMicrovms::launch(const std::string& exact_request, const std::string& expected_run_id) {
    const auto result = client_.RunMicrovm(parse_request(exact_request, expected_run_id));
    if (!result.IsSuccess()) throw api_error("RunMicrovm", result.GetError());
    const auto& run = result.GetResult();
    return {run.GetMicrovmId().c_str(), state_name(run.GetState()), run.GetEndpoint().c_str()};
}
CloudRun CloudMicrovms::get(const std::string& id) {
    return describe(id).run;
}
CloudRunDetails CloudMicrovms::describe(const std::string& id) {
    vm::GetMicrovmRequest request; request.SetMicrovmIdentifier(id.c_str());
    const auto result = client_.GetMicrovm(request);
    if (!result.IsSuccess()) throw api_error("GetMicrovm", result.GetError());
    const auto& run = result.GetResult();
    return {{run.GetMicrovmId().c_str(), state_name(run.GetState()), run.GetEndpoint().c_str()}, run.GetImageArn().c_str()};
}
void CloudMicrovms::terminate(const std::string& id) {
    vm::TerminateMicrovmRequest request; request.SetMicrovmIdentifier(id.c_str());
    const auto result = client_.TerminateMicrovm(request);
    if (!result.IsSuccess()) throw api_error("TerminateMicrovm", result.GetError());
}
std::vector<CloudRun> CloudMicrovms::list(const std::string& image) {
    std::vector<CloudRun> runs;
    for_each_page(image, [&](const auto& page) { runs.insert(runs.end(), page.begin(), page.end()); });
    return runs;
}
void CloudMicrovms::for_each_page(const std::string& image,
                                  const std::function<void(const std::vector<CloudRun>&)>& visit) {
    if (image.empty()) throw std::invalid_argument("image identity required for MicroVM inventory");
    if (!visit) throw std::invalid_argument("inventory page visitor required");
    vm::ListMicrovmsRequest request; request.SetImageIdentifier(image.c_str());
    unsigned pages = 0;
    std::set<Aws::String> seen_tokens;
    do {
        if (++pages > 1000) throw std::runtime_error("lambda-microvms:ListMicrovms pagination limit exceeded");
        const auto result = client_.ListMicrovms(request);
        if (!result.IsSuccess()) throw api_error("ListMicrovms", result.GetError());
        std::vector<CloudRun> page;
        for (const auto& run : result.GetResult().GetItems())
            page.push_back({run.GetMicrovmId().c_str(), state_name(run.GetState()), {}});
        const auto next = result.GetResult().GetNextToken();
        // A page can contain VMs that need stopping even when its next token
        // is cyclic. Deliver it before failing the incomplete inventory.
        visit(page);
        if (!next.empty() && !seen_tokens.insert(next).second)
            throw std::runtime_error("lambda-microvms:ListMicrovms pagination did not advance");
        request.SetNextToken(next);
    } while (!request.GetNextToken().empty());
}
std::string CloudMicrovms::token(const std::string& id, unsigned port, unsigned minutes) {
    if (id.empty() || !port || port > 65535 || !minutes || minutes > 60)
        throw std::invalid_argument("invalid MicroVM token scope or duration");
    vm::CreateMicrovmAuthTokenRequest request;
    request.SetMicrovmIdentifier(id.c_str()); request.SetExpirationInMinutes(static_cast<int>(minutes));
    vm::PortSpecification spec; spec.SetPort(static_cast<int>(port)); request.AddAllowedPorts(std::move(spec));
    const auto result = client_.CreateMicrovmAuthToken(request);
    if (!result.IsSuccess()) throw api_error("CreateMicrovmAuthToken", result.GetError());
    const auto& tokens = result.GetResult().GetAuthToken();
    const auto found = tokens.find("X-aws-proxy-auth");
    if (found == tokens.end() || found->second.empty()) throw std::runtime_error("MicroVM token response missing authentication header");
    if (found->second.size() > 8000 || found->second.find_first_not_of(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-") != Aws::String::npos)
        throw std::runtime_error("MicroVM token response has invalid framing");
    return found->second.c_str();
}
}
