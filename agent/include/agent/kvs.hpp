#pragma once
#include "agent/core.hpp"
#include <aws/core/auth/AWSCredentialsProvider.h>
extern "C" {
#include <com/amazonaws/kinesis/video/common/Include.h>
#include <com/amazonaws/kinesis/video/webrtcclient/Include.h>
}

namespace txing::agent {
void check_kvs(STATUS, const char* operation);
class KvsRuntime {
public:
    KvsRuntime();
    ~KvsRuntime();
    KvsRuntime(const KvsRuntime&) = delete;
    KvsRuntime& operator=(const KvsRuntime&) = delete;
};
// One adapter per signaling client. Follows the KVS provider ownership model:
// SDK requests fresh credentials before signing; borrowed result lives until
// the next refresh or adapter destruction, after signaling has been joined.
class Credentials final : public AwsCredentialProvider {
public:
    explicit Credentials(std::shared_ptr<Aws::Auth::AWSCredentialsProvider>);
    ~Credentials();
    std::string error() const;
private:
    static STATUS get(PAwsCredentialProvider, PAwsCredentials*) noexcept;
    std::shared_ptr<Aws::Auth::AWSCredentialsProvider> source_;
    PAwsCredentials current_ = nullptr;
    mutable std::mutex mutex_;
    std::string error_;
};
std::unique_ptr<Transport> make_kvs_transport(std::shared_ptr<Aws::Auth::AWSCredentialsProvider>);

// The production peer engine can also be connected to an in-process SDK peer
// for transport tests, without contacting AWS or substituting a fake WebRTC.
class Peer {
public:
    using Candidate = std::function<void(std::string)>;
    Peer(const TransportConfig&, const RtcConfiguration&, TransportEvents,
         Candidate, std::function<void(Connection)>);
    ~Peer();
    Peer(const Peer&) = delete;
    Peer& operator=(const Peer&) = delete;
    std::string description(bool offer);
    void remote_description(const std::string&);
    void candidate(const std::string&);
    bool send(const Bytes&, bool);
    bool send_video(const EncodedVideo&);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
