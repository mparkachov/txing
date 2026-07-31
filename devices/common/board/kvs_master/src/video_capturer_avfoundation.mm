// macOS VideoCapturer: AVCaptureSession frames (NV12) encoded through a
// VideoToolbox H.264 compression session. Emits Annex-B access units with
// SPS/PPS prepended on keyframes, matching the libcamera capturer's output
// invariants (see video_capturer_libcamera.cpp).

#include "kvs_master/video_capturer.hpp"

#import <AVFoundation/AVFoundation.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreVideo/CoreVideo.h>
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#if !__has_feature(objc_arc)
#error "video_capturer_avfoundation.mm must be compiled with -fobjc-arc"
#endif

namespace txing::board::kvs_master {
namespace avfoundation {
class AvFoundationVideoCapturer;
}  // namespace avfoundation
}  // namespace txing::board::kvs_master

@interface TxingKvsCaptureDelegate : NSObject <AVCaptureVideoDataOutputSampleBufferDelegate>
@property(atomic, assign) txing::board::kvs_master::avfoundation::AvFoundationVideoCapturer* owner;
@end

namespace txing::board::kvs_master {
namespace avfoundation {

constexpr std::size_t kMaxQueuedFrames = 60;
constexpr std::uint8_t kAnnexBStartCode[] = {0, 0, 0, 1};
constexpr std::int64_t kCameraPermissionPromptTimeoutSeconds = 180;

void CompressionOutputThunk(
    void* refcon,
    void* source_frame_refcon,
    OSStatus status,
    VTEncodeInfoFlags info_flags,
    CMSampleBufferRef sample_buffer
);

class AvFoundationVideoCapturer final : public VideoCapturer {
  public:
    ~AvFoundationVideoCapturer() override {
        Stop();
    }

    void Configure(const CameraConfig& config) override {
        config_ = config;
        status_ = VideoCapturerStatus::kConfigured;
    }

    void Start() override {
        if (status_ == VideoCapturerStatus::kStreaming) {
            return;
        }
        if (status_ == VideoCapturerStatus::kNotReady) {
            throw std::runtime_error("video capturer must be configured before start");
        }

        stop_requested_.store(false);
        @autoreleasepool {
            EnsureCameraAccess();
            try {
                SetupCaptureSession();
            } catch (const std::exception&) {
                TeardownCaptureSession();
                status_ = VideoCapturerStatus::kError;
                throw;
            }
        }
        status_ = VideoCapturerStatus::kStreaming;
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
        encoded_frames_.pop_front();
        return frame;
    }

    void Stop() noexcept override {
        stop_requested_.store(true);
        frame_ready_.notify_all();

        @autoreleasepool {
            TeardownCaptureSession();
        }

        std::lock_guard<std::mutex> lock(queue_lock_);
        encoded_frames_.clear();
        fatal_error_.reset();
        status_ = VideoCapturerStatus::kStopped;
    }

    VideoCapturerStatus GetStatus() const noexcept override {
        return status_;
    }

    // Called on the capture dispatch queue.
    void OnSampleBuffer(CMSampleBufferRef sample_buffer) {
        if (stop_requested_.load() || sample_buffer == nullptr) {
            return;
        }
        CVImageBufferRef image = CMSampleBufferGetImageBuffer(sample_buffer);
        if (image == nullptr) {
            return;
        }

        try {
            EnsureCompressionSession(image);
        } catch (const std::exception& error) {
            SetFatalError(error.what());
            return;
        }

        const CMTime presentation = CMSampleBufferGetPresentationTimeStamp(sample_buffer);
        const CMTime duration = CMSampleBufferGetDuration(sample_buffer);
        VTEncodeInfoFlags info_flags = 0;
        const OSStatus status = VTCompressionSessionEncodeFrame(
            compression_session_,
            image,
            presentation,
            duration,
            nullptr,
            nullptr,
            &info_flags
        );
        if (status != noErr) {
            SetFatalError(
                "VideoToolbox rejected a camera frame for encoding (status " + std::to_string(status) + ")"
            );
        }
    }

