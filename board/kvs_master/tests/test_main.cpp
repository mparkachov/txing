#include "kvs_master/aws_env.hpp"
#include "kvs_master/config.hpp"
#include "kvs_master/markers.hpp"
#include "kvs_master/runtime.hpp"
#include "kvs_master/video_capturer.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {

using txing::board::kvs_master::AwsCredentials;
using txing::board::kvs_master::EncodedVideoFrame;
using txing::board::kvs_master::FormatMarkerLine;
using txing::board::kvs_master::KvsSession;
using txing::board::kvs_master::ParseCli;
using txing::board::kvs_master::ResolveAwsCredentials;
using txing::board::kvs_master::Run;
using txing::board::kvs_master::RuntimeConfig;
using txing::board::kvs_master::RuntimeHooks;
using txing::board::kvs_master::UsageText;
using txing::board::kvs_master::VideoCapturer;
using txing::board::kvs_master::VideoCapturerStatus;

int g_failures = 0;

void Expect(bool condition, const std::string& message) {
    if (!condition) {
        ++g_failures;
        std::cerr << "FAIL: " << message << '\n';
    }
}

txing::board::kvs_master::EnvLookup EnvFrom(const std::unordered_map<std::string, std::string>& values) {
    return [values](const std::string& key) -> std::optional<std::string> {
        const auto it = values.find(key);
        if (it == values.end()) {
            return std::nullopt;
        }
        return it->second;
    };
}

struct FakeKvsPush {
    std::uint64_t pts_100ns = 0;
    std::uint64_t duration_100ns = 0;
    bool is_keyframe = false;
    std::size_t len = 0;
};

struct FakeKvsState {
    bool started = false;
    bool stopped = false;
    std::vector<FakeKvsPush> pushes;
};

class FakeKvsSession final : public KvsSession {
  public:
    explicit FakeKvsSession(FakeKvsState* state) : state_(state) {}

    void Start() override {
        state_->started = true;
    }

    void PushH264AccessUnit(
        const std::uint8_t* data,
        std::size_t len,
        std::uint64_t presentation_ts_100ns,
        std::uint64_t duration_100ns,
        bool is_keyframe
    ) override {
        if (data == nullptr || len == 0) {
            throw std::runtime_error("unexpected empty frame");
        }
        FakeKvsPush push;
        push.pts_100ns = presentation_ts_100ns;
        push.duration_100ns = duration_100ns;
        push.is_keyframe = is_keyframe;
        push.len = len;
        state_->pushes.push_back(push);
    }

    void Stop() noexcept override {
        state_->stopped = true;
    }

    std::optional<std::string> TakeFatalError() override {
        return std::nullopt;
    }

  private:
    FakeKvsState* state_;
};

struct FakeCapturerState {
    VideoCapturerStatus status = VideoCapturerStatus::kNotReady;
    bool configured = false;
    bool started = false;
    bool stopped = false;
    bool throw_on_start = false;
    bool throw_on_get_frame = false;
    std::string error_message = "capturer failure";
    std::vector<EncodedVideoFrame> frames;
};

class FakeVideoCapturer final : public VideoCapturer {
  public:
    explicit FakeVideoCapturer(FakeCapturerState* state) : state_(state) {}

    void Configure(const txing::board::kvs_master::CameraConfig&) override {
        state_->configured = true;
        state_->status = VideoCapturerStatus::kConfigured;
    }

    void Start() override {
        if (state_->throw_on_start) {
            state_->status = VideoCapturerStatus::kError;
            throw std::runtime_error(state_->error_message);
        }
        state_->started = true;
        state_->status = VideoCapturerStatus::kStreaming;
    }

    std::optional<EncodedVideoFrame> GetFrame(std::uint32_t /*timeout_ms*/) override {
        if (state_->throw_on_get_frame) {
            state_->status = VideoCapturerStatus::kError;
            throw std::runtime_error(state_->error_message);
        }
        if (state_->frames.empty()) {
            state_->status = VideoCapturerStatus::kStopped;
            return std::nullopt;
        }
        auto frame = std::move(state_->frames.front());
        state_->frames.erase(state_->frames.begin());
        return frame;
    }

    void Stop() noexcept override {
        state_->stopped = true;
        state_->status = VideoCapturerStatus::kStopped;
    }

    VideoCapturerStatus GetStatus() const noexcept override {
        return state_->status;
    }

  private:
    FakeCapturerState* state_;
};

