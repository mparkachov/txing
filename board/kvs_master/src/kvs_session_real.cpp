#include "kvs_master/kvs_session.hpp"

#include "kvs_master/markers.hpp"

#include <array>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>

extern "C" {
#include "Samples.h"
extern PSampleConfiguration gSampleConfiguration;
extern STATUS signalingClientError(UINT64 customData, STATUS status, PCHAR msg, UINT32 msgLen);
}

namespace txing::board::kvs_master {
namespace {

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
        ApplyAwsEnvironment();

        STATUS status = createSampleConfiguration(
            const_cast<PCHAR>(channel_name_.c_str()),
            SIGNALING_CHANNEL_ROLE_TYPE_MASTER,
            TRUE,
            TRUE,
            LOG_LEVEL_WARN,
            &sample_configuration_
        );
        if (STATUS_FAILED(status) || sample_configuration_ == nullptr) {
            throw std::runtime_error("createSampleConfiguration failed with status " + FormatStatus(status));
        }

        sample_configuration_->customData = reinterpret_cast<UINT64>(this);
        sample_configuration_->mediaType = SAMPLE_STREAMING_VIDEO_ONLY;
        sample_configuration_->videoCodec = RTC_CODEC_H264_PROFILE_42E01F_LEVEL_ASYMMETRY_ALLOWED_PACKETIZATION_MODE;
        sample_configuration_->videoRollingBufferDurationSec = 3;
        sample_configuration_->videoRollingBufferBitratebps = video_bitrate_bps_;
        sample_configuration_->videoSource = nullptr;
        sample_configuration_->audioSource = nullptr;
        sample_configuration_->receiveAudioVideoSource = nullptr;
        sample_configuration_->addTransceiversCallback = AddSendOnlyVideoTransceiver;
        sample_configuration_->signalingClientCallbacks.errorReportFn = SignalingClientError;
    }

    ~RealKvsSession() override {
        Stop();
        if (sample_configuration_ != nullptr) {
            freeSampleConfiguration(&sample_configuration_);
            sample_configuration_ = nullptr;
        }
    }

    void Start() override {
        if (sample_configuration_ == nullptr || started_) {
            return;
        }

        STATUS status = InitSignaling(sample_configuration_, client_id_);
        if (STATUS_FAILED(status)) {
            ReportError("failed to initialize KVS signaling (status=%s)", FormatStatus(status).c_str());
            throw std::runtime_error("txing_kvs_start failed with status " + FormatStatus(status));
        }

        status = THREAD_CREATE(&cleanup_thread_, CleanupRoutine, reinterpret_cast<PVOID>(this));
        if (STATUS_FAILED(status)) {
            ReportError("failed to start session cleanup thread (status=%s)", FormatStatus(status).c_str());
            throw std::runtime_error("failed to start session cleanup thread");
        }

        cleanup_thread_started_ = true;
        started_ = true;
        stopping_ = false;
    }

    void PushH264AccessUnit(
        const std::uint8_t* data,
        std::size_t len,
        std::uint64_t presentation_ts_100ns,
        std::uint64_t duration_100ns,
        bool is_keyframe
    ) override {
        if (sample_configuration_ == nullptr || data == nullptr || len == 0) {
            throw std::runtime_error("KVS session is not initialized");
        }
        if (len > MAX_UINT32) {
            throw std::runtime_error("H.264 access unit exceeds AWS frame size limits");
        }

        Frame frame;
        MEMSET(&frame, 0x00, SIZEOF(frame));
        frame.version = FRAME_CURRENT_VERSION;
        frame.trackId = 1;
        frame.duration = duration_100ns;
        frame.decodingTs = presentation_ts_100ns;
        frame.presentationTs = presentation_ts_100ns;
        frame.size = static_cast<UINT32>(len);
        frame.frameData = const_cast<PBYTE>(data);
        frame.flags = is_keyframe ? FRAME_FLAG_KEY_FRAME : FRAME_FLAG_NONE;

        STATUS first_failure = STATUS_SUCCESS;
        BOOL had_session = FALSE;
        BOOL wrote_frame = FALSE;
        BOOL srtp_pending = FALSE;

        MUTEX_LOCK(sample_configuration_->streamingSessionListReadLock);
        for (UINT32 index = 0; index < sample_configuration_->streamingSessionCount; ++index) {
            auto* session = sample_configuration_->sampleStreamingSessionList[index];
            had_session = TRUE;
            frame.index = static_cast<UINT32>(ATOMIC_INCREMENT(&session->frameIndex));

            const auto status = writeFrame(session->pVideoRtcRtpTransceiver, &frame);
            if (status == STATUS_SUCCESS) {
                wrote_frame = TRUE;
                if (session->firstFrame) {
                    PROFILE_WITH_START_TIME(session->offerReceiveTime, "Time to first frame");
                    session->firstFrame = FALSE;
                }
            } else if (status == STATUS_SRTP_NOT_READY_YET) {
                srtp_pending = TRUE;
            } else if (first_failure == STATUS_SUCCESS) {
                first_failure = status;
            }
        }
        MUTEX_UNLOCK(sample_configuration_->streamingSessionListReadLock);

        if (!had_session || wrote_frame || srtp_pending) {
            return;
        }
        if (STATUS_FAILED(first_failure)) {
            ReportError("writeFrame failed (status=%s)", FormatStatus(first_failure).c_str());
            throw std::runtime_error("txing_kvs_push_h264_au failed with status " + FormatStatus(first_failure));
        }
    }

