#include "kvs_master/kvs_session.hpp"

#include "kvs_master/markers.hpp"

#include <array>
#include <atomic>
#include <cinttypes>
#include <chrono>
#include <condition_variable>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <filesystem>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

extern "C" {
#include <com/amazonaws/kinesis/video/common/Include.h>
#include <com/amazonaws/kinesis/video/webrtcclient/Include.h>
}

namespace txing::board::kvs_master {
namespace {

constexpr UINT32 kMaxConcurrentStreamingSessions = 10;
constexpr UINT64 kCleanupWaitPeriod100ns = 5 * HUNDREDS_OF_NANOS_IN_A_SECOND;
constexpr UINT64 kPendingMessageCleanupDuration100ns = 20 * HUNDREDS_OF_NANOS_IN_A_SECOND;
constexpr DOUBLE kVideoRollingBufferDurationSec = 3.0;
constexpr CHAR kControlPlaneUriEnvVar[] = "CONTROL_PLANE_URI";
constexpr CHAR kKvsCaCertPathEnvVar[] = "AWS_KVS_CACERT_PATH";
constexpr CHAR kIceTransportPolicyEnvVar[] = "KVS_ICE_TRANSPORT_POLICY";
constexpr CHAR kSslCertFileEnvVar[] = "SSL_CERT_FILE";
constexpr CHAR kVideoStreamId[] = "txingBoardVideo";
constexpr CHAR kVideoTrackId[] = "txingBoardVideoTrack";

template <std::size_t N>
void CopyCString(CHAR (&destination)[N], const std::string& value, const char* field_name) {
    if (value.size() >= N) {
        throw std::runtime_error(std::string(field_name) + " exceeds AWS SDK buffer limits");
    }
    std::memcpy(destination, value.c_str(), value.size() + 1);
}

std::string FormatStatus(STATUS status) {
    char buffer[16];
    std::snprintf(buffer, sizeof(buffer), "0x%08x", static_cast<unsigned>(status));
    return std::string(buffer);
}

void ThrowIfFailed(STATUS status, const char* context) {
    if (STATUS_FAILED(status)) {
        throw std::runtime_error(std::string(context) + " failed with status " + FormatStatus(status));
    }
}

bool EnvEnabled(const char* name) {
    const char* value = std::getenv(name);
    if (value == nullptr) {
        return false;
    }

    const std::string normalized(value);
    return normalized == "1" || normalized == "true" || normalized == "TRUE" || normalized == "yes" ||
        normalized == "YES" || normalized == "on" || normalized == "ON";
}

std::optional<std::string> ExistingFile(const char* path) {
    if (path == nullptr || *path == '\0') {
        return std::nullopt;
    }

    std::error_code error;
    const auto file_path = std::filesystem::path(path);
    if (std::filesystem::exists(file_path, error) && !error) {
        return file_path.string();
    }
    return std::nullopt;
}

std::optional<std::string> ExistingPath(const std::filesystem::path& path) {
    std::error_code error;
    if (std::filesystem::exists(path, error) && !error) {
        return path.string();
    }
    return std::nullopt;
}

std::optional<std::string> DiscoverCaCertPath() {
    if (const auto from_kvs_env = ExistingFile(std::getenv(kKvsCaCertPathEnvVar)); from_kvs_env) {
        return from_kvs_env;
    }

    if (const auto from_ssl_env = ExistingFile(std::getenv(kSslCertFileEnvVar)); from_ssl_env) {
        return from_ssl_env;
    }

    std::error_code error;
    const auto cwd = std::filesystem::current_path(error);
    if (!error) {
        static constexpr const char* kRelativeCandidatePaths[] = {
            "aws-kvs-webrtc-sdk/certs/cert.pem",
            "board/aws-kvs-webrtc-sdk/certs/cert.pem",
        };

        for (const auto* candidate : kRelativeCandidatePaths) {
            if (const auto discovered = ExistingPath(cwd / candidate); discovered) {
                return discovered;
            }
        }
    }

    return std::nullopt;
}

bool IsChinaRegion(const std::string& region) {
    return region.rfind("cn-", 0) == 0;
}

std::string BuildKinesisVideoStunUrl(const std::string& region) {
    const bool use_dual_stack = EnvEnabled(USE_DUAL_STACK_ENDPOINTS_ENV_VAR);
    const char* postfix = nullptr;
    if (use_dual_stack) {
        postfix = IsChinaRegion(region) ? KINESIS_VIDEO_DUALSTACK_STUN_URL_POSTFIX_CN
                                        : KINESIS_VIDEO_DUALSTACK_STUN_URL_POSTFIX;
    } else {
        postfix = IsChinaRegion(region) ? KINESIS_VIDEO_STUN_URL_POSTFIX_CN : KINESIS_VIDEO_STUN_URL_POSTFIX;
    }

    char buffer[MAX_ICE_CONFIG_URI_LEN + 1];
    std::snprintf(buffer, sizeof(buffer), KINESIS_VIDEO_STUN_URL, region.c_str(), postfix);
    return std::string(buffer);
}

bool IsSignalingCallFailure(STATUS status) {
    return status == STATUS_SIGNALING_GET_TOKEN_CALL_FAILED || status == STATUS_SIGNALING_DESCRIBE_CALL_FAILED ||
        status == STATUS_SIGNALING_CREATE_CALL_FAILED || status == STATUS_SIGNALING_GET_ENDPOINT_CALL_FAILED ||
        status == STATUS_SIGNALING_GET_ICE_CONFIG_CALL_FAILED || status == STATUS_SIGNALING_CONNECT_CALL_FAILED ||
        status == STATUS_SIGNALING_DESCRIBE_MEDIA_CALL_FAILED;
}

class RealKvsSession;

struct PendingIceMessage {
    UINT64 created_time_100ns = 0;
    ReceivedSignalingMessage message{};
};

struct StreamingSession {
    StreamingSession(RealKvsSession* owner_input, std::string peer_id_input)
        : owner(owner_input), peer_id(std::move(peer_id_input)) {}