    // Called on VideoToolbox's encoder thread.
    void OnEncodedFrame(OSStatus status, VTEncodeInfoFlags info_flags, CMSampleBufferRef sample_buffer) {
        if (stop_requested_.load()) {
            return;
        }
        if (status != noErr) {
            SetFatalError("VideoToolbox H.264 encoding failed (status " + std::to_string(status) + ")");
            return;
        }
        if ((info_flags & kVTEncodeInfo_FrameDropped) != 0 || sample_buffer == nullptr) {
            return;
        }
        if (!CMSampleBufferDataIsReady(sample_buffer)) {
            return;
        }

        EncodedVideoFrame frame;
        frame.is_keyframe = IsKeyframe(sample_buffer);
        try {
            frame.bytes = AnnexBAccessUnit(sample_buffer, frame.is_keyframe);
        } catch (const std::exception& error) {
            SetFatalError(error.what());
            return;
        }
        if (frame.bytes.empty()) {
            return;
        }

        const CMTime presentation = CMSampleBufferGetPresentationTimeStamp(sample_buffer);
        if (CMTIME_IS_NUMERIC(presentation)) {
            const CMTime microseconds =
                CMTimeConvertScale(presentation, 1'000'000, kCMTimeRoundingMethod_Default);
            if (microseconds.value > 0) {
                frame.timestamp_us = static_cast<std::uint64_t>(microseconds.value);
            }
        }

        {
            std::lock_guard<std::mutex> lock(queue_lock_);
            if (encoded_frames_.size() >= kMaxQueuedFrames) {
                encoded_frames_.pop_front();
            }
            encoded_frames_.push_back(std::move(frame));
        }
        frame_ready_.notify_one();
    }

    void SetFatalError(std::string message) {
        std::lock_guard<std::mutex> lock(queue_lock_);
        if (fatal_error_) {
            return;
        }
        fatal_error_ = std::move(message);
        stop_requested_.store(true);
        status_ = VideoCapturerStatus::kError;
        frame_ready_.notify_all();
    }

  private:
    void EnsureCameraAccess() {
        const AVAuthorizationStatus authorization =
            [AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo];
        if (authorization == AVAuthorizationStatusAuthorized) {
            return;
        }
        if (authorization == AVAuthorizationStatusNotDetermined) {
            dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
            __block BOOL granted = NO;
            [AVCaptureDevice requestAccessForMediaType:AVMediaTypeVideo
                                     completionHandler:^(BOOL result) {
                                         granted = result;
                                         dispatch_semaphore_signal(semaphore);
                                     }];
            const dispatch_time_t deadline = dispatch_time(
                DISPATCH_TIME_NOW,
                kCameraPermissionPromptTimeoutSeconds * NSEC_PER_SEC
            );
            if (dispatch_semaphore_wait(semaphore, deadline) != 0) {
                throw std::runtime_error(
                    "timed out waiting for the macOS camera permission prompt; run the camera probe "
                    "from a foreground terminal and grant access"
                );
            }
            if (!granted) {
                throw std::runtime_error(
                    "macOS camera access was denied; allow the terminal application under "
                    "System Settings > Privacy & Security > Camera and retry"
                );
            }
            return;
        }
        throw std::runtime_error(
            "macOS camera access is denied or restricted for this process; allow the terminal "
            "application under System Settings > Privacy & Security > Camera and retry"
        );
    }

