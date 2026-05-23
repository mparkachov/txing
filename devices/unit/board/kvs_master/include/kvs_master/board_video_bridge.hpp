#ifndef TXING_BOARD_KVS_MASTER_BOARD_VIDEO_BRIDGE_HPP
#define TXING_BOARD_KVS_MASTER_BOARD_VIDEO_BRIDGE_HPP

#include "kvs_master/aws_env.hpp"
#include "kvs_master/config.hpp"

#include <chrono>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>

namespace txing::board::kvs_master {

enum class BridgeVideoState {
    kStarting,
    kReady,
    kError,
};

struct BridgeCredentials {
    AwsCredentials credentials;
    std::chrono::system_clock::time_point expires_at;
};

struct BridgeWorkerConfig {
    RuntimeConfig runtime_config;
    BridgeCredentials credentials;
    std::string mcp_data_channel_label;
    std::chrono::milliseconds mcp_response_timeout{7000};
};

class BoardVideoBridgeClient {
  public:
    virtual ~BoardVideoBridgeClient() = default;

    virtual BridgeWorkerConfig GetWorkerConfig(
        const std::string& worker_name,
        const std::string& worker_version
    ) = 0;
    virtual BridgeCredentials RefreshCredentials() = 0;
    virtual void ReportVideoState(
        BridgeVideoState state,
        std::uint32_t viewer_count,
        const std::string& error
    ) = 0;
    virtual void OpenMcpSession(
        const std::string& mcp_session_id,
        const std::string& transport,
        const std::string& peer_id
    ) = 0;
    virtual std::optional<std::string> HandleMcp(
        const std::string& mcp_session_id,
        const std::string& payload
    ) = 0;
    virtual void CloseMcpSession(const std::string& mcp_session_id, const std::string& reason) = 0;
};

std::unique_ptr<BoardVideoBridgeClient> CreateBoardVideoBridgeClient(const std::string& socket_path);

}  // namespace txing::board::kvs_master

#endif
