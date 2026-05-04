#pragma once

#include <cstdint>
#include <cstddef>

namespace txing::weather
{
constexpr std::uint8_t kProtocolVersion = 1;
constexpr std::uint8_t kRedconActive = 3;
constexpr std::uint8_t kRedconIdle = 4;

struct Command
{
	std::uint8_t target_redcon = kRedconIdle;
};

struct StateReport
{
	std::uint8_t redcon = kRedconIdle;
	bool active = false;
	bool bme280_valid = false;
	std::uint16_t battery_mv = 0;
};

struct MeasurementReport
{
	std::int32_t temperature_centi_c = 0;
	std::uint32_t pressure_pa = 0;
	std::uint16_t humidity_centi_percent = 0;
	std::uint16_t battery_mv = 0;
};

bool DecodeCommand(const std::uint8_t *data, std::size_t size, Command &command);
std::size_t EncodeStateReport(const StateReport &state, std::uint8_t *out, std::size_t out_size);
std::size_t EncodeMeasurementReport(const MeasurementReport &measurement, std::uint8_t *out, std::size_t out_size);

bool PollCommand(Command &command);
} // namespace txing::weather
