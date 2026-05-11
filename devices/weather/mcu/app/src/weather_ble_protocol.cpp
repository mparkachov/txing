#include "weather_ble_protocol.h"

namespace txing::weather
{
namespace
{
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
	if (out == nullptr || out_size < 2) {
		return 0;
	}
	out[0] = kProtocolVersion;
	out[1] = state.redcon;
	return 2;
}

std::size_t EncodePowerMeasurementReport(const PowerMeasurementReport &measurement, std::uint8_t *out, std::size_t out_size)
{
	if (out == nullptr || out_size < 3) {
		return 0;
	}
	out[0] = kProtocolVersion;
	PutLe16(out + 1, measurement.battery_mv);
	return 3;
}

std::size_t EncodeWeatherMeasurementReport(const WeatherMeasurementReport &measurement, std::uint8_t *out, std::size_t out_size)
{
	if (out == nullptr || out_size < 11) {
		return 0;
	}
	out[0] = kProtocolVersion;
	PutLe32(out + 1, static_cast<std::uint32_t>(measurement.temperature_centi_c));
	PutLe32(out + 5, measurement.pressure_pa);
	PutLe16(out + 9, measurement.humidity_centi_percent);
	return 11;
}

bool PollCommand(Command &command)
{
	(void)command;
	return false;
}
} // namespace txing::weather