    RealKvsSession* owner = nullptr;
    std::string peer_id;
    PRtcPeerConnection peer_connection = nullptr;
    PRtcRtpTransceiver video_transceiver = nullptr;
    RtcSessionDescriptionInit answer_description{};
    std::atomic_bool terminate_requested{false};
    std::atomic_bool first_frame{true};
    bool connected = false;
    bool remote_can_trickle = false;
    UINT64 frame_index = 0;
    UINT64 correlation_id_postfix = 0;
};

class RealKvsSession final : public KvsSession {
  public:
    RealKvsSession(const RuntimeConfig& config, const AwsCredentials& credentials)
        : region_(config.region),
          channel_name_(config.channel_name),
          client_id_(config.client_id),
          access_key_id_(credentials.access_key_id),
          secret_access_key_(credentials.secret_access_key),
          session_token_(credentials.session_token),
          video_bitrate_bps_(config.camera.bitrate) {
        try {
            CreateCredentialProvider();
            InitializeStaticConfiguration();
            ThrowIfFailed(initKvsWebRtc(), "initKvsWebRtc");
            sdk_initialized_ = true;
        } catch (...) {
            CleanupConstruction();
            throw;
        }
    }

    ~RealKvsSession() override {
        Stop();
        CleanupConstruction();
    }

    void Start() override {
        if (started_) {
            return;
        }

        ThrowIfFailed(CreateSignalingClient(), "create signaling client");
        try {
            stopping_ = false;
            started_ = true;
            cleanup_thread_ = std::thread(&RealKvsSession::CleanupLoop, this);
        } catch (...) {
            started_ = false;
            stopping_ = true;
            DisconnectAndFreeSignalingClient();
            throw;
        }
    }

    void PushH264AccessUnit(
        const std::uint8_t* data,
        std::size_t len,
        std::uint64_t presentation_ts_100ns,
        std::uint64_t duration_100ns,
        bool is_keyframe
    ) override {
        if (data == nullptr || len == 0) {
            throw std::runtime_error("KVS session is not initialized");
        }
        if (len > MAX_UINT32) {
            throw std::runtime_error("H.264 access unit exceeds AWS frame size limits");
        }

        std::vector<std::shared_ptr<StreamingSession>> sessions;
        {
            std::lock_guard<std::mutex> lock(state_lock_);
            sessions.reserve(sessions_by_peer_.size());
            for (const auto& [peer_id, session] : sessions_by_peer_) {
                UNUSED_PARAM(peer_id);
                if (session != nullptr && session->video_transceiver != nullptr && !session->terminate_requested.load()) {
                    sessions.push_back(session);
                }
            }
        }

        if (sessions.empty()) {
            return;
        }

        Frame frame{};
        frame.version = FRAME_CURRENT_VERSION;
        frame.trackId = 1;
        frame.duration = duration_100ns;
        frame.decodingTs = presentation_ts_100ns;
        frame.presentationTs = presentation_ts_100ns;
        frame.size = static_cast<UINT32>(len);
        frame.frameData = const_cast<PBYTE>(data);
        frame.flags = is_keyframe ? FRAME_FLAG_KEY_FRAME : FRAME_FLAG_NONE;

        STATUS first_failure = STATUS_SUCCESS;
        bool wrote_frame = false;
        bool srtp_pending = false;

        for (const auto& session : sessions) {
            frame.index = static_cast<UINT32>(++session->frame_index);
            const STATUS status = writeFrame(session->video_transceiver, &frame);
            if (status == STATUS_SUCCESS) {
                wrote_frame = true;
                session->first_frame.store(false);
            } else if (status == STATUS_SRTP_NOT_READY_YET) {
                srtp_pending = true;
            } else if (first_failure == STATUS_SUCCESS) {
                first_failure = status;
            }
        }

        if (wrote_frame || srtp_pending) {
            return;
        }

        if (STATUS_FAILED(first_failure)) {
            ReportError("writeFrame failed (status=%s)", FormatStatus(first_failure).c_str());
            throw std::runtime_error("txing_kvs_push_h264_au failed with status " + FormatStatus(first_failure));
        }
    }

