#include "camera.hpp"

#include <array>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string_view>

namespace {

using namespace txing::virtual_quad;
using namespace std::chrono_literals;

void Check(bool valid, const char* message) {
    if (valid) return;
    std::fprintf(stderr, "camera test: %s\n", message);
    std::exit(1);
}

bool Close(float actual, float expected) {
    return std::abs(actual - expected) < 0.001f;
}

void CheckPose() {
    // SIM_STATE with 90-degree yaw, +100 degE7 on each axis and 2 m above home.
    constexpr std::string_view hex =
        "fd5c00000101016c0000f304353f0000000000000000f304353f000000000000"
        "0000000000000000000000000000000000000000000000000000000000000000"
        "00000000000000801244000000000000000000000000000000000000000002ff"
        "ebea30cfe858810c";
    std::array<std::uint8_t, hex.size()/2> frame{};
    auto digit = [](char c) { return c <= '9' ? c - '0' : c - 'a' + 10; };
    for (std::size_t i = 0; i < frame.size(); ++i) {
        frame[i] = static_cast<std::uint8_t>(digit(hex[2*i])*16 + digit(hex[2*i + 1]));
    }
    const auto start = Clock::time_point{} + 1s;
    const auto decoded = DecodeSimState(frame.data(), frame.size(), start);
    Check(decoded.has_value(), "valid SIM_STATE was rejected");
    const auto pose = decoded->pose;
    Check(Close(pose.position.north, 1.11319f) && Close(pose.position.east, 0.9077f) &&
        Close(pose.position.down, -2.0f), "SIM_STATE did not convert to local NED");
    Check(Close(pose.attitude.w, 0.7071f) && Close(pose.attitude.z, 0.7071f),
        "SIM_STATE did not preserve the truth quaternion");
    Check(!DecodeSimState(frame.data(), frame.size() - 1, start), "truncated frame accepted");
    frame[10] ^= 1;
    Check(!DecodeSimState(frame.data(), frame.size(), start), "damaged CRC accepted");

    PoseHistory history;
    history.Push({{{0, 0, 0}, {1, 0, 0, 0}}, start});
    Check(!history.At(start + 30ms), "a lone pose was marked usable");
    history.Push({{{2, 4, -2}, {-0.7071068f, 0, 0, -0.7071068f}}, start + 34ms});
    const auto midpoint = history.At(start + 52ms);
    Check(midpoint && midpoint->received == start + 17ms && Close(midpoint->pose.position.north, 1) &&
        Close(midpoint->pose.position.east, 2) && Close(midpoint->pose.position.down, -1) &&
        Close(midpoint->pose.attitude.w, 0.92388f) && Close(midpoint->pose.attitude.z, 0.38268f),
        "camera did not interpolate the short quaternion arc at the recorded time");
    Check(!history.At(start + 184ms), "expired pose was used");
    history.Push(*decoded);
    Check(!history.At(start + 184ms), "an older pose restored freshness");
    history.Push({pose, start + 250ms});
    Check(!history.At(start + 255ms), "camera interpolated across a telemetry outage");
}

std::array<int, 2> MarkerAt(const Pose& pose) {
    std::array<std::uint8_t, camera_frame_bytes> frame{};
    RenderCamera(pose, frame.data());
    constexpr std::size_t offset = (camera_height/2 - 60)*camera_width/4 + camera_width/4;
    constexpr std::size_t y_size = camera_width*camera_height;
    return {frame[y_size + offset], frame[y_size + y_size/4 + offset]};
}

void CheckScene() {
    constexpr float diagonal = 0.70710678f;
    const Ned hover{0, 0, -2};
    const auto north = MarkerAt({hover, {1, 0, 0, 0}});
    const auto east = MarkerAt({hover, {diagonal, 0, 0, diagonal}});
    const auto south = MarkerAt({hover, {0, 0, 0, 1}});
    const auto west = MarkerAt({hover, {diagonal, 0, 0, -diagonal}});
    Check(north[0] < 100 && north[1] > 170, "north should face the orange tower");
    Check(east[0] > 160 && east[1] < 100, "east should face the blue tower");
    Check(south[0] > 130 && south[1] > 150, "south should face the magenta tower");
    Check(west[0] < 130 && west[1] < 100, "west should face the green tower");
    Check(MarkerAt({{0, 2, -2}, {1, 0, 0, 0}}) != north, "translation did not move the north tower off-axis");
    Check(MarkerAt({{0, 0, -5.5f}, {1, 0, 0, 0}}) != north, "climb did not reveal the area above the tower");
    Check(MarkerAt({hover, {0.9659258f, 0, 0.2588190f, 0}}) != north, "pitch did not tilt the camera above the tower");
    Check(MarkerAt({hover, {diagonal, diagonal, 0, 0}}) != north, "roll did not rotate the tower out of the reference ray");
}

}  // namespace

int main() {
    CheckPose();
    CheckScene();
    std::puts("virtual quad camera checks passed");
}
