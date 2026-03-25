#define _POSIX_C_SOURCE 200809L

#include "txing_kvs_shim.h"

#include "Samples.h"

#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern PSampleConfiguration gSampleConfiguration;
extern STATUS signalingClientError(UINT64 customData, STATUS status, PCHAR msg, UINT32 msgLen);

typedef struct {
    PSampleStreamingSession session;
    BOOL connected;
} TxingSessionTracker;

struct txing_kvs_handle {
    txing_kvs_callbacks callbacks;
    PSampleConfiguration sample_configuration;
    TID cleanup_thread;
    BOOL cleanup_thread_started;
    BOOL started;
    BOOL stopping;
    MUTEX lock;
    UINT32 viewer_count;
    TxingSessionTracker trackers[DEFAULT_MAX_CONCURRENT_STREAMING_SESSION];
    CHAR* region;
    CHAR* channel_name;
    CHAR* client_id;
    CHAR* access_key_id;
    CHAR* secret_access_key;
    CHAR* session_token;
    UINT32 video_bitrate_bps;
};

static STATUS txing_add_send_only_video_transceiver(PSampleConfiguration pSampleConfiguration, PSampleStreamingSession pSampleStreamingSession);
static STATUS txing_init_signaling(PSampleConfiguration pSampleConfiguration, PCHAR clientId);
static STATUS txing_signaling_message_received(UINT64 customData, PReceivedSignalingMessage pReceivedSignalingMessage);
static STATUS txing_signaling_client_error(UINT64 customData, STATUS status, PCHAR msg, UINT32 msgLen);
static VOID txing_on_connection_state_change(UINT64 customData, RTC_PEER_CONNECTION_STATE newState);
static VOID txing_on_streaming_session_shutdown(UINT64 customData, PSampleStreamingSession pSampleStreamingSession);
static PVOID txing_cleanup_routine(PVOID customData);

static CHAR* txing_strdup(const CHAR* source);
static void txing_free_handle(txing_kvs_handle* handle);
static STATUS txing_apply_aws_environment(const txing_kvs_handle* handle);
static void txing_report_error(txing_kvs_handle* handle, const CHAR* format, ...);
static STATUS txing_attach_session(txing_kvs_handle* handle, PSampleStreamingSession session);
static void txing_update_viewer_state(txing_kvs_handle* handle, PSampleStreamingSession session, BOOL connected);
static void txing_remove_session(txing_kvs_handle* handle, PSampleStreamingSession session);

int txing_kvs_create(const txing_kvs_config* config, const txing_kvs_callbacks* callbacks, txing_kvs_handle** out_handle)
{
    txing_kvs_handle* handle = NULL;
    STATUS status = STATUS_SUCCESS;

    if (config == NULL || callbacks == NULL || out_handle == NULL) {
        return -1;
    }

    handle = (txing_kvs_handle*) MEMCALLOC(1, SIZEOF(*handle));
    if (handle == NULL) {
        return -2;
    }

    handle->lock = MUTEX_CREATE(FALSE);
    if (!IS_VALID_MUTEX_VALUE(handle->lock)) {
        txing_free_handle(handle);
        return -3;
    }

    handle->callbacks = *callbacks;
    handle->cleanup_thread = INVALID_TID_VALUE;
    handle->video_bitrate_bps = config->video_bitrate_bps;

    handle->region = txing_strdup(config->region);
    handle->channel_name = txing_strdup(config->channel_name);
    handle->client_id = txing_strdup(config->client_id);
    handle->access_key_id = txing_strdup(config->access_key_id);
    handle->secret_access_key = txing_strdup(config->secret_access_key);
    handle->session_token = txing_strdup(config->session_token);

    if (handle->region == NULL || handle->channel_name == NULL || handle->client_id == NULL || handle->access_key_id == NULL ||
        handle->secret_access_key == NULL) {
        txing_free_handle(handle);
        return -4;
    }

    status = txing_apply_aws_environment(handle);
    if (STATUS_FAILED(status)) {
        txing_free_handle(handle);
        return (int) status;
    }

    status = createSampleConfiguration(handle->channel_name, SIGNALING_CHANNEL_ROLE_TYPE_MASTER, TRUE, TRUE, LOG_LEVEL_WARN,
                                       &handle->sample_configuration);
    if (STATUS_FAILED(status) || handle->sample_configuration == NULL) {
        txing_free_handle(handle);
        return (int) status;
    }

    handle->sample_configuration->customData = (UINT64) handle;
    handle->sample_configuration->mediaType = SAMPLE_STREAMING_VIDEO_ONLY;
    handle->sample_configuration->videoCodec = RTC_CODEC_H264_PROFILE_42E01F_LEVEL_ASYMMETRY_ALLOWED_PACKETIZATION_MODE;
    handle->sample_configuration->videoRollingBufferDurationSec = 3;
    handle->sample_configuration->videoRollingBufferBitratebps = handle->video_bitrate_bps;
    handle->sample_configuration->videoSource = NULL;
    handle->sample_configuration->audioSource = NULL;
    handle->sample_configuration->receiveAudioVideoSource = NULL;
    handle->sample_configuration->addTransceiversCallback = txing_add_send_only_video_transceiver;
    handle->sample_configuration->signalingClientCallbacks.errorReportFn = txing_signaling_client_error;

    *out_handle = handle;
    return 0;
}

