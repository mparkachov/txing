#ifndef TXING_BOARD_KVS_MASTER_PEER_NEGOTIATION_HPP
#define TXING_BOARD_KVS_MASTER_PEER_NEGOTIATION_HPP

#include <utility>

namespace txing::board::kvs_master {

// The KVS SDK starts gathering in setLocalDescription and consumes the remote
// description in createAnswer. Defer creating a non-trickle answer until the
// gathered candidates can be included in it.
template <typename Status, typename CreateAnswer, typename SetLocalDescription, typename SendAnswer, typename IsFailure>
Status PrepareMasterAnswer(
    bool remote_can_trickle,
    CreateAnswer&& create_answer,
    SetLocalDescription&& set_local_description,
    SendAnswer&& send_answer,
    IsFailure&& is_failure
) {
    if (!remote_can_trickle) return std::forward<SetLocalDescription>(set_local_description)();

    Status status = std::forward<CreateAnswer>(create_answer)();
    if (std::forward<IsFailure>(is_failure)(status)) {
        return status;
    }

    status = std::forward<SetLocalDescription>(set_local_description)();
    if (std::forward<IsFailure>(is_failure)(status)) {
        return status;
    }

    return std::forward<SendAnswer>(send_answer)();
}

}  // namespace txing::board::kvs_master

#endif