    void Stop() noexcept override {
        if (sample_configuration_ == nullptr || !started_) {
            return;
        }

        stopping_ = true;
        started_ = false;
        ATOMIC_STORE_BOOL(&sample_configuration_->appTerminateFlag, TRUE);
        ATOMIC_STORE_BOOL(&sample_configuration_->interrupted, TRUE);
        CVAR_BROADCAST(sample_configuration_->cvar);

        if (IS_VALID_SIGNALING_CLIENT_HANDLE(sample_configuration_->signalingClientHandle)) {
            UNUSED_PARAM(signalingClientDisconnectSync(sample_configuration_->signalingClientHandle));
        }

        if (cleanup_thread_started_ && IS_VALID_TID_VALUE(cleanup_thread_)) {
            THREAD_JOIN(cleanup_thread_, nullptr);
            cleanup_thread_ = INVALID_TID_VALUE;
            cleanup_thread_started_ = false;
        }
    }

    std::optional<std::string> TakeFatalError() override {
        std::lock_guard<std::mutex> lock(error_lock_);
        auto error = fatal_error_;
        fatal_error_.reset();
        return error;
    }

  private:
    struct SessionTracker {
        PSampleStreamingSession session = nullptr;
        BOOL connected = FALSE;
    };

    static STATUS AddSendOnlyVideoTransceiver(
        PSampleConfiguration sample_configuration,
        PSampleStreamingSession streaming_session
    ) {
        STATUS retStatus = STATUS_SUCCESS;
        RtcRtpTransceiverInit video_transceiver_init = {0};
        RtcMediaStreamTrack video_track = {0};

        CHK(sample_configuration != nullptr && streaming_session != nullptr, STATUS_NULL_ARG);

        video_track.kind = MEDIA_STREAM_TRACK_KIND_VIDEO;
        video_track.codec = sample_configuration->videoCodec;
        video_transceiver_init.direction = RTC_RTP_TRANSCEIVER_DIRECTION_SENDONLY;
        STRCPY(video_track.streamId, "txingBoardVideo");
        STRCPY(video_track.trackId, "txingBoardVideoTrack");

        CHK_STATUS(addTransceiver(
            streaming_session->pPeerConnection,
            &video_track,
            &video_transceiver_init,
            &streaming_session->pVideoRtcRtpTransceiver
        ));
        CHK_STATUS(configureTransceiverRollingBuffer(
            streaming_session->pVideoRtcRtpTransceiver,
            &video_track,
            sample_configuration->videoRollingBufferDurationSec,
            sample_configuration->videoRollingBufferBitratebps
        ));
        CHK_STATUS(transceiverOnBandwidthEstimation(
            streaming_session->pVideoRtcRtpTransceiver,
            reinterpret_cast<UINT64>(streaming_session),
            sampleBandwidthEstimationHandler
        ));

    CleanUp:
        CHK_LOG_ERR(retStatus);
        return retStatus;
    }

