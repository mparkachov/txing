#include "agent/kvs.hpp"
#include <algorithm>
#include <cstring>
#include <sstream>
#include <stdexcept>

namespace txing::agent {
namespace {
template<std::size_t N> void copy(char (&target)[N], const std::string& value) {
    if (value.size() >= N) throw std::invalid_argument("KVS configuration value exceeds SDK limit");
    std::memcpy(target, value.c_str(), value.size() + 1);
}
class KvsTransport final : public Transport {
public:
    explicit KvsTransport(std::shared_ptr<Aws::Auth::AWSCredentialsProvider> p) : credentials_(std::move(p)) {}
    ~KvsTransport() override { stop(); if (worker_.joinable()) worker_.join(); }
    void start(const TransportConfig& c, TransportEvents e) override {
        if (worker_.joinable()) throw std::logic_error("KVS transport already started");
        if (c.channel.empty() || c.region.empty() || c.ca_path.empty() ||
            (c.media == Media::data && c.label.empty())) throw std::invalid_argument("incomplete KVS configuration");
        if (c.role != Role::viewer) throw std::invalid_argument("agent transport requires explicit viewer role");
        config_ = c; events_ = std::move(e); stopping_ = false; finished_ = false; state_ = Connection::connecting;
        try { worker_ = std::thread([this] { run(); }); }
        catch (...) { finished_ = true; state_ = Connection::failed; throw; }
    }
    void stop() noexcept override {
        stopping_ = true; wake_.notify_all();
        state_ = Connection::stopped;
    }
    bool finished() const override { return finished_; }
    Connection state() const override { return state_; }
    std::string error() const override {
        std::lock_guard<std::mutex> lock(mutex_); return error_.empty() ? progress_ : error_;
    }
    bool send(const Bytes& bytes, bool binary) override {
        std::lock_guard<std::mutex> lock(peer_mutex_);
        if (state_ != Connection::connected || !peer_ || bytes.size() > 4096) return false;
        const bool sent = peer_->send(bytes, binary);
        if (!sent) fail(STATUS_INVALID_OPERATION, "dataChannelSend");
        return sent;
    }
private:
    struct Message { SIGNALING_MESSAGE_TYPE type; std::string payload; bool incoming; };
    static KvsTransport& self(UINT64 p) { return *reinterpret_cast<KvsTransport*>(p); }
    void progress(const char* operation) {
        std::lock_guard<std::mutex> lock(mutex_); progress_ = operation;
    }
    void fail(STATUS status, const char* operation) noexcept {
        try {
            std::ostringstream detail; detail << operation << ": KVS status 0x" << std::hex << status;
            auto credential_error = credentials_.error();
            if (!credential_error.empty()) detail << "; " << credential_error;
            { std::lock_guard<std::mutex> lock(mutex_); error_ = detail.str(); }
        } catch (...) {}
        state_ = Connection::failed; wake_.notify_all();
    }
    void queue(Message message) noexcept {
        try {
            std::lock_guard<std::mutex> lock(mutex_);
            if (messages_.size() >= 256 || message.payload.size() > MAX_SIGNALING_MESSAGE_LEN) {
                error_ = "KVS signaling queue exceeded bounded capacity"; state_ = Connection::failed;
            } else messages_.push_back(std::move(message));
            wake_.notify_one();
        } catch (...) { state_ = Connection::failed; }
    }
    static STATUS signaling(UINT64 p, PReceivedSignalingMessage received) noexcept {
        auto& s = self(p);
        if (!received) return STATUS_NULL_ARG;
        const auto& message = received->signalingMessage;
        s.queue({message.messageType, std::string(message.payload, message.payloadLen), true});
        return STATUS_SUCCESS;
    }
    static STATUS signaling_error(UINT64 p, STATUS status, PCHAR, UINT32) noexcept {
        // SDK may include arbitrary remote payload in its message. Keep operation
        // and numeric status; never log credentials, tokens, SDP or TURN URLs.
        self(p).fail(status, "KVS signaling callback"); return STATUS_SUCCESS;
    }
    static STATUS signaling_state(UINT64 p, SIGNALING_CLIENT_STATE state) noexcept {
        // The SDK otherwise creates a missing channel. Native operation uses
        // existing resources only; veto before the SDK issues CreateChannel.
        if (state == SIGNALING_CLIENT_STATE_CREATE || state == SIGNALING_CLIENT_STATE_DELETE) {
            self(p).fail(STATUS_INVALID_OPERATION, "refusing signaling channel mutation");
            return STATUS_INVALID_OPERATION;
        }
        return STATUS_SUCCESS;
    }
    static void ice(UINT64 p, PCHAR candidate) noexcept {
        if (candidate) self(p).queue({SIGNALING_MESSAGE_TYPE_ICE_CANDIDATE, candidate, false});
    }
    void initialize() {
        PAwsCredentials available = nullptr;
        check_kvs(credentials_.getCredentialsFn(&credentials_, &available), "AWS credential provider");
        // Names, region and media/data role all come from the caller. This
        // adapter has no Thing type, MAVLink parser or lifecycle knowledge.
        ChannelInfo channel{}; channel.version = CHANNEL_INFO_CURRENT_VERSION;
        channel.pChannelName = const_cast<PCHAR>(config_.channel.c_str());
        channel.pRegion = const_cast<PCHAR>(config_.region.c_str());
        channel.pCertPath = const_cast<PCHAR>(config_.ca_path.c_str());
        channel.channelType = SIGNALING_CHANNEL_TYPE_SINGLE_MASTER;
        channel.channelRoleType = SIGNALING_CHANNEL_ROLE_TYPE_VIEWER;
        channel.cachingPolicy = SIGNALING_API_CALL_CACHE_TYPE_DESCRIBE_GETENDPOINT;
        channel.cachingPeriod = SIGNALING_API_CALL_CACHE_TTL_SENTINEL_VALUE;
        channel.retry = TRUE; channel.reconnect = TRUE; channel.asyncIceServerConfig = TRUE;
        SignalingClientInfo client{}; client.version = SIGNALING_CLIENT_INFO_CURRENT_VERSION;
        const auto identity = "agent-" + std::to_string(GETTIME());
        copy(client.clientId, identity); client.loggingLevel = LOG_LEVEL_WARN;
        client.signalingClientCreationMaxRetryAttempts = 1;
        SignalingClientCallbacks callbacks{}; callbacks.version = SIGNALING_CLIENT_CALLBACKS_CURRENT_VERSION;
        callbacks.customData = reinterpret_cast<UINT64>(this);
        callbacks.messageReceivedFn = signaling; callbacks.errorReportFn = signaling_error;
        callbacks.stateChangeFn = signaling_state;
        check_kvs(createSignalingClientSync(&client, &channel, &callbacks, &credentials_, &signaling_), "createSignalingClientSync");
        if (stopping_) return;
        check_kvs(signalingClientFetchSync(signaling_), "signalingClientFetchSync");
        if (stopping_) return;
        RtcConfiguration rtc{}; rtc.iceTransportPolicy = ICE_TRANSPORT_POLICY_ALL;
        const auto stun = "stun:stun.kinesisvideo." + config_.region + ".amazonaws.com:443";
        copy(rtc.iceServers[0].urls, stun);
        UINT32 count = 0, next = 1;
        check_kvs(signalingClientGetIceConfigInfoCount(signaling_, &count), "signalingClientGetIceConfigInfoCount");
        for (UINT32 i = 0; i < count && next < MAX_ICE_SERVERS_COUNT; ++i) {
            PIceConfigInfo info = nullptr;
            check_kvs(signalingClientGetIceConfigInfo(signaling_, i, &info), "signalingClientGetIceConfigInfo");
            if (!info) continue;
            for (UINT32 j = 0; j < info->uriCount && next < MAX_ICE_SERVERS_COUNT; ++j, ++next) {
                copy(rtc.iceServers[next].urls, info->uris[j]);
                copy(rtc.iceServers[next].username, info->userName);
                copy(rtc.iceServers[next].credential, info->password);
            }
        }
        peer_ = std::make_unique<Peer>(config_, rtc, events_, [this](std::string candidate) {
            queue({SIGNALING_MESSAGE_TYPE_ICE_CANDIDATE, std::move(candidate), false});
        }, [this](Connection state) {
            if (state == Connection::failed) fail(STATUS_INVALID_OPERATION, "WebRTC connection lost");
            else if (state_ != Connection::failed) state_ = state;
        });
        check_kvs(signalingClientConnectSync(signaling_), "signalingClientConnectSync");
        send_signaling(SIGNALING_MESSAGE_TYPE_OFFER, peer_->description(true));
        progress("SDP offer sent; awaiting SDP answer");
    }
    void send_signaling(SIGNALING_MESSAGE_TYPE type, const std::string& payload) {
        SignalingMessage message{}; message.version = SIGNALING_MESSAGE_CURRENT_VERSION;
        message.messageType = type; copy(message.peerClientId, "ProducerMaster");
        copy(message.payload, payload); message.payloadLen = payload.size();
        check_kvs(signalingClientSendMessageSync(signaling_, &message), "signalingClientSendMessageSync");
    }
    void process(const Message& m) {
        if (!m.incoming) { send_signaling(m.type, m.payload); return; }
        if (m.type == SIGNALING_MESSAGE_TYPE_ANSWER) {
            peer_->remote_description(m.payload);
            answered_ = true;
            progress("SDP answer applied; awaiting ICE/DTLS and media/data readiness");
            for (const auto& candidate : candidates_) add_candidate(candidate);
            candidates_.clear();
        } else if (m.type == SIGNALING_MESSAGE_TYPE_ICE_CANDIDATE) {
            if (answered_) add_candidate(m.payload);
            else if (candidates_.size() < 128) candidates_.push_back(m.payload);
            else throw std::runtime_error("too many pending remote ICE candidates");
        }
    }
    void add_candidate(const std::string& payload) {
        peer_->candidate(payload);
    }
    void run() noexcept {
        try {
            initialize();
            while (!stopping_ && state_ != Connection::failed) {
                std::unique_lock<std::mutex> lock(mutex_);
                wake_.wait_for(lock, std::chrono::milliseconds(100), [this] {
                    return stopping_ || state_ == Connection::failed || !messages_.empty();
                });
                std::deque<Message> messages; messages.swap(messages_); lock.unlock();
                for (const auto& message : messages) {
                    if (stopping_ || state_ == Connection::failed) break;
                    process(message);
                }
            }
        } catch (const std::exception& e) {
            std::lock_guard<std::mutex> lock(mutex_);
            error_ = e.what();
            const auto credential_error = credentials_.error();
            if (!credential_error.empty()) error_ += "; " + credential_error;
            state_ = Connection::failed;
        } catch (...) { state_ = Connection::failed; }
        // Stop SDK callbacks and join signaling before releasing callback data
        // or credentials. The process-owned KvsRuntime outlives both peers.
        if (IS_VALID_SIGNALING_CLIENT_HANDLE(signaling_)) {
            signalingClientDisconnectSync(signaling_); freeSignalingClient(&signaling_);
        }
        {
            std::lock_guard<std::mutex> lock(peer_mutex_);
            peer_.reset();
        }
        finished_ = true;
    }
    Credentials credentials_;
    TransportConfig config_;
    TransportEvents events_;
    std::atomic<Connection> state_{Connection::stopped};
    std::atomic<bool> stopping_{false};
    std::atomic<bool> finished_{true};
    mutable std::mutex mutex_;
    std::mutex peer_mutex_;
    std::condition_variable wake_;
    std::string error_, progress_;
    std::deque<Message> messages_;
    std::vector<std::string> candidates_;
    bool answered_ = false;
    SIGNALING_CLIENT_HANDLE signaling_ = INVALID_SIGNALING_CLIENT_HANDLE_VALUE;
    std::unique_ptr<Peer> peer_;
    std::thread worker_;
};
}
std::unique_ptr<Transport> make_kvs_transport(std::shared_ptr<Aws::Auth::AWSCredentialsProvider> p) {
    return std::make_unique<KvsTransport>(std::move(p));
}
}
