#ifndef TXING_BOARD_KVS_MASTER_AWS_ENV_HPP
#define TXING_BOARD_KVS_MASTER_AWS_ENV_HPP

#include "kvs_master/config.hpp"

#include <filesystem>
#include <functional>
#include <optional>
#include <string>

namespace txing::board::kvs_master {

using FileReader = std::function<std::string(const std::filesystem::path&)>;

struct AwsCredentials {
    std::string access_key_id;
    std::string secret_access_key;
    std::optional<std::string> session_token;
};

AwsCredentials ResolveAwsCredentials(const EnvLookup& lookup_env, const FileReader& read_file);
AwsCredentials ResolveAwsCredentials();
FileReader FilesystemReader();

}  // namespace txing::board::kvs_master

#endif