    static STATUS InitSignaling(PSampleConfiguration sample_configuration, const std::string& client_id) {
        STATUS retStatus = STATUS_SUCCESS;
        SignalingClientMetrics metrics = sample_configuration->signalingClientMetrics;

        sample_configuration->signalingClientCallbacks.messageReceivedFn = SignalingMessageReceived;
        STRCPY(sample_configuration->clientInfo.clientId, client_id.c_str());
        CHK_STATUS(createSignalingClientSync(
            &sample_configuration->clientInfo,
            &sample_configuration->channelInfo,
            &sample_configuration->signalingClientCallbacks,
            sample_configuration->pCredentialProvider,
            &sample_configuration->signalingClientHandle
        ));
        CHK_STATUS(signalingClientFetchSync(sample_configuration->signalingClientHandle));
        CHK_STATUS(signalingClientConnectSync(sample_configuration->signalingClientHandle));
        CHK_STATUS(signalingClientGetMetrics(sample_configuration->signalingClientHandle, &metrics));
        sample_configuration->signalingClientMetrics = metrics;
        gSampleConfiguration = sample_configuration;

    CleanUp:
        return retStatus;
    }

    static STATUS SignalingMessageReceived(UINT64 custom_data, PReceivedSignalingMessage received_message) {
        STATUS retStatus = STATUS_SUCCESS;
        auto* sample_configuration = reinterpret_cast<PSampleConfiguration>(custom_data);
        auto* self = sample_configuration == nullptr
            ? nullptr
            : reinterpret_cast<RealKvsSession*>(sample_configuration->customData);
        BOOL peer_connection_found = FALSE;
        BOOL locked = FALSE;
        BOOL start_stats = FALSE;
        BOOL free_streaming_session = FALSE;
        UINT32 client_id_hash = 0;
        UINT64 hash_value = 0;
        PPendingMessageQueue pending_message_queue = nullptr;
        PSampleStreamingSession streaming_session = nullptr;
        PReceivedSignalingMessage message_copy = nullptr;

        CHK(sample_configuration != nullptr, STATUS_NULL_ARG);

        MUTEX_LOCK(sample_configuration->sampleConfigurationObjLock);
        locked = TRUE;

        client_id_hash = COMPUTE_CRC32(
            reinterpret_cast<PBYTE>(received_message->signalingMessage.peerClientId),
            static_cast<UINT32>(STRLEN(received_message->signalingMessage.peerClientId))
        );
        CHK_STATUS(hashTableContains(
            sample_configuration->pRtcPeerConnectionForRemoteClient,
            client_id_hash,
            &peer_connection_found
        ));
        if (peer_connection_found) {
            CHK_STATUS(hashTableGet(
                sample_configuration->pRtcPeerConnectionForRemoteClient,
                client_id_hash,
                &hash_value
            ));
            streaming_session = reinterpret_cast<PSampleStreamingSession>(hash_value);
        }

        switch (received_message->signalingMessage.messageType) {
            case SIGNALING_MESSAGE_TYPE_OFFER:
                CHK_ERR(
                    !peer_connection_found,
                    STATUS_INVALID_OPERATION,
                    "Peer connection %s is in progress",
                    received_message->signalingMessage.peerClientId
                );

                if (sample_configuration->streamingSessionCount ==
                    ARRAY_SIZE(sample_configuration->sampleStreamingSessionList)) {
                    DLOGW("Max simultaneous streaming session count reached.");
                    CHK_STATUS(getPendingMessageQueueForHash(
                        sample_configuration->pPendingSignalingMessageForRemoteClient,
                        client_id_hash,
                        TRUE,
                        &pending_message_queue
                    ));
                    CHK(FALSE, retStatus);
                }

                CHK_STATUS(createSampleStreamingSession(
                    sample_configuration,
                    received_message->signalingMessage.peerClientId,
                    TRUE,
                    &streaming_session
                ));
                free_streaming_session = TRUE;
                CHK_STATUS(self->AttachSession(streaming_session));
                CHK_STATUS(handleOffer(sample_configuration, streaming_session, &received_message->signalingMessage));
                CHK_STATUS(hashTablePut(
                    sample_configuration->pRtcPeerConnectionForRemoteClient,
                    client_id_hash,
                    reinterpret_cast<UINT64>(streaming_session)
                ));

                CHK_STATUS(getPendingMessageQueueForHash(
                    sample_configuration->pPendingSignalingMessageForRemoteClient,
                    client_id_hash,
                    TRUE,
                    &pending_message_queue
                ));
                if (pending_message_queue != nullptr) {
                    CHK_STATUS(submitPendingIceCandidate(pending_message_queue, streaming_session));
                    pending_message_queue = nullptr;
                }

                MUTEX_LOCK(sample_configuration->streamingSessionListReadLock);
                sample_configuration->sampleStreamingSessionList[sample_configuration->streamingSessionCount++] =
                    streaming_session;
                MUTEX_UNLOCK(sample_configuration->streamingSessionListReadLock);
                free_streaming_session = FALSE;
                start_stats = sample_configuration->iceCandidatePairStatsTimerId == MAX_UINT32;
                break;

            case SIGNALING_MESSAGE_TYPE_ANSWER:
                streaming_session = sample_configuration->sampleStreamingSessionList[0];
                CHK_STATUS(handleAnswer(sample_configuration, streaming_session, &received_message->signalingMessage));
                CHK_STATUS(hashTablePut(
                    sample_configuration->pRtcPeerConnectionForRemoteClient,
                    client_id_hash,
                    reinterpret_cast<UINT64>(streaming_session)
                ));
                CHK_STATUS(getPendingMessageQueueForHash(
                    sample_configuration->pPendingSignalingMessageForRemoteClient,
                    client_id_hash,
                    TRUE,
                    &pending_message_queue
                ));
                if (pending_message_queue != nullptr) {
                    CHK_STATUS(submitPendingIceCandidate(pending_message_queue, streaming_session));
                    pending_message_queue = nullptr;
                }

                start_stats = sample_configuration->iceCandidatePairStatsTimerId == MAX_UINT32;
                CHK_STATUS(signalingClientGetMetrics(
                    sample_configuration->signalingClientHandle,
                    &sample_configuration->signalingClientMetrics
                ));
                break;

            case SIGNALING_MESSAGE_TYPE_ICE_CANDIDATE:
                if (!peer_connection_found) {
                    CHK_STATUS(getPendingMessageQueueForHash(
                        sample_configuration->pPendingSignalingMessageForRemoteClient,
                        client_id_hash,
                        FALSE,
                        &pending_message_queue
                    ));
                    if (pending_message_queue == nullptr) {
                        CHK_STATUS(createMessageQueue(client_id_hash, &pending_message_queue));
                        CHK_STATUS(stackQueueEnqueue(
                            sample_configuration->pPendingSignalingMessageForRemoteClient,
                            reinterpret_cast<UINT64>(pending_message_queue)
                        ));
                    }

                    message_copy = reinterpret_cast<PReceivedSignalingMessage>(MEMCALLOC(1, SIZEOF(ReceivedSignalingMessage)));
                    CHK(message_copy != nullptr, STATUS_NOT_ENOUGH_MEMORY);
                    *message_copy = *received_message;
                    CHK_STATUS(stackQueueEnqueue(
                        pending_message_queue->messageQueue,
                        reinterpret_cast<UINT64>(message_copy)
                    ));
                    pending_message_queue = nullptr;
                    message_copy = nullptr;
                } else {
                    CHK_STATUS(handleRemoteCandidate(streaming_session, &received_message->signalingMessage));
                }
                break;

            default:
                DLOGD("Unhandled signaling message type %u", received_message->signalingMessage.messageType);
                break;
        }

        MUTEX_UNLOCK(sample_configuration->sampleConfigurationObjLock);
        locked = FALSE;

        if (sample_configuration->enableIceStats && start_stats &&
            STATUS_FAILED(retStatus = timerQueueAddTimer(
                sample_configuration->timerQueueHandle,
                SAMPLE_STATS_DURATION,
                SAMPLE_STATS_DURATION,
                getIceCandidatePairStatsCallback,
                reinterpret_cast<UINT64>(sample_configuration),
                &sample_configuration->iceCandidatePairStatsTimerId
            ))) {
            DLOGW(
                "Failed to add getIceCandidatePairStatsCallback to timer queue (code 0x%08x). Cannot pull ice candidate pair metrics periodically",
                retStatus
            );
            retStatus = STATUS_SUCCESS;
        }

    CleanUp:
        SAFE_MEMFREE(message_copy);
        if (pending_message_queue != nullptr) {
            freeMessageQueue(pending_message_queue);
        }
        if (free_streaming_session && streaming_session != nullptr) {
            freeSampleStreamingSession(&streaming_session);
        }
        if (locked) {
            MUTEX_UNLOCK(sample_configuration->sampleConfigurationObjLock);
        }
        if (STATUS_FAILED(retStatus) && self != nullptr) {
            self->ReportError("signaling message processing failed (status=%s)", FormatStatus(retStatus).c_str());
        }
        CHK_LOG_ERR(retStatus);
        return retStatus;
    }