    void SetupCaptureSession() {
        NSMutableArray<AVCaptureDeviceType>* device_types =
            [NSMutableArray arrayWithObject:AVCaptureDeviceTypeBuiltInWideAngleCamera];
        if (@available(macOS 14.0, *)) {
            [device_types addObject:AVCaptureDeviceTypeExternal];
        }
        AVCaptureDeviceDiscoverySession* discovery = [AVCaptureDeviceDiscoverySession
            discoverySessionWithDeviceTypes:device_types
                                  mediaType:AVMediaTypeVideo
                                   position:AVCaptureDevicePositionUnspecified];
        NSArray<AVCaptureDevice*>* devices = discovery.devices;
        if (config_.camera >= devices.count) {
            throw std::runtime_error("configured camera index is not available");
        }
        AVCaptureDevice* device = devices[config_.camera];

        NSError* input_error = nil;
        AVCaptureDeviceInput* input = [AVCaptureDeviceInput deviceInputWithDevice:device
                                                                            error:&input_error];
        if (input == nil) {
            std::string message = "failed to open the camera device";
            if (input_error != nil) {
                message += std::string(": ") + input_error.localizedDescription.UTF8String;
            }
            throw std::runtime_error(message);
        }

        session_ = [[AVCaptureSession alloc] init];
        [session_ beginConfiguration];
        session_.sessionPreset = PreferredSessionPreset();

        if (![session_ canAddInput:input]) {
            [session_ commitConfiguration];
            throw std::runtime_error("failed to attach the camera input to the capture session");
        }
        [session_ addInput:input];

        output_ = [[AVCaptureVideoDataOutput alloc] init];
        output_.videoSettings = @{
            (id)kCVPixelBufferPixelFormatTypeKey : @(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange),
        };
        output_.alwaysDiscardsLateVideoFrames = YES;
        capture_queue_ = dispatch_queue_create("dev.txing.kvs.capture", DISPATCH_QUEUE_SERIAL);
        delegate_ = [[TxingKvsCaptureDelegate alloc] init];
        delegate_.owner = this;
        [output_ setSampleBufferDelegate:delegate_ queue:capture_queue_];
        if (![session_ canAddOutput:output_]) {
            [session_ commitConfiguration];
            throw std::runtime_error("failed to attach the video data output to the capture session");
        }
        [session_ addOutput:output_];
        [session_ commitConfiguration];

        PinFrameDuration(device);

        AvFoundationVideoCapturer* owner = this;
        observer_ = [[NSNotificationCenter defaultCenter]
            addObserverForName:AVCaptureSessionRuntimeErrorNotification
                        object:session_
                         queue:nil
                    usingBlock:^(NSNotification* notification) {
                        NSError* runtime_error = notification.userInfo[AVCaptureSessionErrorKey];
                        std::string message = "AVCaptureSession reported a runtime error";
                        if (runtime_error != nil) {
                            message += std::string(": ") + runtime_error.localizedDescription.UTF8String;
                        }
                        owner->SetFatalError(message);
                    }];

        [session_ startRunning];
        if (!session_.running) {
            throw std::runtime_error("the camera capture session failed to start");
        }
    }

    NSString* PreferredSessionPreset() {
        if (config_.width >= 1920 && [session_ canSetSessionPreset:AVCaptureSessionPreset1920x1080]) {
            return AVCaptureSessionPreset1920x1080;
        }
        if (config_.width >= 1280 && [session_ canSetSessionPreset:AVCaptureSessionPreset1280x720]) {
            return AVCaptureSessionPreset1280x720;
        }
        if ([session_ canSetSessionPreset:AVCaptureSessionPreset640x480]) {
            return AVCaptureSessionPreset640x480;
        }
        return AVCaptureSessionPresetHigh;
    }

    // Best effort: an unsupported duration raises an NSException, and the
    // encoder tolerates whatever rate the camera actually delivers.
    void PinFrameDuration(AVCaptureDevice* device) {
        @try {
            if (![device lockForConfiguration:nil]) {
                return;
            }
            const auto framerate = static_cast<std::int32_t>(std::max<std::uint32_t>(1, config_.framerate));
            for (AVFrameRateRange* range in device.activeFormat.videoSupportedFrameRateRanges) {
                if (framerate >= static_cast<std::int32_t>(std::floor(range.minFrameRate)) &&
                    framerate <= static_cast<std::int32_t>(std::ceil(range.maxFrameRate))) {
                    const CMTime frame_duration = CMTimeMake(1, framerate);
                    device.activeVideoMinFrameDuration = frame_duration;
                    device.activeVideoMaxFrameDuration = frame_duration;
                    break;
                }
            }
            [device unlockForConfiguration];
        } @catch (NSException* exception) {
            (void)exception;
        }
    }

    void TeardownCaptureSession() noexcept {
        if (observer_ != nil) {
            [[NSNotificationCenter defaultCenter] removeObserver:observer_];
            observer_ = nil;
        }
        if (session_ != nil && session_.running) {
            [session_ stopRunning];
        }
        if (output_ != nil) {
            [output_ setSampleBufferDelegate:nil queue:nullptr];
        }
        if (delegate_ != nil) {
            delegate_.owner = nullptr;
        }
        if (capture_queue_ != nullptr) {
            // Drain in-flight capture callbacks before the compression
            // session they encode into is destroyed.
            dispatch_sync(capture_queue_, ^{});
        }
        DestroyCompressionSession();
        output_ = nil;
        delegate_ = nil;
        session_ = nil;
        capture_queue_ = nullptr;
    }

