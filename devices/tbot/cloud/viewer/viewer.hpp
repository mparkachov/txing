#pragma once
#include <atomic>
#include <chrono>
#include <com/amazonaws/kinesis/video/common/Include.h>
#include <com/amazonaws/kinesis/video/webrtcclient/Include.h>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <deque>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

namespace txing {
inline void Check(STATUS status, const char *op) {
  if (STATUS_FAILED(status)) {
    char error[160];
    std::snprintf(error, sizeof(error), "%s failed (0x%08x)", op, status);
    throw std::runtime_error(error);
  }
}
// The provider retains one SDK credential object, like the SDK's IoT provider.
// Only getCredentialsFn replaces it; the IPC thread only updates pending
// values.
struct Credentials : AwsCredentialProvider {
  std::mutex mutex;
  std::vector<std::string> latest;
  PAwsCredentials value = nullptr;
  std::vector<std::string> loaded;
  Credentials() { getCredentialsFn = Get; }
  ~Credentials() { freeAwsCredentials(&value); }
  void Update(const std::vector<std::string> &fields) {
    if (fields.size() != 4 || fields[0].empty() || fields[1].empty() ||
        fields[2].empty())
      throw std::runtime_error("invalid temporary credentials");
    std::lock_guard<std::mutex> lock(mutex);
    latest = fields;
  }
  static STATUS Get(PAwsCredentialProvider base, PAwsCredentials *output) {
    auto *self = static_cast<Credentials *>(base);
    std::lock_guard<std::mutex> lock(self->mutex);
    if (self->latest.size() != 4)
      return STATUS_INVALID_OPERATION;
    UINT64 expires = 0;
    try {
      expires = std::stoull(self->latest[3]) * HUNDREDS_OF_NANOS_IN_A_SECOND;
    } catch (...) {
      return STATUS_INVALID_OPERATION;
    }
    if (expires <= GETTIME())
      return STATUS_INVALID_OPERATION;
    const auto &revision = self->latest;
    if (self->value == nullptr || self->loaded != revision) {
      PAwsCredentials next = nullptr;
      STATUS result = createAwsCredentials(
          self->latest[0].data(), 0, self->latest[1].data(), 0,
          self->latest[2].data(), 0, expires, &next);
      if (STATUS_FAILED(result))
        return result;
      freeAwsCredentials(&self->value);
      self->value = next;
      self->loaded = revision;
    }
    *output = self->value;
    return STATUS_SUCCESS;
  }
};
class Viewer {
public:
  using Sink = std::function<void(char, const std::string &)>;
  explicit Viewer(bool video, Sink sink)
      : video_(video), sink_(std::move(sink)) {}
  ~Viewer() { Stop(); }
  Viewer(const Viewer &) = delete;
  Viewer &operator=(const Viewer &) = delete;
  void Signaling(const std::string &channel, const std::string &region,
                 const std::string &client, const std::string &ca,
                 Credentials *credentials) {
    channel_ = channel;
    region_ = region;
    ca_ = ca;
    ChannelInfo info{};
    info.version = CHANNEL_INFO_CURRENT_VERSION;
    info.pChannelName = channel_.data();
    info.pRegion = region_.data();
    info.pCertPath = ca_.data();
    info.channelType = SIGNALING_CHANNEL_TYPE_SINGLE_MASTER;
    info.channelRoleType = SIGNALING_CHANNEL_ROLE_TYPE_VIEWER;
    info.cachingPolicy = SIGNALING_API_CALL_CACHE_TYPE_DESCRIBE_GETENDPOINT;
    info.cachingPeriod = SIGNALING_API_CALL_CACHE_TTL_SENTINEL_VALUE;
    // One worker performs one attempt. The Go supervisor owns reconnection
    // budgets.
    info.retry = FALSE;
    info.reconnect = FALSE;
    SignalingClientInfo ci{};
    ci.version = SIGNALING_CLIENT_INFO_CURRENT_VERSION;
    ci.loggingLevel = LOG_LEVEL_SILENT;
    ci.signalingClientCreationMaxRetryAttempts = 1;
    if (client.size() > MAX_SIGNALING_CLIENT_ID_LEN)
      throw std::runtime_error("viewer identity too long");
    std::strcpy(ci.clientId, client.c_str());
    SignalingClientCallbacks callbacks{};
    callbacks.version = SIGNALING_CLIENT_CALLBACKS_CURRENT_VERSION;
    callbacks.customData = reinterpret_cast<UINT64>(this);
    callbacks.messageReceivedFn = Message;
    callbacks.errorReportFn = SignalError;
    callbacks.stateChangeFn = SignalState;
    Check(createSignalingClientSync(&ci, &info, &callbacks, credentials,
                                    &signaling_),
          "create signaling viewer");
    Check(signalingClientFetchSync(signaling_), "fetch signaling endpoints");
    Check(signalingClientConnectSync(signaling_), "connect signaling viewer");
  }
  RtcConfiguration Configuration() {
    RtcConfiguration config{};
    config.iceTransportPolicy = ICE_TRANSPORT_POLICY_ALL;
    std::snprintf(config.iceServers[0].urls, sizeof(config.iceServers[0].urls),
                  "stun:stun.kinesisvideo.%s.amazonaws.com:443",
                  region_.c_str());
    UINT32 count = 0;
    Check(signalingClientGetIceConfigInfoCount(signaling_, &count),
          "get TURN configuration count");
    UINT32 index = 1;
    for (UINT32 n = 0; n < count && index < MAX_ICE_SERVERS_COUNT; n++) {
      PIceConfigInfo ice = nullptr;
      Check(signalingClientGetIceConfigInfo(signaling_, n, &ice),
            "get TURN configuration");
      if (!ice)
        continue;
      for (UINT32 uri = 0; uri < ice->uriCount && index < MAX_ICE_SERVERS_COUNT;
           uri++, index++) {
        auto &server = config.iceServers[index];
        std::snprintf(server.urls, sizeof(server.urls), "%s", ice->uris[uri]);
        std::snprintf(server.username, sizeof(server.username), "%s",
                      ice->userName);
        std::snprintf(server.credential, sizeof(server.credential), "%s",
                      ice->password);
      }
    }
    return config;
  }
  // Shared by production and the real local-peer test; no stub transport
  // exists.
  void Peer(RtcConfiguration config) {
    config.kvsRtcConfiguration.iceLocalCandidateGatheringTimeout =
        5000 * HUNDREDS_OF_NANOS_IN_A_MILLISECOND;
    config.kvsRtcConfiguration.iceConnectionCheckTimeout =
        15000 * HUNDREDS_OF_NANOS_IN_A_MILLISECOND;
    config.kvsRtcConfiguration.iceCandidateNominationTimeout =
        10000 * HUNDREDS_OF_NANOS_IN_A_MILLISECOND;
    Check(createPeerConnection(&config, &peer_), "create viewer peer");
    Check(peerConnectionOnIceCandidate(peer_, reinterpret_cast<UINT64>(this),
                                       Ice),
          "register ICE callback");
    Check(peerConnectionOnConnectionStateChange(
              peer_, reinterpret_cast<UINT64>(this), State),
          "register peer state");
    if (video_) {
      Check(
          addSupportedCodec(
              peer_,
              RTC_CODEC_H264_PROFILE_42E01F_LEVEL_ASYMMETRY_ALLOWED_PACKETIZATION_MODE),
          "support H264");
      RtcMediaStreamTrack track{};
      track.kind = MEDIA_STREAM_TRACK_KIND_VIDEO;
      track.codec =
          RTC_CODEC_H264_PROFILE_42E01F_LEVEL_ASYMMETRY_ALLOWED_PACKETIZATION_MODE;
      std::strcpy(track.streamId, "txing-video");
      std::strcpy(track.trackId, "video");
      RtcRtpTransceiverInit init{};
      init.direction = RTC_RTP_TRANSCEIVER_DIRECTION_RECVONLY;
      Check(addTransceiver(peer_, &track, &init, &videoTrack_),
            "add receive-only video");
      Check(transceiverOnFrame(videoTrack_, reinterpret_cast<UINT64>(this),
                               FrameReceived),
            "register discard callback");
    } else {
      RtcDataChannelInit init{};
      init.ordered = TRUE;
      NULLABLE_SET_EMPTY(init.maxRetransmits);
      NULLABLE_SET_EMPTY(init.maxPacketLifeTime);
      Check(createDataChannel(peer_, const_cast<PCHAR>("txing.mavlink.v1"),
                              &init, &data_),
            "create reliable MAVLink channel");
      Check(dataChannelOnOpen(data_, reinterpret_cast<UINT64>(this), DataOpen),
            "register channel open");
      Check(dataChannelOnMessage(data_, reinterpret_cast<UINT64>(this),
                                 DataReceived),
            "register telemetry callback");
    }
  }
  std::string Offer() {
    RtcSessionDescriptionInit offer{};
    offer.useTrickleIce = FALSE;
    Check(setLocalDescription(peer_, &offer), "set viewer description");
    std::unique_lock<std::mutex> lock(mutex_);
    if (!cv_.wait_for(lock, std::chrono::seconds(8),
                      [this] { return gathered_ || closed_; }) ||
        closed_)
      throw std::runtime_error("viewer ICE gathering did not complete");
    lock.unlock();
    Check(createOffer(peer_, &offer), "create viewer offer");
    UINT32 size = 0;
    Check(serializeSessionDescriptionInit(&offer, nullptr, &size),
          "size viewer offer");
    if (size > MAX_SIGNALING_MESSAGE_LEN)
      throw std::runtime_error("viewer offer exceeds signaling limit");
    std::string json(size, '\0');
    Check(serializeSessionDescriptionInit(&offer, json.data(), &size),
          "serialize viewer offer");
    json.resize(size - 1);
    return json;
  }
  void SendOffer(const std::string &offer) {
    SignalingMessage message{};
    message.version = SIGNALING_MESSAGE_CURRENT_VERSION;
    message.messageType = SIGNALING_MESSAGE_TYPE_OFFER;
    std::strcpy(message.peerClientId, "MASTER");
    message.payloadLen = static_cast<UINT32>(offer.size());
    std::memcpy(message.payload, offer.data(), offer.size());
    Check(signalingClientSendMessageSync(signaling_, &message),
          "send viewer offer");
  }
  void Answer(const std::string &json) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (answered_)
      throw std::runtime_error("duplicate viewer answer");
    RtcSessionDescriptionInit answer{};
    Check(deserializeSessionDescriptionInit(const_cast<PCHAR>(json.c_str()),
                                            static_cast<UINT32>(json.size()),
                                            &answer),
          "decode master answer");
    Check(setRemoteDescription(peer_, &answer), "apply master answer");
    answered_ = true;
    for (auto &candidate : pendingIce_)
      ApplyIce(candidate);
    pendingIce_.clear();
  }
  void RemoteIce(const std::string &json) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!answered_) {
      if (pendingIce_.size() >= 64)
        throw std::runtime_error("remote ICE queue exceeds limit");
      pendingIce_.push_back(json);
    } else
      ApplyIce(json);
  }
  void Send(bool binary, const std::string &message) {
    std::lock_guard<std::mutex> lock(sendMutex_);
    if (video_ || !open_ || closed_)
      throw std::runtime_error("MAVLink channel unavailable");
    Check(dataChannelSend(
              data_, binary ? TRUE : FALSE,
              reinterpret_cast<PBYTE>(const_cast<char *>(message.data())),
              static_cast<UINT32>(message.size())),
          "send MAVLink message");
  }
  UINT64 Frames() const { return frames_; }
  bool Closed() const { return closed_; }
  void Stop() {
    closed_ = true;
    cv_.notify_all();
    // Join signaling callbacks before freeing peer or credential provider
    // storage.
    if (IS_VALID_SIGNALING_CLIENT_HANDLE(signaling_)) {
      freeSignalingClient(&signaling_);
    }
    std::lock_guard<std::mutex> lock(sendMutex_);
    if (peer_) {
      closePeerConnection(peer_);
      freePeerConnection(&peer_);
    }
  }