    void Stop() noexcept override {
        {
            std::lock_guard<std::mutex> lock(state_lock_);
            stopping_ = true;
            started_ = false;
        }
        wake_condition_.notify_all();

        DisconnectAndFreeSignalingClient();

        if (cleanup_thread_.joinable()) {
            cleanup_thread_.join();
        }

        std::vector<std::shared_ptr<StreamingSession>> sessions_to_destroy;
        {
            std::lock_guard<std::mutex> lock(state_lock_);
            for (auto& [peer_id, session] : sessions_by_peer_) {
                UNUSED_PARAM(peer_id);
                sessions_to_destroy.push_back(std::move(session));
            }
            sessions_by_peer_.clear();
            pending_ice_by_peer_.clear();
            recreate_signaling_client_ = false;
        }

        for (auto& session : sessions_to_destroy) {
            DestroySession(session);
        }
    }

    std::optional<std::string> TakeFatalError() override {
        std::lock_guard<std::mutex> lock(error_lock_);
        auto error = fatal_error_;
        fatal_error_.reset();
        return error;
    }

  private:
    void CleanupConstruction() noexcept {
        if (credential_provider_ != nullptr) {
            freeStaticCredentialProvider(&credential_provider_);
            credential_provider_ = nullptr;
        }
        if (sdk_initialized_) {
            deinitKvsWebRtc();
            sdk_initialized_ = false;
        }
    }

    void CreateCredentialProvider() {
        ThrowIfFailed(
            createStaticCredentialProvider(
                const_cast<PCHAR>(access_key_id_.c_str()),
                0,
                const_cast<PCHAR>(secret_access_key_.c_str()),
                0,
                session_token_ && !session_token_->empty() ? const_cast<PCHAR>(session_token_->c_str()) : nullptr,
                0,
                MAX_UINT64,
                &credential_provider_
            ),
            "createStaticCredentialProvider"
        );
    }

    void InitializeStaticConfiguration() {
        channel_info_.version = CHANNEL_INFO_CURRENT_VERSION;
        channel_info_.pChannelName = const_cast<PCHAR>(channel_name_.c_str());
        channel_info_.pRegion = const_cast<PCHAR>(region_.c_str());
        channel_info_.channelType = SIGNALING_CHANNEL_TYPE_SINGLE_MASTER;
        channel_info_.channelRoleType = SIGNALING_CHANNEL_ROLE_TYPE_MASTER;
        channel_info_.cachingPolicy = SIGNALING_API_CALL_CACHE_TYPE_FILE;
        channel_info_.cachingPeriod = SIGNALING_API_CALL_CACHE_TTL_SENTINEL_VALUE;
        channel_info_.asyncIceServerConfig = TRUE;
        channel_info_.retry = TRUE;
        channel_info_.reconnect = TRUE;
        channel_info_.messageTtl = 0;

        if (const char* control_plane_url = std::getenv(kControlPlaneUriEnvVar);
            control_plane_url != nullptr && *control_plane_url != '\0') {
            control_plane_url_ = control_plane_url;
            channel_info_.pControlPlaneUrl = const_cast<PCHAR>(control_plane_url_->c_str());
        }

        if (const auto ca_cert_path = DiscoverCaCertPath(); ca_cert_path) {
            ca_cert_path_ = *ca_cert_path;
            channel_info_.pCertPath = const_cast<PCHAR>(ca_cert_path_->c_str());
        }

        client_info_.version = SIGNALING_CLIENT_INFO_CURRENT_VERSION;
        CopyCString(client_info_.clientId, client_id_, "client_id");
        client_info_.loggingLevel = LOG_LEVEL_WARN;
        client_info_.cacheFilePath = nullptr;
        client_info_.signalingClientCreationMaxRetryAttempts = CREATE_SIGNALING_CLIENT_RETRY_ATTEMPTS_SENTINEL_VALUE;

        signaling_client_callbacks_.version = SIGNALING_CLIENT_CALLBACKS_CURRENT_VERSION;
        signaling_client_callbacks_.customData = reinterpret_cast<UINT64>(this);
        signaling_client_callbacks_.messageReceivedFn = SignalingMessageReceived;
        signaling_client_callbacks_.errorReportFn = SignalingClientError;
        signaling_client_callbacks_.stateChangeFn = SignalingStateChanged;
    }

    STATUS CreateSignalingClient() {
        std::lock_guard<std::mutex> lock(signaling_client_lock_);
        DisconnectAndFreeSignalingClientLocked();

        STATUS status = createSignalingClientSync(
            &client_info_,
            &channel_info_,
            &signaling_client_callbacks_,
            credential_provider_,
            &signaling_client_handle_
        );
        if (STATUS_FAILED(status)) {
            return status;
        }

        status = signalingClientFetchSync(signaling_client_handle_);
        if (STATUS_FAILED(status)) {
            freeSignalingClient(&signaling_client_handle_);
            return status;
        }

        status = signalingClientConnectSync(signaling_client_handle_);
        if (STATUS_FAILED(status)) {
            freeSignalingClient(&signaling_client_handle_);
            return status;
        }

        return STATUS_SUCCESS;
    }

    void DisconnectAndFreeSignalingClient() noexcept {
        std::lock_guard<std::mutex> lock(signaling_client_lock_);
        DisconnectAndFreeSignalingClientLocked();
    }

    void DisconnectAndFreeSignalingClientLocked() noexcept {
        if (IS_VALID_SIGNALING_CLIENT_HANDLE(signaling_client_handle_)) {
            UNUSED_PARAM(signalingClientDisconnectSync(signaling_client_handle_));
            UNUSED_PARAM(freeSignalingClient(&signaling_client_handle_));
            signaling_client_handle_ = INVALID_SIGNALING_CLIENT_HANDLE_VALUE;
        }
    }

