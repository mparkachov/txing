#include "kvs_master/video_capturer.hpp"

#include <libcamera/base/span.h>
#include <libcamera/camera.h>
#include <libcamera/camera_manager.h>
#include <libcamera/control_ids.h>
#include <libcamera/framebuffer.h>
#include <libcamera/framebuffer_allocator.h>
#include <libcamera/formats.h>
#include <libcamera/request.h>

#include <linux/videodev2.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <mutex>
#include <optional>
#include <poll.h>
#include <queue>
#include <stdexcept>
#include <string>
#include <string_view>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <thread>
#include <unistd.h>
#include <utility>
#include <vector>

namespace txing::board::kvs_master {
namespace {

constexpr char kEncoderDevice[] = "/dev/video11";
constexpr unsigned int kCaptureBufferCount = 6;
constexpr std::uint32_t kPollTimeoutMs = 100;

int RetryIoctl(const int fd, const unsigned long request, void* arg) {
    int result = -1;
    int attempts = 10;
    do {
        result = ioctl(fd, request, arg);
    } while (result == -1 && errno == EINTR && attempts-- > 0);
    return result;
}

struct CaptureBuffer {
    void* memory = MAP_FAILED;
    std::size_t size = 0;
};

struct PendingCameraRequest {
    libcamera::Request* request = nullptr;
    libcamera::FrameBuffer* buffer = nullptr;
    std::uint64_t timestamp_us = 0;
};

struct OutputSlot {
    libcamera::Request* request = nullptr;
};

std::uint32_t ImportedDmabufSpan(const libcamera::FrameBuffer& buffer) {
    const auto& planes = buffer.planes();
    if (planes.empty()) {
        throw std::runtime_error("libcamera buffer does not contain any planes");
    }

    const int dma_fd = planes.front().fd.get();
    if (dma_fd < 0) {
        throw std::runtime_error("libcamera buffer plane does not expose a valid DMABUF fd");
    }

    std::uint64_t span = 0;
    for (const auto& plane : planes) {
        if (plane.fd.get() != dma_fd) {
            throw std::runtime_error("libcamera buffer uses multiple DMABUF fds; unsupported encoder import layout");
        }
        span = std::max<std::uint64_t>(span, static_cast<std::uint64_t>(plane.offset) + plane.length);
    }

    if (span == 0 || span > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("libcamera buffer span is invalid for V4L2 encoder import");
    }

    return static_cast<std::uint32_t>(span);
}

class LibcameraVideoCapturer final : public VideoCapturer {
  public:
    ~LibcameraVideoCapturer() override {
        Stop();
    }

    void Configure(const CameraConfig& config) override {
        config_ = config;
        SetStatus(VideoCapturerStatus::kConfigured);
    }

    void Start() override {
        if (status_ == VideoCapturerStatus::kStreaming) {
            return;
        }
        EnsureConfigured();

        stop_requested_.store(false);
        InitializeCamera();
        InitializeEncoder();

        encoder_input_thread_ = std::thread(&LibcameraVideoCapturer::EncoderInputLoop, this);
        encoder_poll_thread_ = std::thread(&LibcameraVideoCapturer::EncoderPollLoop, this);
        SetStatus(VideoCapturerStatus::kStreaming);
    }

    std::optional<EncodedVideoFrame> GetFrame(std::uint32_t timeout_ms) override {
        std::unique_lock<std::mutex> lock(queue_lock_);
        frame_ready_.wait_for(
            lock,
            std::chrono::milliseconds(timeout_ms),
            [this]() { return !encoded_frames_.empty() || fatal_error_.has_value() || stop_requested_.load(); }
        );

        if (fatal_error_) {
            throw std::runtime_error(*fatal_error_);
        }
        if (encoded_frames_.empty()) {
            return std::nullopt;
        }

        EncodedVideoFrame frame = std::move(encoded_frames_.front());
        encoded_frames_.pop();
        return frame;
    }

