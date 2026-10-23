#include "agent/aws.hpp"
#include "agent/kvs.hpp"
#include "agent/manual.hpp"
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
}
int main(int argc, char** argv) {
    if (argc > 1 && std::string(argv[1]) == "--microvm")
        return txing::agent::microvm_main(argc - 1, argv + 1);
    std::string thing, region, ca;
    txing::agent::ManualOptions manual;
    bool has_port = false;
    if (const auto* value = std::getenv("TXING_AGENT_CA_PATH")) ca = value;
    try {
        for (int i = 1; i < argc; ++i) {
            const std::string argument = argv[i];
            if (argument == "--help") {
                std::cout << "txing-agent <thing-id> [udp-port] [--control] [--qgc-port <port>] [--region <region>] [--ca <verified-pem>]\n"
                             "UDP listener 127.0.0.1:14551; QGroundControl endpoint 127.0.0.1:14550.\n"
                             "Foreground observation by default; --control attempts a free lease once.\n"
                             "Ctrl-C releases and closes both sessions.\n"
                             "txing-agent --microvm --ca <verified-pem> [--hook-port 8080] [--attachment-port 8081]\n";
                return 0;
            }
            if (argument == "--control") manual.control = true;
            else if (argument == "--qgc-port" && i + 1 < argc) manual.qgc = txing::agent::udp_port(argv[++i]);
            else if ((argument == "--region" || argument == "--ca") && i + 1 < argc) {
                (argument == "--region" ? region : ca) = argv[++i];
            } else if (thing.empty() && !argument.empty() && argument[0] != '-') thing = argument;
            else if (!thing.empty() && !has_port && !argument.empty() &&
                     (argument[0] != '-' || (argument.size() > 1 && argument[1] >= '0' && argument[1] <= '9'))) {
                manual.listener = txing::agent::udp_port(argument); has_port = true;
            }
            else { std::cerr << "invalid argument: " << argument << '\n'; return 2; }
        }
    } catch (const std::invalid_argument& error) { std::cerr << error.what() << '\n'; return 2; }
    if (thing.empty() || ca.empty() || !std::ifstream(ca).good()) {
        std::cerr << "Thing ID and readable verified CA PEM required; use just agent::run <thing-id>\n"; return 2;
    }
    // Bind before credentials/API work so an occupied or invalid local port
    // fails immediately without opening device sessions.
    std::unique_ptr<txing::agent::ManualOperator> observer;
    try { observer = std::make_unique<txing::agent::ManualOperator>(manual, std::cerr); }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 2; }
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
        txing::agent::LifecyclePoller lifecycle([&] { return device.lifecycle(thing); });
        txing::agent::Session session(std::move(profile), [credentials] {
            return txing::agent::make_kvs_transport(credentials);
        }, *observer, std::chrono::steady_clock::now());
        auto report_at = std::chrono::steady_clock::now();
        std::string last_error;
        while (!interrupted) {
            const auto now = std::chrono::steady_clock::now();
            if (const auto state = lifecycle.latest()) session.verified(state->first, state->second);
            const auto error = lifecycle.error();
            if (error != last_error) { if (!error.empty()) std::cerr << error << '\n'; last_error = error; }
            observer->poll(session, now);
            if (!session.tick(now)) break;
            if (now >= report_at) {
                const auto status = observer->status();
                std::cerr << "observations telemetry=" << status.telemetry << " video=" << status.video
                          << " videoDropped=" << session.video_dropped() << " udpDatagrams=" << status.datagrams
                          << " udpRejected=" << status.rejected
                          << " udpDropped=" << status.dropped << " control=" << status.held << '\n';
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
