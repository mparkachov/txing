#include "agent/manual.hpp"
#include <mavlink/v2.0/minimal/mavlink.h>
#include <arpa/inet.h>
#include <array>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <ostream>
#include <sstream>
#include <stdexcept>
#include <sys/socket.h>
#include <unistd.h>

namespace txing::agent {
namespace {
sockaddr_in loopback(unsigned port) {
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = htons(static_cast<std::uint16_t>(port));
    return address;
}
std::string socket_error(const std::string& operation, int code) {
    return operation + ": " + std::strerror(code);
}
// UDP preserves message boundaries. Validate the entire datagram before
// forwarding any frame; never retain a partial frame for the next datagram.
// Header/length validation deliberately leaves dialect-specific CRCs and
// signatures to the flight controller and preserves every MAVLink 2 byte.
bool frames(const std::uint8_t* data, std::size_t size, std::vector<Bytes>& output) {
    if (!size) return false;
    std::size_t offset = 0, count = 0;
    while (offset < size) {
        if (++count > 32 || size - offset < 2) return false;
        const auto* p = data + offset;
        std::size_t length;
        if (p[0] == 0xfd) {
            if (size - offset < 12 || (p[2] & ~1u)) return false;
            length = 12u + p[1] + ((p[2] & 1u) ? 13u : 0u);
        } else if (p[0] == 0xfe) {
            // MAVLink 1 HEARTBEAT: nine payload bytes, six header bytes,
            // two CRC bytes, message ID zero. Presence only, never uplink.
            if (size - offset < 17 || p[1] != MAVLINK_MSG_ID_HEARTBEAT_LEN || p[5] != MAVLINK_MSG_ID_HEARTBEAT) return false;
            length = 17;
            auto crc = crc_calculate(p + 1, 14);
            crc_accumulate(MAVLINK_MSG_ID_HEARTBEAT_CRC, &crc);
            if (p[15] != (crc & 0xff) || p[16] != (crc >> 8)) return false;
        } else return false;
        if (length > size - offset) return false;
        if (p[0] == 0xfd) output.emplace_back(p, p + length);
        offset += length;
    }
    return true;
}
}

std::uint16_t udp_port(const std::string& value) {
    unsigned port = 0;
    if (value.empty()) throw std::invalid_argument("UDP port must be an integer from 1 to 65535");
    for (const auto ch : value) {
        if (ch < '0' || ch > '9' || (port = port * 10 + unsigned(ch - '0')) > 65535)
            throw std::invalid_argument("UDP port must be an integer from 1 to 65535");
    }
    if (!port) throw std::invalid_argument("UDP port must be an integer from 1 to 65535");
    return static_cast<std::uint16_t>(port);
}

ManualOperator::ManualOperator(ManualOptions options, std::ostream& diagnostics)
    : options_(options), diagnostics_(diagnostics) {
    if (!options.qgc || (options.listener && options.listener == options.qgc))
        throw std::invalid_argument("QGroundControl endpoint and agent listener must use different UDP ports");
    socket_ = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (socket_ < 0) throw std::runtime_error(socket_error("create loopback UDP socket", errno));
    try {
        const auto flags = fcntl(socket_, F_GETFL, 0);
        if (flags < 0 || fcntl(socket_, F_SETFL, flags | O_NONBLOCK) < 0 ||
            fcntl(socket_, F_SETFD, FD_CLOEXEC) < 0)
            throw std::runtime_error(socket_error("configure loopback UDP socket", errno));
        auto address = loopback(options.listener);
        if (::bind(socket_, reinterpret_cast<sockaddr*>(&address), sizeof(address)) < 0) {
            const auto code = errno;
            throw std::runtime_error(socket_error("bind 127.0.0.1:" + std::to_string(options.listener), code) +
                (code == EADDRINUSE ? "; stop the other listener or choose another [udp-port]" : ""));
        }
        socklen_t length = sizeof(address);
        if (getsockname(socket_, reinterpret_cast<sockaddr*>(&address), &length) < 0)
            throw std::runtime_error(socket_error("read loopback UDP listener", errno));
        port_ = ntohs(address.sin_port);
    } catch (...) { ::close(socket_); socket_ = -1; throw; }
    diagnostics_ << "QGroundControl UDP listener=127.0.0.1:" << port_
                 << " endpoint=127.0.0.1:" << options.qgc
                 << (options.control ? " explicit control: one free-lease attempt after client presence\n" : " observation only\n");
}
ManualOperator::~ManualOperator() { if (socket_ >= 0) ::close(socket_); }
ManualStatus ManualOperator::status() const {
    std::lock_guard<std::mutex> lock(mutex_); return status_;
}
void ManualOperator::error(const std::string& detail) {
    bool changed;
    { std::lock_guard<std::mutex> lock(mutex_); changed = status_.error != detail; status_.error = detail; }
    if (changed) diagnostic("QGroundControl: " + detail);
}
void ManualOperator::diagnostic(const std::string& text) {
    // Logging never holds the state mutex used by poll/status. In particular,
    // a blocked video diagnostic cannot hold up authority or socket state.
    std::lock_guard<std::mutex> lock(diagnostics_mutex_); diagnostics_ << text << '\n';
}
void ManualOperator::disconnect(Actions& actions, const std::string& reason) {
    // UDP has no disconnect notification; a missing client is detected by the
    // five-second presence deadline. Socket failure is terminal immediately.
    actions.release();
    { std::lock_guard<std::mutex> lock(mutex_); disabled_ = true; status_.client = false; }
    diagnostic("QGroundControl: " + reason + "; control requires a new --control run");
}
void ManualOperator::poll(Actions& actions, Time now) {
    bool expired;
    { std::lock_guard<std::mutex> lock(mutex_); expired = status_.client && now - last_client_ >= std::chrono::seconds(5); }
    if (expired) disconnect(actions, "client inactive for 5 seconds");
    if (socket_failed_) {
        if (!disabled_) disconnect(actions, "UDP socket failed");
        return;
    }
    // Bound work even when a local sender floods the listener. Excess packets
    // stay in the bounded kernel buffer; no blocking socket work on this tick.
    for (unsigned packet = 0; packet < 32; ++packet) {
        std::array<std::uint8_t, 16384> buffer{};
        sockaddr_in source{};
        iovec vector{buffer.data(), buffer.size()};
        msghdr message{}; message.msg_name = &source; message.msg_namelen = sizeof(source);
        message.msg_iov = &vector; message.msg_iovlen = 1;
        const auto size = recvmsg(socket_, &message, 0);
        if (size < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) break;
            if (errno == EINTR) continue;
            error(socket_error("receive UDP", errno)); socket_failed_ = true;
            disconnect(actions, "UDP receive failed"); return;
        }
        // Pin the configured client endpoint; unrelated local senders cannot
        // establish presence, renew a lease or inject traffic into this run.
        if (source.sin_family != AF_INET || source.sin_addr.s_addr != htonl(INADDR_LOOPBACK) ||
            ntohs(source.sin_port) != options_.qgc) continue;
        { std::lock_guard<std::mutex> lock(mutex_); ++status_.datagrams; }
        std::vector<Bytes> parsed;
        if ((message.msg_flags & MSG_TRUNC) || !frames(buffer.data(), static_cast<std::size_t>(size), parsed)) {
            std::lock_guard<std::mutex> lock(mutex_); ++status_.rejected; continue;
        }
        bool acquire;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            status_.client = true; last_client_ = now;
            acquire = options_.control && !disabled_ && !status_.attempted && telemetry_connected_;
        }
        actions.client_activity();
        if (acquire && actions.acquire("QGroundControl")) {
            std::lock_guard<std::mutex> lock(mutex_); status_.attempted = true;
        }
        for (auto& frame : parsed) {
            bool forward;
            { std::lock_guard<std::mutex> lock(mutex_); forward = options_.control && !disabled_ && status_.held; }
            if (forward && !actions.send(std::move(frame))) {
                std::lock_guard<std::mutex> lock(mutex_); ++status_.dropped;
            }
        }
    }
    // A heartbeat can arrive before WebRTC is ready. A later connection must
    // still permit the initial attempt without requiring another MAVLink 2
    // packet. Once attempted (even if busy/lost), this flag never resets.
    bool acquire;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        acquire = options_.control && !disabled_ && !status_.attempted && status_.client && telemetry_connected_;
    }
    if (acquire && actions.acquire("QGroundControl")) {
        std::lock_guard<std::mutex> lock(mutex_); status_.attempted = true;
    }
}
void ManualOperator::telemetry(const Bytes& frame) {
    if (!valid_mavlink2(frame)) return;
    { std::lock_guard<std::mutex> lock(mutex_); ++status_.telemetry; }
    const auto address = loopback(options_.qgc);
    if (sendto(socket_, frame.data(), frame.size(), 0, reinterpret_cast<const sockaddr*>(&address), sizeof(address)) < 0) {
        const auto code = errno;
        { std::lock_guard<std::mutex> lock(mutex_); ++status_.dropped; }
        if (code != EAGAIN && code != EWOULDBLOCK && code != EINTR) {
            error(socket_error("send UDP to QGroundControl", code)); socket_failed_ = true;
        }
    }
}
void ManualOperator::video(const EncodedVideo& frame) {
    bool first;
    { std::lock_guard<std::mutex> lock(mutex_); first = ++status_.video == 1; }
    if (!first) return;
    std::ostringstream text;
    text << "video observation codec=" << frame.codec << " bytes=" << frame.bytes.size()
        << " presentation100ns=" << frame.presentation_100ns << " receiptUnixMs="
        << std::chrono::duration_cast<std::chrono::milliseconds>(frame.received.time_since_epoch()).count();
    diagnostic(text.str());
}
void ManualOperator::connection(Stream stream, Connection state, const std::string& detail) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (stream == Stream::telemetry) { telemetry_connected_ = state == Connection::connected; status_.telemetry_error = detail; }
        else status_.video_error = detail;
    }
    diagnostic(std::string(stream == Stream::telemetry ? "telemetry" : "video") +
               " connection=" + std::to_string(static_cast<int>(state)) + " " + detail);
}
void ManualOperator::control(bool held, const std::string& reason) {
    { std::lock_guard<std::mutex> lock(mutex_); status_.held = held; }
    diagnostic("control=" + std::to_string(held) + " " + reason);
}
}