    void Stop() noexcept override {
        stop_requested_.store(true);
        pending_ready_.notify_all();
        frame_ready_.notify_all();

        if (camera_) {
            camera_->requestCompleted.disconnect(this, &LibcameraVideoCapturer::OnRequestCompleted);
            camera_->stop();
        }

        JoinThread(encoder_input_thread_);
        JoinThread(encoder_poll_thread_);
        ShutdownEncoder();
        ShutdownCamera();

        std::lock_guard<std::mutex> lock(queue_lock_);
        while (!pending_requests_.empty()) {
            pending_requests_.pop();
        }
        while (!encoded_frames_.empty()) {
            encoded_frames_.pop();
        }
        fatal_error_.reset();
        SetStatus(VideoCapturerStatus::kStopped);
    }

    VideoCapturerStatus GetStatus() const noexcept override {
        return status_;
    }

  private:
    void EnsureConfigured() const {
        if (status_ == VideoCapturerStatus::kNotReady) {
            throw std::runtime_error("video capturer must be configured before start");
        }
    }

    void SetStatus(const VideoCapturerStatus status) noexcept {
        status_ = status;
    }

    void SetFatalError(std::string message) {
        std::lock_guard<std::mutex> lock(queue_lock_);
        if (fatal_error_) {
            return;
        }
        fatal_error_ = std::move(message);
        stop_requested_.store(true);
        status_ = VideoCapturerStatus::kError;
        pending_ready_.notify_all();
        frame_ready_.notify_all();
    }

    void InitializeCamera() {
        camera_manager_ = std::make_unique<libcamera::CameraManager>();
        if (camera_manager_->start() != 0) {
            throw std::runtime_error("failed to start libcamera camera manager");
        }

        const auto cameras = camera_manager_->cameras();
        if (config_.camera >= cameras.size()) {
            throw std::runtime_error("configured camera index is not available");
        }

        camera_ = cameras[config_.camera];
        if (!camera_) {
            throw std::runtime_error("failed to resolve libcamera device");
        }
        if (camera_->acquire() != 0) {
            throw std::runtime_error("failed to acquire libcamera device");
        }

        camera_configuration_ = camera_->generateConfiguration({libcamera::StreamRole::VideoRecording});
        if (!camera_configuration_ || camera_configuration_->empty()) {
            throw std::runtime_error("failed to generate libcamera video configuration");
        }

        auto& stream_config = camera_configuration_->at(0);
        stream_config.pixelFormat = libcamera::formats::YUV420;
        stream_config.size.width = config_.width;
        stream_config.size.height = config_.height;
        if (stream_config.bufferCount < 6) {
            stream_config.bufferCount = 6;
        }

        const auto validation = camera_configuration_->validate();
        if (validation == libcamera::CameraConfiguration::Status::Invalid) {
            throw std::runtime_error("invalid libcamera video configuration");
        }
        if (camera_->configure(camera_configuration_.get()) != 0) {
            throw std::runtime_error("failed to apply libcamera video configuration");
        }

        video_stream_ = stream_config.stream();
        frame_size_ = stream_config.frameSize;
        stride_ = stream_config.stride;

        allocator_ = std::make_unique<libcamera::FrameBufferAllocator>(camera_);
        if (allocator_->allocate(video_stream_) < 0) {
            throw std::runtime_error("failed to allocate libcamera frame buffers");
        }

        const auto& buffers = allocator_->buffers(video_stream_);
        requests_.clear();
        requests_.reserve(buffers.size());
        for (const auto& buffer : buffers) {
            auto request = camera_->createRequest();
            if (!request) {
                throw std::runtime_error("failed to create libcamera request");
            }
            if (request->addBuffer(video_stream_, buffer.get()) < 0) {
                throw std::runtime_error("failed to add video buffer to libcamera request");
            }
            requests_.push_back(std::move(request));
        }

        std::array<std::int64_t, 2> frame_duration_limits = {
            static_cast<std::int64_t>(1'000'000 / std::max<std::uint32_t>(1, config_.framerate)),
            static_cast<std::int64_t>(1'000'000 / std::max<std::uint32_t>(1, config_.framerate)),
        };
        libcamera::ControlList controls(camera_->controls());
        controls.set(
            libcamera::controls::FrameDurationLimits,
            libcamera::Span<const std::int64_t, 2>(frame_duration_limits.data(), frame_duration_limits.size())
        );

        camera_->requestCompleted.connect(this, &LibcameraVideoCapturer::OnRequestCompleted);
        if (camera_->start(&controls) != 0) {
            throw std::runtime_error("failed to start libcamera capture");
        }

        for (const auto& request : requests_) {
            if (camera_->queueRequest(request.get()) < 0) {
                throw std::runtime_error("failed to queue initial libcamera request");
            }
        }
    }

