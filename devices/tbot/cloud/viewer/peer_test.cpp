#include "viewer.hpp"
#include <iostream>
#include <thread>

using namespace std::chrono_literals;
static void Require(bool value, const char *why) {
  if (!value)
    throw std::runtime_error(why);
}
template <class Predicate> static void Await(Predicate pred, const char *why) {
  for (int n = 0; n < 300 && !pred(); n++)
    std::this_thread::sleep_for(20ms);
  Require(pred(), why);
}
struct Master {
  PRtcPeerConnection peer = nullptr;
  PRtcRtpTransceiver track = nullptr;
  std::atomic<PRtcDataChannel> data{nullptr};
  std::atomic<bool> gathered{false};
  std::atomic<int> received{0};
  std::atomic<bool> connected{false};
  explicit Master(bool video) {
    RtcConfiguration config{};
    config.kvsRtcConfiguration.iceLocalCandidateGatheringTimeout =
        2 * HUNDREDS_OF_NANOS_IN_A_SECOND;
    txing::Check(createPeerConnection(&config, &peer), "test master peer");
    txing::Check(peerConnectionOnConnectionStateChange(
                     peer, reinterpret_cast<UINT64>(this),
                     [](UINT64 d, RTC_PEER_CONNECTION_STATE state) {
                       if (state == RTC_PEER_CONNECTION_STATE_CONNECTED)
                         reinterpret_cast<Master *>(d)->connected = true;
                     }),
                 "test master connection callback");
    txing::Check(peerConnectionOnIceCandidate(
                     peer, reinterpret_cast<UINT64>(this),
                     [](UINT64 d, PCHAR c) {
                       if (!c)
                         reinterpret_cast<Master *>(d)->gathered = true;
                     }),
                 "test ICE callback");
    txing::Check(peerConnectionOnDataChannel(
                     peer, reinterpret_cast<UINT64>(this),
                     [](UINT64 d, PRtcDataChannel c) {
                       auto *s = reinterpret_cast<Master *>(d);
                       s->data = c;
                       dataChannelOnMessage(
                           c, d,
                           [](UINT64 x, PRtcDataChannel, BOOL, PBYTE, UINT32) {
                             reinterpret_cast<Master *>(x)->received++;
                           });
                     }),
                 "test data callback");
    if (video) {
      txing::Check(
          addSupportedCodec(
              peer,
              RTC_CODEC_H264_PROFILE_42E01F_LEVEL_ASYMMETRY_ALLOWED_PACKETIZATION_MODE),
          "test codec");
      RtcMediaStreamTrack media{};
      media.kind = MEDIA_STREAM_TRACK_KIND_VIDEO;
      media.codec =
          RTC_CODEC_H264_PROFILE_42E01F_LEVEL_ASYMMETRY_ALLOWED_PACKETIZATION_MODE;
      std::strcpy(media.streamId, "txing-video");
      std::strcpy(media.trackId, "video");
      RtcRtpTransceiverInit init{};
      init.direction = RTC_RTP_TRANSCEIVER_DIRECTION_SENDONLY;
      txing::Check(addTransceiver(peer, &media, &init, &track),
                   "test video sender");
    }
  }
  ~Master() {
    if (peer) {
      closePeerConnection(peer);
      freePeerConnection(&peer);
    }
  }
  std::string Answer(const std::string &json) {
    RtcSessionDescriptionInit offer{};
    txing::Check(deserializeSessionDescriptionInit(
                     const_cast<PCHAR>(json.c_str()),
                     static_cast<UINT32>(json.size()), &offer),
                 "test offer decode");
    txing::Check(setRemoteDescription(peer, &offer), "test remote offer");
    RtcSessionDescriptionInit answer{};
    answer.useTrickleIce = FALSE;
    txing::Check(setLocalDescription(peer, &answer), "test local answer");
    Await([this] { return gathered.load(); }, "master ICE gathering timed out");
    txing::Check(createAnswer(peer, &answer), "test answer");
    UINT32 size = 0;
    txing::Check(serializeSessionDescriptionInit(&answer, nullptr, &size),
                 "test answer size");
    std::string result(size, '\0');
    txing::Check(serializeSessionDescriptionInit(&answer, result.data(), &size),
                 "test answer serialize");
    result.resize(size - 1);
    return result;
  }
};
static void CredentialsRotate(txing::Credentials &c) {
  const auto expiry = GETTIME() / HUNDREDS_OF_NANOS_IN_A_SECOND + 3600;
  c.Update(
      {"TESTKEY1", "test-secret-1", "test-session-1", std::to_string(expiry)});
  PAwsCredentials value = nullptr;
  txing::Check(c.getCredentialsFn(&c, &value), "initial temporary credentials");
  Require(std::string(value->accessKeyId) == "TESTKEY1",
          "wrong initial credentials");
  c.Update({"TESTKEY2", "test-secret-2", "test-session-2",
            std::to_string(expiry + 3600)});
  txing::Check(c.getCredentialsFn(&c, &value), "rotated temporary credentials");
  Require(std::string(value->accessKeyId) == "TESTKEY2",
          "credentials did not rotate");
  c.Update({"EXPIRED", "secret", "session", "1"});
  Require(STATUS_FAILED(c.getCredentialsFn(&c, &value)),
          "expired credentials accepted");
}
static void MAVLink() {
  Master master(false);
  std::atomic<bool> connected{false};
  std::mutex mutex;
  std::vector<std::pair<char, std::string>> messages;
  txing::Viewer viewer(false, [&](char k, const std::string &p) {
    if (k == 'S' && p == "connected")
      connected = true;
    if (k == 'B' || k == 'J') {
      std::lock_guard<std::mutex> lock(mutex);
      messages.emplace_back(k, p);
    }
  });
  viewer.Peer(RtcConfiguration{});
  auto offer = viewer.Offer();
  Require(offer.find("m=application") != std::string::npos,
          "MAVLink SDP missing application");
  Require(offer.find("m=video") == std::string::npos,
          "MAVLink SDP unexpectedly has video");
  if (std::getenv("TXING_TEST_SDK_LOG"))
    std::cerr << "OFFER " << offer << "\n";
  auto answer = master.Answer(offer);
  if (std::getenv("TXING_TEST_SDK_LOG"))
    std::cerr << "ANSWER " << answer << "\n";
  viewer.Answer(answer);
  Await([&] { return connected.load() && master.data.load() != nullptr; },
        "reliable MAVLink channel did not open");
  std::this_thread::sleep_for(200ms);
  Require(master.received == 0,
          "observer sent uplink or acquired control on open");
  // A full, signed MAVLink 2 frame; the tunnel preserves even unfamiliar
  // dialects.
  const unsigned char signedFrame[] = {0xfd, 0, 1, 0,  42, 1,  1, 0x12, 0x34,
                                       0x56, 0, 0, 1,  2,  3,  4, 5,    6,
                                       7,    8, 9, 10, 11, 12, 13};
  std::string binary(reinterpret_cast<const char *>(signedFrame),
                     sizeof(signedFrame));
  const std::string json = "{\"op\":\"control.status\",\"active\":false}";
  txing::Check(dataChannelSend(master.data, true,
                               reinterpret_cast<PBYTE>(binary.data()),
                               binary.size()),
               "test send telemetry");
  txing::Check(
      dataChannelSend(master.data, false,
                      reinterpret_cast<PBYTE>(const_cast<char *>(json.data())),
                      json.size()),
      "test send JSON");
  Await(
      [&] {
        std::lock_guard<std::mutex> lock(mutex);
        return messages.size() == 2;
      },
      "telemetry did not reach viewer");
  {
    std::lock_guard<std::mutex> lock(mutex);
    Require(messages[0] == std::make_pair('B', binary) &&
                messages[1] == std::make_pair('J', json),
            "message boundaries or signed bytes changed");
  }
  txing::Credentials credentials;
  CredentialsRotate(credentials);
  Require(connected, "credential rotation reset peer");
  viewer.Send(true, binary);
  Await([&] { return master.received == 1; },
        "future uplink hook did not work");
  std::cout << "MAVLink: real SCTP ordered binary/JSON reception; observer "
               "startup; signed bytes; credential rotation passed\n";
}
static void Video() {
  Master master(true);
  txing::Viewer viewer(true, [](char, const std::string &) {});
  viewer.Peer(RtcConfiguration{});
  auto offer = viewer.Offer();
  Require(offer.find("recvonly") != std::string::npos,
          "video viewer is not receive-only");
  viewer.Answer(master.Answer(offer));
  Await([&] { return master.connected.load(); }, "video peer did not connect");
  // Small Annex-B IDR NAL. The receiving SDK assembles media; no decoder is
  // used.
  BYTE bytes[] = {0, 0, 0, 1, 0x65, 0x88, 0x84, 0, 0x21, 0, 0};
  for (UINT64 n = 0; n < 150 && viewer.Frames() == 0; n++) {
    Frame frame{};
    frame.version = FRAME_CURRENT_VERSION;
    frame.index = n;
    frame.flags = FRAME_FLAG_KEY_FRAME;
    frame.decodingTs = frame.presentationTs =
        n * HUNDREDS_OF_NANOS_IN_A_SECOND / 30;
    frame.duration = HUNDREDS_OF_NANOS_IN_A_SECOND / 30;
    frame.size = sizeof(bytes);
    frame.frameData = bytes;
    txing::Check(writeFrame(master.track, &frame), "test video frame");
    std::this_thread::sleep_for(40ms);
  }
  Require(viewer.Frames() > 0, "H264 frames were not received/discarded");
  Require(master.data.load() == nullptr, "video viewer opened a data channel");
  std::cout
      << "Video: real H264 receive-only callback and frame discard passed\n";
}
int main() {
  SET_LOGGER_LOG_LEVEL(std::getenv("TXING_TEST_SDK_LOG") ? LOG_LEVEL_DEBUG
                                                         : LOG_LEVEL_SILENT);
  try {
    txing::Check(initKvsWebRtc(), "test SDK init");
    MAVLink();
    Video();
    deinitKvsWebRtc();
    return 0;
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    deinitKvsWebRtc();
    return 1;
  }
}
