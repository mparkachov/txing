#ifndef TXING_WEATHER_BME280_H_
#define TXING_WEATHER_BME280_H_

#include <stdbool.h>
#include <stdint.h>

struct weather_bme280_sample {
	int32_t temperature_centi_c;
	uint32_t pressure_pa;
	uint16_t humidity_centi_percent;
};

int weather_bme280_init(void);
bool weather_bme280_ready(void);
int weather_bme280_sample(struct weather_bme280_sample *sample);

#endif
