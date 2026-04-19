#include "kvs_master/video_capturer.hpp"

#include <memory>
#include <stdexcept>

namespace txing::board::kvs_master {
namespace {

class UnsupportedVideoCapturer final : public VideoCapturer {
  public:
    void Configure(const CameraConfig& config) override {
        config_ = config;
        status_ = VideoCapturerStatus::kConfigured;
    }

    void Start() override {
        status_ = VideoCapturerStatus::kError;
        throw std::runtime_error(
            "libcamera hardware H.264 support is not available in this build; rebuild on Raspberry Pi OS with libcamera-dev"
        );
    }

    std::optional<EncodedVideoFrame> GetFrame(std::uint32_t /*timeout_ms*/) override {
        return std::nullopt;
    }

    void Stop() noexcept override {
        status_ = VideoCapturerStatus::kStopped;
    }

    VideoCapturerStatus GetStatus() const noexcept override {
        return status_;
    }

  private:
    CameraConfig config_;
    VideoCapturerStatus status_ = VideoCapturerStatus::kNotReady;
};

}  // namespace

std::unique_ptr<VideoCapturer> CreateVideoCapturer() {
    return std::make_unique<UnsupportedVideoCapturer>();
}

}  // namespace txing::board::kvs_master
