#include "agent/core.hpp"
#include "agent/kvs.hpp"
#include "agent/manual.hpp"
#include <aws/core/utils/json/JsonSerializer.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <unistd.h>
#include <array>
#include <sstream>
#include <stdexcept>
using namespace txing::agent;
using namespace std::chrono_literals;
Bytes frame(bool);
namespace {
void require(bool ok, const char* what) { if (!ok) throw std::runtime_error(what); }
// Signaling is exchanged in memory; the production Peer, ICE/DTLS/SRTP/SCTP,
// H264 packetization and callbacks are the actual pinned C SDK.
class Pair {
public:
    std::unique_ptr<Peer> viewer, master;
    std::atomic<Connection> viewer_state{Connection::connecting}, master_state{Connection::connecting};
    std::atomic<int> actions{0}, releases{0};
    std::atomic<bool> frame_preserved{false};
    Pair(TransportConfig config, TransportEvents events) {
        RtcConfiguration rtc{};
        viewer = std::make_unique<Peer>(config, rtc, std::move(events), [this](std::string c) {
            std::lock_guard<std::mutex> lock(mutex); to_master.push_back(std::move(c));
        }, [this](Connection state) { viewer_state = state; });
        auto master_config = config; master_config.role = Role::master;
        TransportEvents master_events;
        master_events.data = [this](Bytes bytes, bool binary) {
            if (binary) { frame_preserved = bytes == frame(true); ++actions; return; }
            // This models only board authorization; transport is real SDK.
            Aws::Utils::Json::JsonValue json(std::string(bytes.begin(), bytes.end()).c_str());
            auto v = json.View(); const auto type = v.GetString("type");
            if (type == "control.release_active") { ++releases; return; }
            const std::string response_type = type == "control.activate" ? "control.activated" : "control.renewed";
            const std::string response = "{\"type\":\"" + response_type + "\",\"requestId\":\"" +
                std::string(v.GetString("requestId").c_str()) +
                "\",\"state\":{\"epoch\":9,\"leaseTtlMs\":5000,\"activeControl\":{\"sessionId\":\"real-peer\",\"actor\":\"test\",\"epoch\":9}}}";
            master->send(Bytes(response.begin(), response.end()), false);
        };
        master = std::make_unique<Peer>(master_config, rtc, std::move(master_events), [this](std::string c) {
            std::lock_guard<std::mutex> lock(mutex); to_viewer.push_back(std::move(c));
        }, [this](Connection state) { master_state = state; });
        const auto offer = viewer->description(true);
        master->remote_description(offer);
        const auto answer = master->description(false);
        viewer->remote_description(answer);
        worker = std::thread([this] {
            try {
                while (!stop) {
                    std::vector<std::string> v, m;
                    { std::lock_guard<std::mutex> lock(mutex); v.swap(to_viewer); m.swap(to_master); }
                    for (const auto& c : v) viewer->candidate(c);
                    for (const auto& c : m) master->candidate(c);
                    std::this_thread::sleep_for(2ms);
                }
            } catch (...) { viewer_state = Connection::failed; }
        });
    }
    ~Pair() {
        stop = true; if (worker.joinable()) worker.join();
        // Peer callbacks still reference Pair, which outlives these resets.
        viewer.reset(); master.reset();
    }
private:
    std::mutex mutex;
    std::vector<std::string> to_viewer, to_master;
    std::atomic<bool> stop{false};
    std::thread worker;
};
class LocalTransport : public Transport {
public:
    std::shared_ptr<Pair>* output;
    std::shared_ptr<Pair> pair;
    explicit LocalTransport(std::shared_ptr<Pair>* p) : output(p) {}
    void start(const TransportConfig& config, TransportEvents events) override {
        pair = std::make_shared<Pair>(config, std::move(events)); *output = pair;
    }
    void stop() noexcept override { pair.reset(); }
    bool finished() const override { return true; }
    Connection state() const override { return pair ? pair->viewer_state.load() : Connection::stopped; }
    std::string error() const override { return "local SDK peer failed"; }
    bool send(const Bytes& b, bool binary) override { return pair && pair->viewer->send(b, binary); }
};
class TestOperator : public Operator {
public:
    Actions* actions = nullptr;
    std::atomic<int> telemetry_frames{0}, video_frames{0}, granted{0}, lost{0};
    std::atomic<bool> metadata_valid{false};
    void telemetry(const Bytes& b) override { if (valid_mavlink2(b)) ++telemetry_frames; }
    void video(const EncodedVideo& v) override {
        metadata_valid = v.codec == "h264" && v.bytes.size() >= 6 &&
                         v.received.time_since_epoch().count() > 0;
        ++video_frames;
    }
    void connection(Stream, Connection, const std::string&) override {}
    void control(bool held, const std::string&) override {
        if (!held) { ++lost; return; }
        ++granted;
        actions->send(frame(true));
    }
};
}
void sdk_peers() {
    TestOperator op;
    std::shared_ptr<Pair> telemetry, video;
    int index = 0;
    Session session(profile("tbot", "local-test", "eu-central-1", "not-used"), [&] {
        return std::make_unique<LocalTransport>(index++ == 0 ? &telemetry : &video);
    }, op, std::chrono::steady_clock::now());
    struct Cleanup {
        Session& session;
        std::shared_ptr<Pair>& telemetry;
        std::shared_ptr<Pair>& video;
        ~Cleanup() { session.shutdown("test cleanup"); telemetry.reset(); video.reset(); }
    } cleanup{session, telemetry, video};
    op.actions = &session;
    const auto deadline = std::chrono::steady_clock::now() + 12s;
    bool requested = false;
    Bytes telemetry_frame(12, 0); telemetry_frame[0] = 0xfd;
    EncodedVideo encoded{{0,0,0,1,0x65,0x88,0x84,0,0x10,0xff,0xff}, "h264", 10000000, {}};
    while (std::chrono::steady_clock::now() < deadline) {
        const auto now = std::chrono::steady_clock::now();
        session.verified({true, 1}, now); require(session.tick(now), "SDK peer session stopped");
        if (telemetry && telemetry->master_state == Connection::connected) {
            telemetry->master->send(telemetry_frame, true);
            if (!requested && telemetry->viewer_state == Connection::connected) {
                session.acquire("test-operator"); requested = true;
            }
        }
        if (video && video->master_state == Connection::connected) {
            video->master->send_video(encoded); encoded.presentation_100ns += 333333;
        }
        if (op.telemetry_frames > 0 && op.video_frames > 0 && telemetry->actions > 0) break;
        std::this_thread::sleep_for(20ms);
    }
    require(op.telemetry_frames > 0, "real SDK telemetry missing");
    require(op.video_frames > 0 && op.metadata_valid, "real SDK encoded video/metadata missing");
    require(op.granted == 1 && telemetry->actions > 0 && telemetry->frame_preserved,
            "substitute operator signed authorized action missing/corrupted");
    session.release(); session.tick(std::chrono::steady_clock::now());
    const auto release_deadline = std::chrono::steady_clock::now() + 1s;
    while (!telemetry->releases && std::chrono::steady_clock::now() < release_deadline) std::this_thread::sleep_for(5ms);
    require(telemetry->releases == 1, "real SDK graceful lease release missing");
    const auto previous_telemetry = op.telemetry_frames.load();
    auto now = std::chrono::steady_clock::now();
    session.verified({true, 2}, now); session.tick(now);
    video.reset(); // Destroy both video SDK peers while telemetry stays alive.
    const auto telemetry_deadline = std::chrono::steady_clock::now() + 1s;
    while (op.telemetry_frames == previous_telemetry && std::chrono::steady_clock::now() < telemetry_deadline) {
        telemetry->master->send(telemetry_frame, true);
        session.tick(std::chrono::steady_clock::now()); std::this_thread::sleep_for(5ms);
    }
    require(op.telemetry_frames > previous_telemetry, "video teardown broke healthy SDK telemetry");
    session.shutdown("SDK test complete");
    // Destroy peers while the session's callback queues and the process SDK
    // are still alive. Stopping one must leave the other SDK peer operational.
    telemetry.reset();
}