class ScopedStdoutCapture {
  public:
    ScopedStdoutCapture() : previous_(std::cout.rdbuf(stream_.rdbuf())) {}
    ~ScopedStdoutCapture() {
        std::cout.rdbuf(previous_);
    }

    std::string str() const {
        return stream_.str();
    }

  private:
    std::ostringstream stream_;
    std::streambuf* previous_;
};

RuntimeHooks HooksFrom(FakeKvsState* kvs_state, FakeCapturerState* capturer_state) {
    RuntimeHooks hooks;
    hooks.resolve_aws_credentials = [] {
        AwsCredentials credentials;
        credentials.access_key_id = "test-access";
        credentials.secret_access_key = "test-secret";
        credentials.session_token = std::nullopt;
        return credentials;
    };
    hooks.create_kvs_session = [kvs_state](
                                   const RuntimeConfig&,
                                   const AwsCredentials&
                               ) { return std::make_unique<FakeKvsSession>(kvs_state); };
    hooks.create_video_capturer = [capturer_state] { return std::make_unique<FakeVideoCapturer>(capturer_state); };
    return hooks;
}

RuntimeConfig TestRuntimeConfig() {
    RuntimeConfig config;
    config.region = "eu-central-1";
    config.channel_name = "txing-board-video";
    config.client_id = "board-master";
    config.camera.width = 1920;
    config.camera.height = 1080;
    config.camera.framerate = 30;
    config.camera.bitrate = 8'000'000;
    config.camera.intra = 30;
    return config;
}

void TestCliParsing() {
    const auto parsed = ParseCli(
        {
            "txing-board-kvs-master",
            "--region",
            "eu-central-1",
            "--channel-name",
            "txing-board-video",
            "--client-id",
            "board-master",
            "--width",
            "1280",
            "--height",
            "720",
            "--framerate",
            "15",
            "--bitrate",
            "1200000",
            "--intra",
            "15",
        },
        EnvFrom({})
    );

    Expect(parsed.config.region == "eu-central-1", "CLI should parse region");
    Expect(parsed.config.channel_name == "txing-board-video", "CLI should parse channel name");
    Expect(parsed.config.client_id == "board-master", "CLI should parse client id");
    Expect(parsed.config.camera.width == 1280, "CLI should parse width");
    Expect(parsed.config.camera.height == 720, "CLI should parse height");
    Expect(parsed.config.camera.framerate == 15, "CLI should parse framerate");
    Expect(parsed.config.camera.bitrate == 1'200'000, "CLI should parse bitrate");
    Expect(parsed.config.camera.intra == 15, "CLI should parse intra");
}

void TestUsageText() {
    const auto usage = UsageText();
    Expect(
        usage.find("--rpicam-vid-path") == std::string::npos,
        "usage text should not mention the removed rpicam-vid path"
    );
    Expect(usage.find("--camera <index>") != std::string::npos, "usage text should still document camera selection");
}

void TestCredentialResolution() {
    const auto env_credentials = ResolveAwsCredentials(
        EnvFrom(
            {
                {"AWS_ACCESS_KEY_ID", "env-access"},
                {"AWS_SECRET_ACCESS_KEY", "env-secret"},
                {"AWS_SESSION_TOKEN", "env-token"},
            }
        ),
        [](const std::filesystem::path&) { return std::string(); }
    );

    Expect(env_credentials.access_key_id == "env-access", "env access key should win");
    Expect(env_credentials.secret_access_key == "env-secret", "env secret key should win");
    Expect(env_credentials.session_token == "env-token", "env session token should be preserved");

    const auto temp_dir = std::filesystem::temp_directory_path() / "txing-board-kvs-master-tests";
    std::filesystem::create_directories(temp_dir);
    const auto credentials_path = temp_dir / "credentials";
    {
        std::ofstream stream(credentials_path);
        stream << "[board]\n"
               << "aws_access_key_id = file-access\n"
               << "aws_secret_access_key = file-secret\n";
    }

    const auto file_credentials = ResolveAwsCredentials(
        EnvFrom(
            {
                {"AWS_SHARED_CREDENTIALS_FILE", credentials_path.string()},
                {"AWS_PROFILE", "board"},
            }
        ),
        [](const std::filesystem::path& path) {
            std::ifstream stream(path);
            return std::string(
                std::istreambuf_iterator<char>(stream),
                std::istreambuf_iterator<char>()
            );
        }
    );

    Expect(file_credentials.access_key_id == "file-access", "file access key should resolve");
    Expect(file_credentials.secret_access_key == "file-secret", "file secret key should resolve");
    Expect(!file_credentials.session_token.has_value(), "file session token should be optional");
}

