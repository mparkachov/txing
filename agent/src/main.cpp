#include "agent/aws.hpp"
#include "agent/kvs.hpp"
#include "agent/microvm.hpp"
#include <aws/core/Aws.h>
#include <aws/core/auth/AWSCredentialsProviderChain.h>
#include <aws/core/client/DefaultRetryStrategy.h>
#include <csignal>
#include <cstdlib>
#include <fstream>
#include <iostream>

namespace {
volatile std::sig_atomic_t interrupted = 0;
void interrupt(int) { interrupted = 1; }
class Observer final : public txing::agent::Operator {
public:
    void telemetry(const txing::agent::Bytes&) override { ++telemetry_frames; }
    void video(const txing::agent::EncodedVideo& frame) override {
        // Encoded bytes and both clocks arrive here, before count/discard.
        if (frame.codec == "h264" && !frame.bytes.empty() && ++video_frames == 1) {
            std::cerr << "video observation codec=" << frame.codec << " bytes=" << frame.bytes.size()
                      << " presentation100ns=" << frame.presentation_100ns << " receiptUnixMs="
                      << std::chrono::duration_cast<std::chrono::milliseconds>(frame.received.time_since_epoch()).count() << '\n';
        }
    }
    void connection(txing::agent::Stream stream, txing::agent::Connection state, const std::string& detail) override {
        std::cerr << (stream == txing::agent::Stream::telemetry ? "telemetry" : "video")
                  << " connection=" << static_cast<int>(state) << " " << detail << '\n';
    }
    void control(bool held, const std::string& reason) override {
        std::cerr << "control=" << held << " " << reason << '\n';
    }
    std::atomic<std::uint64_t> telemetry_frames{0}, video_frames{0};
};
}
int main(int argc, char** argv) {
    if (argc > 1 && std::string(argv[1]) == "--microvm")
        return txing::agent::microvm_main(argc - 1, argv + 1);
    std::string thing, region, ca;
    if (const auto* value = std::getenv("TXING_AGENT_CA_PATH")) ca = value;
    for (int i = 1; i < argc; ++i) {
        const std::string argument = argv[i];
        if (argument == "--help") {
            std::cout << "txing-agent <thing-id> [--region <region>] [--ca <verified-pem>]\n"
                         "Foreground observation; Ctrl-C releases and closes both sessions.\n"
                         "txing-agent --microvm --ca <verified-pem> [--hook-port 8080] [--attachment-port 8081]\n";
            return 0;
        }
        if ((argument == "--region" || argument == "--ca") && i + 1 < argc) {
            (argument == "--region" ? region : ca) = argv[++i];
        } else if (thing.empty() && !argument.empty() && argument[0] != '-') thing = argument;
        else { std::cerr << "invalid argument: " << argument << '\n'; return 2; }
    }
    if (thing.empty() || ca.empty() || !std::ifstream(ca).good()) {
        std::cerr << "Thing ID and readable verified CA PEM required; use just agent::run <thing-id>\n"; return 2;
    }
    std::signal(SIGINT, interrupt); std::signal(SIGTERM, interrupt);
    Aws::SDKOptions options;
    Aws::InitAPI(options);
    int result = 0;
    try {
        auto credentials = Aws::MakeShared<Aws::Auth::DefaultAWSCredentialsProviderChain>("txing-agent");
        Aws::Client::ClientConfiguration config;
        if (!region.empty()) config.region = region.c_str();
        config.caFile = ca.c_str(); config.connectTimeoutMs = 2000; config.requestTimeoutMs = 2000;
        config.retryStrategy = Aws::MakeShared<Aws::Client::DefaultRetryStrategy>("txing-agent", 0);
        txing::agent::AwsDevice device(credentials, config);
        const auto registered_type = device.registered_type(thing);
        auto profile = txing::agent::profile(registered_type, thing, config.region.c_str(), ca);
        std::cerr << "observing Thing=" << thing << " registeredType=" << registered_type
                  << " region=" << config.region << '\n';
        txing::agent::KvsRuntime sdk;
        Observer observer;
        txing::agent::LifecyclePoller lifecycle([&] { return device.lifecycle(thing); });
        txing::agent::Session session(std::move(profile), [credentials] {
            return txing::agent::make_kvs_transport(credentials);
        }, observer, std::chrono::steady_clock::now());
        auto report_at = std::chrono::steady_clock::now();
        std::string last_error;
        while (!interrupted) {
            const auto now = std::chrono::steady_clock::now();
            if (const auto state = lifecycle.latest()) session.verified(state->first, state->second);
            const auto error = lifecycle.error();
            if (error != last_error) { if (!error.empty()) std::cerr << error << '\n'; last_error = error; }
            if (!session.tick(now)) break;
            if (now >= report_at) {
                std::cerr << "observations telemetry=" << observer.telemetry_frames << " video=" << observer.video_frames
                          << " videoDropped=" << session.video_dropped() << '\n';
                report_at = now + std::chrono::seconds(5);
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }
        session.shutdown(interrupted ? "process signal" : "lifecycle shutdown");
        std::cerr << "agent stopped: " << session.stop_reason() << '\n';
        if (session.stop_reason() == "lifecycle unverified for 15 seconds") result = 1;
    } catch (const std::exception& e) { std::cerr << "txing-agent: " << e.what() << '\n'; result = 1; }
    Aws::ShutdownAPI(options);
    return result;
}
