#ifndef TXING_REDCON_H
#define TXING_REDCON_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <zephyr/drivers/gpio.h>

#define TXING_REDCON_PROTOCOL_VERSION 2U
#define TXING_REDCON_LEVEL_1 1U
#define TXING_REDCON_LEVEL_2 2U
#define TXING_REDCON_ACTIVE 3U
#define TXING_REDCON_IDLE 4U
#define TXING_REDCON_STATE_PAYLOAD_SIZE 2U
#define TXING_REDCON_COMMAND_PAYLOAD_SIZE 2U
#define TXING_REDCON_POWER_MEASUREMENT_PAYLOAD_SIZE 3U
#define TXING_REDCON_WEATHER_MEASUREMENT_PAYLOAD_SIZE 11U
#define TXING_REDCON_BLE_ADV_MAX_NAME_LEN 26U

struct txing_redcon_ops {
	const struct gpio_dt_spec *led;
	const struct gpio_dt_spec *power;
	int (*sample_weather_measurement)(uint8_t *payload, size_t len);
	void (*before_idle_measurement)(void);
	void (*after_idle_measurement)(void);
	void (*app_init)(void);
};

void txing_redcon_configure_output_inactive(const struct gpio_dt_spec *pin);
void txing_redcon_set_output_active(const struct gpio_dt_spec *pin, bool active);
int txing_redcon_run(const struct txing_redcon_ops *ops);

#endif
