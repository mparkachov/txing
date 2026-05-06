#include "weather_bme280.h"

#include <errno.h>
#include <nrfx_twim.h>
#include <hal/nrf_gpio.h>

#include <zephyr/kernel.h>

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define BME280_ADDR 0x76u
#define BME280_CHIP_ID 0x60u

#define REG_ID 0xd0u
#define REG_RESET 0xe0u
#define REG_CTRL_HUM 0xf2u
#define REG_STATUS 0xf3u
#define REG_CTRL_MEAS 0xf4u
#define REG_CONFIG 0xf5u
#define REG_PRESS_MSB 0xf7u
#define REG_CALIB_00 0x88u
#define REG_CALIB_26 0xe1u

#define XIAO_I2C_SDA_PIN NRF_PIN_PORT_TO_PIN_NUMBER(10, 1)
#define XIAO_I2C_SCL_PIN NRF_PIN_PORT_TO_PIN_NUMBER(11, 1)

struct bme280_calibration {
	uint16_t dig_t1;
	int16_t dig_t2;
	int16_t dig_t3;
	uint16_t dig_p1;
	int16_t dig_p2;
	int16_t dig_p3;
	int16_t dig_p4;
	int16_t dig_p5;
	int16_t dig_p6;
	int16_t dig_p7;
	int16_t dig_p8;
	int16_t dig_p9;
	uint8_t dig_h1;
	int16_t dig_h2;
	uint8_t dig_h3;
	int16_t dig_h4;
	int16_t dig_h5;
	int8_t dig_h6;
};

static nrfx_twim_t g_twim = NRFX_TWIM_INSTANCE(NRF_TWIM22);
static struct bme280_calibration g_calibration;
static bool g_ready;
static int32_t g_t_fine;

static uint16_t u16_le(const uint8_t *data)
{
	return (uint16_t)data[0] | ((uint16_t)data[1] << 8);
}

static int16_t s16_le(const uint8_t *data)
{
	return (int16_t)u16_le(data);
}

static int16_t s12_from_u16(uint16_t value)
{
	if ((value & 0x0800u) != 0u) {
		value |= 0xf000u;
	}
	return (int16_t)value;
}

static int twim_write(uint8_t reg, const uint8_t *data, size_t len)
{
	uint8_t buffer[8];
	nrfx_twim_xfer_desc_t desc;

	if (len + 1u > sizeof(buffer)) {
		return -EINVAL;
	}

	buffer[0] = reg;
	if (len > 0u) {
		memcpy(&buffer[1], data, len);
	}

	desc = (nrfx_twim_xfer_desc_t)NRFX_TWIM_XFER_DESC_TX(BME280_ADDR, buffer, len + 1u);
	return nrfx_twim_xfer(&g_twim, &desc, 0);
}

static int twim_write_u8(uint8_t reg, uint8_t value)
{
	return twim_write(reg, &value, 1u);
}

static int twim_read(uint8_t reg, uint8_t *data, size_t len)
{
	nrfx_twim_xfer_desc_t tx_desc =
		NRFX_TWIM_XFER_DESC_TX(BME280_ADDR, &reg, sizeof(reg));
	nrfx_twim_xfer_desc_t rx_desc =
		NRFX_TWIM_XFER_DESC_RX(BME280_ADDR, data, len);
	int err;

	err = nrfx_twim_xfer(&g_twim, &tx_desc, NRFX_TWIM_FLAG_TX_NO_STOP);
	if (err != 0) {
		return err;
	}
	return nrfx_twim_xfer(&g_twim, &rx_desc, 0);
}

