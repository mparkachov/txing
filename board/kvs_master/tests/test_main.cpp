#include "txing_board_kvs_master/aws_env.hpp"
#include "txing_board_kvs_master/config.hpp"
#include "txing_board_kvs_master/h264.hpp"
#include "txing_board_kvs_master/markers.hpp"
#include "txing_board_kvs_master/rpicam.hpp"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

using txing::board::kvs_master::AccessUnit;
using txing::board::kvs_master::AnnexBAccessUnitParser;
using txing::board::kvs_master::AwsCredentials;
using txing::board::kvs_master::BuildRpicamArguments;
using txing::board::kvs_master::CameraConfig;
using txing::board::kvs_master::FormatMarkerLine;
using txing::board::kvs_master::ParseCli;
using txing::board::kvs_master::ResolveAwsCredentials;

int g_failures = 0;

void Expect(bool condition, const std::string& message) {
    if (!condition) {
        ++g_failures;
        std::cerr << "FAIL: " << message << '\n';
    }
}

std::vector<std::uint8_t> Nal(std::initializer_list<std::uint8_t> payload) {
    std::vector<std::uint8_t> bytes = {0x00, 0x00, 0x00, 0x01};
    bytes.insert(bytes.end(), payload.begin(), payload.end());
    return bytes;
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

void TestRpicamArguments() {
    CameraConfig config;
    config.path = "/usr/bin/rpicam-vid";
    config.camera = 1;
    config.width = 1920;
    config.height = 1080;
    config.framerate = 30;
    config.bitrate = 8'000'000;
    config.intra = 30;
    const auto arguments = BuildRpicamArguments(config);

    Expect(arguments.size() == 18, "rpicam arguments should have the expected count");
    Expect(arguments[0] == "-n", "rpicam should disable preview");
    Expect(arguments[3] == "--inline", "rpicam should request inline SPS/PPS");
    Expect(arguments[5] == "1", "rpicam should include camera index");
    Expect(arguments[17] == "-", "rpicam should stream to stdout");
}

void TestAnnexBParser() {
    AnnexBAccessUnitParser parser;
    std::vector<std::uint8_t> stream;
    const auto sps = Nal({0x67, 0xaa});
    const auto pps = Nal({0x68, 0xbb});
    const auto idr = Nal({0x65, 0x80});
    const auto p = Nal({0x41, 0x80});
    stream.insert(stream.end(), sps.begin(), sps.end());
    stream.insert(stream.end(), pps.begin(), pps.end());
    stream.insert(stream.end(), idr.begin(), idr.end());
    stream.insert(stream.end(), p.begin(), p.end());

    std::vector<AccessUnit> access_units;
    const auto chunk_one = parser.Push(stream.data(), 11);
    access_units.insert(access_units.end(), chunk_one.begin(), chunk_one.end());
    const auto chunk_two = parser.Push(stream.data() + 11, stream.size() - 11);
    access_units.insert(access_units.end(), chunk_two.begin(), chunk_two.end());
    const auto final_units = parser.Finish();
    access_units.insert(access_units.end(), final_units.begin(), final_units.end());

    Expect(access_units.size() == 2, "parser should emit two access units");
    Expect(access_units[0].is_keyframe, "first access unit should be a keyframe");
    Expect(!access_units[1].is_keyframe, "second access unit should not be a keyframe");
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
    TestCredentialResolution();
    TestRpicamArguments();
    TestAnnexBParser();
    TestMarkerFormatting();

    if (g_failures != 0) {
        std::cerr << g_failures << " test(s) failed\n";
        return 1;
    }

    std::cout << "all tests passed\n";
    return 0;
}