    STATUS EnsureSignalingConnected() {
        std::lock_guard<std::mutex> lock(signaling_client_lock_);
        if (!IS_VALID_SIGNALING_CLIENT_HANDLE(signaling_client_handle_)) {
            return STATUS_INVALID_OPERATION;
        }

        SIGNALING_CLIENT_STATE current_state = SIGNALING_CLIENT_STATE_UNKNOWN;
        STATUS status = signalingClientGetCurrentState(signaling_client_handle_, &current_state);
        if (STATUS_FAILED(status)) {
            return status;
        }
        if (current_state == SIGNALING_CLIENT_STATE_READY) {
            return signalingClientConnectSync(signaling_client_handle_);
        }
        return STATUS_SUCCESS;
    }

    STATUS RefreshOrRecreateSignalingClient() {
        bool needs_create = false;
        {
            std::lock_guard<std::mutex> lock(signaling_client_lock_);
            if (!IS_VALID_SIGNALING_CLIENT_HANDLE(signaling_client_handle_)) {
                needs_create = true;
            } else {
                STATUS status = signalingClientFetchSync(signaling_client_handle_);
                if (STATUS_SUCCEEDED(status)) {
                    return STATUS_SUCCESS;
                }

                if (!IsSignalingCallFailure(status)) {
                    return status;
                }

                DisconnectAndFreeSignalingClientLocked();
                needs_create = true;
            }
        }

        return needs_create ? CreateSignalingClient() : STATUS_SUCCESS;
    }

    STATUS SendSignalingMessage(SignalingMessage* message) {
        if (message == nullptr) {
            return STATUS_NULL_ARG;
        }

        std::lock_guard<std::mutex> lock(signaling_client_lock_);
        if (!IS_VALID_SIGNALING_CLIENT_HANDLE(signaling_client_handle_)) {
            return STATUS_INVALID_OPERATION;
        }
        return signalingClientSendMessageSync(signaling_client_handle_, message);
    }

    STATUS BuildPeerConnectionConfiguration(RtcConfiguration* configuration) {
        if (configuration == nullptr) {
            return STATUS_NULL_ARG;
        }

        std::memset(configuration, 0, sizeof(RtcConfiguration));
        configuration->iceTransportPolicy = ICE_TRANSPORT_POLICY_ALL;

        if (const char* policy = std::getenv(kIceTransportPolicyEnvVar);
            policy != nullptr && std::strcmp(policy, "relay") == 0) {
            configuration->iceTransportPolicy = ICE_TRANSPORT_POLICY_RELAY;
        }

        const auto stun_url = BuildKinesisVideoStunUrl(region_);
        CopyCString(configuration->iceServers[0].urls, stun_url, "iceServers[0].urls");

        UINT32 ice_config_count = 0;
        {
            std::lock_guard<std::mutex> lock(signaling_client_lock_);
            if (!IS_VALID_SIGNALING_CLIENT_HANDLE(signaling_client_handle_)) {
                return STATUS_INVALID_OPERATION;
            }

            STATUS status = signalingClientGetIceConfigInfoCount(signaling_client_handle_, &ice_config_count);
            if (STATUS_FAILED(status)) {
                return status;
            }

            const UINT32 max_turn_servers = 1;
            UINT32 next_server_index = 1;
            for (UINT32 ice_index = 0;
                 ice_index < max_turn_servers && ice_index < ice_config_count && next_server_index < MAX_ICE_SERVERS_COUNT;
                 ++ice_index) {
                PIceConfigInfo ice_config = nullptr;
                status = signalingClientGetIceConfigInfo(signaling_client_handle_, ice_index, &ice_config);
                if (STATUS_FAILED(status)) {
                    return status;
                }
                if (ice_config == nullptr) {
                    continue;
                }

                for (UINT32 uri_index = 0;
                     uri_index < ice_config->uriCount && next_server_index < MAX_ICE_SERVERS_COUNT;
                     ++uri_index, ++next_server_index) {
                    std::snprintf(
                        configuration->iceServers[next_server_index].urls,
                        sizeof(configuration->iceServers[next_server_index].urls),
                        "%s",
                        ice_config->uris[uri_index]
                    );
                    std::snprintf(
                        configuration->iceServers[next_server_index].username,
                        sizeof(configuration->iceServers[next_server_index].username),
                        "%s",
                        ice_config->userName
                    );
                    std::snprintf(
                        configuration->iceServers[next_server_index].credential,
                        sizeof(configuration->iceServers[next_server_index].credential),
                        "%s",
                        ice_config->password
                    );
                }
            }
        }

        return STATUS_SUCCESS;
    }