static int read_calibration(void)
{
	uint8_t c0[26];
	uint8_t c1[7];
	int err;

	err = twim_read(REG_CALIB_00, c0, sizeof(c0));
	if (err != 0) {
		return err;
	}
	err = twim_read(REG_CALIB_26, c1, sizeof(c1));
	if (err != 0) {
		return err;
	}

	g_calibration.dig_t1 = u16_le(&c0[0]);
	g_calibration.dig_t2 = s16_le(&c0[2]);
	g_calibration.dig_t3 = s16_le(&c0[4]);
	g_calibration.dig_p1 = u16_le(&c0[6]);
	g_calibration.dig_p2 = s16_le(&c0[8]);
	g_calibration.dig_p3 = s16_le(&c0[10]);
	g_calibration.dig_p4 = s16_le(&c0[12]);
	g_calibration.dig_p5 = s16_le(&c0[14]);
	g_calibration.dig_p6 = s16_le(&c0[16]);
	g_calibration.dig_p7 = s16_le(&c0[18]);
	g_calibration.dig_p8 = s16_le(&c0[20]);
	g_calibration.dig_p9 = s16_le(&c0[22]);
	g_calibration.dig_h1 = c0[25];
	g_calibration.dig_h2 = s16_le(&c1[0]);
	g_calibration.dig_h3 = c1[2];
	g_calibration.dig_h4 = s12_from_u16(((uint16_t)c1[3] << 4) | (c1[4] & 0x0fu));
	g_calibration.dig_h5 = s12_from_u16(((uint16_t)c1[5] << 4) | (c1[4] >> 4));
	g_calibration.dig_h6 = (int8_t)c1[6];

	if (g_calibration.dig_t1 == 0u || g_calibration.dig_p1 == 0u) {
		return -EIO;
	}
	return 0;
}

static int init_failed(int err)
{
	weather_bme280_reset();
	return err;
}

static int32_t compensate_temperature(int32_t adc_t)
{
	int32_t var1;
	int32_t var2;

	var1 = ((((adc_t >> 3) - ((int32_t)g_calibration.dig_t1 << 1))) *
		((int32_t)g_calibration.dig_t2)) >> 11;
	var2 = (((((adc_t >> 4) - ((int32_t)g_calibration.dig_t1)) *
		  ((adc_t >> 4) - ((int32_t)g_calibration.dig_t1))) >> 12) *
		((int32_t)g_calibration.dig_t3)) >> 14;
	g_t_fine = var1 + var2;
	return (g_t_fine * 5 + 128) >> 8;
}

static uint32_t compensate_pressure(int32_t adc_p)
{
	int64_t var1;
	int64_t var2;
	int64_t p;

	var1 = ((int64_t)g_t_fine) - 128000;
	var2 = var1 * var1 * (int64_t)g_calibration.dig_p6;
	var2 = var2 + ((var1 * (int64_t)g_calibration.dig_p5) << 17);
	var2 = var2 + (((int64_t)g_calibration.dig_p4) << 35);
	var1 = ((var1 * var1 * (int64_t)g_calibration.dig_p3) >> 8) +
	       ((var1 * (int64_t)g_calibration.dig_p2) << 12);
	var1 = (((((int64_t)1) << 47) + var1) * (int64_t)g_calibration.dig_p1) >> 33;
	if (var1 == 0) {
		return 0u;
	}
	p = 1048576 - adc_p;
	p = (((p << 31) - var2) * 3125) / var1;
	var1 = ((int64_t)g_calibration.dig_p9 * (p >> 13) * (p >> 13)) >> 25;
	var2 = ((int64_t)g_calibration.dig_p8 * p) >> 19;
	p = ((p + var1 + var2) >> 8) + (((int64_t)g_calibration.dig_p7) << 4);
	if (p < 0) {
		return 0u;
	}
	return (uint32_t)(p >> 8);
}

