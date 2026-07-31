#ifndef TXING_BOARD_KVS_MASTER_KVS_SESSION_HPP
#define TXING_BOARD_KVS_MASTER_KVS_SESSION_HPP

#include "kvs_master/aws_env.hpp"
#include "kvs_master/config.hpp"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>

namespace txing::board::kvs_master {

class KvsSession {
  public:
    virtual ~KvsSession() = default;

    virtual void Start() = 0;
    virtual void PushH264AccessUnit(
        const std::uint8_t* data,
        std::size_t len,
        std::uint64_t presentation_ts_100ns,
        std::uint64_t duration_100ns,
        bool is_keyframe
    ) = 0;
    virtual void Stop() noexcept = 0;
    virtual std::optional<std::string> TakeFatalError() = 0;
};

std::unique_ptr<KvsSession> CreateKvsSession(const RuntimeConfig& config, const AwsCredentials& credentials);

}  // namespace txing::board::kvs_master

#endif