    STATUS AddSendOnlyVideoTransceiver(StreamingSession* session) {
        if (session == nullptr || session->peer_connection == nullptr) {
            return STATUS_NULL_ARG;
        }

        RtcRtpTransceiverInit transceiver_init{};
        RtcMediaStreamTrack video_track{};

        video_track.kind = MEDIA_STREAM_TRACK_KIND_VIDEO;
        video_track.codec = RTC_CODEC_H264_PROFILE_42E01F_LEVEL_ASYMMETRY_ALLOWED_PACKETIZATION_MODE;
        CopyCString(video_track.streamId, kVideoStreamId, "video_track.streamId");
        CopyCString(video_track.trackId, kVideoTrackId, "video_track.trackId");
        transceiver_init.direction = RTC_RTP_TRANSCEIVER_DIRECTION_SENDONLY;

        STATUS status = addTransceiver(
            session->peer_connection,
            &video_track,
            &transceiver_init,
            &session->video_transceiver
        );
        if (STATUS_FAILED(status)) {
            return status;
        }

        return configureTransceiverRollingBuffer(
            session->video_transceiver,
            &video_track,
            kVideoRollingBufferDurationSec,
            video_bitrate_bps_
        );
    }

    STATUS CreateStreamingSession(const std::string& peer_id, std::shared_ptr<StreamingSession>* session_out) {
        if (session_out == nullptr) {
            return STATUS_NULL_ARG;
        }

        auto session = std::make_shared<StreamingSession>(this, peer_id);
        RtcConfiguration configuration{};
        STATUS status = BuildPeerConnectionConfiguration(&configuration);
        if (STATUS_FAILED(status)) {
            return status;
        }

        status = createPeerConnection(&configuration, &session->peer_connection);
        if (STATUS_FAILED(status)) {
            return status;
        }

        status = peerConnectionOnIceCandidate(
            session->peer_connection,
            reinterpret_cast<UINT64>(session.get()),
            OnIceCandidate
        );
        if (STATUS_FAILED(status)) {
            DestroySession(session);
            return status;
        }

        status = peerConnectionOnConnectionStateChange(
            session->peer_connection,
            reinterpret_cast<UINT64>(session.get()),
            OnConnectionStateChange
        );
        if (STATUS_FAILED(status)) {
            DestroySession(session);
            return status;
        }

        status = addSupportedCodec(
            session->peer_connection,
            RTC_CODEC_H264_PROFILE_42E01F_LEVEL_ASYMMETRY_ALLOWED_PACKETIZATION_MODE
        );
        if (STATUS_FAILED(status)) {
            DestroySession(session);
            return status;
        }

        status = AddSendOnlyVideoTransceiver(session.get());
        if (STATUS_FAILED(status)) {
            DestroySession(session);
            return status;
        }

        *session_out = std::move(session);
        return STATUS_SUCCESS;
    }

    STATUS HandleOffer(StreamingSession* session, PSignalingMessage signaling_message) {
        if (session == nullptr || signaling_message == nullptr) {
            return STATUS_NULL_ARG;
        }

        RtcSessionDescriptionInit offer_description{};
        std::memset(&session->answer_description, 0, sizeof(RtcSessionDescriptionInit));

        STATUS status = deserializeSessionDescriptionInit(
            signaling_message->payload,
            signaling_message->payloadLen,
            &offer_description
        );
        if (STATUS_FAILED(status)) {
            return status;
        }

        status = setRemoteDescription(session->peer_connection, &offer_description);
        if (STATUS_FAILED(status)) {
            return status;
        }

        const NullableBool can_trickle = canTrickleIceCandidates(session->peer_connection);
        if (NULLABLE_CHECK_EMPTY(can_trickle)) {
            return STATUS_INTERNAL_ERROR;
        }
        session->remote_can_trickle = can_trickle.value;

        status = setLocalDescription(session->peer_connection, &session->answer_description);
        if (STATUS_FAILED(status)) {
            return status;
        }

        if (session->remote_can_trickle) {
            status = createAnswer(session->peer_connection, &session->answer_description);
            if (STATUS_FAILED(status)) {
                return status;
            }
            return SendAnswer(session);
        }

        return STATUS_SUCCESS;
    }

    STATUS HandleAnswer(StreamingSession* session, PSignalingMessage signaling_message) {
        if (session == nullptr || signaling_message == nullptr) {
            return STATUS_NULL_ARG;
        }

        RtcSessionDescriptionInit answer_description{};
        STATUS status = deserializeSessionDescriptionInit(
            signaling_message->payload,
            signaling_message->payloadLen,
            &answer_description
        );
        if (STATUS_FAILED(status)) {
            return status;
        }

        return setRemoteDescription(session->peer_connection, &answer_description);
    }

    STATUS HandleRemoteCandidate(StreamingSession* session, PSignalingMessage signaling_message) {
        if (session == nullptr || signaling_message == nullptr) {
            return STATUS_NULL_ARG;
        }

        RtcIceCandidateInit ice_candidate{};
        STATUS status = deserializeRtcIceCandidateInit(
            signaling_message->payload,
            signaling_message->payloadLen,
            &ice_candidate
        );
        if (STATUS_FAILED(status)) {
            return status;
        }

        return addIceCandidate(session->peer_connection, ice_candidate.candidate);
    }

    STATUS SendAnswer(StreamingSession* session) {
        if (session == nullptr) {
            return STATUS_NULL_ARG;
        }

        SignalingMessage message{};
        UINT32 payload_length = MAX_SIGNALING_MESSAGE_LEN;
        STATUS status = serializeSessionDescriptionInit(&session->answer_description, message.payload, &payload_length);
        if (STATUS_FAILED(status)) {
            return status;
        }

        message.version = SIGNALING_MESSAGE_CURRENT_VERSION;
        message.messageType = SIGNALING_MESSAGE_TYPE_ANSWER;
        CopyCString(message.peerClientId, session->peer_id, "answer.peerClientId");
        message.payloadLen = static_cast<UINT32>(std::strlen(message.payload));
        std::snprintf(
            message.correlationId,
            sizeof(message.correlationId),
            "%" PRIu64 "_%" PRIu64,
            GETTIME(),
            ++session->correlation_id_postfix
        );
        return SendSignalingMessage(&message);
    }

