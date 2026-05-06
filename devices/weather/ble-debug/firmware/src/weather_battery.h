#ifndef TXING_WEATHER_BATTERY_H_
#define TXING_WEATHER_BATTERY_H_

#include <stdint.h>

int weather_battery_init(void);
uint16_t weather_battery_sample_mv(void);

#endif