    void EnsureCompressionSession(CVImageBufferRef image) {
        const std::size_t width = CVPixelBufferGetWidth(image);
        const std::size_t height = CVPixelBufferGetHeight(image);
        if (compression_session_ != nullptr && width == encode_width_ && height == encode_height_) {
            return;
        }
        DestroyCompressionSession();

        VTCompressionSessionRef session = nullptr;
        const OSStatus status = VTCompressionSessionCreate(
            kCFAllocatorDefault,
            static_cast<std::int32_t>(width),
            static_cast<std::int32_t>(height),
            kCMVideoCodecType_H264,
            nullptr,
            nullptr,
            nullptr,
            &CompressionOutputThunk,
            this,
            &session
        );
        if (status != noErr || session == nullptr) {
            throw std::runtime_error(
                "failed to create the VideoToolbox H.264 compression session (status " +
                std::to_string(status) + ")"
            );
        }
        compression_session_ = session;
        encode_width_ = width;
        encode_height_ = height;

        const auto framerate = std::max<std::uint32_t>(1, config_.framerate);
        const auto intra = std::max<std::uint32_t>(1, config_.intra);
        SetProperty(kVTCompressionPropertyKey_RealTime, kCFBooleanTrue);
        SetProperty(kVTCompressionPropertyKey_AllowFrameReordering, kCFBooleanFalse);
        SetProperty(kVTCompressionPropertyKey_ProfileLevel, kVTProfileLevel_H264_Baseline_AutoLevel);
        SetNumberProperty(kVTCompressionPropertyKey_AverageBitRate, static_cast<std::int64_t>(config_.bitrate));
        SetNumberProperty(kVTCompressionPropertyKey_MaxKeyFrameInterval, static_cast<std::int64_t>(intra));
        SetDoubleProperty(
            kVTCompressionPropertyKey_MaxKeyFrameIntervalDuration,
            static_cast<double>(intra) / static_cast<double>(framerate)
        );
        SetNumberProperty(kVTCompressionPropertyKey_ExpectedFrameRate, static_cast<std::int64_t>(framerate));
        VTCompressionSessionPrepareToEncodeFrames(compression_session_);
    }

    // Encoder capability hints; unsupported properties are not fatal.
    void SetProperty(CFStringRef key, CFTypeRef value) noexcept {
        VTSessionSetProperty(compression_session_, key, value);
    }

    void SetNumberProperty(CFStringRef key, std::int64_t value) noexcept {
        CFNumberRef number = CFNumberCreate(kCFAllocatorDefault, kCFNumberSInt64Type, &value);
        if (number != nullptr) {
            VTSessionSetProperty(compression_session_, key, number);
            CFRelease(number);
        }
    }

    void SetDoubleProperty(CFStringRef key, double value) noexcept {
        CFNumberRef number = CFNumberCreate(kCFAllocatorDefault, kCFNumberDoubleType, &value);
        if (number != nullptr) {
            VTSessionSetProperty(compression_session_, key, number);
            CFRelease(number);
        }
    }

    void DestroyCompressionSession() noexcept {
        if (compression_session_ == nullptr) {
            return;
        }
        VTCompressionSessionCompleteFrames(compression_session_, kCMTimeInvalid);
        VTCompressionSessionInvalidate(compression_session_);
        CFRelease(compression_session_);
        compression_session_ = nullptr;
        encode_width_ = 0;
        encode_height_ = 0;
    }

    static bool IsKeyframe(CMSampleBufferRef sample_buffer) {
        CFArrayRef attachments = CMSampleBufferGetSampleAttachmentsArray(sample_buffer, false);
        if (attachments == nullptr || CFArrayGetCount(attachments) == 0) {
            return true;
        }
        const auto attachment =
            static_cast<CFDictionaryRef>(CFArrayGetValueAtIndex(attachments, 0));
        if (attachment == nullptr) {
            return true;
        }
        const void* not_sync = CFDictionaryGetValue(attachment, kCMSampleAttachmentKey_NotSync);
        if (not_sync == nullptr) {
            return true;
        }
        return !CFBooleanGetValue(static_cast<CFBooleanRef>(not_sync));
    }

    static std::vector<std::uint8_t> AnnexBAccessUnit(CMSampleBufferRef sample_buffer, bool keyframe) {
        CMFormatDescriptionRef format = CMSampleBufferGetFormatDescription(sample_buffer);
        if (format == nullptr) {
            throw std::runtime_error("encoded sample buffer is missing its format description");
        }

        std::size_t parameter_set_count = 0;
        int nal_length_size = 0;
        OSStatus status = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
            format, 0, nullptr, nullptr, &parameter_set_count, &nal_length_size
        );
        if (status != noErr || nal_length_size < 1 || nal_length_size > 4) {
            throw std::runtime_error(
                "failed to read H.264 parameter sets from the encoded frame (status " +
                std::to_string(status) + ")"
            );
        }