    STATUS SendIceCandidate(StreamingSession* session, const char* candidate_json) {
        if (session == nullptr || candidate_json == nullptr) {
            return STATUS_NULL_ARG;
        }

        SignalingMessage message{};
        message.version = SIGNALING_MESSAGE_CURRENT_VERSION;
        message.messageType = SIGNALING_MESSAGE_TYPE_ICE_CANDIDATE;
        CopyCString(message.peerClientId, session->peer_id, "iceCandidate.peerClientId");
        std::snprintf(message.payload, sizeof(message.payload), "%s", candidate_json);
        message.payloadLen = static_cast<UINT32>(std::strlen(message.payload));
        message.correlationId[0] = '\0';
        return SendSignalingMessage(&message);
    }

    STATUS SubmitPendingIceCandidates(
        StreamingSession* session,
        const std::deque<PendingIceMessage>& pending_messages
    ) {
        if (session == nullptr) {
            return STATUS_NULL_ARG;
        }

        for (const auto& pending_message : pending_messages) {
            if (pending_message.message.signalingMessage.messageType == SIGNALING_MESSAGE_TYPE_ICE_CANDIDATE) {
                STATUS status = HandleRemoteCandidate(
                    session,
                    const_cast<PSignalingMessage>(&pending_message.message.signalingMessage)
                );
                if (STATUS_FAILED(status)) {
                    return status;
                }
            }
        }

        return STATUS_SUCCESS;
    }

    STATUS HandleSignalingMessage(PReceivedSignalingMessage received_message) {
        if (received_message == nullptr) {
            return STATUS_NULL_ARG;
        }

        const std::string peer_id(received_message->signalingMessage.peerClientId);
        if (peer_id.empty()) {
            return STATUS_INVALID_ARG;
        }

        switch (received_message->signalingMessage.messageType) {
            case SIGNALING_MESSAGE_TYPE_OFFER: {
                {
                    std::lock_guard<std::mutex> lock(state_lock_);
                    if (sessions_by_peer_.find(peer_id) != sessions_by_peer_.end()) {
                        return STATUS_INVALID_OPERATION;
                    }
                    if (sessions_by_peer_.size() >= kMaxConcurrentStreamingSessions) {
                        pending_ice_by_peer_.erase(peer_id);
                        return STATUS_SUCCESS;
                    }
                }

                std::shared_ptr<StreamingSession> session;
                STATUS status = CreateStreamingSession(peer_id, &session);
                if (STATUS_FAILED(status)) {
                    return status;
                }

                status = HandleOffer(session.get(), &received_message->signalingMessage);
                if (STATUS_FAILED(status)) {
                    DestroySession(session);
                    return status;
                }

                std::deque<PendingIceMessage> pending_messages;
                bool destroy_session = false;
                STATUS post_insert_status = STATUS_SUCCESS;
                {
                    std::lock_guard<std::mutex> lock(state_lock_);
                    if (sessions_by_peer_.find(peer_id) != sessions_by_peer_.end()) {
                        destroy_session = true;
                        post_insert_status = STATUS_INVALID_OPERATION;
                    } else if (sessions_by_peer_.size() >= kMaxConcurrentStreamingSessions) {
                        pending_ice_by_peer_.erase(peer_id);
                        destroy_session = true;
                        post_insert_status = STATUS_SUCCESS;
                    } else {
                        auto pending_iterator = pending_ice_by_peer_.find(peer_id);
                        if (pending_iterator != pending_ice_by_peer_.end()) {
                            pending_messages = std::move(pending_iterator->second);
                            pending_ice_by_peer_.erase(pending_iterator);
                        }
                        sessions_by_peer_.emplace(peer_id, session);
                    }
                }

                if (destroy_session) {
                    DestroySession(session);
                    return post_insert_status;
                }

                status = SubmitPendingIceCandidates(session.get(), pending_messages);
                if (STATUS_FAILED(status)) {
                    session->terminate_requested.store(true);
                    wake_condition_.notify_all();
                }
                return status;
            }

            case SIGNALING_MESSAGE_TYPE_ANSWER: {
                std::shared_ptr<StreamingSession> session;
                {
                    std::lock_guard<std::mutex> lock(state_lock_);
                    auto iterator = sessions_by_peer_.find(peer_id);
                    if (iterator != sessions_by_peer_.end()) {
                        session = iterator->second;
                    } else if (sessions_by_peer_.size() == 1) {
                        session = sessions_by_peer_.begin()->second;
                    }
                }

                if (!session) {
                    return STATUS_SUCCESS;
                }
                return HandleAnswer(session.get(), &received_message->signalingMessage);
            }

            case SIGNALING_MESSAGE_TYPE_ICE_CANDIDATE: {
                std::shared_ptr<StreamingSession> session;
                {
                    std::lock_guard<std::mutex> lock(state_lock_);
                    auto iterator = sessions_by_peer_.find(peer_id);
                    if (iterator == sessions_by_peer_.end()) {
                        PendingIceMessage pending_message;
                        pending_message.created_time_100ns = GETTIME();
                        pending_message.message = *received_message;
                        pending_ice_by_peer_[peer_id].push_back(std::move(pending_message));
                        return STATUS_SUCCESS;
                    }
                    session = iterator->second;
                }
                return HandleRemoteCandidate(session.get(), &received_message->signalingMessage);
            }

            default:
                return STATUS_SUCCESS;
        }
    }

