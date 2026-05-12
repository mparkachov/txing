#include <errno.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/bluetooth/att.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/hci.h>
#include <zephyr/bluetooth/hci_vs.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/regulator.h>
#include <nrfx_saadc.h>
#include <zephyr/kernel.h>
#include <zephyr/net_buf.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/crc.h>
#include <zephyr/sys/util.h>

#if (!DT_NODE_EXISTS(DT_PATH(zephyr_user)) ||                                      \
     !DT_NODE_HAS_PROP(DT_PATH(zephyr_user), io_channels))
#error "weather REDCON battery reporting requires zephyr,user io-channels"
#endif

#if !DT_NODE_HAS_STATUS(DT_ALIAS(bme280), okay)
#error "weather REDCON BME280 reporting requires a bme280 devicetree alias"
#endif

#define REDCON_SERVICE_UUID_VAL                                                             \
	BT_UUID_128_ENCODE(0xf6b4b000, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define REDCON_COMMAND_UUID_VAL                                                             \
	BT_UUID_128_ENCODE(0xf6b4b001, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define REDCON_STATE_UUID_VAL                                                               \
	BT_UUID_128_ENCODE(0xf6b4b002, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define REDCON_POWER_MEASUREMENT_UUID_VAL                                                   \
	BT_UUID_128_ENCODE(0xf6b4b003, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define REDCON_WEATHER_MEASUREMENT_UUID_VAL                                                 \
	BT_UUID_128_ENCODE(0xf6b4b004, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)

#define REDCON_PROTOCOL_VERSION 2U
#define REDCON_IDLE 4U
#define REDCON_STATE_PAYLOAD_SIZE 2U
#define REDCON_COMMAND_PAYLOAD_SIZE 2U
#define REDCON_POWER_MEASUREMENT_PAYLOAD_SIZE 3U
#define REDCON_WEATHER_MEASUREMENT_PAYLOAD_SIZE 11U
#define REDCON_BLE_ADV_MAX_NAME_LEN 26U

#define REDCON_FACTORY_DATA_MAGIC "TXR1"
#define REDCON_FACTORY_DATA_VERSION 1U
#define REDCON_FACTORY_DEVICE_NAME_SIZE 26U
#define REDCON_DEFAULT_DEVICE_NAME "txing-unconfigured"

#define REDCON_BLE_ADV_OPTIONS BT_LE_ADV_OPT_CONN

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

BUILD_ASSERT(CONFIG_BT_DEVICE_NAME_MAX <= REDCON_BLE_ADV_MAX_NAME_LEN,
	     "REDCON BLE device name must fit legacy advertising data");
BUILD_ASSERT(sizeof(REDCON_DEFAULT_DEVICE_NAME) - 1 <= CONFIG_BT_DEVICE_NAME_MAX,
	     "default REDCON BLE device name exceeds configured limit");
BUILD_ASSERT(REDCON_FACTORY_DEVICE_NAME_SIZE == REDCON_BLE_ADV_MAX_NAME_LEN,
	     "REDCON factory name capacity must match BLE advertising name capacity");

struct redcon_factory_data {
	uint8_t magic[4];
	uint8_t version;
	uint8_t device_name_len;
	uint8_t device_name[REDCON_FACTORY_DEVICE_NAME_SIZE];
	uint32_t crc32_le;
};

BUILD_ASSERT(sizeof(struct redcon_factory_data) == 36U,
	     "REDCON factory data must match the NVE writer layout");
BUILD_ASSERT(offsetof(struct redcon_factory_data, crc32_le) == 32U,
	     "REDCON factory data CRC offset must match the NVE writer layout");

struct redcon_command {
	uint8_t redcon;
};

struct gatt_payload {
	uint8_t *data;
	size_t len;
};

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
static const struct adc_dt_spec battery_adc =
	ADC_DT_SPEC_GET_BY_IDX(DT_PATH(zephyr_user), 0);

#define DEFINE_REGULATOR_DEVICE(name)                                                \
	COND_CODE_1(DT_NODE_HAS_STATUS(DT_NODELABEL(name), okay),                    \
		    (static const struct device *const name##_reg =                  \
			     DEVICE_DT_GET(DT_NODELABEL(name));),                    \
		    ())

DEFINE_REGULATOR_DEVICE(pdm_imu_pwr)
DEFINE_REGULATOR_DEVICE(vbat_pwr)

static char device_name[CONFIG_BT_DEVICE_NAME_MAX + 1] = REDCON_DEFAULT_DEVICE_NAME;

static struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
	BT_DATA(BT_DATA_NAME_COMPLETE, device_name, sizeof(REDCON_DEFAULT_DEVICE_NAME) - 1),
};

static const struct bt_data sd[] = {
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, REDCON_SERVICE_UUID_VAL),
};

static const struct bt_le_adv_param adv_params =
	BT_LE_ADV_PARAM_INIT(REDCON_BLE_ADV_OPTIONS, CONFIG_REDCON_BLE_ADV_INTERVAL,
			     CONFIG_REDCON_BLE_ADV_INTERVAL, NULL);

static uint8_t redcon_state_payload[REDCON_STATE_PAYLOAD_SIZE] = {
	REDCON_PROTOCOL_VERSION,
	REDCON_IDLE,
};
static uint8_t power_measurement_payload[REDCON_POWER_MEASUREMENT_PAYLOAD_SIZE] = {
	REDCON_PROTOCOL_VERSION,
	0,
	0,
};
static uint8_t weather_measurement_payload[REDCON_WEATHER_MEASUREMENT_PAYLOAD_SIZE] = {
	REDCON_PROTOCOL_VERSION,
	0,
	0,
	0,
	0,
	0,
	0,
	0,
	0,
	0,
	0,
};
static struct gatt_payload redcon_state_value = {
	.data = redcon_state_payload,
	.len = sizeof(redcon_state_payload),
};
static struct gatt_payload power_measurement_value = {
	.data = power_measurement_payload,
	.len = sizeof(power_measurement_payload),
};
static struct gatt_payload weather_measurement_value = {
	.data = weather_measurement_payload,
	.len = sizeof(weather_measurement_payload),
};

static const struct bt_uuid_128 redcon_service_uuid =
	BT_UUID_INIT_128(REDCON_SERVICE_UUID_VAL);
static const struct bt_uuid_128 redcon_command_uuid =
	BT_UUID_INIT_128(REDCON_COMMAND_UUID_VAL);
static const struct bt_uuid_128 redcon_state_uuid =
	BT_UUID_INIT_128(REDCON_STATE_UUID_VAL);
static const struct bt_uuid_128 redcon_power_measurement_uuid =
	BT_UUID_INIT_128(REDCON_POWER_MEASUREMENT_UUID_VAL);
static const struct bt_uuid_128 redcon_weather_measurement_uuid =
	BT_UUID_INIT_128(REDCON_WEATHER_MEASUREMENT_UUID_VAL);

static struct bt_conn *connected_conn;
K_MUTEX_DEFINE(connected_conn_lock);

static bool is_valid_device_name_byte(uint8_t value)
{
	return value >= 0x21U && value <= 0x7eU;
}

static bool set_device_name_from_bytes(const uint8_t *name, uint8_t len)
{
	if (len == 0U || len > CONFIG_BT_DEVICE_NAME_MAX ||
	    len > REDCON_BLE_ADV_MAX_NAME_LEN) {
		return false;
	}

	for (uint8_t i = 0U; i < len; i++) {
		if (!is_valid_device_name_byte(name[i])) {
			return false;
		}
	}

	memcpy(device_name, name, len);
	device_name[len] = '\0';
	ad[1].data_len = len;
	return true;
}

static bool load_device_name_from_nve(void)
{
	struct redcon_factory_data factory;
	const size_t without_crc = offsetof(struct redcon_factory_data, crc32_le);
	const struct redcon_factory_data *stored =
		(const struct redcon_factory_data *)CONFIG_REDCON_FACTORY_DATA_ADDRESS;
	uint32_t crc;

	memcpy(&factory, stored, sizeof(factory));

	if (memcmp(factory.magic, REDCON_FACTORY_DATA_MAGIC, 4U) != 0 ||
	    factory.version != REDCON_FACTORY_DATA_VERSION) {
		return false;
	}
	if (factory.device_name_len == 0U ||
	    factory.device_name_len > REDCON_FACTORY_DEVICE_NAME_SIZE) {
		return false;
	}

	crc = crc32_ieee((const uint8_t *)&factory, without_crc);
	if (crc != sys_le32_to_cpu(factory.crc32_le)) {
		return false;
	}

	return set_device_name_from_bytes(factory.device_name, factory.device_name_len);
}

static void configure_output_inactive(const struct gpio_dt_spec *pin)
{
	if (device_is_ready(pin->port)) {
		(void)gpio_pin_configure_dt(pin, GPIO_OUTPUT_INACTIVE);
	}
}

static void set_output_active(const struct gpio_dt_spec *pin, bool active)
{
	if (device_is_ready(pin->port)) {
		(void)gpio_pin_set_dt(pin, active ? 1 : 0);
	}
}

static void disable_regulator(const struct device *reg)
{
	if (device_is_ready(reg)) {
		(void)regulator_disable(reg);
	}
}

static void disable_xiao_load_regulators(void)
{
#if DT_NODE_HAS_STATUS(DT_NODELABEL(pdm_imu_pwr), okay)
	disable_regulator(pdm_imu_pwr_reg);
#endif
#if DT_NODE_HAS_STATUS(DT_NODELABEL(vbat_pwr), okay)
	disable_regulator(vbat_pwr_reg);
#endif
}

static void resume_battery_adc(void)
{
	if (!nrfx_saadc_init_check()) {
		(void)nrfx_saadc_init(0);
	}
}

static void suspend_battery_adc(void)
{
	if (nrfx_saadc_init_check()) {
		nrfx_saadc_uninit();
	}
}

static uint16_t sample_battery_mv(void)
{
	uint16_t buf;
	uint16_t result = 0U;
	int32_t val_mv;
	struct adc_sequence sequence = {
		.buffer = &buf,
		.buffer_size = sizeof(buf),
	};
	int err;

	if (!adc_is_ready_dt(&battery_adc)) {
		suspend_battery_adc();
		return 0U;
	}

	resume_battery_adc();

#if DT_NODE_HAS_STATUS(DT_NODELABEL(vbat_pwr), okay)
	if (device_is_ready(vbat_pwr_reg)) {
		(void)regulator_enable(vbat_pwr_reg);
		k_sleep(K_MSEC(CONFIG_REDCON_BATTERY_ADC_SETTLE_MS));
	}
#endif

	err = adc_channel_setup_dt(&battery_adc);
	if (err < 0) {
		goto out;
	}

	(void)adc_sequence_init_dt(&battery_adc, &sequence);
	err = adc_read_dt(&battery_adc, &sequence);
	if (err < 0) {
		goto out;
	}

	if (battery_adc.channel_cfg.differential) {
		val_mv = (int32_t)((int16_t)buf);
	} else {
		val_mv = (int32_t)buf;
	}

	err = adc_raw_to_millivolts_dt(&battery_adc, &val_mv);
	if (err < 0 || val_mv < 0) {
		goto out;
	}

	val_mv *= 2;
	if (val_mv > UINT16_MAX) {
		val_mv = UINT16_MAX;
	}

	result = (uint16_t)val_mv;

out:
#if DT_NODE_HAS_STATUS(DT_NODELABEL(vbat_pwr), okay)
	if (device_is_ready(vbat_pwr_reg)) {
		(void)regulator_disable(vbat_pwr_reg);
	}
#endif
	suspend_battery_adc();
	return result;
}

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

static int sample_bme280_payload(void)
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

	if (!i2c_is_ready_dt(&bme280_i2c)) {
		return -ENODEV;
	}

	set_output_active(&bme280_power, true);
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

	weather_measurement_payload[0] = REDCON_PROTOCOL_VERSION;
	sys_put_le32((uint32_t)temperature_centi_c, &weather_measurement_payload[1]);
	sys_put_le32(pressure_pa, &weather_measurement_payload[5]);
	sys_put_le16((uint16_t)humidity_centi_percent, &weather_measurement_payload[9]);

out:
	set_output_active(&bme280_power, false);
	return err;
}

static void encode_redcon_state(void)
{
	redcon_state_payload[0] = REDCON_PROTOCOL_VERSION;
	redcon_state_payload[1] = REDCON_IDLE;
}

static void encode_power_measurement(uint16_t battery_mv)
{
	power_measurement_payload[0] = REDCON_PROTOCOL_VERSION;
	sys_put_le16(battery_mv, &power_measurement_payload[1]);
}

static void refresh_power_measurement_payload(void)
{
	const uint16_t battery_mv = sample_battery_mv();

	encode_power_measurement(battery_mv);
}

static bool decode_redcon_command(const uint8_t *data, size_t len,
				  struct redcon_command *command)
{
	if (data == NULL || command == NULL ||
	    len != REDCON_COMMAND_PAYLOAD_SIZE) {
		return false;
	}
	if (data[0] != REDCON_PROTOCOL_VERSION) {
		return false;
	}
	if (data[1] != REDCON_IDLE) {
		return false;
	}

	command->redcon = REDCON_IDLE;
	return true;
}

static ssize_t read_state(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			  void *buf, uint16_t len, uint16_t offset)
{
	const struct gatt_payload *payload = attr->user_data;

	encode_redcon_state();
	return bt_gatt_attr_read(conn, attr, buf, len, offset, payload->data, payload->len);
}

static ssize_t read_power_measurement(struct bt_conn *conn, const struct bt_gatt_attr *attr,
				      void *buf, uint16_t len, uint16_t offset)
{
	const struct gatt_payload *payload = attr->user_data;

	refresh_power_measurement_payload();
	return bt_gatt_attr_read(conn, attr, buf, len, offset, payload->data, payload->len);
}

static ssize_t read_weather_measurement(struct bt_conn *conn, const struct bt_gatt_attr *attr,
					void *buf, uint16_t len, uint16_t offset)
{
	const struct gatt_payload *payload = attr->user_data;

	if (sample_bme280_payload() < 0) {
		return BT_GATT_ERR(BT_ATT_ERR_UNLIKELY);
	}
	return bt_gatt_attr_read(conn, attr, buf, len, offset, payload->data, payload->len);
}

static void notify_redcon_state(void);
static void notify_power_measurement(void);
static void notify_weather_measurement(void);
static void schedule_idle_measurement_notification(void);

static struct bt_conn *ref_connected_conn(void)
{
	struct bt_conn *conn;

	k_mutex_lock(&connected_conn_lock, K_FOREVER);
	conn = connected_conn == NULL ? NULL : bt_conn_ref(connected_conn);
	k_mutex_unlock(&connected_conn_lock);

	return conn;
}

static void set_connected_conn(struct bt_conn *conn)
{
	struct bt_conn *next = conn == NULL ? NULL : bt_conn_ref(conn);
	struct bt_conn *previous;

	k_mutex_lock(&connected_conn_lock, K_FOREVER);
	previous = connected_conn;
	connected_conn = next;
	k_mutex_unlock(&connected_conn_lock);

	if (previous != NULL) {
		bt_conn_unref(previous);
	}
}

static void idle_measurement_notify_work_handler(struct k_work *work)
{
	struct bt_conn *conn;
	int weather_err;

	ARG_UNUSED(work);

	conn = ref_connected_conn();
	if (conn == NULL) {
		return;
	}
	bt_conn_unref(conn);

	set_output_active(&led, true);
	refresh_power_measurement_payload();
	weather_err = sample_bme280_payload();
	set_output_active(&led, false);

	notify_power_measurement();
	if (weather_err == 0) {
		notify_weather_measurement();
	}
	schedule_idle_measurement_notification();
}

K_WORK_DELAYABLE_DEFINE(idle_measurement_notify_work, idle_measurement_notify_work_handler);

static void cancel_idle_measurement_notifications(void)
{
	(void)k_work_cancel_delayable(&idle_measurement_notify_work);
}

static void schedule_idle_measurement_notification(void)
{
	struct bt_conn *conn;

	conn = ref_connected_conn();
	if (conn == NULL) {
		return;
	}
	bt_conn_unref(conn);

	(void)k_work_schedule(
		&idle_measurement_notify_work,
		K_SECONDS(CONFIG_REDCON_BLE_IDLE_MEASUREMENT_NOTIFY_INTERVAL_SECONDS));
}

static ssize_t write_command(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			     const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	struct redcon_command command;

	ARG_UNUSED(conn);
	ARG_UNUSED(attr);
	ARG_UNUSED(flags);

	if (offset != 0U) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
	}
	if (!decode_redcon_command(buf, len, &command)) {
		return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
	}

	encode_redcon_state();
	notify_redcon_state();
	refresh_power_measurement_payload();
	notify_power_measurement();
	if (sample_bme280_payload() == 0) {
		notify_weather_measurement();
	}
	cancel_idle_measurement_notifications();
	schedule_idle_measurement_notification();

	return len;
}