int txing_kvs_start(txing_kvs_handle* handle)
{
    STATUS status = STATUS_SUCCESS;

    if (handle == NULL || handle->sample_configuration == NULL) {
        return -1;
    }
    if (handle->started) {
        return 0;
    }

    status = txing_init_signaling(handle->sample_configuration, handle->client_id);
    if (STATUS_FAILED(status)) {
        txing_report_error(handle, "failed to initialize KVS signaling (status=0x%08x)", status);
        return (int) status;
    }

    status = THREAD_CREATE(&handle->cleanup_thread, txing_cleanup_routine, (PVOID) handle);
    if (STATUS_FAILED(status)) {
        txing_report_error(handle, "failed to start session cleanup thread (status=0x%08x)", status);
        return (int) status;
    }

    handle->cleanup_thread_started = TRUE;
    handle->started = TRUE;
    handle->stopping = FALSE;
    if (handle->callbacks.on_ready != NULL) {
        handle->callbacks.on_ready(handle->callbacks.user_data);
    }
    return 0;
}

int txing_kvs_push_h264_au(
    txing_kvs_handle* handle,
    const uint8_t* data,
    size_t len,
    uint64_t presentation_ts_100ns,
    uint64_t duration_100ns,
    bool is_keyframe)
{
    Frame frame;
    STATUS status = STATUS_SUCCESS;
    STATUS first_failure = STATUS_SUCCESS;
    BOOL had_session = FALSE;
    BOOL wrote_frame = FALSE;
    BOOL srtp_pending = FALSE;
    UINT32 i;

    if (handle == NULL || handle->sample_configuration == NULL || data == NULL || len == 0) {
        return -1;
    }
    if (len > MAX_UINT32) {
        return -2;
    }

    MEMSET(&frame, 0x00, SIZEOF(frame));
    frame.version = FRAME_CURRENT_VERSION;
    frame.trackId = 1;
    frame.duration = duration_100ns;
    frame.decodingTs = presentation_ts_100ns;
    frame.presentationTs = presentation_ts_100ns;
    frame.size = (UINT32) len;
    frame.frameData = (PBYTE) data;
    frame.flags = is_keyframe ? FRAME_FLAG_KEY_FRAME : FRAME_FLAG_NONE;

    MUTEX_LOCK(handle->sample_configuration->streamingSessionListReadLock);
    for (i = 0; i < handle->sample_configuration->streamingSessionCount; ++i) {
        PSampleStreamingSession session = handle->sample_configuration->sampleStreamingSessionList[i];

        had_session = TRUE;
        frame.index = (UINT32) ATOMIC_INCREMENT(&session->frameIndex);
        status = writeFrame(session->pVideoRtcRtpTransceiver, &frame);
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
    MUTEX_UNLOCK(handle->sample_configuration->streamingSessionListReadLock);

    if (!had_session || wrote_frame || srtp_pending) {
        return 0;
    }
    if (STATUS_FAILED(first_failure)) {
        txing_report_error(handle, "writeFrame failed (status=0x%08x)", first_failure);
        return (int) first_failure;
    }
    return 0;
}

void txing_kvs_stop(txing_kvs_handle* handle)
{
    if (handle == NULL || handle->sample_configuration == NULL || !handle->started) {
        return;
    }

    handle->stopping = TRUE;
    handle->started = FALSE;
    ATOMIC_STORE_BOOL(&handle->sample_configuration->appTerminateFlag, TRUE);
    ATOMIC_STORE_BOOL(&handle->sample_configuration->interrupted, TRUE);
    CVAR_BROADCAST(handle->sample_configuration->cvar);

    if (IS_VALID_SIGNALING_CLIENT_HANDLE(handle->sample_configuration->signalingClientHandle)) {
        UNUSED_PARAM(signalingClientDisconnectSync(handle->sample_configuration->signalingClientHandle));
    }

    if (handle->cleanup_thread_started && IS_VALID_TID_VALUE(handle->cleanup_thread)) {
        THREAD_JOIN(handle->cleanup_thread, NULL);
        handle->cleanup_thread = INVALID_TID_VALUE;
        handle->cleanup_thread_started = FALSE;
    }
}

void txing_kvs_destroy(txing_kvs_handle* handle)
{
    if (handle == NULL) {
        return;
    }

    txing_kvs_stop(handle);
    if (handle->sample_configuration != NULL) {
        freeSampleConfiguration(&handle->sample_configuration);
        handle->sample_configuration = NULL;
    }
    txing_free_handle(handle);
}

static STATUS txing_add_send_only_video_transceiver(PSampleConfiguration pSampleConfiguration, PSampleStreamingSession pSampleStreamingSession)
{
    STATUS retStatus = STATUS_SUCCESS;
    RtcRtpTransceiverInit videoRtpTransceiverInit;
    RtcMediaStreamTrack videoTrack = {0};

    CHK(pSampleConfiguration != NULL && pSampleStreamingSession != NULL, STATUS_NULL_ARG);

    videoTrack.kind = MEDIA_STREAM_TRACK_KIND_VIDEO;
    videoTrack.codec = pSampleConfiguration->videoCodec;
    videoRtpTransceiverInit.direction = RTC_RTP_TRANSCEIVER_DIRECTION_SENDONLY;
    STRCPY(videoTrack.streamId, "txingBoardVideo");
    STRCPY(videoTrack.trackId, "txingBoardVideoTrack");

    CHK_STATUS(addTransceiver(pSampleStreamingSession->pPeerConnection, &videoTrack, &videoRtpTransceiverInit,
                              &pSampleStreamingSession->pVideoRtcRtpTransceiver));
    CHK_STATUS(configureTransceiverRollingBuffer(pSampleStreamingSession->pVideoRtcRtpTransceiver, &videoTrack,
                                                 pSampleConfiguration->videoRollingBufferDurationSec,
                                                 pSampleConfiguration->videoRollingBufferBitratebps));
    CHK_STATUS(transceiverOnBandwidthEstimation(pSampleStreamingSession->pVideoRtcRtpTransceiver, (UINT64) pSampleStreamingSession,
                                                sampleBandwidthEstimationHandler));

CleanUp:
    CHK_LOG_ERR(retStatus);
    return retStatus;
}

static STATUS txing_init_signaling(PSampleConfiguration pSampleConfiguration, PCHAR clientId)
{
    STATUS retStatus = STATUS_SUCCESS;
    SignalingClientMetrics signalingClientMetrics = pSampleConfiguration->signalingClientMetrics;

    pSampleConfiguration->signalingClientCallbacks.messageReceivedFn = txing_signaling_message_received;
    STRCPY(pSampleConfiguration->clientInfo.clientId, clientId);
    CHK_STATUS(createSignalingClientSync(&pSampleConfiguration->clientInfo, &pSampleConfiguration->channelInfo,
                                         &pSampleConfiguration->signalingClientCallbacks, pSampleConfiguration->pCredentialProvider,
                                         &pSampleConfiguration->signalingClientHandle));
    CHK_STATUS(signalingClientFetchSync(pSampleConfiguration->signalingClientHandle));
    CHK_STATUS(signalingClientConnectSync(pSampleConfiguration->signalingClientHandle));
    CHK_STATUS(signalingClientGetMetrics(pSampleConfiguration->signalingClientHandle, &signalingClientMetrics));
    pSampleConfiguration->signalingClientMetrics = signalingClientMetrics;
    gSampleConfiguration = pSampleConfiguration;

CleanUp:
    return retStatus;
}

static STATUS txing_signaling_message_received(UINT64 customData, PReceivedSignalingMessage pReceivedSignalingMessage)
{
    STATUS retStatus = STATUS_SUCCESS;
    PSampleConfiguration pSampleConfiguration = (PSampleConfiguration) customData;
    txing_kvs_handle* handle = (txing_kvs_handle*) pSampleConfiguration->customData;
    BOOL peerConnectionFound = FALSE, locked = FALSE, startStats = FALSE, freeStreamingSession = FALSE;
    UINT32 clientIdHash;
    UINT64 hashValue = 0;
    PPendingMessageQueue pPendingMessageQueue = NULL;
    PSampleStreamingSession pSampleStreamingSession = NULL;
    PReceivedSignalingMessage pReceivedSignalingMessageCopy = NULL;

    CHK(pSampleConfiguration != NULL, STATUS_NULL_ARG);

    MUTEX_LOCK(pSampleConfiguration->sampleConfigurationObjLock);
    locked = TRUE;

    clientIdHash = COMPUTE_CRC32((PBYTE) pReceivedSignalingMessage->signalingMessage.peerClientId,
                                 (UINT32) STRLEN(pReceivedSignalingMessage->signalingMessage.peerClientId));
    CHK_STATUS(hashTableContains(pSampleConfiguration->pRtcPeerConnectionForRemoteClient, clientIdHash, &peerConnectionFound));
    if (peerConnectionFound) {
        CHK_STATUS(hashTableGet(pSampleConfiguration->pRtcPeerConnectionForRemoteClient, clientIdHash, &hashValue));
        pSampleStreamingSession = (PSampleStreamingSession) hashValue;
    }

    switch (pReceivedSignalingMessage->signalingMessage.messageType) {
        case SIGNALING_MESSAGE_TYPE_OFFER:
            CHK_ERR(!peerConnectionFound, STATUS_INVALID_OPERATION, "Peer connection %s is in progress",
                    pReceivedSignalingMessage->signalingMessage.peerClientId);

            if (pSampleConfiguration->streamingSessionCount == ARRAY_SIZE(pSampleConfiguration->sampleStreamingSessionList)) {
                DLOGW("Max simultaneous streaming session count reached.");
                CHK_STATUS(getPendingMessageQueueForHash(pSampleConfiguration->pPendingSignalingMessageForRemoteClient, clientIdHash, TRUE,
                                                         &pPendingMessageQueue));
                CHK(FALSE, retStatus);
            }

            CHK_STATUS(createSampleStreamingSession(pSampleConfiguration, pReceivedSignalingMessage->signalingMessage.peerClientId, TRUE,
                                                    &pSampleStreamingSession));
            freeStreamingSession = TRUE;
            CHK_STATUS(txing_attach_session(handle, pSampleStreamingSession));
            CHK_STATUS(handleOffer(pSampleConfiguration, pSampleStreamingSession, &pReceivedSignalingMessage->signalingMessage));
            CHK_STATUS(hashTablePut(pSampleConfiguration->pRtcPeerConnectionForRemoteClient, clientIdHash, (UINT64) pSampleStreamingSession));

            CHK_STATUS(getPendingMessageQueueForHash(pSampleConfiguration->pPendingSignalingMessageForRemoteClient, clientIdHash, TRUE,
                                                     &pPendingMessageQueue));
            if (pPendingMessageQueue != NULL) {
                CHK_STATUS(submitPendingIceCandidate(pPendingMessageQueue, pSampleStreamingSession));
                pPendingMessageQueue = NULL;
            }

            MUTEX_LOCK(pSampleConfiguration->streamingSessionListReadLock);
            pSampleConfiguration->sampleStreamingSessionList[pSampleConfiguration->streamingSessionCount++] = pSampleStreamingSession;
            MUTEX_UNLOCK(pSampleConfiguration->streamingSessionListReadLock);
            freeStreamingSession = FALSE;
            startStats = pSampleConfiguration->iceCandidatePairStatsTimerId == MAX_UINT32;
            break;

        case SIGNALING_MESSAGE_TYPE_ANSWER:
            pSampleStreamingSession = pSampleConfiguration->sampleStreamingSessionList[0];
            CHK_STATUS(handleAnswer(pSampleConfiguration, pSampleStreamingSession, &pReceivedSignalingMessage->signalingMessage));
            CHK_STATUS(hashTablePut(pSampleConfiguration->pRtcPeerConnectionForRemoteClient, clientIdHash, (UINT64) pSampleStreamingSession));
            CHK_STATUS(getPendingMessageQueueForHash(pSampleConfiguration->pPendingSignalingMessageForRemoteClient, clientIdHash, TRUE,
                                                     &pPendingMessageQueue));
            if (pPendingMessageQueue != NULL) {
                CHK_STATUS(submitPendingIceCandidate(pPendingMessageQueue, pSampleStreamingSession));
                pPendingMessageQueue = NULL;
            }

            startStats = pSampleConfiguration->iceCandidatePairStatsTimerId == MAX_UINT32;
            CHK_STATUS(signalingClientGetMetrics(pSampleConfiguration->signalingClientHandle, &pSampleConfiguration->signalingClientMetrics));
            break;

        case SIGNALING_MESSAGE_TYPE_ICE_CANDIDATE:
            if (!peerConnectionFound) {
                CHK_STATUS(getPendingMessageQueueForHash(pSampleConfiguration->pPendingSignalingMessageForRemoteClient, clientIdHash, FALSE,
                                                         &pPendingMessageQueue));
                if (pPendingMessageQueue == NULL) {
                    CHK_STATUS(createMessageQueue(clientIdHash, &pPendingMessageQueue));
                    CHK_STATUS(stackQueueEnqueue(pSampleConfiguration->pPendingSignalingMessageForRemoteClient, (UINT64) pPendingMessageQueue));
                }

                pReceivedSignalingMessageCopy = (PReceivedSignalingMessage) MEMCALLOC(1, SIZEOF(ReceivedSignalingMessage));
                *pReceivedSignalingMessageCopy = *pReceivedSignalingMessage;
                CHK_STATUS(stackQueueEnqueue(pPendingMessageQueue->messageQueue, (UINT64) pReceivedSignalingMessageCopy));
                pPendingMessageQueue = NULL;
                pReceivedSignalingMessageCopy = NULL;
            } else {
                CHK_STATUS(handleRemoteCandidate(pSampleStreamingSession, &pReceivedSignalingMessage->signalingMessage));
            }
            break;

        default:
            DLOGD("Unhandled signaling message type %u", pReceivedSignalingMessage->signalingMessage.messageType);
            break;
    }

    MUTEX_UNLOCK(pSampleConfiguration->sampleConfigurationObjLock);
    locked = FALSE;

    if (pSampleConfiguration->enableIceStats && startStats &&
        STATUS_FAILED(retStatus = timerQueueAddTimer(pSampleConfiguration->timerQueueHandle, SAMPLE_STATS_DURATION, SAMPLE_STATS_DURATION,
                                                     getIceCandidatePairStatsCallback, (UINT64) pSampleConfiguration,
                                                     &pSampleConfiguration->iceCandidatePairStatsTimerId))) {
        DLOGW("Failed to add getIceCandidatePairStatsCallback to add to timer queue (code 0x%08x). "
              "Cannot pull ice candidate pair metrics periodically",
              retStatus);
        retStatus = STATUS_SUCCESS;
    }

CleanUp:
    SAFE_MEMFREE(pReceivedSignalingMessageCopy);
    if (pPendingMessageQueue != NULL) {
        freeMessageQueue(pPendingMessageQueue);
    }
    if (freeStreamingSession && pSampleStreamingSession != NULL) {
        freeSampleStreamingSession(&pSampleStreamingSession);
    }
    if (locked) {
        MUTEX_UNLOCK(pSampleConfiguration->sampleConfigurationObjLock);
    }
    if (STATUS_FAILED(retStatus) && handle != NULL) {
        txing_report_error(handle, "signaling message processing failed (status=0x%08x)", retStatus);
    }
    CHK_LOG_ERR(retStatus);
    return retStatus;
}

static STATUS txing_signaling_client_error(UINT64 customData, STATUS status, PCHAR msg, UINT32 msgLen)
{
    STATUS retStatus = signalingClientError(customData, status, msg, msgLen);
    PSampleConfiguration pSampleConfiguration = (PSampleConfiguration) customData;
    txing_kvs_handle* handle = pSampleConfiguration == NULL ? NULL : (txing_kvs_handle*) pSampleConfiguration->customData;

    if (handle != NULL && status != STATUS_SIGNALING_ICE_CONFIG_REFRESH_FAILED && status != STATUS_SIGNALING_RECONNECT_FAILED) {
        txing_report_error(handle, "signaling client error 0x%08x: %.*s", status, msgLen, msg == NULL ? "" : msg);
    }

    return retStatus;
}

static VOID txing_on_connection_state_change(UINT64 customData, RTC_PEER_CONNECTION_STATE newState)
{
    PSampleStreamingSession session = (PSampleStreamingSession) customData;
    txing_kvs_handle* handle = NULL;

    onConnectionStateChange(customData, newState);
    if (session == NULL || session->pSampleConfiguration == NULL) {
        return;
    }

    handle = (txing_kvs_handle*) session->pSampleConfiguration->customData;
    if (handle == NULL) {
        return;
    }

    switch (newState) {
        case RTC_PEER_CONNECTION_STATE_CONNECTED:
            txing_update_viewer_state(handle, session, TRUE);
            break;
        case RTC_PEER_CONNECTION_STATE_FAILED:
        case RTC_PEER_CONNECTION_STATE_CLOSED:
        case RTC_PEER_CONNECTION_STATE_DISCONNECTED:
            txing_update_viewer_state(handle, session, FALSE);
            break;
        default:
            break;
    }
}

static VOID txing_on_streaming_session_shutdown(UINT64 customData, PSampleStreamingSession pSampleStreamingSession)
{
    txing_kvs_handle* handle = (txing_kvs_handle*) customData;

    if (handle == NULL && pSampleStreamingSession != NULL && pSampleStreamingSession->pSampleConfiguration != NULL) {
        handle = (txing_kvs_handle*) pSampleStreamingSession->pSampleConfiguration->customData;
    }
    if (handle == NULL || pSampleStreamingSession == NULL) {
        return;
    }

    txing_update_viewer_state(handle, pSampleStreamingSession, FALSE);
    txing_remove_session(handle, pSampleStreamingSession);
}

static PVOID txing_cleanup_routine(PVOID customData)
{
    txing_kvs_handle* handle = (txing_kvs_handle*) customData;
    STATUS status;

    if (handle == NULL || handle->sample_configuration == NULL) {
        return (PVOID) (uintptr_t) STATUS_NULL_ARG;
    }

    status = sessionCleanupWait(handle->sample_configuration);
    if (STATUS_FAILED(status) && !handle->stopping) {
        txing_report_error(handle, "session cleanup loop failed (status=0x%08x)", status);
    }

    return (PVOID) (uintptr_t) status;
}

static CHAR* txing_strdup(const CHAR* source)
{
    size_t length;
    CHAR* copy;

    if (source == NULL) {
        return NULL;
    }

    length = STRLEN(source) + 1;
    copy = (CHAR*) MEMALLOC(length);
    if (copy == NULL) {
        return NULL;
    }
    MEMCPY(copy, source, length);
    return copy;
}

static void txing_free_handle(txing_kvs_handle* handle)
{
    if (handle == NULL) {
        return;
    }

    SAFE_MEMFREE(handle->region);
    SAFE_MEMFREE(handle->channel_name);
    SAFE_MEMFREE(handle->client_id);
    SAFE_MEMFREE(handle->access_key_id);
    SAFE_MEMFREE(handle->secret_access_key);
    SAFE_MEMFREE(handle->session_token);

    if (IS_VALID_MUTEX_VALUE(handle->lock)) {
        MUTEX_FREE(handle->lock);
    }
    SAFE_MEMFREE(handle);
}

static STATUS txing_apply_aws_environment(const txing_kvs_handle* handle)
{
    STATUS retStatus = STATUS_SUCCESS;

    CHK(handle != NULL && handle->region != NULL && handle->access_key_id != NULL && handle->secret_access_key != NULL, STATUS_NULL_ARG);
    CHK_ERR(setenv("AWS_DEFAULT_REGION", handle->region, 1) == 0, STATUS_INVALID_OPERATION, "failed to set AWS_DEFAULT_REGION");
    CHK_ERR(setenv("AWS_REGION", handle->region, 1) == 0, STATUS_INVALID_OPERATION, "failed to set AWS_REGION");
    CHK_ERR(setenv("AWS_ACCESS_KEY_ID", handle->access_key_id, 1) == 0, STATUS_INVALID_OPERATION, "failed to set AWS_ACCESS_KEY_ID");
    CHK_ERR(setenv("AWS_SECRET_ACCESS_KEY", handle->secret_access_key, 1) == 0, STATUS_INVALID_OPERATION,
            "failed to set AWS_SECRET_ACCESS_KEY");

    if (handle->session_token != NULL && handle->session_token[0] != '\0') {
        CHK_ERR(setenv("AWS_SESSION_TOKEN", handle->session_token, 1) == 0, STATUS_INVALID_OPERATION,
                "failed to set AWS_SESSION_TOKEN");
    } else {
        unsetenv("AWS_SESSION_TOKEN");
    }

CleanUp:
    return retStatus;
}

static void txing_report_error(txing_kvs_handle* handle, const CHAR* format, ...)
{
    CHAR buffer[512];
    va_list arguments;

    if (handle == NULL || handle->callbacks.on_error == NULL) {
        return;
    }

    va_start(arguments, format);
    VSNPRINTF(buffer, ARRAY_SIZE(buffer), format, arguments);
    va_end(arguments);
    handle->callbacks.on_error(handle->callbacks.user_data, buffer);
}

static STATUS txing_attach_session(txing_kvs_handle* handle, PSampleStreamingSession session)
{
    STATUS retStatus = STATUS_SUCCESS;
    UINT32 index;

    CHK(handle != NULL && session != NULL, STATUS_NULL_ARG);
    CHK_STATUS(streamingSessionOnShutdown(session, (UINT64) handle, txing_on_streaming_session_shutdown));
    CHK_STATUS(peerConnectionOnConnectionStateChange(session->pPeerConnection, (UINT64) session, txing_on_connection_state_change));

    MUTEX_LOCK(handle->lock);
    for (index = 0; index < ARRAY_SIZE(handle->trackers); ++index) {
        if (handle->trackers[index].session == session) {
            MUTEX_UNLOCK(handle->lock);
            return STATUS_SUCCESS;
        }
        if (handle->trackers[index].session == NULL) {
            handle->trackers[index].session = session;
            handle->trackers[index].connected = FALSE;
            break;
        }
    }
    MUTEX_UNLOCK(handle->lock);
    CHK(index < ARRAY_SIZE(handle->trackers), STATUS_NOT_ENOUGH_MEMORY);

CleanUp:
    return retStatus;
}

static void txing_update_viewer_state(txing_kvs_handle* handle, PSampleStreamingSession session, BOOL connected)
{
    UINT32 index;
    UINT32 previous_viewer_count = 0;
    UINT32 viewer_count = 0;
    BOOL emit_connected = FALSE;
    BOOL emit_disconnected = FALSE;
    const CHAR* peer_id = NULL;

    if (handle == NULL || session == NULL) {
        return;
    }

    MUTEX_LOCK(handle->lock);
    for (index = 0; index < ARRAY_SIZE(handle->trackers); ++index) {
        if (handle->trackers[index].session == session) {
            break;
        }
    }
    if (index == ARRAY_SIZE(handle->trackers)) {
        MUTEX_UNLOCK(handle->lock);
        return;
    }
    if (handle->trackers[index].connected == connected) {
        MUTEX_UNLOCK(handle->lock);
        return;
    }

    previous_viewer_count = handle->viewer_count;
    handle->trackers[index].connected = connected;
    if (connected) {
        handle->viewer_count++;
    } else if (handle->viewer_count > 0) {
        handle->viewer_count--;
    }

    viewer_count = handle->viewer_count;
    peer_id = session->peerId;
    emit_connected = previous_viewer_count == 0 && viewer_count > 0;
    emit_disconnected = previous_viewer_count > 0 && viewer_count == 0;
    MUTEX_UNLOCK(handle->lock);

    if (emit_connected && handle->callbacks.on_viewer_count_changed != NULL) {
        handle->callbacks.on_viewer_count_changed(handle->callbacks.user_data, peer_id, viewer_count, true);
    }
    if (emit_disconnected && handle->callbacks.on_viewer_count_changed != NULL) {
        handle->callbacks.on_viewer_count_changed(handle->callbacks.user_data, peer_id, viewer_count, false);
    }
}

static void txing_remove_session(txing_kvs_handle* handle, PSampleStreamingSession session)
{
    UINT32 index;

    if (handle == NULL || session == NULL) {
        return;
    }

    MUTEX_LOCK(handle->lock);
    for (index = 0; index < ARRAY_SIZE(handle->trackers); ++index) {
        if (handle->trackers[index].session == session) {
            handle->trackers[index].session = NULL;
            handle->trackers[index].connected = FALSE;
            break;
        }
    }
    MUTEX_UNLOCK(handle->lock);
}
