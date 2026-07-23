#ifndef TXING_CYBERBRICK_KVS_MASTER_VERSION_HPP
#define TXING_CYBERBRICK_KVS_MASTER_VERSION_HPP

#include <string_view>

namespace txing::board::kvs_master {

#ifndef TXING_CYBERBRICK_KVS_MASTER_VERSION
#define TXING_CYBERBRICK_KVS_MASTER_VERSION "0.15.7"
#endif

inline constexpr std::string_view kTxingCyberbrickKvsMasterVersion =
    TXING_CYBERBRICK_KVS_MASTER_VERSION;

}  // namespace txing::board::kvs_master

#endif