    void ShutdownCamera() noexcept {
        requests_.clear();
        allocator_.reset();
        camera_configuration_.reset();
        video_stream_ = nullptr;
        frame_size_ = 0;
        stride_ = 0;

        if (camera_) {
            camera_->release();
            camera_.reset();
        }
        if (camera_manager_) {
            camera_manager_->stop();
            camera_manager_.reset();
        }
    }

    void InitializeEncoder() {
        encoder_fd_ = open(kEncoderDevice, O_RDWR | O_NONBLOCK, 0);
        if (encoder_fd_ < 0) {
            throw std::runtime_error("failed to open V4L2 H.264 encoder");
        }

        v4l2_control control = {};
        control.id = V4L2_CID_MPEG_VIDEO_BITRATE;
        control.value = static_cast<__s32>(config_.bitrate);
        if (RetryIoctl(encoder_fd_, VIDIOC_S_CTRL, &control) < 0) {
            throw std::runtime_error("failed to configure encoder bitrate");
        }

        control = {};
        control.id = V4L2_CID_MPEG_VIDEO_H264_I_PERIOD;
        control.value = static_cast<__s32>(config_.intra);
        if (RetryIoctl(encoder_fd_, VIDIOC_S_CTRL, &control) < 0) {
            throw std::runtime_error("failed to configure encoder intra period");
        }

        control = {};
        control.id = V4L2_CID_MPEG_VIDEO_REPEAT_SEQ_HEADER;
        control.value = 1;
        if (RetryIoctl(encoder_fd_, VIDIOC_S_CTRL, &control) < 0) {
            throw std::runtime_error("failed to configure encoder inline sequence headers");
        }

        v4l2_format format = {};
        format.type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
        format.fmt.pix_mp.width = config_.width;
        format.fmt.pix_mp.height = config_.height;
        format.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_YUV420;
        format.fmt.pix_mp.field = V4L2_FIELD_ANY;
        format.fmt.pix_mp.num_planes = 1;
        format.fmt.pix_mp.plane_fmt[0].bytesperline = stride_;
        if (RetryIoctl(encoder_fd_, VIDIOC_S_FMT, &format) < 0) {
            throw std::runtime_error("failed to configure encoder input format");
        }

        format = {};
        format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        format.fmt.pix_mp.width = config_.width;
        format.fmt.pix_mp.height = config_.height;
        format.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_H264;
        format.fmt.pix_mp.field = V4L2_FIELD_ANY;
        format.fmt.pix_mp.num_planes = 1;
        format.fmt.pix_mp.plane_fmt[0].sizeimage = 512 << 10;
        if (RetryIoctl(encoder_fd_, VIDIOC_S_FMT, &format) < 0) {
            throw std::runtime_error("failed to configure encoder output format");
        }

        v4l2_streamparm stream_parameters = {};
        stream_parameters.type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
        stream_parameters.parm.output.timeperframe.numerator = 90000 / std::max<std::uint32_t>(1, config_.framerate);
        stream_parameters.parm.output.timeperframe.denominator = 90000;
        if (RetryIoctl(encoder_fd_, VIDIOC_S_PARM, &stream_parameters) < 0) {
            throw std::runtime_error("failed to configure encoder frame rate");
        }

        const auto output_buffer_count = static_cast<unsigned int>(requests_.size());

        v4l2_requestbuffers request_buffers = {};
        request_buffers.count = output_buffer_count;
        request_buffers.type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
        request_buffers.memory = V4L2_MEMORY_DMABUF;
        if (RetryIoctl(encoder_fd_, VIDIOC_REQBUFS, &request_buffers) < 0) {
            throw std::runtime_error("failed to allocate encoder input buffers");
        }

        output_slots_.assign(request_buffers.count, {});
        for (unsigned int index = 0; index < request_buffers.count; ++index) {
            available_output_buffers_.push(index);
        }

        request_buffers = {};
        request_buffers.count = kCaptureBufferCount;
        request_buffers.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        request_buffers.memory = V4L2_MEMORY_MMAP;
        if (RetryIoctl(encoder_fd_, VIDIOC_REQBUFS, &request_buffers) < 0) {
            throw std::runtime_error("failed to allocate encoder capture buffers");
        }

        capture_buffers_.assign(request_buffers.count, {});
        for (unsigned int index = 0; index < request_buffers.count; ++index) {
            v4l2_plane planes[VIDEO_MAX_PLANES] = {};
            v4l2_buffer buffer = {};
            buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
            buffer.memory = V4L2_MEMORY_MMAP;
            buffer.index = index;
            buffer.length = 1;
            buffer.m.planes = planes;
            if (RetryIoctl(encoder_fd_, VIDIOC_QUERYBUF, &buffer) < 0) {
                throw std::runtime_error("failed to query encoder capture buffer");
            }

            void* memory = mmap(
                nullptr,
                buffer.m.planes[0].length,
                PROT_READ | PROT_WRITE,
                MAP_SHARED,
                encoder_fd_,
                buffer.m.planes[0].m.mem_offset
            );
            if (memory == MAP_FAILED) {
                throw std::runtime_error("failed to map encoder capture buffer");
            }

            capture_buffers_[index].memory = memory;
            capture_buffers_[index].size = buffer.m.planes[0].length;

            if (RetryIoctl(encoder_fd_, VIDIOC_QBUF, &buffer) < 0) {
                throw std::runtime_error("failed to queue encoder capture buffer");
            }
        }

        v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
        if (RetryIoctl(encoder_fd_, VIDIOC_STREAMON, &type) < 0) {
            throw std::runtime_error("failed to start encoder input stream");
        }
        type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        if (RetryIoctl(encoder_fd_, VIDIOC_STREAMON, &type) < 0) {
            throw std::runtime_error("failed to start encoder capture stream");
        }
    }

