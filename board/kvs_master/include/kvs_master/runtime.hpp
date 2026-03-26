#ifndef TXING_BOARD_KVS_MASTER_RUNTIME_HPP
#define TXING_BOARD_KVS_MASTER_RUNTIME_HPP

#include "kvs_master/aws_env.hpp"
#include "kvs_master/config.hpp"
#include "kvs_master/kvs_session.hpp"
#include "kvs_master/video_capturer.hpp"

#include <functional>
#include <memory>

namespace txing::board::kvs_master {

struct RuntimeHooks {
    std::function<AwsCredentials()> resolve_aws_credentials;
    std::function<std::unique_ptr<KvsSession>(const RuntimeConfig&, const AwsCredentials&)> create_kvs_session;
    std::function<std::unique_ptr<VideoCapturer>()> create_video_capturer;
};

RuntimeHooks DefaultRuntimeHooks();
void Run(const RuntimeConfig& config);
void Run(const RuntimeConfig& config, const RuntimeHooks& hooks);

}  // namespace txing::board::kvs_master

#endif
