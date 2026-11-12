#ifndef TXING_VIRTUAL_QUAD_CAMERA_HPP
#define TXING_VIRTUAL_QUAD_CAMERA_HPP

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <optional>

namespace txing::virtual_quad {

using Clock = std::chrono::steady_clock;
inline constexpr int camera_width = 640;
inline constexpr int camera_height = 360;
inline constexpr int camera_fps = 15;
inline constexpr std::size_t camera_frame_bytes = camera_width * camera_height * 3 / 2;

struct Ned {
    float north, east, down;
};

struct Attitude {
    float w, x, y, z;
};

struct Pose {
    Ned position;
    Attitude attitude;
};

struct PoseSample {
    Pose pose;
    Clock::time_point received;
};

std::optional<PoseSample> DecodeSimState(const std::uint8_t* frame, std::size_t size, Clock::time_point received);

class PoseHistory {
  public:
    void Push(PoseSample sample);
    std::optional<PoseSample> At(Clock::time_point now) const;

  private:
    std::optional<PoseSample> older_;
    std::optional<PoseSample> newer_;
};

// Writes a tightly packed 640x360 I420 frame.
void RenderCamera(const Pose& pose, std::uint8_t* frame);

}  // namespace txing::virtual_quad

#endif
