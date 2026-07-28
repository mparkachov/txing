#ifndef TXING_BOARD_KVS_MASTER_VERSION_HPP
#define TXING_BOARD_KVS_MASTER_VERSION_HPP

#include <string_view>

namespace txing::board::kvs_master {

// Each device type keeps its own release stream, so the version is injected at
// build time from release/versions/<device>. This fallback only ever reaches a
// developer build that skipped the injection.
#ifndef TXING_BOARD_KVS_MASTER_VERSION
#define TXING_BOARD_KVS_MASTER_VERSION "0.0.0-dev"
#endif

inline constexpr std::string_view kTxingBoardKvsMasterVersion =
    TXING_BOARD_KVS_MASTER_VERSION;

}  // namespace txing::board::kvs_master

#endif