    void ShutdownEncoder() noexcept {
        if (encoder_fd_ < 0) {
            return;
        }

        v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
        RetryIoctl(encoder_fd_, VIDIOC_STREAMOFF, &type);
        type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
        RetryIoctl(encoder_fd_, VIDIOC_STREAMOFF, &type);

        for (auto& buffer : capture_buffers_) {
            if (buffer.memory != MAP_FAILED) {
                munmap(buffer.memory, buffer.size);
                buffer.memory = MAP_FAILED;
                buffer.size = 0;
            }
        }
        capture_buffers_.clear();
        output_slots_.clear();
        while (!available_output_buffers_.empty()) {
            available_output_buffers_.pop();
        }

        close(encoder_fd_);
        encoder_fd_ = -1;
    }

    void OnRequestCompleted(libcamera::Request* request) {
        if (request == nullptr || stop_requested_.load()) {
            return;
        }

        if (request->status() == libcamera::Request::RequestCancelled) {
            SetFatalError("libcamera request was cancelled");
            return;
        }

        const auto buffer_it = request->buffers().find(video_stream_);
        if (buffer_it == request->buffers().end()) {
            SetFatalError("completed libcamera request did not include the video stream");
            return;
        }

        auto* buffer = buffer_it->second;
        if (buffer == nullptr) {
            SetFatalError("completed libcamera request returned a null buffer");
            return;
        }
        if (buffer->metadata().status != libcamera::FrameMetadata::FrameSuccess) {
            request->reuse(libcamera::Request::ReuseBuffers);
            if (camera_->queueRequest(request) < 0) {
                SetFatalError("failed to requeue libcamera request after a skipped frame");
            }
            return;
        }

        PendingCameraRequest pending;
        pending.request = request;
        pending.buffer = buffer;
        auto timestamp_ns = request->metadata().get(libcamera::controls::SensorTimestamp);
        if (timestamp_ns) {
            pending.timestamp_us = static_cast<std::uint64_t>(*timestamp_ns / 1000);
        } else {
            pending.timestamp_us = static_cast<std::uint64_t>(buffer->metadata().timestamp / 1000);
        }

        {
            std::lock_guard<std::mutex> lock(queue_lock_);
            pending_requests_.push(pending);
        }
        pending_ready_.notify_one();
    }

