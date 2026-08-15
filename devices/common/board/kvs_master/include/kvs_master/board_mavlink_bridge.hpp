#ifndef TXING_BOARD_KVS_MASTER_BOARD_MAVLINK_BRIDGE_HPP
#define TXING_BOARD_KVS_MASTER_BOARD_MAVLINK_BRIDGE_HPP

#include "kvs_master/aws_env.hpp"
#include "kvs_master/board_video_bridge.hpp"

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace txing::board::kvs_master {

struct MavlinkControlChannelConfig {
    std::string region;
    std::string channel_name;
    std::string client_id;
    std::string data_channel_label;
    bool data_channel_ordered = true;
    bool data_channel_reliable = true;
    BridgeCredentials credentials;
};

using MavlinkTelemetryReceiver = std::function<void(std::vector<std::uint8_t>)>;

class BoardMavlinkPeer {
  public:
    virtual ~BoardMavlinkPeer() = default;

    virtual std::string HandleControl(const std::string& payload) = 0;
    virtual void SendFrame(const std::vector<std::uint8_t>& frame, std::uint64_t epoch) = 0;
    virtual void Close(const std::string& reason) noexcept = 0;
};

class BoardMavlinkBridgeClient {
  public:
    virtual ~BoardMavlinkBridgeClient() = default;

    virtual MavlinkControlChannelConfig GetControlChannelConfig(
        const std::string& worker_name,
        const std::string& worker_version
    ) = 0;
    virtual BridgeCredentials RefreshControlChannelCredentials() = 0;
    virtual void ReportControlChannelState(bool ready, const std::string& error) = 0;
    virtual std::unique_ptr<BoardMavlinkPeer> OpenPeer(
        const std::string& peer_id,
        MavlinkTelemetryReceiver telemetry_receiver
    ) = 0;
};

std::unique_ptr<BoardMavlinkBridgeClient> CreateBoardMavlinkBridgeClient(const std::string& socket_path);

}  // namespace txing::board::kvs_master

#endif
