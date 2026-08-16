#ifndef TXING_BOARD_KVS_MASTER_VERSION_HPP
#define TXING_BOARD_KVS_MASTER_VERSION_HPP

#include <string_view>

namespace txing::board::kvs_master {

// The board-wide KVS release version is injected from
// release/versions/kvs-master. This fallback only ever reaches a developer
// build that skipped the injection.
#ifndef TXING_BOARD_KVS_MASTER_VERSION
#define TXING_BOARD_KVS_MASTER_VERSION "0.0.0-dev"
#endif

inline constexpr std::string_view kTxingBoardKvsMasterVersion =
    TXING_BOARD_KVS_MASTER_VERSION;

}  // namespace txing::board::kvs_master

#endif
