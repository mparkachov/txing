#include "agent/manual.hpp"
#include <aws/core/Aws.h>
#include <aws/core/utils/json/JsonSerializer.h>
#include <mavlink/v2.0/common/mavlink.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <unistd.h>
#include <array>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>

using namespace txing::agent;
using namespace std::chrono_literals;
using Aws::Utils::Json::JsonValue;
#define REQUIRE(...) do { if (!(__VA_ARGS__)) throw std::runtime_error(std::string(__func__) + ": " + #__VA_ARGS__); } while (false)
template<class F> void eventually(F f) {
    const auto deadline = std::chrono::steady_clock::now() + 2s;
    while (!f()) {
        if (std::chrono::steady_clock::now() > deadline) throw std::runtime_error("manual UDP event deadline exceeded");
        std::this_thread::sleep_for(1ms);
    }
}
sockaddr_in local(unsigned port) {
    sockaddr_in a{}; a.sin_family = AF_INET; a.sin_addr.s_addr = htonl(INADDR_LOOPBACK); a.sin_port = htons(port); return a;
}
struct Client {
    int fd = -1; unsigned port;
    Client() {
        fd = socket(AF_INET, SOCK_DGRAM, 0); REQUIRE(fd >= 0);
        // macOS defaults its UDP send buffer below the truncation test size.
        const int send_buffer = 65536;
        REQUIRE(setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &send_buffer, sizeof(send_buffer)) == 0);
        auto address = local(0); REQUIRE(bind(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0);
        socklen_t length = sizeof(address); REQUIRE(getsockname(fd, reinterpret_cast<sockaddr*>(&address), &length) == 0);
        port = ntohs(address.sin_port); REQUIRE(fcntl(fd, F_SETFL, O_NONBLOCK) == 0);
    }
    ~Client() { if (fd >= 0) close(fd); }
    void send(const Bytes& bytes, unsigned port) {
        const auto address = local(port);
        REQUIRE(sendto(fd, bytes.data(), bytes.size(), 0, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) == static_cast<ssize_t>(bytes.size()));
    }
    std::optional<Bytes> receive(unsigned expected_port) {
        std::array<std::uint8_t, 1024> bytes{}; sockaddr_in source{}; socklen_t length = sizeof(source);
        const auto size = recvfrom(fd, bytes.data(), bytes.size(), 0, reinterpret_cast<sockaddr*>(&source), &length);
        if (size < 0) { REQUIRE(errno == EAGAIN || errno == EWOULDBLOCK); return {}; }
        REQUIRE(ntohs(source.sin_port) == expected_port && source.sin_addr.s_addr == htonl(INADDR_LOOPBACK));
        return Bytes(bytes.begin(), bytes.begin() + size);
    }
    void disconnect() { close(fd); fd = -1; }
};
Bytes encoded(const mavlink_message_t& message) {
    Bytes bytes(MAVLINK_MAX_PACKET_LEN);
    bytes.resize(mavlink_msg_to_send_buffer(bytes.data(), &message)); return bytes;
}
Bytes heartbeat(bool v1 = false) {
    auto* status = mavlink_get_channel_status(MAVLINK_COMM_0);
    status->flags = v1 ? MAVLINK_STATUS_FLAG_OUT_MAVLINK1 : 0;
    mavlink_message_t message{};
    mavlink_msg_heartbeat_pack_chan(255, 190, MAVLINK_COMM_0, &message, MAV_TYPE_GCS, MAV_AUTOPILOT_INVALID, 0, 0, MAV_STATE_ACTIVE);
    return encoded(message);
}
Bytes parameter_request() {
    mavlink_message_t message{};
    mavlink_get_channel_status(MAVLINK_COMM_0)->flags = 0;
    mavlink_msg_param_request_list_pack(255, 190, &message, 1, 1); return encoded(message);
}
Bytes arm(bool armed) {
    mavlink_message_t message{};
    mavlink_msg_command_long_pack(255, 190, &message, 1, 1, MAV_CMD_COMPONENT_ARM_DISARM, 0, armed ? 1 : 0, 0, 0, 0, 0, 0, 0);
    return encoded(message);
}
Bytes unfamiliar(bool signed_frame = true) {
    Bytes bytes(12 + 255 + (signed_frame ? 13 : 0));
    for (std::size_t i = 0; i < bytes.size(); ++i) bytes[i] = static_cast<std::uint8_t>(i * 53);
    bytes[0] = 0xfd; bytes[1] = 255; bytes[2] = signed_frame ? 1 : 0;
    bytes[7] = 0xfe; bytes[8] = 0xee; bytes[9] = 0x7f; return bytes;
}
struct Board {
    TransportEvents events;
    Connection connection = Connection::connected;
    bool busy = false, respond = true, send_ok = true;
    int epoch = 7, stops = 0;
    std::string error = "WebRTC loss after long healthy operation";
    std::vector<std::string> requests;
    std::vector<Bytes> binary;
    void text(const std::string& text) { events.data(Bytes(text.begin(), text.end()), false); }
    std::string state(const std::string& type, const std::string& id, int e = 7) {
        return "{\"type\":\"" + type + "\",\"requestId\":\"" + id + "\",\"state\":{\"epoch\":" + std::to_string(e) +
            ",\"leaseTtlMs\":5000,\"activeControl\":{\"sessionId\":\"manual-peer\",\"actor\":\"QGroundControl\",\"epoch\":" + std::to_string(e) + "}}}";
    }
    int count(const std::string& type) const {
        int n = 0; for (const auto& s : requests) if (s.find(type) != std::string::npos) ++n; return n;
    }
};
struct TransportStub : Transport {
    std::shared_ptr<Board> b;
    explicit TransportStub(std::shared_ptr<Board> board) : b(std::move(board)) {}
    void start(const TransportConfig&, TransportEvents events) override { b->events = std::move(events); }
    void stop() noexcept override { ++b->stops; }
    bool finished() const override { return true; }
    Connection state() const override { return b->connection; }
    std::string error() const override { return b->error; }
    bool send(const Bytes& bytes, bool binary) override {
        if (!b->send_ok) return false;
        if (binary) { b->binary.push_back(bytes); return true; }
        const std::string text(bytes.begin(), bytes.end()); b->requests.push_back(text);
        JsonValue json(text.c_str()); auto v = json.View();
        const std::string type = v.GetString("type").c_str(), id = v.GetString("requestId").c_str();
        if (type == "control.activate") {
            REQUIRE(!v.GetBool("takeover"));
            if (b->busy) b->text("{\"type\":\"control.error\",\"requestId\":\"" + id + "\",\"code\":\"control_busy\"}");
            else if (b->respond) b->text(b->state("control.activated", id, b->epoch));
        } else if (type == "control.renew_active" && b->respond) b->text(b->state("control.renewed", id, b->epoch));
        return true;
    }
};
struct Fixture {
    Client client;
    std::ostringstream diagnostics;
    ManualOperator op;
    std::vector<std::shared_ptr<Board>> boards;
    Time now = Time{} + 100s;
    Session session;
    explicit Fixture(bool control = true) : op({0, static_cast<std::uint16_t>(client.port), control}, diagnostics),
        session(profile("tbot", "fixture", "region", "ca"), [this] {
            auto b = std::make_shared<Board>(); boards.push_back(b); return std::make_unique<TransportStub>(b);
        }, op, now) { tick(); }
    void tick() { op.poll(session, now); session.verified({true, 1}, now); REQUIRE(session.tick(now)); }
    void send(const Bytes& bytes) {
        const auto before = op.status().datagrams; client.send(bytes, op.port());
        eventually([&] { tick(); return op.status().datagrams > before; });
    }
    void acquire() {
        send(heartbeat(true));
        eventually([&] { tick(); return op.status().held; });
        REQUIRE(boards[0]->count("control.activate") == 1);
        REQUIRE(boards[0]->binary.empty()); // V1 presence never enters the board.
    }
    void lost() { eventually([&] { return !op.status().held; }); }
};

