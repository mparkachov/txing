#include "camera.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>

namespace txing::virtual_quad {
namespace {

using namespace std::chrono_literals;

// Matches the fixed SITL home in the supervisor.
constexpr std::int32_t home_lat = -353632610;
constexpr std::int32_t home_lon = 1491652300;
constexpr float home_alt = 584.0f;
constexpr double metres_per_lat_e7 = 0.011131884502145034;
constexpr double radians_per_lat_e7 = 1.74532925199433e-9;
constexpr auto pose_delay = 35ms;
constexpr auto maximum_pose_age = 150ms;

template<typename T>
T Decode32(const std::uint8_t* bytes) {
    std::uint32_t bits = 0;
    for (unsigned i = 0; i < 4; ++i) bits |= std::uint32_t(bytes[i]) << (8 * i);
    T value;
    static_assert(sizeof(value) == sizeof(bits));
    std::memcpy(&value, &bits, sizeof(bits));
    return value;
}

std::uint16_t AccumulateCrc(std::uint16_t crc, std::uint8_t byte) {
    std::uint8_t tmp = byte ^ static_cast<std::uint8_t>(crc);
    tmp ^= static_cast<std::uint8_t>(tmp << 4);
    return (crc >> 8) ^ (std::uint16_t(tmp) << 8) ^ (std::uint16_t(tmp) << 3) ^ (tmp >> 4);
}

float Dot(Attitude a, Attitude b) {
    return a.w*b.w + a.x*b.x + a.y*b.y + a.z*b.z;
}

Attitude Normalize(Attitude q, float norm_squared) {
    const float scale = 1.0f / std::sqrt(norm_squared);
    return {q.w*scale, q.x*scale, q.y*scale, q.z*scale};
}

Ned operator+(Ned a, Ned b) {
    return {a.north + b.north, a.east + b.east, a.down + b.down};
}

Ned operator-(Ned a, Ned b) {
    return {a.north - b.north, a.east - b.east, a.down - b.down};
}

Ned operator*(Ned v, float scale) {
    return {v.north*scale, v.east*scale, v.down*scale};
}

Ned Cross(Ned a, Ned b) {
    return {a.east*b.down - a.down*b.east, a.down*b.north - a.north*b.down, a.north*b.east - a.east*b.north};
}

Ned Rotate(Attitude q, Ned v) {
    const Ned axis{q.x, q.y, q.z};
    const Ned offset = Cross(axis, v) * 2.0f;
    return v + offset*q.w + Cross(axis, offset);
}

Attitude Interpolate(Attitude a, Attitude b, float fraction) {
    // Quaternions q and -q describe the same attitude. Choose the short arc.
    const float sign = Dot(a, b) < 0 ? -1.0f : 1.0f;
    const float from = 1.0f - fraction;
    const float to = fraction * sign;
    const Attitude q{from*a.w + to*b.w, from*a.x + to*b.x, from*a.y + to*b.y, from*a.z + to*b.z};
    return Normalize(q, Dot(q, q));
}

struct Color {
    std::uint8_t y, u, v;
};

constexpr Color RGB(int r, int g, int b) {
    return {
        static_cast<std::uint8_t>((66*r + 129*g + 25*b + 128) / 256 + 16),
        static_cast<std::uint8_t>((-38*r - 74*g + 112*b + 32896) / 256),
        static_cast<std::uint8_t>((112*r - 94*g - 18*b + 32896) / 256),
    };
}

constexpr float wall_distance = 14.0f;
constexpr float wall_height = 8.0f;
constexpr Color sky = RGB(128, 164, 190);
constexpr Color white = RGB(229, 235, 235);
constexpr Color yellow = RGB(249, 192, 62);
constexpr Color dark = RGB(35, 45, 55);
constexpr Color floor_even = RGB(91, 108, 115);
constexpr Color floor_odd = RGB(108, 126, 131);
constexpr Color floor_joint = RGB(62, 76, 83);
constexpr std::array<Color, 4> directions{
    RGB(219, 108, 42), RGB(50, 141, 220), RGB(172, 71, 144), RGB(65, 164, 110),
};
constexpr std::array<Color, 4> wall_panels{
    RGB(119, 82, 65), RGB(67, 103, 143), RGB(116, 79, 115), RGB(70, 116, 96),
};

struct Box {
    Ned min, max;
    Color color;
};

constexpr std::array<Box, 6> landmarks{{
    {{6.4f, -0.65f, -3.7f}, {7.6f, 0.65f, 0}, directions[0]},
    {{-0.8f, 6.6f, -4.5f}, {0.8f, 7.7f, 0}, directions[1]},
    {{-7.8f, -1.0f, -2.4f}, {-6.4f, 1.0f, 0}, directions[2]},
    {{-1.5f, -7.8f, -3.1f}, {1.5f, -6.5f, 0}, directions[3]},
    {{5.0f, 5.4f, -1.25f}, {7.1f, 6.2f, 0}, RGB(235, 194, 115)},
    {{-7.4f, -6.8f, -1.7f}, {-5.6f, -5.2f, 0}, RGB(118, 204, 197)},
}};

Color FloorAt(Ned point) {
    const float n = std::abs(point.north);
    const float e = std::abs(point.east);
    const float pad = std::max(n, e);
    if (pad < 1.65f) {
        if (pad > 1.54f) return white;
        if (pad > 1.43f) return dark;
        const float radius_squared = n*n + e*e;
        if (radius_squared > 1.25f && radius_squared < 1.54f) return yellow;
        if (n < 0.61f && e < 0.56f && (e > 0.35f || n < 0.1f)) return white;
        return dark;
    }
    if (n > 2.0f && e < 0.07f) return directions[point.north > 0 ? 0 : 2];
    if (e > 2.0f && n < 0.07f) return directions[point.east > 0 ? 1 : 3];
    const auto north_tile = std::floor(point.north);
    const auto east_tile = std::floor(point.east);
    if (point.north - north_tile < 0.035f || point.east - east_tile < 0.035f) return floor_joint;
    return (static_cast<int>(north_tile + east_tile) & 1) ? floor_odd : floor_even;
}

struct Ray {
    Ned origin, direction, inverse;
};

float Inverse(float direction) {
    return 1.0f / (std::abs(direction) < 1e-7f ? std::copysign(1e-7f, direction) : direction);
}

bool HitBox(const Ray& ray, const Box& box, float& closest, Color& color) {
    const Ned first{
        (box.min.north - ray.origin.north)*ray.inverse.north,
        (box.min.east - ray.origin.east)*ray.inverse.east,
        (box.min.down - ray.origin.down)*ray.inverse.down,
    };
    const Ned last{
        (box.max.north - ray.origin.north)*ray.inverse.north,
        (box.max.east - ray.origin.east)*ray.inverse.east,
        (box.max.down - ray.origin.down)*ray.inverse.down,
    };
    const float n = std::min(first.north, last.north);
    const float e = std::min(first.east, last.east);
    const float d = std::min(first.down, last.down);
    const float entry = std::max({n, e, d});
    const float exit = std::min({std::max(first.north, last.north), std::max(first.east, last.east),
        std::max(first.down, last.down)});
    if (exit < std::max(entry, 0.02f) || entry >= closest) return false;
    const float distance = entry >= 0.02f ? entry : exit;
    if (distance >= closest) return false;
    closest = distance;
    color = box.color;
    if (entry == e) color.y = static_cast<std::uint8_t>(color.y * 0.82f);
    if (entry == n) color.y = static_cast<std::uint8_t>(color.y * 0.94f);
    const float height = -(ray.origin.down + distance * ray.direction.down);
    if (height > 0.55f && height < 0.69f) color = white;
    return true;
}

Color Trace(Ned origin, Ned direction) {
    const Ray ray{origin, direction, {Inverse(direction.north), Inverse(direction.east), Inverse(direction.down)}};
    float closest = 70.0f;
    Color color = sky;
    const float floor_distance = -origin.down * ray.inverse.down;
    if (direction.down > 0 && floor_distance > 0.02f && floor_distance < closest) {
        const auto point = origin + direction * floor_distance;
        if (std::abs(point.north) <= wall_distance && std::abs(point.east) <= wall_distance) {
            closest = floor_distance;
            color = FloorAt(point);
        }
    }

    const auto wall = [&](float distance, float along, unsigned face) {
        if (distance <= 0.02f || distance >= closest || std::abs(along) > wall_distance) return;
        const float height = -(origin.down + direction.down*distance);
        if (height < 0 || height > wall_height) return;
        closest = distance;
        color = wall_panels[face];
        const float seam = along - std::floor(along);
        if (height < 0.35f || height > wall_height - 0.17f || seam < 0.035f) color = dark;
        if (height > 1.25f && height < 1.85f) color = directions[face];
        if (height > 4.0f && height < 5.9f && std::abs(along) < 2.1f) {
            color = (seam < 0.13f) ? dark : RGB(185, 205, 212);
        }
    };
    const bool north = direction.north > 0;
    const float n_wall = ((north ? wall_distance : -wall_distance) - origin.north)*ray.inverse.north;
    wall(n_wall, origin.east + direction.east*n_wall, north ? 0 : 2);
    const bool east = direction.east > 0;
    const float e_wall = ((east ? wall_distance : -wall_distance) - origin.east)*ray.inverse.east;
    wall(e_wall, origin.north + direction.north*e_wall, east ? 1 : 3);
    for (const auto& landmark : landmarks) HitBox(ray, landmark, closest, color);
    return color;
}

}  // namespace

std::optional<PoseSample> DecodeSimState(const std::uint8_t* frame, std::size_t size, Clock::time_point received) {
    constexpr std::size_t header_size = 10;
    constexpr std::size_t payload_size = 92;
    constexpr std::uint8_t message_id = 108;
    constexpr std::uint8_t crc_extra = 32;
    if (size < header_size + 2 || frame[0] != 0xfd || (frame[2] & ~1) != 0 ||
        frame[5] != 1 || frame[6] != 1 || frame[7] != message_id || frame[8] != 0 || frame[9] != 0) {
        return std::nullopt;
    }
    const std::size_t length = frame[1];
    const std::size_t checksum_offset = header_size + length;
    if (length <= 88 || length > payload_size || size != checksum_offset + 2 + ((frame[2] & 1) ? 13 : 0)) {
        return std::nullopt;
    }
    std::uint16_t crc = 0xffff;
    for (std::size_t i = 1; i < checksum_offset; ++i) crc = AccumulateCrc(crc, frame[i]);
    crc = AccumulateCrc(crc, crc_extra);
    if (crc != (frame[checksum_offset] | (std::uint16_t(frame[checksum_offset + 1]) << 8))) return std::nullopt;

    std::array<std::uint8_t, payload_size> payload{};
    std::copy_n(frame + header_size, length, payload.data());
    const Attitude q{Decode32<float>(&payload[0]), Decode32<float>(&payload[4]),
        Decode32<float>(&payload[8]), Decode32<float>(&payload[12])};
    const float norm = Dot(q, q);
    const auto latitude = Decode32<std::int32_t>(&payload[84]);
    const auto longitude = Decode32<std::int32_t>(&payload[88]);
    const auto altitude = Decode32<float>(&payload[60]);
    if (!std::isfinite(norm) || norm < 0.81f || norm > 1.21f || !std::isfinite(altitude) ||
        latitude == 0 || latitude < -900000000 || latitude > 900000000 ||
        longitude == 0 || longitude < -1800000000 || longitude > 1800000000) {
        return std::nullopt;
    }
    static const double metres_per_lon_e7 = metres_per_lat_e7 * std::cos(home_lat * radians_per_lat_e7);
    const Ned position{
        static_cast<float>((double(latitude) - home_lat) * metres_per_lat_e7),
        static_cast<float>((double(longitude) - home_lon) * metres_per_lon_e7),
        home_alt - altitude,
    };
    return PoseSample{Pose{position, Normalize(q, norm)}, received};
}

void PoseHistory::Push(PoseSample sample) {
    if (newer_ && sample.received <= newer_->received) return;
    older_ = newer_ && sample.received - newer_->received < maximum_pose_age ? newer_ : std::nullopt;
    newer_ = sample;
}

std::optional<PoseSample> PoseHistory::At(Clock::time_point now) const {
    if (!older_ || !newer_ || now < newer_->received || now - newer_->received >= maximum_pose_age) return std::nullopt;
    const auto target = std::clamp(now - pose_delay, older_->received, newer_->received);
    const auto span = std::chrono::duration<float>(newer_->received - older_->received).count();
    const auto offset = std::chrono::duration<float>(target - older_->received).count();
    const float fraction = offset / span;
    const auto from = older_->pose;
    const auto to = newer_->pose;
    return PoseSample{
        {from.position + (to.position - from.position)*fraction, Interpolate(from.attitude, to.attitude, fraction)},
        target,
    };
}

void RenderCamera(const Pose& pose, std::uint8_t* frame) {
    // Body axes are forward, right, down. The mounting rotates the optical
    // axis down by 15 degrees before the truth quaternion maps it into NED.
    constexpr float mount_cos = 0.9659258f;
    constexpr float mount_sin = 0.2588190f;
    constexpr float half_horizontal_fov = 0.70f; // Tangent of the half-angle.
    constexpr float step = 2.0f * half_horizontal_fov / camera_width;
    const auto q = pose.attitude;
    const Ned origin = pose.position + Rotate(q, {0.14f, 0, -0.11f});
    const Ned forward = Rotate(q, {mount_cos, 0, mount_sin});
    const Ned right = Rotate(q, {0, 1, 0});
    const Ned down = Rotate(q, {-mount_sin, 0, mount_cos});
    auto* u = frame + camera_width*camera_height;
    auto* v = u + camera_width*camera_height/4;

    for (int y = 0; y < camera_height; y += 2) {
        const auto row = forward + down * ((y + 0.5f - camera_height/2) * step);
        for (int x = 0; x < camera_width; x += 2) {
            const auto ray = row + right * ((x + 0.5f - camera_width/2) * step);
            const auto a = Trace(origin, ray);
            const auto b = Trace(origin, ray + right*step);
            const auto c = Trace(origin, ray + down*step);
            const auto d = Trace(origin, ray + right*step + down*step);
            const auto index = y*camera_width + x;
            frame[index] = a.y;
            frame[index + 1] = b.y;
            frame[index + camera_width] = c.y;
            frame[index + camera_width + 1] = d.y;
            const auto uv = y*camera_width/4 + x/2;
            u[uv] = static_cast<std::uint8_t>((a.u + b.u + c.u + d.u + 2) / 4);
            v[uv] = static_cast<std::uint8_t>((a.v + b.v + c.v + d.v + 2) / 4);
        }
    }
}

}  // namespace txing::virtual_quad
