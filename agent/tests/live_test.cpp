#include "agent/aws.hpp"
#include "agent/kvs.hpp"
#include <aws/core/Aws.h>
#include <aws/core/auth/AWSCredentialsProviderChain.h>
#include <aws/core/client/DefaultRetryStrategy.h>
#include <array>
#include <iostream>
#include <stdexcept>

using namespace txing::agent;
using namespace std::chrono_literals;

namespace {
void require(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
}
struct Faults {
    std::array<std::atomic<unsigned>, 2> generation{};
    std::atomic<int> redcon{0};
    std::atomic<bool> verification_failure{false};
};
// The wrapped transport is the production KVS engine. Changing a generation
// makes Session retire that real connection, without touching device state.
class FaultTransport final : public Transport {
public:
    FaultTransport(std::unique_ptr<Transport> transport, Faults& faults)
        : transport_(std::move(transport)), faults_(faults) {}
    void start(const TransportConfig& config, TransportEvents events) override {
        index_ = config.media == Media::h264 ? 1 : 0;
        generation_ = faults_.generation[index_].load();
        transport_->start(config, std::move(events));
    }
    void stop() noexcept override { transport_->stop(); }
    bool finished() const override { return transport_->finished(); }
    Connection state() const override {
        return failed() ? Connection::failed : transport_->state();
    }
    std::string error() const override {
        return failed() ? "acceptance injected peer loss" : transport_->error();
    }
    bool send(const Bytes& bytes, bool binary) override { return transport_->send(bytes, binary); }
private:
    bool failed() const { return generation_ != faults_.generation[index_].load(); }
    std::unique_ptr<Transport> transport_;
    Faults& faults_;
    unsigned index_ = 0, generation_ = 0;
};
class Observer final : public Operator {
public:
    std::atomic<unsigned> telemetry_frames{0}, video_frames{0};
    std::array<std::atomic<unsigned>, 2> connections{}, stops{};
    std::atomic<bool> metadata{false}, authority{false};
    void telemetry(const Bytes&) override { ++telemetry_frames; }
    void video(const EncodedVideo& frame) override {
        metadata = frame.codec == "h264" && !frame.bytes.empty() &&
                   frame.received.time_since_epoch().count() > 0;
        ++video_frames;
    }
    void connection(Stream stream, Connection state, const std::string& detail) override {
        const auto index = stream == Stream::video ? 1 : 0;
        if (state == Connection::connected) ++connections[index];
        if (state == Connection::stopped) ++stops[index];
        std::cerr << "LIVE connection stream=" << index << " state=" << static_cast<int>(state)
                  << " detail=" << detail << '\n';
    }
    void control(bool held, const std::string&) override { if (held) authority = true; }
};
void live(const std::string& thing, const std::string& region, const std::string& ca) {
    auto credentials = Aws::MakeShared<Aws::Auth::DefaultAWSCredentialsProviderChain>("live-acceptance");
    Aws::Client::ClientConfiguration config;
    config.region = region.c_str(); config.caFile = ca.c_str();
    config.connectTimeoutMs = 2000; config.requestTimeoutMs = 2000;
    config.retryStrategy = Aws::MakeShared<Aws::Client::DefaultRetryStrategy>("live-acceptance", 0);
    AwsDevice device(credentials, config);
    const auto registered_type = device.registered_type(thing);
    auto selected = profile(registered_type, thing, region, ca);
    KvsRuntime sdk;
    Faults faults;
    Observer observer;
    LifecyclePoller lifecycle([&] {
        if (faults.verification_failure) throw std::runtime_error("acceptance injected verification failure");
        auto current = device.lifecycle(thing);
        const auto override = faults.redcon.load();
        if (override && current.born && current.redcon <= 2) current.redcon = override;
        return current;
    });
    Session session(std::move(selected), [&] {
        return std::make_unique<FaultTransport>(make_kvs_transport(credentials), faults);
    }, observer, std::chrono::steady_clock::now());
    Time last_verified{}, report_at{};
    const auto pump = [&] {
        const auto now = std::chrono::steady_clock::now();
        if (const auto state = lifecycle.latest()) {
            session.verified(state->first, state->second); last_verified = state->second;
        }
        if (now >= report_at) {
            std::cerr << "LIVE counts telemetry=" << observer.telemetry_frames << " video="
                      << observer.video_frames << " dropped=" << session.video_dropped() << '\n';
            report_at = now + 5s;
        }
        const bool running = session.tick(now);
        std::this_thread::sleep_for(20ms);
        return running;
    };
    const auto wait = [&](auto predicate, const char* message, auto timeout) {
        const auto deadline = std::chrono::steady_clock::now() + timeout;
        while (!predicate()) {
            require(std::chrono::steady_clock::now() < deadline, message);
            if (!pump()) throw std::runtime_error(session.stop_reason());
        }
    };

    wait([&] { return observer.telemetry_frames > 10 && observer.video_frames > 10 && observer.metadata; },
         "live streams/metadata missing", 40s);
    std::cerr << "LIVE PASS real AWS streams registeredType=" << registered_type << '\n';

    auto telemetry_before = observer.telemetry_frames.load();
    auto video_before = observer.video_frames.load();
    ++faults.generation[1];
    wait([&] { return observer.connections[1] >= 2 && observer.video_frames > video_before + 10; },
         "video did not recover", 40s);
    require(observer.connections[0] == 1 && observer.telemetry_frames > telemetry_before,
            "video loss interrupted telemetry");
    std::cerr << "LIVE PASS injected video-peer loss; telemetry stayed connected\n";

    telemetry_before = observer.telemetry_frames.load(); video_before = observer.video_frames.load();
    ++faults.generation[0];
    wait([&] { return observer.connections[0] >= 2 && observer.telemetry_frames > telemetry_before + 10; },
         "telemetry did not recover", 40s);
    require(observer.connections[1] == 2 && observer.video_frames > video_before,
            "telemetry loss interrupted video");
    std::cerr << "LIVE PASS injected telemetry-peer loss; video stayed connected\n";

    const auto stops_before = observer.stops[1].load();
    telemetry_before = observer.telemetry_frames.load();
    faults.redcon = 2;
    wait([&] { return observer.stops[1] > stops_before && observer.telemetry_frames > telemetry_before + 10; },
         "injected REDCON 2 did not retire only video", 10s);
    require(observer.connections[0] == 2, "injected REDCON 2 reconnected telemetry");
    video_before = observer.video_frames.load();
    faults.redcon = 0;
    wait([&] { return observer.connections[1] >= 3 && observer.video_frames > video_before + 10; },
         "video did not resume after lifecycle override", 40s);
    require(observer.connections[0] == 2, "video resumption reconnected telemetry");
    std::cerr << "LIVE PASS injected lifecycle 1/2/1; actual device shadow unchanged\n";

    faults.verification_failure = true;
    const auto deadline = std::chrono::steady_clock::now() + 20s;
    while (pump()) require(std::chrono::steady_clock::now() < deadline, "verification timeout did not stop");
    require(session.stop_reason() == "lifecycle unverified for 15 seconds", "unexpected shutdown reason");
    const auto age = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - last_verified).count();
    require(age >= 15000 && age < 16000, "verification deadline outside expected bound");
    require(!observer.authority, "observation unexpectedly acquired authority");
    std::cerr << "LIVE PASS injected verification failure; stopped at ageMs=" << age << '\n';
}
}

// Explicit operator-run test only: never register this with default CTest.
int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "agent-live-tests <active-thing-id> <region> <verified-ca-pem>\n"
                     "Uses real AWS/device observations; injects faults only inside this test process.\n";
        return 2;
    }
    Aws::SDKOptions options; Aws::InitAPI(options);
    int result = 0;
    try { live(argv[1], argv[2], argv[3]); }
    catch (const std::exception& error) { std::cerr << "LIVE FAIL " << error.what() << '\n'; result = 1; }
    Aws::ShutdownAPI(options);
    return result;
}
