#include "kvs_master/board_video_bridge.hpp"

#include <stdexcept>

namespace txing::board::kvs_master {

std::unique_ptr<BoardVideoBridgeClient> CreateBoardVideoBridgeClient(const std::string&) {
    throw std::runtime_error(
        "txing-board-kvs-master was built without gRPC bridge support; rebuild with TXING_KVS_GRPC_BRIDGE=ON"
    );
}

}  // namespace txing::board::kvs_master
