#include <errno.h>
#include <stddef.h>
#include <stdint.h>

#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/byteorder.h>

#include <txing_redcon.h>

#if !DT_NODE_HAS_STATUS(DT_ALIAS(bme280), okay)
#error "weather REDCON BME280 reporting requires a bme280 devicetree alias"
#endif

#define BME280_REG_PRESS_MSB 0xf7U
#define BME280_REG_COMP_START 0x88U
#define BME280_REG_HUM_COMP_PART1 0xa1U
#define BME280_REG_HUM_COMP_PART2 0xe1U
#define BME280_REG_ID 0xd0U
#define BME280_REG_CONFIG 0xf5U
#define BME280_REG_CTRL_MEAS 0xf4U
#define BME280_REG_CTRL_HUM 0xf2U
#define BME280_REG_STATUS 0xf3U
#define BME280_REG_RESET 0xe0U
#define BME280_CHIP_ID 0x60U
#define BME280_CMD_SOFT_RESET 0xb6U
#define BME280_STATUS_MEASURING 0x08U
#define BME280_STATUS_IM_UPDATE 0x01U
#define BME280_OVERSAMPLE_1X 1U
#define BME280_CTRL_HUM_VAL BME280_OVERSAMPLE_1X
#define BME280_CTRL_MEAS_FORCED ((BME280_OVERSAMPLE_1X << 5U) | \
				 (BME280_OVERSAMPLE_1X << 2U) | 1U)
#define BME280_CONFIG_VAL 0U
#define BME280_EXPECTED_SAMPLE_TIME_MS 8U
#define BME280_MEASUREMENT_TIMEOUT_MS 150U

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
	int32_t t_fine;
};

static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
static const struct gpio_dt_spec bme280_power = GPIO_DT_SPEC_GET(DT_ALIAS(power), gpios);
static const struct i2c_dt_spec bme280_i2c = I2C_DT_SPEC_GET(DT_ALIAS(bme280));

static int bme280_read(uint8_t reg, uint8_t *buf, uint32_t len)
{
	return i2c_burst_read_dt(&bme280_i2c, reg, buf, len);
}

static int bme280_write(uint8_t reg, uint8_t value)
{
	return i2c_reg_write_byte_dt(&bme280_i2c, reg, value);
}

static int bme280_wait_until_ready(uint32_t timeout_ms)
{
	const int64_t deadline = k_uptime_get() + timeout_ms;
	uint8_t status;
	int err;

	while (true) {
		err = bme280_read(BME280_REG_STATUS, &status, 1U);
		if (err < 0) {
			return err;
		}
		if ((status & (BME280_STATUS_MEASURING | BME280_STATUS_IM_UPDATE)) == 0U) {
			return 0;
		}
		if (k_uptime_get() >= deadline) {
			return -ETIMEDOUT;
		}
		k_sleep(K_MSEC(3));
	}
}

static int16_t bme280_s12_to_i16(uint16_t value)
{
	value &= 0x0fffU;
	if ((value & 0x0800U) != 0U) {
		value |= 0xf000U;
	}
	return (int16_t)value;
}