        std::vector<std::uint8_t> annex_b;
        if (keyframe) {
            for (std::size_t index = 0; index < parameter_set_count; ++index) {
                const std::uint8_t* parameter_set = nullptr;
                std::size_t parameter_set_size = 0;
                status = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
                    format, index, &parameter_set, &parameter_set_size, nullptr, nullptr
                );
                if (status != noErr || parameter_set == nullptr || parameter_set_size == 0) {
                    throw std::runtime_error("failed to copy an H.264 parameter set for a keyframe");
                }
                annex_b.insert(annex_b.end(), std::begin(kAnnexBStartCode), std::end(kAnnexBStartCode));
                annex_b.insert(annex_b.end(), parameter_set, parameter_set + parameter_set_size);
            }
        }

        CMBlockBufferRef block = CMSampleBufferGetDataBuffer(sample_buffer);
        if (block == nullptr) {
            throw std::runtime_error("encoded sample buffer is missing its data buffer");
        }
        const std::size_t total_length = CMBlockBufferGetDataLength(block);
        std::vector<std::uint8_t> avcc(total_length);
        if (total_length > 0 &&
            CMBlockBufferCopyDataBytes(block, 0, total_length, avcc.data()) != kCMBlockBufferNoErr) {
            throw std::runtime_error("failed to copy encoded frame bytes from the sample buffer");
        }

        const auto length_size = static_cast<std::size_t>(nal_length_size);
        std::size_t offset = 0;
        while (offset + length_size <= avcc.size()) {
            std::uint32_t nal_length = 0;
            for (std::size_t index = 0; index < length_size; ++index) {
                nal_length = (nal_length << 8) | avcc[offset + index];
            }
            offset += length_size;
            if (nal_length == 0 || offset + nal_length > avcc.size()) {
                throw std::runtime_error("encoded frame contains a malformed AVCC NAL unit length");
            }
            annex_b.insert(annex_b.end(), std::begin(kAnnexBStartCode), std::end(kAnnexBStartCode));
            annex_b.insert(annex_b.end(), avcc.data() + offset, avcc.data() + offset + nal_length);
            offset += nal_length;
        }
        if (offset != avcc.size()) {
            throw std::runtime_error("encoded frame contains trailing bytes after the last NAL unit");
        }
        return annex_b;
    }

    CameraConfig config_;
    VideoCapturerStatus status_ = VideoCapturerStatus::kNotReady;
    std::atomic_bool stop_requested_ = false;

    std::mutex queue_lock_;
    std::condition_variable frame_ready_;
    std::deque<EncodedVideoFrame> encoded_frames_;
    std::optional<std::string> fatal_error_;

    AVCaptureSession* session_ = nil;
    AVCaptureVideoDataOutput* output_ = nil;
    TxingKvsCaptureDelegate* delegate_ = nil;
    dispatch_queue_t capture_queue_ = nullptr;
    id observer_ = nil;

    VTCompressionSessionRef compression_session_ = nullptr;
    std::size_t encode_width_ = 0;
    std::size_t encode_height_ = 0;
};

void CompressionOutputThunk(
    void* refcon,
    void* source_frame_refcon,
    OSStatus status,
    VTEncodeInfoFlags info_flags,
    CMSampleBufferRef sample_buffer
) {
    (void)source_frame_refcon;
    auto* capturer = static_cast<AvFoundationVideoCapturer*>(refcon);
    if (capturer != nullptr) {
        capturer->OnEncodedFrame(status, info_flags, sample_buffer);
    }
}

}  // namespace avfoundation
}  // namespace txing::board::kvs_master

@implementation TxingKvsCaptureDelegate

- (void)captureOutput:(AVCaptureOutput*)output
    didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer
           fromConnection:(AVCaptureConnection*)connection {
    (void)output;
    (void)connection;
    auto* owner = self.owner;
    if (owner != nullptr) {
        owner->OnSampleBuffer(sampleBuffer);
    }
}

@end

namespace txing::board::kvs_master {

std::unique_ptr<VideoCapturer> CreateVideoCapturer() {
    return std::make_unique<avfoundation::AvFoundationVideoCapturer>();
}

}  // namespace txing::board::kvs_master
