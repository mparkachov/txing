#pragma once

#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace txing::virtual_quad {

// Owns the single write path into this session's loopback SITL socket.
class FlightControl {
  public:
    using Clock = std::chrono::steady_clock;
    using Frame = std::vector<std::uint8_t>;
    using Sender = std::function<bool(const Frame&)>;
    using Now = std::function<Clock::time_point()>;

    explicit FlightControl(Sender send, Now now = Clock::now);
    ~FlightControl();

    std::uint64_t OpenPeer();
    void ClosePeer(std::uint64_t peer);
    std::string HandleControl(std::uint64_t peer, const std::string& request);
    void SendFrame(std::uint64_t peer, std::uint64_t epoch, const Frame& frame);

    // Returns true for a valid heartbeat from the pinned autopilot target.
    static bool IsAutopilotHeartbeat(const Frame& frame);
    void Observe(const Frame& frame);
    void Tick(bool media_ready);
    void Stop();
    bool SafeToExit();

  private:
    struct State;
    std::unique_ptr<State> state_;
};

}  // namespace txing::virtual_quad
