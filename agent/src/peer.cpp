#include "agent/kvs.hpp"
#include <cstring>
#include <stdexcept>

namespace txing::agent {
struct Peer::Impl {
    TransportConfig config;
    TransportEvents events;
    Candidate on_candidate;
    std::function<void(Connection)> on_state;
    PRtcPeerConnection peer = nullptr;
    std::atomic<PRtcDataChannel> channel{nullptr};
    PRtcRtpTransceiver video = nullptr;
    std::mutex mutex;
    static Impl& self(UINT64 p) { return *reinterpret_cast<Impl*>(p); }
    static void ice(UINT64 p, PCHAR c) noexcept {
        auto& s = self(p);
        try { if (c) s.on_candidate(c); } catch (...) { s.on_state(Connection::failed); }
    }
    static void state(UINT64 p, RTC_PEER_CONNECTION_STATE value) noexcept {
        auto& s = self(p);
        if (value == RTC_PEER_CONNECTION_STATE_CONNECTED && s.config.media == Media::h264) {
            s.on_state(Connection::connected);
        } else if (value == RTC_PEER_CONNECTION_STATE_FAILED || value == RTC_PEER_CONNECTION_STATE_DISCONNECTED ||
                   value == RTC_PEER_CONNECTION_STATE_CLOSED) s.on_state(Connection::failed);
    }
    static void open(UINT64 p, PRtcDataChannel) noexcept {
        auto& s = self(p);
        // SDK callbacks must not take the send/close mutex: SCTP can invoke an
        // open callback synchronously while processing outbound traffic.
        s.on_state(Connection::connected);
    }
    static void message(UINT64 p, PRtcDataChannel, BOOL binary, PBYTE bytes, UINT32 size) noexcept {
        auto& s = self(p);
        try {
            if (size > 4096) { s.on_state(Connection::failed); return; }
            if (s.events.data) s.events.data(Bytes(bytes, bytes + size), binary);
        } catch (...) { s.on_state(Connection::failed); }
    }
    static void incoming_channel(UINT64 p, PRtcDataChannel channel) noexcept {
        auto& s = self(p);
        if (s.config.label != channel->name) { s.on_state(Connection::failed); return; }
        // Peer is only destroyed after its transport stops all senders.
        s.channel = channel;
        dataChannelOnMessage(channel, p, message);
        s.on_state(Connection::connected);
    }
    static void frame(UINT64 p, PFrame f) noexcept {
        auto& s = self(p);
        try {
            if (!f || f->size > 2 * 1024 * 1024) return;
            if (s.events.video) s.events.video({Bytes(f->frameData, f->frameData + f->size), "h264",
                                              f->presentationTs, std::chrono::system_clock::now()});
        } catch (...) { s.on_state(Connection::failed); }
    }
    ~Impl() { if (peer) { closePeerConnection(peer); freePeerConnection(&peer); } }
};

Peer::Peer(const TransportConfig& config, const RtcConfiguration& rtc, TransportEvents events,
           Candidate candidate, std::function<void(Connection)> state) : impl_(std::make_unique<Impl>()) {
    auto& s = *impl_; s.config = config; s.events = std::move(events);
    s.on_candidate = std::move(candidate); s.on_state = std::move(state);
    auto rtc_copy = rtc;
    check_kvs(createPeerConnection(&rtc_copy, &s.peer), "createPeerConnection");
    auto context = reinterpret_cast<UINT64>(&s);
    check_kvs(peerConnectionOnIceCandidate(s.peer, context, Impl::ice), "peerConnectionOnIceCandidate");
    check_kvs(peerConnectionOnConnectionStateChange(s.peer, context, Impl::state), "peerConnectionOnConnectionStateChange");
    if (config.media == Media::data) {
        if (config.role == Role::viewer) {
            RtcDataChannelInit init{}; init.ordered = TRUE;
            NULLABLE_SET_EMPTY(init.maxPacketLifeTime);
            NULLABLE_SET_EMPTY(init.maxRetransmits);
            PRtcDataChannel channel = nullptr;
            check_kvs(createDataChannel(s.peer, const_cast<PCHAR>(config.label.c_str()), &init, &channel), "createDataChannel");
            s.channel = channel;
            check_kvs(dataChannelOnOpen(channel, context, Impl::open), "dataChannelOnOpen");
            check_kvs(dataChannelOnMessage(channel, context, Impl::message), "dataChannelOnMessage");
        } else check_kvs(peerConnectionOnDataChannel(s.peer, context, Impl::incoming_channel), "peerConnectionOnDataChannel");
    } else {
        auto codec = RTC_CODEC_H264_PROFILE_42E01F_LEVEL_ASYMMETRY_ALLOWED_PACKETIZATION_MODE;
        check_kvs(addSupportedCodec(s.peer, codec), "addSupportedCodec");
        RtcMediaStreamTrack track{}; track.kind = MEDIA_STREAM_TRACK_KIND_VIDEO; track.codec = codec;
        std::strcpy(track.streamId, "agentVideo"); std::strcpy(track.trackId, "agentVideoTrack");
        RtcRtpTransceiverInit init{};
        init.direction = config.role == Role::viewer ? RTC_RTP_TRANSCEIVER_DIRECTION_RECVONLY : RTC_RTP_TRANSCEIVER_DIRECTION_SENDONLY;
        check_kvs(addTransceiver(s.peer, &track, &init, &s.video), "addTransceiver");
        if (config.role == Role::viewer) check_kvs(transceiverOnFrame(s.video, context, Impl::frame), "transceiverOnFrame");
    }
}
Peer::~Peer() = default;
std::string Peer::description(bool offer) {
    RtcSessionDescriptionInit description{}; description.useTrickleIce = TRUE;
    if (!offer) check_kvs(createAnswer(impl_->peer, &description), "createAnswer");
    check_kvs(setLocalDescription(impl_->peer, &description), "setLocalDescription");
    if (offer) check_kvs(createOffer(impl_->peer, &description), "createOffer");
    UINT32 length = 0;
    check_kvs(serializeSessionDescriptionInit(&description, nullptr, &length), "serializeSessionDescriptionInit(size)");
    std::vector<char> json(length);
    check_kvs(serializeSessionDescriptionInit(&description, json.data(), &length), "serializeSessionDescriptionInit");
    return json.data();
}
void Peer::remote_description(const std::string& json) {
    RtcSessionDescriptionInit description{};
    check_kvs(deserializeSessionDescriptionInit(const_cast<PCHAR>(json.c_str()), json.size(), &description), "deserializeSessionDescriptionInit");
    check_kvs(setRemoteDescription(impl_->peer, &description), "setRemoteDescription");
}
void Peer::candidate(const std::string& json) {
    RtcIceCandidateInit candidate{};
    check_kvs(deserializeRtcIceCandidateInit(const_cast<PCHAR>(json.c_str()), json.size(), &candidate), "deserializeRtcIceCandidateInit");
    check_kvs(addIceCandidate(impl_->peer, candidate.candidate), "addIceCandidate");
}
bool Peer::send(const Bytes& bytes, bool binary) {
    auto& s = *impl_;
    std::lock_guard<std::mutex> lock(s.mutex);
    auto channel = s.channel.load();
    return channel && bytes.size() <= 4096 &&
        STATUS_SUCCEEDED(dataChannelSend(channel, binary, const_cast<PBYTE>(bytes.data()), bytes.size()));
}
bool Peer::send_video(const EncodedVideo& video) {
    auto& s = *impl_;
    if (!s.video || s.config.role != Role::master) return false;
    Frame frame{}; frame.version = FRAME_CURRENT_VERSION; frame.flags = FRAME_FLAG_KEY_FRAME;
    frame.frameData = const_cast<PBYTE>(video.bytes.data()); frame.size = video.bytes.size();
    frame.presentationTs = video.presentation_100ns; frame.decodingTs = frame.presentationTs;
    frame.duration = HUNDREDS_OF_NANOS_IN_A_SECOND / 30;
    return STATUS_SUCCEEDED(writeFrame(s.video, &frame));
}
}
