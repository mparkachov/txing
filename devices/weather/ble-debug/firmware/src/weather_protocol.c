#include "weather_protocol.h"

static void put_u16_le(uint8_t *out, uint16_t value)
{
	out[0] = (uint8_t)(value & 0xffu);
	out[1] = (uint8_t)(value >> 8);
}

static void put_u32_le(uint8_t *out, uint32_t value)
{
	out[0] = (uint8_t)(value & 0xffu);
	out[1] = (uint8_t)((value >> 8) & 0xffu);
	out[2] = (uint8_t)((value >> 16) & 0xffu);
	out[3] = (uint8_t)((value >> 24) & 0xffu);
}

bool weather_decode_command(const uint8_t *data, size_t len, uint8_t *target_redcon)
{
	uint8_t redcon;

	if (data == NULL || target_redcon == NULL || len < WEATHER_COMMAND_PAYLOAD_SIZE) {
		return false;
	}
	if (data[0] != WEATHER_PROTOCOL_VERSION) {
		return false;
	}

	redcon = data[1];
	if (redcon == 1u || redcon == 2u) {
		redcon = WEATHER_REDCON_ACTIVE;
	}
	if (redcon != WEATHER_REDCON_ACTIVE && redcon != WEATHER_REDCON_IDLE) {
		return false;
	}

	*target_redcon = redcon;
	return true;
}

void weather_encode_state(const struct weather_state *state,
			  uint8_t out[WEATHER_STATE_PAYLOAD_SIZE])
{
	uint8_t flags = 0u;

	if (state->redcon < WEATHER_REDCON_IDLE) {
		flags |= WEATHER_STATE_FLAG_ACTIVE;
	}
	if (state->bme280_valid) {
		flags |= WEATHER_STATE_FLAG_BME280_VALID;
	}

	out[0] = WEATHER_PROTOCOL_VERSION;
	out[1] = state->redcon;
	out[2] = flags;
	put_u16_le(&out[3], state->battery_mv);
}

void weather_encode_measurement(const struct weather_measurement *measurement,
				uint8_t out[WEATHER_MEASUREMENT_PAYLOAD_SIZE])
{
	out[0] = WEATHER_PROTOCOL_VERSION;
	put_u32_le(&out[1], (uint32_t)measurement->temperature_centi_c);
	put_u32_le(&out[5], measurement->pressure_pa);
	put_u16_le(&out[9], measurement->humidity_centi_percent);
	put_u16_le(&out[11], measurement->battery_mv);
}