static uint16_t compensate_humidity(int32_t adc_h)
{
	int32_t v_x1_u32r;
	uint32_t humidity_q1024;
	uint32_t humidity_centi;

	v_x1_u32r = g_t_fine - 76800;
	v_x1_u32r = (((((adc_h << 14) - (((int32_t)g_calibration.dig_h4) << 20) -
			(((int32_t)g_calibration.dig_h5) * v_x1_u32r)) + 16384) >> 15) *
		      (((((((v_x1_u32r * ((int32_t)g_calibration.dig_h6)) >> 10) *
			   (((v_x1_u32r * ((int32_t)g_calibration.dig_h3)) >> 11) +
			    32768)) >> 10) + 2097152) *
			((int32_t)g_calibration.dig_h2) + 8192) >> 14));
	v_x1_u32r = v_x1_u32r -
		    (((((v_x1_u32r >> 15) * (v_x1_u32r >> 15)) >> 7) *
		      ((int32_t)g_calibration.dig_h1)) >> 4);
	if (v_x1_u32r < 0) {
		v_x1_u32r = 0;
	}
	if (v_x1_u32r > 419430400) {
		v_x1_u32r = 419430400;
	}
	humidity_q1024 = (uint32_t)(v_x1_u32r >> 12);
	humidity_centi = (humidity_q1024 * 100u + 512u) / 1024u;
	if (humidity_centi > 10000u) {
		humidity_centi = 10000u;
	}
	return (uint16_t)humidity_centi;
}

int weather_bme280_init(void)
{
	nrfx_twim_config_t config =
		NRFX_TWIM_DEFAULT_CONFIG(XIAO_I2C_SCL_PIN, XIAO_I2C_SDA_PIN);
	uint8_t chip_id = 0u;
	int err;

	g_ready = false;
	memset(&g_calibration, 0, sizeof(g_calibration));

	if (!nrfx_twim_init_check(&g_twim)) {
		err = nrfx_twim_init(&g_twim, &config, NULL, NULL);
		if (err != 0) {
			return err;
		}
	}
	nrfx_twim_enable(&g_twim);

	err = twim_read(REG_ID, &chip_id, sizeof(chip_id));
	if (err != 0) {
		return init_failed(err);
	}
	if (chip_id != BME280_CHIP_ID) {
		return init_failed(-ENODEV);
	}

	err = read_calibration();
	if (err != 0) {
		return init_failed(err);
	}

	err = twim_write_u8(REG_CTRL_HUM, 0x01u);
	if (err != 0) {
		return init_failed(err);
	}
	err = twim_write_u8(REG_CONFIG, 0x00u);
	if (err != 0) {
		return init_failed(err);
	}

	g_ready = true;
	return 0;
}

void weather_bme280_reset(void)
{
	if (nrfx_twim_init_check(&g_twim)) {
		nrfx_twim_uninit(&g_twim);
	}
	nrf_gpio_cfg_default(XIAO_I2C_SCL_PIN);
	nrf_gpio_cfg_default(XIAO_I2C_SDA_PIN);
	memset(&g_calibration, 0, sizeof(g_calibration));
	g_ready = false;
	g_t_fine = 0;
}

bool weather_bme280_ready(void)
{
	return g_ready;
}

int weather_bme280_sample(struct weather_bme280_sample *sample)
{
	uint8_t data[8];
	uint8_t status = 0u;
	int32_t adc_p;
	int32_t adc_t;
	int32_t adc_h;
	int err;

	if (!g_ready || sample == NULL) {
		return -ENODEV;
	}

	err = twim_write_u8(REG_CTRL_HUM, 0x01u);
	if (err != 0) {
		return err;
	}
	err = twim_write_u8(REG_CTRL_MEAS, 0x25u);
	if (err != 0) {
		return err;
	}

	for (int attempt = 0; attempt < 10; ++attempt) {
		k_sleep(K_MSEC(10));
		err = twim_read(REG_STATUS, &status, sizeof(status));
		if (err != 0) {
			return err;
		}
		if ((status & 0x08u) == 0u) {
			break;
		}
	}

	err = twim_read(REG_PRESS_MSB, data, sizeof(data));
	if (err != 0) {
		return err;
	}

	adc_p = ((int32_t)data[0] << 12) | ((int32_t)data[1] << 4) | ((int32_t)data[2] >> 4);
	adc_t = ((int32_t)data[3] << 12) | ((int32_t)data[4] << 4) | ((int32_t)data[5] >> 4);
	adc_h = ((int32_t)data[6] << 8) | (int32_t)data[7];

	sample->temperature_centi_c = compensate_temperature(adc_t);
	sample->pressure_pa = compensate_pressure(adc_p);
	sample->humidity_centi_percent = compensate_humidity(adc_h);
	return 0;
}