void ports_and_unsolicited_telemetry() {
    for (const auto* port : {"", "0", "65536", "-1", "1.2", "abc", "999999999999999999"}) {
        bool rejected = false; try { udp_port(port); } catch (const std::invalid_argument& e) {
            rejected = std::string(e.what()).find("1 to 65535") != std::string::npos;
        } REQUIRE(rejected);
    }
    REQUIRE(udp_port("1") == 1 && udp_port("65535") == 65535);
    Fixture f(false);
    bool occupied = false;
    try { ManualOperator other({static_cast<std::uint16_t>(f.op.port()), static_cast<std::uint16_t>(f.client.port), false}, f.diagnostics); }
    catch (const std::exception& e) { occupied = std::string(e.what()).find("choose another [udp-port]") != std::string::npos; }
    REQUIRE(occupied);
    auto bytes = heartbeat(); f.boards[0]->events.data(bytes, true);
    std::optional<Bytes> received;
    eventually([&] { received = f.client.receive(f.op.port()); return received.has_value(); });
    REQUIRE(*received == bytes && !f.op.status().client);
    f.send(heartbeat(true)); f.send(parameter_request());
    for (int i = 0; i < 10; ++i) { f.tick(); std::this_thread::sleep_for(1ms); }
    REQUIRE(f.op.status().client && !f.op.status().attempted && f.boards[0]->requests.empty() && f.boards[0]->binary.empty());
}
void startup_and_byte_preservation() {
    Fixture f;
    f.boards[0]->connection = Connection::connecting; f.tick();
    f.send(heartbeat(true)); REQUIRE(f.boards[0]->requests.empty());
    f.boards[0]->connection = Connection::connected; f.tick();
    eventually([&] { f.tick(); return f.op.status().held; });
    REQUIRE(f.boards[0]->count("control.activate") == 1 && f.boards[0]->binary.empty());
    const auto unknown = unfamiliar(), param = parameter_request();
    Bytes combined = unknown; combined.insert(combined.end(), param.begin(), param.end()); f.send(combined);
    REQUIRE(f.boards[0]->binary == std::vector<Bytes>({unknown, param}));
    f.boards[0]->events.data(unknown, true);
    std::optional<Bytes> received;
    eventually([&] { received = f.client.receive(f.op.port()); return received.has_value(); }); REQUIRE(*received == unknown);
    Client intruder; intruder.send(param, f.op.port()); f.tick(); REQUIRE(f.boards[0]->binary.size() == 2);
    // Parameter traffic precedes arming; none of these command payloads changes
    // session authority. Signed and unknown messages are not dialect-filtered.
    const auto armed = arm(true), disarmed = arm(false);
    for (const auto& bytes : {armed, disarmed, armed}) f.send(bytes);
    REQUIRE(f.boards[0]->binary == std::vector<Bytes>({unknown, param, armed, disarmed, armed}));
    REQUIRE(f.op.status().held && f.boards[0]->count("control.activate") == 1 && f.boards[0]->count("control.release_active") == 0);
}
void malformed_datagrams() {
    Fixture f; f.acquire();
    const auto good = unfamiliar();
    std::vector<Bytes> invalid{{}, {0xfd}, {0xfe, 9}, {0, 0}, Bytes(good.begin(), good.end() - 1)};
    auto flags = good; flags[2] = 2; invalid.push_back(flags);
    auto partial = good; partial.push_back(0xfd); invalid.push_back(partial); // No prefix dispatch.
    auto v1 = heartbeat(true); v1[5] = 1; invalid.push_back(v1);
    v1 = heartbeat(true); v1.back() ^= 0x80; invalid.push_back(v1);
    invalid.push_back(Bytes(20000, 0xfd)); // recvmsg truncation cannot become a valid frame.
    for (const auto& bytes : invalid) f.send(bytes);
    REQUIRE(f.boards[0]->binary.empty() && f.op.status().rejected == invalid.size());
    // Never join fragments across UDP datagrams, including a signed suffix.
    f.send(Bytes(good.begin(), good.begin() + 20)); f.send(Bytes(good.begin() + 20, good.end()));
    REQUIRE(f.boards[0]->binary.empty());
    f.send(good); REQUIRE(f.boards[0]->binary == std::vector<Bytes>{good});
}
void contention_and_stale_authority() {
    Fixture busy; busy.boards[0]->busy = true;
    busy.send(heartbeat(true));
    eventually([&] { busy.tick(); return busy.op.status().attempted; });
    for (int i = 0; i < 20; ++i) busy.send(parameter_request());
    REQUIRE(!busy.op.status().held && busy.boards[0]->binary.empty() && busy.boards[0]->count("control.activate") == 1);
    busy.boards[0]->busy = false; busy.send(heartbeat()); busy.tick();
    REQUIRE(!busy.op.status().held && busy.boards[0]->count("control.activate") == 1);

    Fixture f; f.acquire();
    // Queue a complete datagram under the old lease, then deliver a takeover
    // before the Session dispatches it. The common Actions generation fences it.
    const auto before = f.op.status().datagrams; f.client.send(unfamiliar(), f.op.port());
    eventually([&] { f.op.poll(f.session, f.now); return f.op.status().datagrams > before; });
    f.boards[0]->text(f.boards[0]->state("control.state", "takeover", 8)); f.session.tick(f.now); f.lost();
    REQUIRE(f.boards[0]->binary.empty());
    f.boards[0]->epoch = 9; f.send(parameter_request()); f.tick();
    REQUIRE(f.boards[0]->count("control.activate") == 1 && f.boards[0]->binary.empty());
}
void inactivity_and_disconnect() {
    for (const bool close_client : {false, true}) {
        Fixture f; f.acquire();
        if (close_client) f.client.disconnect();
        f.now += 4999ms; f.tick(); REQUIRE(f.op.status().held);
        f.now += 1ms; f.tick(); f.lost();
        REQUIRE(f.boards[0]->count("control.release_active") == 1);
        if (!close_client) f.send(parameter_request());
        f.tick(); REQUIRE(!f.op.status().held && f.boards[0]->count("control.activate") == 1 && f.boards[0]->binary.empty());
    }
    Fixture pending; pending.boards[0]->respond = false; pending.send(heartbeat(true));
    eventually([&] { pending.tick(); return pending.boards[0]->count("control.activate") == 1; });
    JsonValue request(pending.boards[0]->requests[0].c_str()); const auto id = request.View().GetString("requestId");
    pending.op.disconnect(pending.session, "explicit hosting disconnect"); pending.tick();
    pending.boards[0]->text(pending.boards[0]->state("control.activated", id.c_str())); pending.tick();
    pending.send(parameter_request()); REQUIRE(!pending.op.status().held && pending.boards[0]->binary.empty());
}
void independent_video_and_long_healthy_diagnostics() {
    Fixture f; f.acquire();
    // Monotonic host time is accelerated; this is a duration regression check,
    // not a claim of a long physical run. Refresh lifecycle and valid receipts.
    for (int seconds = 1; seconds <= 3600; ++seconds) {
        f.now += 1s; f.boards[0]->events.data(heartbeat(), true); f.send(heartbeat(true));
    }
    REQUIRE(f.op.status().held);
    f.boards[1]->events.video({{0,0,0,1,0x65,1}, "h264", 123456, std::chrono::system_clock::now()});
    eventually([&] { return f.op.status().video == 1; });
    f.boards[1]->connection = Connection::failed; f.tick();
    const auto param = parameter_request(); f.send(param); REQUIRE(f.boards[0]->binary.back() == param);
    REQUIRE(f.boards[0]->stops == 0 && f.op.status().held);
    f.boards[0]->connection = Connection::failed; f.tick(); f.lost();
    // This callback follows the control-loss event on the observation worker.
    eventually([&] { return f.op.status().telemetry_error == "WebRTC loss after long healthy operation"; });
    f.now += 1s; f.tick(); f.send(param);
    REQUIRE(f.boards[0]->binary == std::vector<Bytes>{param} && f.boards[0]->count("control.activate") == 1);
}
void lease_lifecycle_and_shutdown() {
    for (const auto reason : {0, 1, 2, 3}) {
        Fixture f; f.acquire();
        if (reason == 0) {
            // A stale-epoch refusal to a pending renewal revokes authority.
            f.boards[0]->respond = false; f.now += 1s; f.send(heartbeat(true));
            JsonValue renew(f.boards[0]->requests.back().c_str()); const auto id = renew.View().GetString("requestId");
            f.boards[0]->text("{\"type\":\"control.error\",\"requestId\":\"" + std::string(id.c_str()) + "\",\"code\":\"stale_epoch\"}");
            f.tick(); f.lost(); f.send(parameter_request()); f.tick();
            REQUIRE(f.boards[0]->count("control.activate") == 1);
        } else if (reason == 1) {
            f.session.verified({true, 3}, f.now); REQUIRE(!f.session.tick(f.now));
        } else if (reason == 2) {
            f.now += 15s; REQUIRE(!f.session.tick(f.now));
        } else f.session.shutdown("process signal");
        f.lost(); REQUIRE(f.boards[0]->binary.empty());
        REQUIRE(f.boards[0]->count("control.release_active") == 1);
    }
}
int main() {
    // Keep any SDK configuration initialization inside repository scratch.
    const auto scratch = std::filesystem::path(__FILE__).parent_path().parent_path().parent_path() / "tmp/agent-manual-test";
    std::filesystem::create_directories(scratch);
    const auto config = (scratch / "config").string(), credentials = (scratch / "credentials").string();
    std::ofstream(config).close(); std::ofstream(credentials).close();
    setenv("AWS_CONFIG_FILE", config.c_str(), 1); setenv("AWS_SHARED_CREDENTIALS_FILE", credentials.c_str(), 1);
    setenv("AWS_EC2_METADATA_DISABLED", "true", 1);
    Aws::SDKOptions options; Aws::InitAPI(options); int result = 0;
    try {
        for (const auto& test : std::vector<std::pair<const char*, void(*)()>>{
            {"ports and unsolicited telemetry", ports_and_unsolicited_telemetry},
            {"startup and byte preservation", startup_and_byte_preservation},
            {"malformed datagrams", malformed_datagrams},
            {"contention and stale authority", contention_and_stale_authority},
            {"inactivity and disconnect", inactivity_and_disconnect},
            {"independent video and long healthy diagnostics", independent_video_and_long_healthy_diagnostics},
            {"lease lifecycle and shutdown", lease_lifecycle_and_shutdown}}) {
            test.second(); std::cout << "PASS " << test.first << std::endl;
        }
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; result = 1; }
    Aws::ShutdownAPI(options); return result;
}