    void EncoderInputLoop() {
        while (!stop_requested_.load()) {
            PendingCameraRequest pending;
            unsigned int output_index = 0;

            {
                std::unique_lock<std::mutex> lock(queue_lock_);
                pending_ready_.wait(lock, [this]() {
                    return stop_requested_.load() || fatal_error_.has_value() ||
                        (!pending_requests_.empty() && !available_output_buffers_.empty());
                });

                if (stop_requested_.load() || fatal_error_) {
                    return;
                }

                pending = pending_requests_.front();
                pending_requests_.pop();
                output_index = available_output_buffers_.front();
                available_output_buffers_.pop();
            }

            try {
                QueueEncoderInput(output_index, pending);
            } catch (const std::exception& error) {
                SetFatalError(error.what());
                return;
            }
        }
    }

    void QueueEncoderInput(const unsigned int output_index, const PendingCameraRequest& pending) {
        const auto imported_span = ImportedDmabufSpan(*pending.buffer);
        v4l2_plane planes[VIDEO_MAX_PLANES] = {};
        v4l2_buffer buffer = {};
        buffer.type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
        buffer.memory = V4L2_MEMORY_DMABUF;
        buffer.index = output_index;
        buffer.length = 1;
        buffer.m.planes = planes;
        buffer.timestamp.tv_sec = static_cast<decltype(buffer.timestamp.tv_sec)>(pending.timestamp_us / 1'000'000);
        buffer.timestamp.tv_usec = static_cast<decltype(buffer.timestamp.tv_usec)>(pending.timestamp_us % 1'000'000);

        planes[0].m.fd = pending.buffer->planes()[0].fd.get();
        planes[0].length = imported_span;
        planes[0].bytesused = imported_span;

        if (RetryIoctl(encoder_fd_, VIDIOC_QBUF, &buffer) < 0) {
            throw std::runtime_error("failed to queue libcamera buffer into the H.264 encoder");
        }

        output_slots_[output_index].request = pending.request;
    }

    void EncoderPollLoop() {
        while (!stop_requested_.load()) {
            pollfd poll_descriptor = {};
            poll_descriptor.fd = encoder_fd_;
            poll_descriptor.events = POLLIN | POLLOUT | POLLERR;
            const auto poll_result = poll(&poll_descriptor, 1, static_cast<int>(kPollTimeoutMs));
            if (poll_result < 0) {
                if (errno == EINTR) {
                    continue;
                }
                SetFatalError("failed to poll the H.264 encoder");
                return;
            }
            if (poll_result == 0) {
                continue;
            }
            if ((poll_descriptor.revents & POLLERR) != 0) {
                SetFatalError("the H.264 encoder reported a poll error");
                return;
            }

            try {
                DrainEncoderInputCompletions();
                DrainEncoderCapture();
            } catch (const std::exception& error) {
                SetFatalError(error.what());
                return;
            }
        }
    }

