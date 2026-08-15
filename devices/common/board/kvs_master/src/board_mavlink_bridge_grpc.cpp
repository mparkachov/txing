#include "kvs_master/board_mavlink_bridge.hpp"

#include "txing/board/mavlink_bridge/v1/mavlink_bridge.grpc.pb.h"

#include <grpcpp/create_channel.h>
#include <grpcpp/security/credentials.h>

#include <atomic>
#include <chrono>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <utility>

namespace txing::board::kvs_master {
namespace {

namespace pb = ::txing::board::mavlink_bridge::v1;

std::chrono::system_clock::time_point TimestampToTimePoint(
    const google::protobuf::Timestamp& timestamp
) {
    return std::chrono::system_clock::time_point{
        std::chrono::duration_cast<std::chrono::system_clock::duration>(
            std::chrono::seconds(timestamp.seconds()) + std::chrono::nanoseconds(timestamp.nanos())
        )
    };
}

BridgeCredentials CredentialsFromProto(const pb::KvsCredentials& credentials) {
    if (!credentials.has_expires_at()) {
        throw std::runtime_error("MAVLink bridge returned credentials without expires_at");
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
    throw std::runtime_error(std::string(operation) + " failed: " + status.error_message());
}

class GrpcBoardMavlinkPeer final : public BoardMavlinkPeer {
  public:
    GrpcBoardMavlinkPeer(
        pb::BoardMavlinkBridge::Stub* stub,
        std::string session_id,
        MavlinkTelemetryReceiver telemetry_receiver
    )
        : stub_(stub), session_id_(std::move(session_id)), telemetry_receiver_(std::move(telemetry_receiver)) {
        if (stub_ == nullptr || session_id_.empty()) {
            throw std::runtime_error("MAVLink bridge peer is not initialized");
        }
        stream_ = stub_->ExchangeFrames(&stream_context_);
        if (stream_ == nullptr) {
            throw std::runtime_error("failed to open MAVLink bridge frame exchange");
        }
        pb::PeerFrame bind;
        bind.set_session_id(session_id_);
        if (!stream_->Write(bind)) {
            throw std::runtime_error("failed to bind MAVLink bridge frame exchange");
        }
        reader_ = std::thread(&GrpcBoardMavlinkPeer::ReadTelemetry, this);
    }

    ~GrpcBoardMavlinkPeer() override {
        Close("MAVLink KVS peer destroyed");
    }

    std::string HandleControl(const std::string& payload) override {
        pb::ControlMessageRequest request;
        request.set_session_id(session_id_);
        request.set_json(payload);
        pb::ControlMessageResponse response;
        grpc::ClientContext context;
        context.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(7));
        ThrowIfNotOk(stub_->HandleControlMessage(&context, request, &response), "HandleControlMessage");
        return response.json();
    }

    void SendFrame(const std::vector<std::uint8_t>& frame, std::uint64_t epoch) override {
        if (frame.empty() || epoch == 0) {
            throw std::runtime_error("MAVLink frame requires a non-empty frame and active epoch");
        }
        std::lock_guard<std::mutex> lock(write_lock_);
        if (closed_.load()) {
            throw std::runtime_error("MAVLink bridge frame exchange is closed");
        }
        pb::PeerFrame request;
        request.set_session_id(session_id_);
        request.set_epoch(epoch);
        request.set_frame(frame.data(), frame.size());
        if (!stream_->Write(request)) {
            throw std::runtime_error("failed to send MAVLink bridge frame");
        }
    }

    void Close(const std::string& reason) noexcept override {
        bool expected = false;
        if (!closed_.compare_exchange_strong(expected, true)) {
            return;
        }
        stream_context_.TryCancel();
        {
            std::lock_guard<std::mutex> lock(write_lock_);
            if (stream_ != nullptr) {
                stream_->WritesDone();
            }
        }
        if (reader_.joinable()) {
            reader_.join();
        }
        if (stub_ == nullptr) {
            return;
        }
        try {
            pb::ClosePeerRequest request;
            request.set_session_id(session_id_);
            request.set_reason(reason);
            pb::Ack response;
            grpc::ClientContext context;
            ThrowIfNotOk(stub_->ClosePeer(&context, request, &response), "ClosePeer");
        } catch (...) {
            // Peer teardown is best effort; daemon ownership still expires the
            // lease if this local worker disappears abruptly.
        }
    }

  private:
    void ReadTelemetry() noexcept {
        pb::PeerFrame response;
        while (!closed_.load() && stream_ != nullptr && stream_->Read(&response)) {
            if (response.session_id() != session_id_ || response.frame().empty()) {
                continue;
            }
            try {
                telemetry_receiver_(std::vector<std::uint8_t>(response.frame().begin(), response.frame().end()));
            } catch (...) {
                // A data-channel callback must never terminate the bridge
                // reader; its peer close path handles any later cleanup.
            }
            response.Clear();
        }
    }

    pb::BoardMavlinkBridge::Stub* stub_ = nullptr;
    std::string session_id_;
    MavlinkTelemetryReceiver telemetry_receiver_;
    grpc::ClientContext stream_context_;
    std::unique_ptr<grpc::ClientReaderWriter<pb::PeerFrame, pb::PeerFrame>> stream_;
    std::mutex write_lock_;
    std::thread reader_;
    std::atomic_bool closed_{false};
};

class GrpcBoardMavlinkBridgeClient final : public BoardMavlinkBridgeClient {
  public:
    explicit GrpcBoardMavlinkBridgeClient(const std::string& socket_path)
        : stub_(pb::BoardMavlinkBridge::NewStub(grpc::CreateChannel(
              "unix://" + socket_path,
              grpc::InsecureChannelCredentials()
          ))) {}