BT_GATT_SERVICE_DEFINE(weather_svc,
	BT_GATT_PRIMARY_SERVICE(&redcon_service_uuid),
	BT_GATT_CHARACTERISTIC(&redcon_command_uuid.uuid, BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_WRITE, NULL, write_command, NULL),
	BT_GATT_CHARACTERISTIC(&redcon_state_uuid.uuid, BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_READ, read_state, NULL, &redcon_state_value),
	BT_GATT_CCC(NULL, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	BT_GATT_CHARACTERISTIC(&redcon_power_measurement_uuid.uuid,
			       BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY, BT_GATT_PERM_READ,
			       read_power_measurement, NULL, &power_measurement_value),
	BT_GATT_CCC(NULL, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	BT_GATT_CHARACTERISTIC(&redcon_weather_measurement_uuid.uuid,
			       BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY, BT_GATT_PERM_READ,
			       read_weather_measurement, NULL, &weather_measurement_value),
	BT_GATT_CCC(NULL, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
);

static void notify_redcon_state(void)
{
	(void)bt_gatt_notify(NULL, &weather_svc.attrs[4], redcon_state_payload,
			     sizeof(redcon_state_payload));
}

static void notify_power_measurement(void)
{
	(void)bt_gatt_notify(NULL, &weather_svc.attrs[7], power_measurement_payload,
			     sizeof(power_measurement_payload));
}

static void notify_weather_measurement(void)
{
	(void)bt_gatt_notify(NULL, &weather_svc.attrs[10], weather_measurement_payload,
			     sizeof(weather_measurement_payload));
}

static void enter_ble_idle_hardware_state(void)
{
	set_output_active(&led, false);
	set_output_active(&bme280_power, false);
	suspend_battery_adc();
	disable_xiao_load_regulators();
}

static int set_adv_tx_power(int8_t dbm)
{
	struct bt_hci_cp_vs_write_tx_power_level *cp;
	struct bt_hci_rp_vs_write_tx_power_level *rp;
	struct net_buf *buf;
	struct net_buf *rsp = NULL;
	int err;

	buf = bt_hci_cmd_alloc(K_FOREVER);
	if (buf == NULL) {
		return -ENOMEM;
	}

	cp = net_buf_add(buf, sizeof(*cp));
	cp->handle_type = BT_HCI_VS_LL_HANDLE_TYPE_ADV;
	cp->handle = sys_cpu_to_le16(0);
	cp->tx_power_level = dbm;

	err = bt_hci_cmd_send_sync(BT_HCI_OP_VS_WRITE_TX_POWER_LEVEL, buf, &rsp);
	if (err < 0) {
		return err;
	}

	rp = (void *)rsp->data;
	if (rp->status != 0U || rp->selected_tx_power != dbm) {
		err = -EIO;
	}

	net_buf_unref(rsp);
	return err;
}

static int start_advertising(void)
{
	return bt_le_adv_start(&adv_params, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
}

static void advertise_work_handler(struct k_work *work)
{
	ARG_UNUSED(work);
	(void)start_advertising();
}

K_WORK_DEFINE(advertise_work, advertise_work_handler);

static void connected(struct bt_conn *conn, uint8_t err)
{
	if (err != 0U) {
		k_work_submit(&advertise_work);
		return;
	}

	set_connected_conn(conn);
	schedule_idle_measurement_notification();
}

static void disconnected(struct bt_conn *conn, uint8_t reason)
{
	ARG_UNUSED(conn);
	ARG_UNUSED(reason);
	cancel_idle_measurement_notifications();
	set_connected_conn(NULL);
	enter_ble_idle_hardware_state();
	encode_redcon_state();
	k_work_submit(&advertise_work);
}

BT_CONN_CB_DEFINE(conn_callbacks) = {
	.connected = connected,
	.disconnected = disconnected,
};

int main(void)
{
	int err;

	(void)load_device_name_from_nve();

	configure_output_inactive(&led);
	configure_output_inactive(&bme280_power);
	enter_ble_idle_hardware_state();
	encode_redcon_state();

	err = bt_enable(NULL);
	if (err < 0) {
		return err;
	}

	err = bt_set_name(device_name);
	if (err < 0) {
		return err;
	}

	err = set_adv_tx_power(CONFIG_REDCON_BLE_ADV_TX_POWER_DBM);
	if (err < 0) {
		return err;
	}

	err = start_advertising();
	if (err < 0) {
		return err;
	}

	while (true) {
		k_sleep(K_FOREVER);
	}

	return 0;
}