    static STATUS SignalingClientError(UINT64 custom_data, STATUS status, PCHAR msg, UINT32 msg_len) {
        STATUS retStatus = signalingClientError(custom_data, status, msg, msg_len);
        auto* sample_configuration = reinterpret_cast<PSampleConfiguration>(custom_data);
        auto* self = sample_configuration == nullptr
            ? nullptr
            : reinterpret_cast<RealKvsSession*>(sample_configuration->customData);

        if (self != nullptr &&
            status != STATUS_SIGNALING_ICE_CONFIG_REFRESH_FAILED &&
            status != STATUS_SIGNALING_RECONNECT_FAILED) {
            self->ReportError(
                "signaling client error %s: %.*s",
                FormatStatus(status).c_str(),
                msg_len,
                msg == nullptr ? "" : msg
            );
        }

        return retStatus;
    }

    static VOID OnConnectionStateChange(UINT64 custom_data, RTC_PEER_CONNECTION_STATE new_state) {
        auto* session = reinterpret_cast<PSampleStreamingSession>(custom_data);
        onConnectionStateChange(custom_data, new_state);

        if (session == nullptr || session->pSampleConfiguration == nullptr) {
            return;
        }

        auto* self = reinterpret_cast<RealKvsSession*>(session->pSampleConfiguration->customData);
        if (self == nullptr) {
            return;
        }

        switch (new_state) {
            case RTC_PEER_CONNECTION_STATE_CONNECTED:
                self->UpdateViewerState(session, TRUE);
                break;
            case RTC_PEER_CONNECTION_STATE_FAILED:
            case RTC_PEER_CONNECTION_STATE_CLOSED:
            case RTC_PEER_CONNECTION_STATE_DISCONNECTED:
                self->UpdateViewerState(session, FALSE);
                break;
            default:
                break;
        }
    }

