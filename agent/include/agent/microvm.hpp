#pragma once

#include "agent/core.hpp"
#include <aws/core/auth/AWSCredentialsProvider.h>
#include <array>

namespace txing::agent {
struct MicrovmRun {
    std::string id, thing, region;
    std::string run_id, activation_id;
    std::int64_t deadline = 0;
};
struct ProjectionObservation;
struct ControllerState;
// Caller verifies registry capability separately. Preserve the actual REDCON
// from the same projection whose identity/order authorizes this assignment.
Lifecycle assigned_run_lifecycle(const MicrovmRun&, const ProjectionObservation&, const ControllerState&);
struct HookReply { unsigned status; std::string body; };
struct WireMessage { Bytes bytes; bool binary; };

// Tracks changes in memory; diagnostics contain only counts and expiration.
// Never retain a credential tuple in image-build state or serialize it.
class AuditedCredentials final : public Aws::Auth::AWSCredentialsProvider {
public:
    explicit AuditedCredentials(std::shared_ptr<Aws::Auth::AWSCredentialsProvider>);
    Aws::Auth::AWSCredentials GetAWSCredentials() override;
    std::string status() const;
private:
    std::shared_ptr<Aws::Auth::AWSCredentialsProvider> source_;
    mutable std::mutex mutex_;
    Aws::Auth::AWSCredentials previous_;
    std::uint64_t calls_ = 0, generations_ = 0;
};

// One disposable experiment, not the production lifecycle controller. The
// runner is created exclusively by /run, after the image snapshot is restored.
class MicrovmApplication final : public Operator {
public:
    using Runner = std::function<void(const MicrovmRun&, MicrovmApplication&)>;
    explicit MicrovmApplication(Runner, std::function<void()> prepare = {}, bool require_assignment = false);
    ~MicrovmApplication();
    HookReply hook(const std::string& path, const std::string& body);
    std::string status() const;
    bool attach();
    bool attached() const;
    void detach();
    void message(Bytes, bool binary);
    std::optional<WireMessage> outgoing();
    void wake_with(std::function<void()>);
    bool stopping() const { return stopping_; }
    void stop();
    void actions(Actions*);
    void authorized(bool, Time verified_at = Time{});
    void credential_status(std::string);
    void stopped(std::string);
    void telemetry(const Bytes&) override;
    void video(const EncodedVideo&) override;
    void connection(Stream, Connection, const std::string&) override;
    void control(bool, const std::string&) override;
private:
    bool assignment_fresh(Time now) const;
    void publish(std::string);
    void publish(WireMessage);
    Runner runner_;
    std::function<void()> prepare_;
    std::thread worker_;
    std::atomic<bool> stopping_{false};
    mutable std::mutex mutex_;
    MicrovmRun run_;
    Time started_{};
    std::string phase_ = "waiting-for-run", reason_, credentials_ = "{}";
    std::string codec_, control_state_ = "observing", control_error_;
    std::uint64_t telemetry_ = 0, video_ = 0, presentation_ = 0, receipt_ = 0;
    std::size_t frame_bytes_ = 0;
    std::array<Connection, 2> connections_{Connection::stopped, Connection::stopped};
    std::array<std::string, 2> errors_;
    Actions* actions_ = nullptr;
    bool attached_ = false, held_ = false, prepared_ = false, control_attempted_ = false;
    const bool require_assignment_;
    bool authorized_ = false;
    Time assignment_verified_at_{};
    std::function<void()> wake_;
    Queue<WireMessage> outgoing_{128, 512 * 1024};
};

// The hook listener and attachment listener use separate ports. AWS ingress
// tokens grant only the attachment port, never access to lifecycle hooks.
int microvm_main(int argc, char** argv);
int serve_microvm(MicrovmApplication&, unsigned hook_port, unsigned attachment_port,
                  const std::function<bool()>& interrupted);
}
