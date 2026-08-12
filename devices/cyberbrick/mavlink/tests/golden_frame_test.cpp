#include <array>
#include <cstdint>
#include <cstdio>

#include "mavlink/v2.0/common/mavlink.h"

int main() {
    mavlink_message_t message{};
    mavlink_msg_heartbeat_pack(
        255,
        190,
        &message,
        MAV_TYPE_GROUND_ROVER,
        MAV_AUTOPILOT_ARDUPILOTMEGA,
        0,
        0,
        MAV_STATE_ACTIVE
    );

    std::array<std::uint8_t, MAVLINK_MAX_PACKET_LEN> encoded{};
    const auto encoded_length = mavlink_msg_to_send_buffer(encoded.data(), &message);
    constexpr std::array<std::uint8_t, 21> expected{
        0xfd, 0x09, 0x00, 0x00, 0x00, 0xff, 0xbe, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x0a, 0x03, 0x00, 0x04, 0x03, 0x25, 0x3e,
    };
    if (encoded_length != expected.size()) {
        std::fprintf(stderr, "encoded heartbeat length %u, expected %zu\n", encoded_length, expected.size());
        return 1;
    }
    for (std::size_t index = 0; index < expected.size(); ++index) {
        if (encoded[index] != expected[index]) {
            std::fprintf(stderr, "encoded heartbeat byte %zu was 0x%02x, expected 0x%02x\n", index, encoded[index], expected[index]);
            return 1;
        }
    }
    return 0;
}