    MavlinkControlChannelConfig GetControlChannelConfig(
        const std::string& worker_name,
        const std::string& worker_version
    ) override {
        pb::WorkerHello request;
        request.set_protocol_version("1");
        request.set_worker_name(worker_name);
        request.set_worker_version(worker_version);
        pb::ControlChannelConfig response;
        grpc::ClientContext context;
        ThrowIfNotOk(stub_->GetControlChannelConfig(&context, request, &response), "GetControlChannelConfig");
        if (!response.has_credentials()) {
            throw std::runtime_error("MAVLink bridge returned control config without credentials");
        }
        MavlinkControlChannelConfig result;
        result.region = response.region();
        result.channel_name = response.channel_name();
        result.client_id = response.client_id();
        result.data_channel_label = response.data_channel_label();
        result.data_channel_ordered = response.data_channel_ordered();
        result.data_channel_reliable = response.data_channel_reliable();
        result.credentials = CredentialsFromProto(response.credentials());
        return result;
    }

    BridgeCredentials RefreshControlChannelCredentials() override {
        pb::RefreshCredentialsRequest request;
        pb::KvsCredentials response;
        grpc::ClientContext context;
        ThrowIfNotOk(
            stub_->RefreshControlChannelCredentials(&context, request, &response),
            "RefreshControlChannelCredentials"
        );
        return CredentialsFromProto(response);
    }

    void ReportControlChannelState(bool ready, const std::string& error) override {
        pb::ControlChannelState request;
        request.set_ready(ready);
        request.set_error(error);
        pb::Ack response;
        grpc::ClientContext context;
        ThrowIfNotOk(stub_->ReportControlChannelState(&context, request, &response), "ReportControlChannelState");
    }

    std::unique_ptr<BoardMavlinkPeer> OpenPeer(
        const std::string& peer_id,
        MavlinkTelemetryReceiver telemetry_receiver
    ) override {
        pb::OpenPeerRequest request;
        request.set_peer_id(peer_id);
        pb::OpenPeerResponse response;
        grpc::ClientContext context;
        ThrowIfNotOk(stub_->OpenPeer(&context, request, &response), "OpenPeer");
        if (response.session_id().empty()) {
            throw std::runtime_error("MAVLink bridge returned an empty peer session ID");
        }
        return std::make_unique<GrpcBoardMavlinkPeer>(stub_.get(), response.session_id(), std::move(telemetry_receiver));
    }

  private:
    std::unique_ptr<pb::BoardMavlinkBridge::Stub> stub_;
};

}  // namespace

std::unique_ptr<BoardMavlinkBridgeClient> CreateBoardMavlinkBridgeClient(const std::string& socket_path) {
    return std::make_unique<GrpcBoardMavlinkBridgeClient>(socket_path);
}

}  // namespace txing::board::kvs_master
