#include "agent/microvm.hpp"
#include <aws/core/Aws.h>
#include <aws/core/utils/json/JsonSerializer.h>
#include <csignal>
#include <iostream>
#include <stdexcept>

using namespace txing::agent;
using namespace std::chrono_literals;
namespace {
void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
const std::string run = R"({"microvmId":"mvm-test-1","runHookPayload":"{\"thingId\":\"tbot-test\",\"region\":\"eu-central-1\"}"})";
Bytes frame() { return {0xfd, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0}; }
volatile std::sig_atomic_t interrupted = 0;
void interrupt(int) { interrupted = 1; }
struct MutableCredentials : Aws::Auth::AWSCredentialsProvider {
    Aws::Auth::AWSCredentials value;
    Aws::Auth::AWSCredentials GetAWSCredentials() override { return value; }
};
void tests() {
    std::atomic<unsigned> starts{0}, prepares{0};
    MicrovmApplication app([&](const MicrovmRun& selected, MicrovmApplication& host) {
        require(selected.id == "mvm-test-1", "restored identity missing");
        ++starts;
        while (!host.stopping()) std::this_thread::sleep_for(1ms);
    }, [&] { ++prepares; });
    require(app.hook("/ready", "").status == 200 && app.hook("/validate", "").status == 200 && starts == 0 && prepares == 0,
            "build hooks initialized a runtime");
    require(!app.attach(), "attached before restoration");
    require(app.hook("/run", "{}").status == 400 && app.hook("/run", std::string(16385, 'x')).status == 413,
            "invalid/oversized hook accepted");
    require(app.hook("/run", R"({"microvmId" "mvm-test-1","runHookPayload":"{}"})").status == 400 &&
            app.hook("/run", run + "{}").status == 400, "malformed separators/trailing JSON accepted");
    require(app.hook("/run", R"({"microvmId":"mvm-test-1","runHookPayload":"{\"thingId\":\"tbot-test\",\"region\":\"us-east-1\"}"})").status == 400,
            "wrong region accepted");
    require(app.hook("/run", run).status == 200 && app.hook("/run", run).status == 200,
            "valid/idempotent run rejected");
    require(app.hook("/ready", "").status == 409 && app.hook("/resume", "").status == 409,
            "runtime was eligible for image snapshot/resumption");
    require(app.attach() && !app.attach(), "manual attachment exclusivity missing");
    app.message(frame(), true);
    auto response = app.outgoing();
    require(response && !response->binary && std::string(response->bytes.begin(), response->bytes.end()).find("false") != std::string::npos,
            "unauthorized action accepted");
    for (unsigned index = 0; index < 1000; ++index) app.telemetry(frame());
    require(app.status().find("attachmentDrops") != std::string::npos, "missing bounded queue diagnostics");
    unsigned queued = 0;
    while (app.outgoing()) ++queued;
    require(queued == 128, "attachment queue unbounded");
    app.detach(); app.telemetry(frame());
    require(!app.outgoing(), "unattached observations retained");
    require(app.hook("/terminate", "").status == 200 && starts == 1 && prepares == 1, "termination/idempotent start failed");
    require(app.hook("/run", run).status == 409, "stopped run restarted");

    auto source = Aws::MakeShared<MutableCredentials>("credential-test");
    AuditedCredentials credentials(source);
    const auto expiry = Aws::Utils::DateTime::Now() + 60s;
    source->value = {"private-key-one", "private-secret-one", "private-token-one", expiry};
    credentials.GetAWSCredentials(); credentials.GetAWSCredentials();
    require(credentials.status().find("\"generations\":1") != std::string::npos, "stable tuple counted as rotation");
    source->value = {"private-key-two", "private-secret-two", "private-token-two", expiry};
    credentials.GetAWSCredentials();
    const auto audit = credentials.status();
    require(audit.find("\"generations\":2") != std::string::npos && audit.find("private-") == std::string::npos &&
            audit.find("\"finiteExpiration\":true") != std::string::npos, "rotation/secret-free diagnostics failed");
    for (const std::string detail : {"private-secret: KVS status 0xdeadbeef", "iot:DescribeThing: private-secret HTTP 403"}) {
        MicrovmApplication failed([detail](const MicrovmRun&, MicrovmApplication&) { throw std::runtime_error(detail); });
        require(failed.hook("/run", run).status == 200, "failure fixture did not start");
        const auto deadline = std::chrono::steady_clock::now() + 2s;
        while (failed.status().find("\"phase\":\"stopped\"") == std::string::npos) {
            require(std::chrono::steady_clock::now() < deadline, "failure fixture did not finish");
            std::this_thread::sleep_for(1ms);
        }
        require(failed.status().find("private-secret") == std::string::npos, "runtime exception exposed secret material");
    }
    std::cout << "PASS MicroVM restoration, hooks, attachment bounds and credential audit\n";
}
}
int main(int argc, char** argv) {
    Aws::SDKOptions options; Aws::InitAPI(options);
    int result = 0;
    try {
        if (argc == 4 && std::string(argv[1]) == "--serve") {
            std::signal(SIGINT, interrupt); std::signal(SIGTERM, interrupt);
            // Explicit test fixture only: never compiled into txing-agent.
            MicrovmApplication app([](const MicrovmRun&, MicrovmApplication& host) {
                while (!host.stopping()) {
                    host.telemetry(frame());
                    host.video({Bytes{1, 2, 3}, "h264", 42, std::chrono::system_clock::now()});
                    std::this_thread::sleep_for(20ms);
                }
            });
            result = serve_microvm(app, std::stoul(argv[2]), std::stoul(argv[3]), [] { return interrupted != 0; });
        } else tests();
    } catch (const std::exception& error) { std::cerr << "FAIL " << error.what() << '\n'; result = 1; }
    Aws::ShutdownAPI(options); return result;
}
