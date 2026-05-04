#include "weather_ble_protocol.h"

namespace txing::weather
{
namespace
{
constexpr std::uint8_t kStateFlagActive = 0x01;
constexpr std::uint8_t kStateFlagBme280Valid = 0x02;

void PutLe16(std::uint8_t *out, std::uint16_t value)
{
	out[0] = static_cast<std::uint8_t>(value & 0xffu);
	out[1] = static_cast<std::uint8_t>((value >> 8u) & 0xffu);
}

void PutLe32(std::uint8_t *out, std::uint32_t value)
{
	out[0] = static_cast<std::uint8_t>(value & 0xffu);
	out[1] = static_cast<std::uint8_t>((value >> 8u) & 0xffu);
	out[2] = static_cast<std::uint8_t>((value >> 16u) & 0xffu);
	out[3] = static_cast<std::uint8_t>((value >> 24u) & 0xffu);
}
} // namespace

bool DecodeCommand(const std::uint8_t *data, std::size_t size, Command &command)
{
	if (data == nullptr || size < 2 || data[0] != kProtocolVersion) {
		return false;
	}
	std::uint8_t redcon = data[1];
	if (redcon == 1 || redcon == 2) {
		redcon = kRedconActive;
	}
	if (redcon != kRedconActive && redcon != kRedconIdle) {
		return false;
	}
	command.target_redcon = redcon;
	return true;
}

std::size_t EncodeStateReport(const StateReport &state, std::uint8_t *out, std::size_t out_size)
{
	if (out == nullptr || out_size < 5) {
		return 0;
	}
	out[0] = kProtocolVersion;
	out[1] = state.redcon;
	out[2] = (state.active ? kStateFlagActive : 0) | (state.bme280_valid ? kStateFlagBme280Valid : 0);
	PutLe16(out + 3, state.battery_mv);
	return 5;
}

std::size_t EncodeMeasurementReport(const MeasurementReport &measurement, std::uint8_t *out, std::size_t out_size)
{
	if (out == nullptr || out_size < 13) {
		return 0;
	}
	out[0] = kProtocolVersion;
	PutLe32(out + 1, static_cast<std::uint32_t>(measurement.temperature_centi_c));
	PutLe32(out + 5, measurement.pressure_pa);
	PutLe16(out + 9, measurement.humidity_centi_percent);
	PutLe16(out + 11, measurement.battery_mv);
	return 13;
}

bool PollCommand(Command &command)
{
	(void)command;
	return false;
}
} // namespace txing::weather
