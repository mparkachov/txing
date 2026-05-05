#ifndef TXING_WEATHER_PROTOCOL_H_
#define TXING_WEATHER_PROTOCOL_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define WEATHER_PROTOCOL_VERSION 1u
#define WEATHER_REDCON_ACTIVE 3u
#define WEATHER_REDCON_IDLE 4u

#define WEATHER_COMMAND_PAYLOAD_SIZE 2u
#define WEATHER_STATE_PAYLOAD_SIZE 5u
#define WEATHER_MEASUREMENT_PAYLOAD_SIZE 13u

#define WEATHER_STATE_FLAG_ACTIVE 0x01u
#define WEATHER_STATE_FLAG_BME280_VALID 0x02u

struct weather_state {
	uint8_t redcon;
	bool bme280_valid;
	uint16_t battery_mv;
};

struct weather_measurement {
	int32_t temperature_centi_c;
	uint32_t pressure_pa;
	uint16_t humidity_centi_percent;
	uint16_t battery_mv;
};

bool weather_decode_command(const uint8_t *data, size_t len, uint8_t *target_redcon);
void weather_encode_state(const struct weather_state *state,
			  uint8_t out[WEATHER_STATE_PAYLOAD_SIZE]);
void weather_encode_measurement(const struct weather_measurement *measurement,
				uint8_t out[WEATHER_MEASUREMENT_PAYLOAD_SIZE]);

#endif
