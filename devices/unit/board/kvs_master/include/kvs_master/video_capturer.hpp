#ifndef TXING_BOARD_KVS_MASTER_VIDEO_CAPTURER_HPP
#define TXING_BOARD_KVS_MASTER_VIDEO_CAPTURER_HPP

#include "kvs_master/config.hpp"

#include <cstdint>
#include <memory>
#include <optional>
#include <vector>

namespace txing::board::kvs_master {

enum class VideoCapturerStatus {
    kNotReady,
    kConfigured,
    kStreaming,
    kStopped,
    kError,
};

struct EncodedVideoFrame {
    std::vector<std::uint8_t> bytes;
    std::uint64_t timestamp_us = 0;
    bool is_keyframe = false;
};

class VideoCapturer {
  public:
    virtual ~VideoCapturer() = default;

    virtual void Configure(const CameraConfig& config) = 0;
    virtual void Start() = 0;
    virtual std::optional<EncodedVideoFrame> GetFrame(std::uint32_t timeout_ms) = 0;
    virtual void Stop() noexcept = 0;
    virtual VideoCapturerStatus GetStatus() const noexcept = 0;
};

std::unique_ptr<VideoCapturer> CreateVideoCapturer();

}  // namespace txing::board::kvs_master

#endif