    static VOID OnStreamingSessionShutdown(UINT64 custom_data, PSampleStreamingSession streaming_session) {
        auto* self = reinterpret_cast<RealKvsSession*>(custom_data);
        if (self == nullptr && streaming_session != nullptr && streaming_session->pSampleConfiguration != nullptr) {
            self = reinterpret_cast<RealKvsSession*>(streaming_session->pSampleConfiguration->customData);
        }
        if (self == nullptr || streaming_session == nullptr) {
            return;
        }

        self->UpdateViewerState(streaming_session, FALSE);
        self->RemoveSession(streaming_session);
    }

    static PVOID CleanupRoutine(PVOID custom_data) {
        auto* self = reinterpret_cast<RealKvsSession*>(custom_data);
        if (self == nullptr || self->sample_configuration_ == nullptr) {
            return reinterpret_cast<PVOID>(static_cast<uintptr_t>(STATUS_NULL_ARG));
        }

        const auto status = sessionCleanupWait(self->sample_configuration_);
        if (STATUS_FAILED(status) && !self->stopping_) {
            self->ReportError("session cleanup loop failed (status=%s)", FormatStatus(status).c_str());
        }
        return reinterpret_cast<PVOID>(static_cast<uintptr_t>(status));
    }

    STATUS AttachSession(PSampleStreamingSession session) {
        STATUS retStatus = STATUS_SUCCESS;
        UINT32 index = 0;

        CHK(session != nullptr, STATUS_NULL_ARG);
        CHK_STATUS(streamingSessionOnShutdown(session, reinterpret_cast<UINT64>(this), OnStreamingSessionShutdown));
        CHK_STATUS(peerConnectionOnConnectionStateChange(
            session->pPeerConnection,
            reinterpret_cast<UINT64>(session),
            OnConnectionStateChange
        ));

        {
            std::lock_guard<std::mutex> lock(trackers_lock_);
            for (index = 0; index < trackers_.size(); ++index) {
                if (trackers_[index].session == session) {
                    return STATUS_SUCCESS;
                }
                if (trackers_[index].session == nullptr) {
                    trackers_[index].session = session;
                    trackers_[index].connected = FALSE;
                    break;
                }
            }
        }
        CHK(index < trackers_.size(), STATUS_NOT_ENOUGH_MEMORY);

    CleanUp:
        return retStatus;
    }