    void HandleLocalIceCandidate(StreamingSession* session, const char* candidate_json) {
        if (session == nullptr) {
            return;
        }

        if (candidate_json == nullptr) {
            if (!session->remote_can_trickle) {
                ThrowIfFailed(createAnswer(session->peer_connection, &session->answer_description), "createAnswer");
                ThrowIfFailed(SendAnswer(session), "send answer");
            }
            return;
        }

        if (session->remote_can_trickle) {
            const STATUS status = SendIceCandidate(session, candidate_json);
            if (STATUS_FAILED(status)) {
                DLOGW(
                    "send ICE candidate failed with status %s for peer %s; keeping session alive",
                    FormatStatus(status).c_str(),
                    session->peer_id.c_str()
                );
                RequestSignalingRecreate();
            }
        }
    }

    void SetSessionConnected(StreamingSession* session, bool connected) {
        if (session == nullptr) {
            return;
        }

        UINT32 previous_viewer_count = 0;
        UINT32 viewer_count = 0;
        bool emit_connected = false;
        bool emit_disconnected = false;
        const std::string client_id = session->peer_id;

        {
            std::lock_guard<std::mutex> lock(state_lock_);
            if (session->connected == connected) {
                return;
            }

            previous_viewer_count = viewer_count_;
            session->connected = connected;
            if (connected) {
                ++viewer_count_;
            } else if (viewer_count_ > 0) {
                --viewer_count_;
            }

            viewer_count = viewer_count_;
            emit_connected = previous_viewer_count == 0 && viewer_count > 0;
            emit_disconnected = previous_viewer_count > 0 && viewer_count == 0;
        }

        if (emit_connected) {
            EmitMarker("TXING_VIEWER_CONNECTED", {{"clientId", client_id}, {"viewers", std::to_string(viewer_count)}});
        }
        if (emit_disconnected) {
            EmitMarker("TXING_VIEWER_DISCONNECTED", {{"clientId", client_id}, {"viewers", std::to_string(viewer_count)}});
        }
    }

    void DestroySession(const std::shared_ptr<StreamingSession>& session) noexcept {
        if (!session) {
            return;
        }

        SetSessionConnected(session.get(), false);
        session->terminate_requested.store(true);

        if (session->peer_connection != nullptr) {
            UNUSED_PARAM(closePeerConnection(session->peer_connection));
            UNUSED_PARAM(freePeerConnection(&session->peer_connection));
            session->peer_connection = nullptr;
            session->video_transceiver = nullptr;
        }
    }

    void CollectTerminatedSessions(std::vector<std::shared_ptr<StreamingSession>>* sessions_to_destroy) {
        if (sessions_to_destroy == nullptr) {
            return;
        }

        std::lock_guard<std::mutex> lock(state_lock_);
        for (auto iterator = sessions_by_peer_.begin(); iterator != sessions_by_peer_.end();) {
            if (iterator->second != nullptr && iterator->second->terminate_requested.load()) {
                sessions_to_destroy->push_back(iterator->second);
                iterator = sessions_by_peer_.erase(iterator);
            } else {
                ++iterator;
            }
        }
    }

    void RemoveExpiredPendingMessages() {
        const UINT64 now = GETTIME();
        std::lock_guard<std::mutex> lock(state_lock_);
        for (auto iterator = pending_ice_by_peer_.begin(); iterator != pending_ice_by_peer_.end();) {
            auto& pending_messages = iterator->second;
            while (!pending_messages.empty() &&
                   pending_messages.front().created_time_100ns + kPendingMessageCleanupDuration100ns < now) {
                pending_messages.pop_front();
            }

            if (pending_messages.empty()) {
                iterator = pending_ice_by_peer_.erase(iterator);
            } else {
                ++iterator;
            }
        }
    }

    void RequestSignalingRecreate() {
        {
            std::lock_guard<std::mutex> lock(state_lock_);
            recreate_signaling_client_ = true;
        }
        wake_condition_.notify_all();
    }

    void CleanupLoop() noexcept {
        while (true) {
            std::vector<std::shared_ptr<StreamingSession>> sessions_to_destroy;
            CollectTerminatedSessions(&sessions_to_destroy);
            for (const auto& session : sessions_to_destroy) {
                DestroySession(session);
            }

            RemoveExpiredPendingMessages();

            bool stopping = false;
            bool recreate_signaling = false;
            {
                std::lock_guard<std::mutex> lock(state_lock_);
                stopping = stopping_;
                recreate_signaling = recreate_signaling_client_;
            }

            if (stopping) {
                break;
            }

            STATUS status = recreate_signaling ? RefreshOrRecreateSignalingClient() : EnsureSignalingConnected();
            if (STATUS_SUCCEEDED(status) && recreate_signaling) {
                std::lock_guard<std::mutex> lock(state_lock_);
                recreate_signaling_client_ = false;
            } else if (STATUS_FAILED(status) && !stopping_) {
                if (IsSignalingCallFailure(status)) {
                    RequestSignalingRecreate();
                } else {
                    ReportError("signaling maintenance failed (status=%s)", FormatStatus(status).c_str());
                }
            }

            std::unique_lock<std::mutex> lock(state_lock_);
            wake_condition_.wait_for(
                lock,
                std::chrono::nanoseconds(kCleanupWaitPeriod100ns * 100)
            );
        }
    }

