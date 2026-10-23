#pragma once

#include "agent/core.hpp"
#include <iosfwd>

namespace txing::agent {
// User-facing ports are 1..65535. Zero is available only to the socket API
// below, so integration tests can ask the OS for an unused listener.
std::uint16_t udp_port(const std::string&);
struct ManualOptions {
    std::uint16_t listener = 14551, qgc = 14550;
    bool control = false;
};
struct ManualStatus {
    std::uint64_t telemetry = 0, video = 0, datagrams = 0, rejected = 0, dropped = 0;
    bool client = false, attempted = false, held = false;
    std::string error, telemetry_error, video_error;
};

// Local QGroundControl is an ordinary Operator. poll()/disconnect() call
// Actions on the hosting thread; network/video callbacks never wait for QGC.
class ManualOperator final : public Operator {
public:
    ManualOperator(ManualOptions, std::ostream& diagnostics);
    ~ManualOperator();
    ManualOperator(const ManualOperator&) = delete;
    ManualOperator& operator=(const ManualOperator&) = delete;
    unsigned port() const { return port_; }
    void poll(Actions&, Time);
    void disconnect(Actions&, const std::string& reason);
    ManualStatus status() const;
    void telemetry(const Bytes&) override;
    void video(const EncodedVideo&) override;
    void connection(Stream, Connection, const std::string&) override;
    void control(bool, const std::string&) override;
private:
    void error(const std::string&);
    void diagnostic(const std::string&);
    ManualOptions options_;
    int socket_ = -1;
    unsigned port_ = 0;
    std::ostream& diagnostics_;
    mutable std::mutex mutex_;
    std::mutex diagnostics_mutex_;
    ManualStatus status_;
    bool telemetry_connected_ = false, disabled_ = false;
    std::atomic<bool> socket_failed_{false};
    Time last_client_{};
};
}