    void DrainEncoderInputCompletions() {
        while (true) {
            v4l2_plane planes[VIDEO_MAX_PLANES] = {};
            v4l2_buffer buffer = {};
            buffer.type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
            buffer.memory = V4L2_MEMORY_DMABUF;
            buffer.length = 1;
            buffer.m.planes = planes;

            if (RetryIoctl(encoder_fd_, VIDIOC_DQBUF, &buffer) < 0) {
                if (errno == EAGAIN) {
                    return;
                }
                throw std::runtime_error("failed to dequeue completed encoder input buffer");
            }

            libcamera::Request* request = output_slots_.at(buffer.index).request;
            output_slots_[buffer.index].request = nullptr;
            {
                std::lock_guard<std::mutex> lock(queue_lock_);
                available_output_buffers_.push(buffer.index);
            }
            pending_ready_.notify_one();

            if (request != nullptr && !stop_requested_.load()) {
                request->reuse(libcamera::Request::ReuseBuffers);
                if (camera_->queueRequest(request) < 0) {
                    throw std::runtime_error("failed to requeue libcamera request after encoding");
                }
            }
        }
    }

    void DrainEncoderCapture() {
        while (true) {
            v4l2_plane planes[VIDEO_MAX_PLANES] = {};
            v4l2_buffer buffer = {};
            buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
            buffer.memory = V4L2_MEMORY_MMAP;
            buffer.length = 1;
            buffer.m.planes = planes;

            if (RetryIoctl(encoder_fd_, VIDIOC_DQBUF, &buffer) < 0) {
                if (errno == EAGAIN) {
                    return;
                }
                throw std::runtime_error("failed to dequeue encoder capture buffer");
            }

            EncodedVideoFrame frame;
            const auto bytes_used = static_cast<std::size_t>(buffer.m.planes[0].bytesused);
            frame.bytes.resize(bytes_used);
            std::memcpy(frame.bytes.data(), capture_buffers_.at(buffer.index).memory, bytes_used);
            frame.timestamp_us = static_cast<std::uint64_t>(buffer.timestamp.tv_sec) * 1'000'000ULL +
                static_cast<std::uint64_t>(buffer.timestamp.tv_usec);
            frame.is_keyframe = (buffer.flags & V4L2_BUF_FLAG_KEYFRAME) != 0;

            {
                std::lock_guard<std::mutex> lock(queue_lock_);
                encoded_frames_.push(std::move(frame));
            }
            frame_ready_.notify_one();

            if (RetryIoctl(encoder_fd_, VIDIOC_QBUF, &buffer) < 0) {
                throw std::runtime_error("failed to requeue encoder capture buffer");
            }
        }
    }

    void JoinThread(std::thread& thread) noexcept {
        if (thread.joinable()) {
            thread.join();
        }
    }

    CameraConfig config_;
    VideoCapturerStatus status_ = VideoCapturerStatus::kNotReady;
    std::atomic_bool stop_requested_ = false;

    std::mutex queue_lock_;
    std::condition_variable pending_ready_;
    std::condition_variable frame_ready_;
    std::queue<PendingCameraRequest> pending_requests_;
    std::queue<EncodedVideoFrame> encoded_frames_;
    std::queue<unsigned int> available_output_buffers_;
    std::optional<std::string> fatal_error_;

    std::unique_ptr<libcamera::CameraManager> camera_manager_;
    std::shared_ptr<libcamera::Camera> camera_;
    std::unique_ptr<libcamera::CameraConfiguration> camera_configuration_;
    std::unique_ptr<libcamera::FrameBufferAllocator> allocator_;
    libcamera::Stream* video_stream_ = nullptr;
    std::vector<std::unique_ptr<libcamera::Request>> requests_;

    int encoder_fd_ = -1;
    std::size_t frame_size_ = 0;
    std::uint32_t stride_ = 0;
    std::vector<CaptureBuffer> capture_buffers_;
    std::vector<OutputSlot> output_slots_;

    std::thread encoder_input_thread_;
    std::thread encoder_poll_thread_;
};

}  // namespace

std::unique_ptr<VideoCapturer> CreateVideoCapturer() {
    return std::make_unique<LibcameraVideoCapturer>();
}

}  // namespace txing::board::kvs_master