    void UpdateViewerState(PSampleStreamingSession session, BOOL connected) {
        UINT32 previous_viewer_count = 0;
        UINT32 viewer_count = 0;
        BOOL emit_connected = FALSE;
        BOOL emit_disconnected = FALSE;
        const CHAR* peer_id = nullptr;

        {
            std::lock_guard<std::mutex> lock(trackers_lock_);
            std::size_t index = 0;
            for (; index < trackers_.size(); ++index) {
                if (trackers_[index].session == session) {
                    break;
                }
            }
            if (index == trackers_.size() || trackers_[index].connected == connected) {
                return;
            }

            previous_viewer_count = viewer_count_;
            trackers_[index].connected = connected;
            if (connected) {
                ++viewer_count_;
            } else if (viewer_count_ > 0) {
                --viewer_count_;
            }

            viewer_count = viewer_count_;
            peer_id = session->peerId;
            emit_connected = previous_viewer_count == 0 && viewer_count > 0;
            emit_disconnected = previous_viewer_count > 0 && viewer_count == 0;
        }

        const std::string client_id = peer_id == nullptr ? "unknown" : std::string(peer_id);
        const auto viewers = std::to_string(viewer_count);
        if (emit_connected) {
            EmitMarker("TXING_VIEWER_CONNECTED", {{"clientId", client_id}, {"viewers", viewers}});
        }
        if (emit_disconnected) {
            EmitMarker("TXING_VIEWER_DISCONNECTED", {{"clientId", client_id}, {"viewers", viewers}});
        }
    }

    void RemoveSession(PSampleStreamingSession session) {
        std::lock_guard<std::mutex> lock(trackers_lock_);
        for (auto& tracker : trackers_) {
            if (tracker.session == session) {
                tracker.session = nullptr;
                tracker.connected = FALSE;
                return;
            }
        }
    }

    void ApplyAwsEnvironment() {
        if (setenv("AWS_DEFAULT_REGION", region_.c_str(), 1) != 0) {
            throw std::runtime_error("failed to set AWS_DEFAULT_REGION");
        }
        if (setenv("AWS_REGION", region_.c_str(), 1) != 0) {
            throw std::runtime_error("failed to set AWS_REGION");
        }
        if (setenv("AWS_ACCESS_KEY_ID", access_key_id_.c_str(), 1) != 0) {
            throw std::runtime_error("failed to set AWS_ACCESS_KEY_ID");
        }
        if (setenv("AWS_SECRET_ACCESS_KEY", secret_access_key_.c_str(), 1) != 0) {
            throw std::runtime_error("failed to set AWS_SECRET_ACCESS_KEY");
        }
        if (session_token_ && !session_token_->empty()) {
            if (setenv("AWS_SESSION_TOKEN", session_token_->c_str(), 1) != 0) {
                throw std::runtime_error("failed to set AWS_SESSION_TOKEN");
            }
        } else {
            unsetenv("AWS_SESSION_TOKEN");
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

    static std::string FormatStatus(STATUS status) {
        char buffer[16];
        std::snprintf(buffer, sizeof(buffer), "0x%08x", static_cast<unsigned>(status));
        return std::string(buffer);
    }

    std::string region_;
    std::string channel_name_;
    std::string client_id_;
    std::string access_key_id_;
    std::string secret_access_key_;
    std::optional<std::string> session_token_;
    UINT32 video_bitrate_bps_ = 0;
    PSampleConfiguration sample_configuration_ = nullptr;
    TID cleanup_thread_ = INVALID_TID_VALUE;
    BOOL cleanup_thread_started_ = FALSE;
    BOOL started_ = FALSE;
    BOOL stopping_ = FALSE;
    std::mutex error_lock_;
    std::optional<std::string> fatal_error_;
    std::mutex trackers_lock_;
    UINT32 viewer_count_ = 0;
    std::array<SessionTracker, DEFAULT_MAX_CONCURRENT_STREAMING_SESSION> trackers_{};
};

}  // namespace

std::unique_ptr<KvsSession> CreateKvsSession(const RuntimeConfig& config, const AwsCredentials& credentials) {
    return std::make_unique<RealKvsSession>(config, credentials);
}

}  // namespace txing::board::kvs_master