private:
  void Emit(char kind, const std::string &body) { sink_(kind, body); }
  void Failure(const char *op, STATUS status) {
    char message[160];
    std::snprintf(message, sizeof(message), "%s failed (0x%08x)", op, status);
    Emit('E', message);
    closed_ = true;
    cv_.notify_all();
  }
  void ApplyIce(const std::string &json) {
    RtcIceCandidateInit candidate{};
    Check(deserializeRtcIceCandidateInit(const_cast<PCHAR>(json.c_str()),
                                         static_cast<UINT32>(json.size()),
                                         &candidate),
          "decode remote ICE");
    Check(addIceCandidate(peer_, candidate.candidate), "apply remote ICE");
  }
  static VOID Ice(UINT64 data, PCHAR candidate) {
    auto *s = reinterpret_cast<Viewer *>(data);
    if (!candidate) {
      std::lock_guard<std::mutex> lock(s->mutex_);
      s->gathered_ = true;
      s->cv_.notify_all();
    }
  }
  static VOID State(UINT64 data, RTC_PEER_CONNECTION_STATE state) {
    auto *s = reinterpret_cast<Viewer *>(data);
    if (state == RTC_PEER_CONNECTION_STATE_FAILED ||
        state == RTC_PEER_CONNECTION_STATE_DISCONNECTED ||
        state == RTC_PEER_CONNECTION_STATE_CLOSED) {
      s->open_ = false;
      s->closed_ = true;
      s->Emit('S', "disconnected");
      s->cv_.notify_all();
    }
  }
  static VOID DataOpen(UINT64 data, PRtcDataChannel) {
    auto *s = reinterpret_cast<Viewer *>(data);
    s->open_ = true;
    s->Emit('S',
            "connected"); /* Observer startup intentionally sends nothing. */
  }
  static VOID DataReceived(UINT64 data, PRtcDataChannel, BOOL binary,
                           PBYTE bytes, UINT32 size) {
    auto *s = reinterpret_cast<Viewer *>(data);
    if (size > 65536) {
      s->Failure("data message size", STATUS_INVALID_OPERATION);
      return;
    }
    s->Emit(binary ? 'B' : 'J',
            std::string(reinterpret_cast<char *>(bytes), size));
  }
  static VOID FrameReceived(UINT64 data, PFrame) {
    auto *s = reinterpret_cast<Viewer *>(data);
    if (s->frames_.fetch_add(1) == 0)
      s->Emit('S', "connected"); /* No decode, output, or storage. */
  }
  static STATUS Message(UINT64 data, PReceivedSignalingMessage received) {
    auto *s = reinterpret_cast<Viewer *>(data);
    const auto &m = received->signalingMessage;
    if (m.payloadLen > MAX_SIGNALING_MESSAGE_LEN || s->closed_)
      return STATUS_INVALID_OPERATION;
    try {
      const std::string payload(m.payload, m.payloadLen);
      if (m.messageType == SIGNALING_MESSAGE_TYPE_ANSWER)
        s->Answer(payload);
      else if (m.messageType == SIGNALING_MESSAGE_TYPE_ICE_CANDIDATE)
        s->RemoteIce(payload);
      return STATUS_SUCCESS;
    } catch (...) {
      s->Failure("receive master signaling", STATUS_INVALID_OPERATION);
      return STATUS_INVALID_OPERATION;
    }
  }
  static STATUS SignalError(UINT64 data, STATUS code, PCHAR, UINT32) {
    reinterpret_cast<Viewer *>(data)->Failure("signaling", code);
    return STATUS_SUCCESS;
  }
  static STATUS SignalState(UINT64 data, SIGNALING_CLIENT_STATE state) {
    auto *s = reinterpret_cast<Viewer *>(data);
    if (state == SIGNALING_CLIENT_STATE_CONNECTED)
      s->signalConnected_ = true;
    else if (s->signalConnected_ &&
             state == SIGNALING_CLIENT_STATE_DISCONNECTED)
      s->Failure("signaling disconnected", STATUS_INVALID_OPERATION);
    return STATUS_SUCCESS;
  }
  bool video_;
  Sink sink_;
  std::string channel_, region_, ca_;
  std::atomic<bool> open_{false}, closed_{false}, signalConnected_{false};
  std::atomic<UINT64> frames_{0};
  PRtcPeerConnection peer_ = nullptr;
  PRtcDataChannel data_ = nullptr;
  PRtcRtpTransceiver videoTrack_ = nullptr;
  SIGNALING_CLIENT_HANDLE signaling_ = INVALID_SIGNALING_CLIENT_HANDLE_VALUE;
  std::mutex mutex_, sendMutex_;
  std::condition_variable cv_;
  bool gathered_ = false, answered_ = false;
  std::vector<std::string> pendingIce_;
};
} // namespace txing