static int bme280_read_calibration(struct bme280_calibration *cal)
{
	uint8_t buf[24];
	uint8_t h1;
	uint8_t hbuf[7];
	int err;

	err = bme280_read(BME280_REG_COMP_START, buf, sizeof(buf));
	if (err < 0) {
		return err;
	}
	err = bme280_read(BME280_REG_HUM_COMP_PART1, &h1, sizeof(h1));
	if (err < 0) {
		return err;
	}
	err = bme280_read(BME280_REG_HUM_COMP_PART2, hbuf, sizeof(hbuf));
	if (err < 0) {
		return err;
	}

	cal->dig_t1 = sys_get_le16(&buf[0]);
	cal->dig_t2 = (int16_t)sys_get_le16(&buf[2]);
	cal->dig_t3 = (int16_t)sys_get_le16(&buf[4]);
	cal->dig_p1 = sys_get_le16(&buf[6]);
	cal->dig_p2 = (int16_t)sys_get_le16(&buf[8]);
	cal->dig_p3 = (int16_t)sys_get_le16(&buf[10]);
	cal->dig_p4 = (int16_t)sys_get_le16(&buf[12]);
	cal->dig_p5 = (int16_t)sys_get_le16(&buf[14]);
	cal->dig_p6 = (int16_t)sys_get_le16(&buf[16]);
	cal->dig_p7 = (int16_t)sys_get_le16(&buf[18]);
	cal->dig_p8 = (int16_t)sys_get_le16(&buf[20]);
	cal->dig_p9 = (int16_t)sys_get_le16(&buf[22]);
	cal->dig_h1 = h1;
	cal->dig_h2 = (int16_t)sys_get_le16(&hbuf[0]);
	cal->dig_h3 = hbuf[2];
	cal->dig_h4 = bme280_s12_to_i16(((uint16_t)hbuf[3] << 4U) | (hbuf[4] & 0x0fU));
	cal->dig_h5 = bme280_s12_to_i16(((uint16_t)hbuf[5] << 4U) | (hbuf[4] >> 4U));
	cal->dig_h6 = (int8_t)hbuf[6];
	cal->t_fine = 0;

	return 0;
}

static int32_t bme280_compensate_temp(struct bme280_calibration *cal, int32_t adc_temp)
{
	int32_t var1;
	int32_t var2;

	var1 = (((adc_temp >> 3) - ((int32_t)cal->dig_t1 << 1)) *
		((int32_t)cal->dig_t2)) >> 11;
	var2 = (((((adc_temp >> 4) - ((int32_t)cal->dig_t1)) *
		  ((adc_temp >> 4) - ((int32_t)cal->dig_t1))) >> 12) *
		((int32_t)cal->dig_t3)) >> 14;

	cal->t_fine = var1 + var2;
	return (cal->t_fine * 5 + 128) >> 8;
}

static uint32_t bme280_compensate_press(struct bme280_calibration *cal, int32_t adc_press)
{
	int64_t var1;
	int64_t var2;
	int64_t p;

	var1 = ((int64_t)cal->t_fine) - 128000;
	var2 = var1 * var1 * (int64_t)cal->dig_p6;
	var2 = var2 + ((var1 * (int64_t)cal->dig_p5) << 17);
	var2 = var2 + (((int64_t)cal->dig_p4) << 35);
	var1 = ((var1 * var1 * (int64_t)cal->dig_p3) >> 8) +
		((var1 * (int64_t)cal->dig_p2) << 12);
	var1 = (((((int64_t)1) << 47) + var1)) * ((int64_t)cal->dig_p1) >> 33;

	if (var1 == 0) {
		return 0U;
	}

	p = 1048576 - adc_press;
	p = (((p << 31) - var2) * 3125) / var1;
	var1 = (((int64_t)cal->dig_p9) * (p >> 13) * (p >> 13)) >> 25;
	var2 = (((int64_t)cal->dig_p8) * p) >> 19;
	p = ((p + var1 + var2) >> 8) + (((int64_t)cal->dig_p7) << 4);

	if (p < 0) {
		return 0U;
	}
	if (p > UINT32_MAX) {
		return UINT32_MAX;
	}
	return (uint32_t)p;
}

static uint32_t bme280_compensate_humidity(struct bme280_calibration *cal,
					   int32_t adc_humidity)
{
	int32_t h;

	h = (cal->t_fine - ((int32_t)76800));
	h = ((((adc_humidity << 14) - (((int32_t)cal->dig_h4) << 20) -
	      (((int32_t)cal->dig_h5) * h)) + ((int32_t)16384)) >> 15) *
	    (((((((h * ((int32_t)cal->dig_h6)) >> 10) *
		  (((h * ((int32_t)cal->dig_h3)) >> 11) + ((int32_t)32768))) >> 10) +
		((int32_t)2097152)) * ((int32_t)cal->dig_h2) + 8192) >> 14);
	h = (h - (((((h >> 15) * (h >> 15)) >> 7) *
		   ((int32_t)cal->dig_h1)) >> 4));
	h = (h > 419430400 ? 419430400 : h);
	h = (h < 0 ? 0 : h);

	return (uint32_t)(h >> 12);
}

