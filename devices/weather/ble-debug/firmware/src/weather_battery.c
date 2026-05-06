#include "weather_battery.h"

#include <hal/nrf_gpio.h>
#include <nrfx_saadc.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include <stdbool.h>
#include <stdint.h>

LOG_MODULE_REGISTER(txing_weather_battery, CONFIG_TXING_WEATHER_BLE_DEBUG_LOG_LEVEL);

#define XIAO_VBAT_AIN_PIN NRF_PIN_PORT_TO_PIN_NUMBER(14, 1)
#define XIAO_VBAT_ENABLE_PIN NRF_PIN_PORT_TO_PIN_NUMBER(15, 1)
#define XIAO_VBAT_ENABLE_ACTIVE_STATE 1u
#define XIAO_VBAT_SETTLE_MS 100u
#define XIAO_VBAT_DIVIDER_NUMERATOR 2u
#define XIAO_VBAT_DIVIDER_DENOMINATOR 1u
#define BATTERY_SAADC_CHANNEL_INDEX 0u
#define BATTERY_SAADC_RESOLUTION NRF_SAADC_RESOLUTION_12BIT

static nrf_saadc_value_t g_sample;
static bool g_ready;

static void vbat_enable(bool enabled)
{
	nrf_gpio_pin_write(XIAO_VBAT_ENABLE_PIN,
			   enabled ? XIAO_VBAT_ENABLE_ACTIVE_STATE :
				     !XIAO_VBAT_ENABLE_ACTIVE_STATE);
}

int weather_battery_init(void)
{
	nrfx_saadc_channel_t channel =
		NRFX_SAADC_DEFAULT_CHANNEL_SE(NRFX_ANALOG_EXTERNAL_AIN7,
					      BATTERY_SAADC_CHANNEL_INDEX);
	uint32_t channels_mask;
	int err;

	g_ready = false;
	nrf_gpio_cfg_default(XIAO_VBAT_AIN_PIN);
#if NRF_GPIO_HAS_SEL
	nrf_gpio_pin_control_select(XIAO_VBAT_ENABLE_PIN, NRF_GPIO_PIN_SEL_GPIO);
#endif
	vbat_enable(false);
	nrf_gpio_cfg_output(XIAO_VBAT_ENABLE_PIN);

	err = nrfx_saadc_init(NRFX_SAADC_DEFAULT_CONFIG_IRQ_PRIORITY);
	if (err != 0) {
		return err;
	}

	channel.channel_config.gain = NRF_SAADC_GAIN1_4;
#if NRF_SAADC_HAS_ACQTIME_ENUM
	channel.channel_config.acq_time = NRF_SAADC_ACQTIME_40US;
#else
	channel.channel_config.acq_time = 40;
#endif

	err = nrfx_saadc_channel_config(&channel);
	if (err != 0) {
		return err;
	}

	channels_mask = nrfx_saadc_channels_configured_get();
	err = nrfx_saadc_simple_mode_set(channels_mask, BATTERY_SAADC_RESOLUTION,
					 NRF_SAADC_OVERSAMPLE_8X, NULL);
	if (err != 0) {
		return err;
	}

	err = nrfx_saadc_offset_calibrate(NULL);
	if (err != 0) {
		return err;
	}

	g_ready = true;
	LOG_INF("Battery ADC initialized input=AIN7/P1.14 enable=P1.15 divider=2");
	return 0;
}

uint16_t weather_battery_sample_mv(void)
{
	const uint32_t full_scale = (uint32_t)nrf_saadc_value_max_get(BATTERY_SAADC_RESOLUTION);
	int64_t mv;
	int err;

	if (!g_ready) {
		return 0u;
	}

	vbat_enable(true);
	k_sleep(K_MSEC(XIAO_VBAT_SETTLE_MS));

	err = nrfx_saadc_buffer_set(&g_sample, 1);
	if (err == 0) {
		err = nrfx_saadc_mode_trigger();
	}

	vbat_enable(false);
	if (err != 0 || g_sample <= 0 || full_scale == 0u) {
		LOG_WRN("Battery sample failed err=%d raw=%d", err, g_sample);
		return 0u;
	}

	mv = (int64_t)g_sample * NRFX_SAADC_REF_INTERNAL_VALUE;
	mv *= 4;
	mv *= XIAO_VBAT_DIVIDER_NUMERATOR;
	mv /= XIAO_VBAT_DIVIDER_DENOMINATOR;
	mv = (mv + (full_scale / 2)) / full_scale;

	if (mv < 0 || mv > UINT16_MAX) {
		return 0u;
	}
	return (uint16_t)mv;
}