void sdk_manual() {
    // Real UDP -> ManualOperator -> Session/Actions -> pinned SCTP/DTLS peers,
    // and real H.264 delivery to that same manual operator. No AWS/device.
    const auto fd = socket(AF_INET, SOCK_DGRAM, 0);
    require(fd >= 0, "create QGC test socket");
    struct Socket { int fd; ~Socket() { close(fd); } } socket_guard{fd};
    sockaddr_in endpoint{}; endpoint.sin_family = AF_INET; endpoint.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    require(bind(fd, reinterpret_cast<sockaddr*>(&endpoint), sizeof(endpoint)) == 0, "bind QGC test socket");
    socklen_t length = sizeof(endpoint);
    require(getsockname(fd, reinterpret_cast<sockaddr*>(&endpoint), &length) == 0, "read QGC test port");
    require(fcntl(fd, F_SETFL, O_NONBLOCK) == 0, "nonblocking QGC test socket");
    std::ostringstream diagnostics;
    ManualOperator op({0, ntohs(endpoint.sin_port), true}, diagnostics);
    auto listener = endpoint; listener.sin_port = htons(op.port());
    std::shared_ptr<Pair> telemetry, video;
    int index = 0;
    Session session(profile("tbot", "local-manual-test", "eu-central-1", "not-used"), [&] {
        return std::make_unique<LocalTransport>(index++ == 0 ? &telemetry : &video);
    }, op, std::chrono::steady_clock::now());
    struct Cleanup {
        Session& session; std::shared_ptr<Pair>& telemetry; std::shared_ptr<Pair>& video;
        ~Cleanup() { session.shutdown("manual SDK cleanup"); telemetry.reset(); video.reset(); }
    } cleanup{session, telemetry, video};
    const auto bytes = frame(true);
    EncodedVideo encoded{{0,0,0,1,0x65,0x88,0x84,0,0x10,0xff,0xff}, "h264", 10000000, {}};
    bool received_without_presence = false;
    const auto deadline = std::chrono::steady_clock::now() + 12s;
    while (std::chrono::steady_clock::now() < deadline) {
        const auto now = std::chrono::steady_clock::now();
        op.poll(session, now); session.verified({true, 1}, now); require(session.tick(now), "manual SDK session stopped");
        if (telemetry && telemetry->master_state == Connection::connected) telemetry->master->send(bytes, true);
        if (video && video->master_state == Connection::connected) {
            video->master->send_video(encoded); encoded.presentation_100ns += 333333;
        }
        std::array<std::uint8_t, 512> buffer{};
        const auto size = recv(fd, buffer.data(), buffer.size(), 0);
        if (size >= 0) {
            require(Bytes(buffer.begin(), buffer.begin() + size) == bytes, "SDK downlink signature/frame altered");
            if (!received_without_presence) {
                require(!op.status().client, "SDK telemetry waited for client presence"); received_without_presence = true;
            }
            require(sendto(fd, bytes.data(), bytes.size(), 0, reinterpret_cast<sockaddr*>(&listener), sizeof(listener)) ==
                    static_cast<ssize_t>(bytes.size()), "send QGC SDK test frame");
        }
        if (telemetry && telemetry->actions > 0 && op.status().video > 0) break;
        std::this_thread::sleep_for(20ms);
    }
    require(received_without_presence && op.status().telemetry > 0 && op.status().video > 0, "manual SDK observations missing");
    require(op.status().held && telemetry->actions > 0 && telemetry->frame_preserved, "manual SDK authorized frame missing/corrupt");
    op.disconnect(session, "manual SDK test disconnect"); session.tick(std::chrono::steady_clock::now());
    const auto released = std::chrono::steady_clock::now() + 1s;
    while (!telemetry->releases && std::chrono::steady_clock::now() < released) std::this_thread::sleep_for(5ms);
    require(telemetry->releases == 1, "manual SDK disconnect did not release");
}