static int sample_bme280_payload(uint8_t *payload, size_t len)
{
	struct bme280_calibration cal;
	uint8_t id;
	uint8_t raw[8];
	int32_t adc_press;
	int32_t adc_temp;
	int32_t adc_humidity;
	int32_t temperature_centi_c;
	uint32_t pressure_q24_8;
	uint32_t pressure_pa;
	uint32_t humidity_q22_10;
	uint32_t humidity_centi_percent;
	int err;

	if (payload == NULL || len != TXING_REDCON_WEATHER_MEASUREMENT_PAYLOAD_SIZE) {
		return -EINVAL;
	}
	if (!i2c_is_ready_dt(&bme280_i2c)) {
		return -ENODEV;
	}

	txing_redcon_set_output_active(&bme280_power, true);
	k_sleep(K_MSEC(CONFIG_WEATHER_BME280_POWER_SETTLE_MS));

	err = bme280_read(BME280_REG_ID, &id, sizeof(id));
	if (err < 0) {
		goto out;
	}
	if (id != BME280_CHIP_ID) {
		err = -ENOTSUP;
		goto out;
	}

	err = bme280_write(BME280_REG_RESET, BME280_CMD_SOFT_RESET);
	if (err < 0) {
		goto out;
	}
	k_sleep(K_MSEC(2));
	err = bme280_wait_until_ready(100U);
	if (err < 0) {
		goto out;
	}

	err = bme280_read_calibration(&cal);
	if (err < 0) {
		goto out;
	}

	err = bme280_write(BME280_REG_CTRL_HUM, BME280_CTRL_HUM_VAL);
	if (err < 0) {
		goto out;
	}
	err = bme280_write(BME280_REG_CONFIG, BME280_CONFIG_VAL);
	if (err < 0) {
		goto out;
	}
	err = bme280_write(BME280_REG_CTRL_MEAS, BME280_CTRL_MEAS_FORCED);
	if (err < 0) {
		goto out;
	}

	k_sleep(K_MSEC(BME280_EXPECTED_SAMPLE_TIME_MS));
	err = bme280_wait_until_ready(BME280_MEASUREMENT_TIMEOUT_MS);
	if (err < 0) {
		goto out;
	}

	err = bme280_read(BME280_REG_PRESS_MSB, raw, sizeof(raw));
	if (err < 0) {
		goto out;
	}

	adc_press = ((int32_t)raw[0] << 12) | ((int32_t)raw[1] << 4) |
		    ((int32_t)raw[2] >> 4);
	adc_temp = ((int32_t)raw[3] << 12) | ((int32_t)raw[4] << 4) |
		   ((int32_t)raw[5] >> 4);
	adc_humidity = ((int32_t)raw[6] << 8) | raw[7];

	temperature_centi_c = bme280_compensate_temp(&cal, adc_temp);
	pressure_q24_8 = bme280_compensate_press(&cal, adc_press);
	pressure_pa = pressure_q24_8 >> 8;
	humidity_q22_10 = bme280_compensate_humidity(&cal, adc_humidity);
	humidity_centi_percent = (humidity_q22_10 * 100U) / 1024U;
	if (humidity_centi_percent > 10000U) {
		humidity_centi_percent = 10000U;
	}

	payload[0] = TXING_REDCON_PROTOCOL_VERSION;
	sys_put_le32((uint32_t)temperature_centi_c, &payload[1]);
	sys_put_le32(pressure_pa, &payload[5]);
	sys_put_le16((uint16_t)humidity_centi_percent, &payload[9]);

out:
	txing_redcon_set_output_active(&bme280_power, false);
	return err;
}

static void before_idle_measurement(void)
{
	txing_redcon_set_output_active(&led, true);
}

static void after_idle_measurement(void)
{
	txing_redcon_set_output_active(&led, false);
}

static const struct txing_redcon_ops redcon_ops = {
	.led = &led,
	.power = &bme280_power,
	.sample_weather_measurement = sample_bme280_payload,
	.before_idle_measurement = before_idle_measurement,
	.after_idle_measurement = after_idle_measurement,
};

int main(void)
{
	return txing_redcon_run(&redcon_ops);
}