void TestRuntimeReadyAndTimestamps() {
    FakeKvsState kvs_state;
    FakeCapturerState capturer_state;
    capturer_state.frames = {
        EncodedVideoFrame {{0x00, 0x00, 0x01}, 1'000'000, false},
        EncodedVideoFrame {{0x00, 0x00, 0x02}, 1'033'333, true},
        EncodedVideoFrame {{0x00, 0x00, 0x03}, 1'066'666, false},
    };

    ScopedStdoutCapture stdout_capture;
    Run(TestRuntimeConfig(), HooksFrom(&kvs_state, &capturer_state));
    const auto output = stdout_capture.str();

    Expect(kvs_state.started, "runtime should start the KVS session");
    Expect(kvs_state.stopped, "runtime should stop the KVS session");
    Expect(capturer_state.configured, "runtime should configure the video capturer");
    Expect(capturer_state.started, "runtime should start the video capturer");
    Expect(capturer_state.stopped, "runtime should stop the video capturer");
    Expect(kvs_state.pushes.size() == 3, "runtime should forward each encoded frame to KVS");
    Expect(kvs_state.pushes[0].pts_100ns == 0, "runtime should start presentation timestamps at zero");
    Expect(
        kvs_state.pushes[1].pts_100ns == 333'330,
        "runtime should advance presentation timestamps from successive frame deltas"
    );
    Expect(
        kvs_state.pushes[1].duration_100ns == 333'330,
        "runtime should derive frame duration from successive encoder timestamps"
    );
    Expect(kvs_state.pushes[1].is_keyframe, "runtime should preserve keyframe flags");
    Expect(
        output.find("TXING_KVS_READY") != std::string::npos,
        "runtime should emit readiness only after receiving a keyframe"
    );
}

void TestRuntimeAdvancesWhenEncoderTimestampsStayZero() {
    FakeKvsState kvs_state;
    FakeCapturerState capturer_state;
    capturer_state.frames = {
        EncodedVideoFrame {{0x00, 0x00, 0x01}, 0, false},
        EncodedVideoFrame {{0x00, 0x00, 0x02}, 0, true},
        EncodedVideoFrame {{0x00, 0x00, 0x03}, 0, false},
    };

    Run(TestRuntimeConfig(), HooksFrom(&kvs_state, &capturer_state));

    Expect(kvs_state.pushes.size() == 3, "runtime should forward frames even with zero encoder timestamps");
    Expect(kvs_state.pushes[0].pts_100ns == 0, "runtime should still start at zero");
    Expect(
        kvs_state.pushes[1].pts_100ns == kvs_state.pushes[0].duration_100ns,
        "runtime should advance with the default frame duration after the first zero timestamp"
    );
    Expect(
        kvs_state.pushes[2].pts_100ns == kvs_state.pushes[0].duration_100ns + kvs_state.pushes[1].duration_100ns,
        "runtime should keep advancing when encoder timestamps remain zero"
    );
}

void TestRuntimePropagatesCapturerErrors() {
    FakeKvsState kvs_state;
    FakeCapturerState capturer_state;
    capturer_state.throw_on_start = true;
    capturer_state.error_message = "camera startup failed";

    bool threw = false;
    try {
        Run(TestRuntimeConfig(), HooksFrom(&kvs_state, &capturer_state));
    } catch (const std::exception& error) {
        threw = true;
        Expect(std::string(error.what()) == "camera startup failed", "runtime should bubble up capturer errors");
    }

    Expect(threw, "runtime should throw when the capturer fails");
    Expect(kvs_state.started, "runtime should already have started the KVS session before capturer startup");
    Expect(kvs_state.stopped, "runtime should stop KVS after a capturer failure");
}

void TestMarkerFormatting() {
    const auto line = FormatMarkerLine(
        "TXING_KVS_ERROR",
        {{"detail", "bad\tline\nhere"}}
    );
    Expect(line == "TXING_KVS_ERROR detail=bad line here", "marker values should be sanitized");
}

}  // namespace

int main() {
    TestCliParsing();
    TestUsageText();
    TestCredentialResolution();
    TestRuntimeReadyAndTimestamps();
    TestRuntimeAdvancesWhenEncoderTimestampsStayZero();
    TestRuntimePropagatesCapturerErrors();
    TestMarkerFormatting();

    if (g_failures != 0) {
        std::cerr << g_failures << " test(s) failed\n";
        return 1;
    }

    std::cout << "all tests passed\n";
    return 0;
}