    void ReportError(const char* format, ...) {
        std::array<char, 512> buffer{};
        va_list arguments;
        va_start(arguments, format);
        std::vsnprintf(buffer.data(), buffer.size(), format, arguments);
        va_end(arguments);

        {
            std::lock_guard<std::mutex> lock(error_lock_);
            if (!fatal_error_) {
                fatal_error_ = std::string(buffer.data());
            }
        }
        EmitMarker("TXING_KVS_ERROR", {{"detail", buffer.data()}});
    }

    static STATUS SignalingStateChanged(UINT64 custom_data, SIGNALING_CLIENT_STATE state) {
        UNUSED_PARAM(custom_data);
        UNUSED_PARAM(state);
        return STATUS_SUCCESS;
    }

    static STATUS SignalingClientError(UINT64 custom_data, STATUS status, PCHAR msg, UINT32 msg_len) {
        auto* self = reinterpret_cast<RealKvsSession*>(custom_data);
        if (self == nullptr) {
            return STATUS_SUCCESS;
        }

        if (status == STATUS_SIGNALING_ICE_CONFIG_REFRESH_FAILED || status == STATUS_SIGNALING_RECONNECT_FAILED) {
            self->RequestSignalingRecreate();
            return STATUS_SUCCESS;
        }

        self->ReportError(
            "signaling client error %s: %.*s",
            FormatStatus(status).c_str(),
            static_cast<int>(msg_len),
            msg == nullptr ? "" : msg
        );
        return STATUS_SUCCESS;
    }

    static STATUS SignalingMessageReceived(UINT64 custom_data, PReceivedSignalingMessage received_message) {
        auto* self = reinterpret_cast<RealKvsSession*>(custom_data);
        if (self == nullptr) {
            return STATUS_NULL_ARG;
        }

        STATUS status = self->HandleSignalingMessage(received_message);
        if (STATUS_FAILED(status)) {
            self->ReportError("signaling message processing failed (status=%s)", FormatStatus(status).c_str());
        }
        return status;
    }

    static VOID OnIceCandidate(UINT64 custom_data, PCHAR candidate_json) {
        auto* session = reinterpret_cast<StreamingSession*>(custom_data);
        if (session == nullptr || session->owner == nullptr) {
            return;
        }

        session->owner->HandleLocalIceCandidate(session, candidate_json);
    }

    static VOID OnConnectionStateChange(UINT64 custom_data, RTC_PEER_CONNECTION_STATE new_state) {
        auto* session = reinterpret_cast<StreamingSession*>(custom_data);
        if (session == nullptr || session->owner == nullptr) {
            return;
        }

        switch (new_state) {
            case RTC_PEER_CONNECTION_STATE_CONNECTED:
                session->owner->SetSessionConnected(session, true);
                break;
            case RTC_PEER_CONNECTION_STATE_FAILED:
            case RTC_PEER_CONNECTION_STATE_CLOSED:
            case RTC_PEER_CONNECTION_STATE_DISCONNECTED:
                session->terminate_requested.store(true);
                session->owner->SetSessionConnected(session, false);
                session->owner->wake_condition_.notify_all();
                break;
            default:
                break;
        }
    }

    std::string region_;
    std::string channel_name_;
    std::string client_id_;
    std::string access_key_id_;
    std::string secret_access_key_;
    std::optional<std::string> session_token_;
    UINT32 video_bitrate_bps_ = 0;

    std::optional<std::string> ca_cert_path_;
    std::optional<std::string> control_plane_url_;

    PAwsCredentialProvider credential_provider_ = nullptr;
    SIGNALING_CLIENT_HANDLE signaling_client_handle_ = INVALID_SIGNALING_CLIENT_HANDLE_VALUE;
    ChannelInfo channel_info_{};
    SignalingClientInfo client_info_{};
    SignalingClientCallbacks signaling_client_callbacks_{};

    bool sdk_initialized_ = false;
    bool started_ = false;
    bool stopping_ = true;
    bool recreate_signaling_client_ = false;

    std::thread cleanup_thread_;
    std::mutex state_lock_;
    std::condition_variable wake_condition_;
    std::mutex signaling_client_lock_;
    std::mutex error_lock_;
    std::optional<std::string> fatal_error_;
    UINT32 viewer_count_ = 0;
    std::unordered_map<std::string, std::shared_ptr<StreamingSession>> sessions_by_peer_;
    std::unordered_map<std::string, std::deque<PendingIceMessage>> pending_ice_by_peer_;
};

}  // namespace

std::unique_ptr<KvsSession> CreateKvsSession(const RuntimeConfig& config, const AwsCredentials& credentials) {
    return std::make_unique<RealKvsSession>(config, credentials);
}

}  // namespace txing::board::kvs_master
