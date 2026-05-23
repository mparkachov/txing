#include "kvs_master/board_video_bridge.hpp"

#include "txing/unit/board_video/v1/board_video.grpc.pb.h"

#include <grpcpp/create_channel.h>
#include <grpcpp/security/credentials.h>

#include <stdexcept>

namespace txing::board::kvs_master {
namespace {

namespace pb = ::txing::unit::board_video::v1;

std::chrono::system_clock::time_point TimestampToTimePoint(
    const google::protobuf::Timestamp& timestamp
) {
    return std::chrono::system_clock::time_point{
        std::chrono::seconds(timestamp.seconds()) + std::chrono::nanoseconds(timestamp.nanos())
    };
}

BridgeCredentials CredentialsFromProto(const pb::KvsCredentials& credentials) {
    if (!credentials.has_expires_at()) {
        throw std::runtime_error("board video bridge returned credentials without expires_at");
    }
    BridgeCredentials result;
    result.credentials.access_key_id = credentials.access_key_id();
    result.credentials.secret_access_key = credentials.secret_access_key();
    if (!credentials.session_token().empty()) {
        result.credentials.session_token = credentials.session_token();
    }
    result.expires_at = TimestampToTimePoint(credentials.expires_at());
    return result;
}

void ThrowIfNotOk(const grpc::Status& status, const char* operation) {
    if (status.ok()) {
        return;
    }
    throw std::runtime_error(
        std::string(operation) + " failed: " + status.error_message()
    );
}

pb::VideoState_State ToProtoVideoState(BridgeVideoState state) {
    switch (state) {
        case BridgeVideoState::kStarting:
            return pb::VideoState_State_STARTING;
        case BridgeVideoState::kReady:
            return pb::VideoState_State_READY;
        case BridgeVideoState::kError:
            return pb::VideoState_State_ERROR;
    }
    return pb::VideoState_State_STATE_UNSPECIFIED;
}

class GrpcBoardVideoBridgeClient final : public BoardVideoBridgeClient {
  public:
    explicit GrpcBoardVideoBridgeClient(const std::string& socket_path)
        : stub_(pb::BoardVideoBridge::NewStub(grpc::CreateChannel(
              "unix://" + socket_path,
              grpc::InsecureChannelCredentials()
          ))) {}

    BridgeWorkerConfig GetWorkerConfig(
        const std::string& worker_name,
        const std::string& worker_version
    ) override {
        pb::WorkerHello request;
        request.set_protocol_version("1");
        request.set_worker_name(worker_name);
        request.set_worker_version(worker_version);

        pb::WorkerConfig response;
        grpc::ClientContext context;
        ThrowIfNotOk(
            stub_->GetWorkerConfig(&context, request, &response),
            "GetWorkerConfig"
        );
        if (!response.has_credentials()) {
            throw std::runtime_error("board video bridge returned worker config without credentials");
        }

        BridgeWorkerConfig result;
        result.runtime_config.region = response.region();
        result.runtime_config.channel_name = response.channel_name();
        result.runtime_config.client_id = response.client_id();
        result.runtime_config.mcp_data_channel_label = response.mcp_data_channel_label();
        result.runtime_config.prefer_ipv6 = response.prefer_ipv6();
        result.runtime_config.disable_ipv4_turn = response.disable_ipv4_turn();
        result.credentials = CredentialsFromProto(response.credentials());
        result.mcp_data_channel_label = response.mcp_data_channel_label();
        result.mcp_response_timeout = std::chrono::milliseconds(response.mcp_response_timeout_ms());
        return result;
    }

    BridgeCredentials RefreshCredentials() override {
        pb::RefreshCredentialsRequest request;
        pb::KvsCredentials response;
        grpc::ClientContext context;
        ThrowIfNotOk(
            stub_->RefreshCredentials(&context, request, &response),
            "RefreshCredentials"
        );
        return CredentialsFromProto(response);
    }

    void ReportVideoState(
        BridgeVideoState state,
        std::uint32_t viewer_count,
        const std::string& error
    ) override {
        pb::VideoState request;
        request.set_state(ToProtoVideoState(state));
        request.set_viewer_count(viewer_count);
        request.set_error(error);
        pb::Ack response;
        grpc::ClientContext context;
        ThrowIfNotOk(
            stub_->ReportVideoState(&context, request, &response),
            "ReportVideoState"
        );
    }

    void OpenMcpSession(
        const std::string& mcp_session_id,
        const std::string& transport,
        const std::string& peer_id
    ) override {
        pb::OpenMcpSessionRequest request;
        request.set_mcp_session_id(mcp_session_id);
        request.set_transport(transport);
        request.set_peer_id(peer_id);
        pb::Ack response;
        grpc::ClientContext context;
        ThrowIfNotOk(
            stub_->OpenMcpSession(&context, request, &response),
            "OpenMcpSession"
        );
    }

    std::optional<std::string> HandleMcp(
        const std::string& mcp_session_id,
        const std::string& payload
    ) override {
        pb::McpRequest request;
        request.set_mcp_session_id(mcp_session_id);
        request.set_payload(payload);
        pb::McpResponse response;
        grpc::ClientContext context;
        context.set_deadline(
            std::chrono::system_clock::now() + std::chrono::milliseconds(7000)
        );
        ThrowIfNotOk(stub_->HandleMcp(&context, request, &response), "HandleMcp");
        if (!response.has_payload()) {
            return std::nullopt;
        }
        return response.payload();
    }

    void CloseMcpSession(const std::string& mcp_session_id, const std::string& reason) override {
        pb::CloseMcpSessionRequest request;
        request.set_mcp_session_id(mcp_session_id);
        request.set_reason(reason);
        pb::Ack response;
        grpc::ClientContext context;
        ThrowIfNotOk(
            stub_->CloseMcpSession(&context, request, &response),
            "CloseMcpSession"
        );
    }

  private:
    std::unique_ptr<pb::BoardVideoBridge::Stub> stub_;
};

}  // namespace

std::unique_ptr<BoardVideoBridgeClient> CreateBoardVideoBridgeClient(const std::string& socket_path) {
    return std::make_unique<GrpcBoardVideoBridgeClient>(socket_path);
}

}  // namespace txing::board::kvs_master
