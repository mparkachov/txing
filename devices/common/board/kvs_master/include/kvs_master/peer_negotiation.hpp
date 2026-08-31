#ifndef TXING_BOARD_KVS_MASTER_PEER_NEGOTIATION_HPP
#define TXING_BOARD_KVS_MASTER_PEER_NEGOTIATION_HPP

#include <utility>

namespace txing::board::kvs_master {

// The WebRTC answer must be created before it is installed as the local
// description. Non-trickle peers receive that completed answer only after ICE
// gathering reports its terminal candidate; trickle peers receive it now and
// receive candidates independently.
template <typename Status, typename CreateAnswer, typename SetLocalDescription, typename SendAnswer, typename IsFailure>
Status PrepareMasterAnswer(
    bool remote_can_trickle,
    CreateAnswer&& create_answer,
    SetLocalDescription&& set_local_description,
    SendAnswer&& send_answer,
    IsFailure&& is_failure
) {
    Status status = std::forward<CreateAnswer>(create_answer)();
    if (std::forward<IsFailure>(is_failure)(status)) {
        return status;
    }

    status = std::forward<SetLocalDescription>(set_local_description)();
    if (std::forward<IsFailure>(is_failure)(status) || !remote_can_trickle) {
        return status;
    }

    return std::forward<SendAnswer>(send_answer)();
}

}  // namespace txing::board::kvs_master

#endif
