#include <errno.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include <nrfx_saadc.h>
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
#include <zephyr/drivers/regulator.h>
#include <zephyr/kernel.h>
#include <zephyr/net_buf.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/crc.h>
#include <zephyr/sys/util.h>

#include <txing_redcon.h>

#if (!DT_NODE_EXISTS(DT_PATH(zephyr_user)) ||                                      \
     !DT_NODE_HAS_PROP(DT_PATH(zephyr_user), io_channels))
#error "REDCON GATT battery reporting requires zephyr,user io-channels"
#endif

BUILD_ASSERT(CONFIG_REDCON_BLE_CONN_SUPERVISION_MS >
		     CONFIG_REDCON_BLE_CONN_INTERVAL_MS *
			     (CONFIG_REDCON_BLE_CONN_LATENCY + 1) * 2,
	     "invalid REDCON supervision timeout");

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

#define REDCON_CONN_INTERVAL_MIN_UNITS 6U
#define REDCON_CONN_INTERVAL_MAX_UNITS 3200U
#define REDCON_CONN_LATENCY_MAX 499U
#define REDCON_CONN_SUPERVISION_MIN_UNITS 10U
#define REDCON_CONN_SUPERVISION_MAX_UNITS 3200U

#define REDCON_FACTORY_DATA_MAGIC "TXR1"
#define REDCON_FACTORY_DATA_VERSION 1U
#define REDCON_FACTORY_DEVICE_NAME_SIZE 26U
#define REDCON_DEFAULT_DEVICE_NAME "txing-unconfigured"

#define REDCON_BLE_ADV_OPTIONS BT_LE_ADV_OPT_CONN

BUILD_ASSERT(CONFIG_BT_DEVICE_NAME_MAX <= TXING_REDCON_BLE_ADV_MAX_NAME_LEN,
	     "REDCON BLE device name must fit legacy advertising data");
BUILD_ASSERT(sizeof(REDCON_DEFAULT_DEVICE_NAME) - 1 <= CONFIG_BT_DEVICE_NAME_MAX,
	     "default REDCON BLE device name exceeds configured limit");
BUILD_ASSERT(REDCON_FACTORY_DEVICE_NAME_SIZE == TXING_REDCON_BLE_ADV_MAX_NAME_LEN,
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

struct gatt_payload {
	uint8_t *data;
	size_t len;
};

struct redcon_command {
	uint8_t redcon;
};

#define DEFINE_REGULATOR_DEVICE(name)                                                \
	COND_CODE_1(DT_NODE_HAS_STATUS(DT_NODELABEL(name), okay),                    \
		    (static const struct device *const name##_reg =                  \
			     DEVICE_DT_GET(DT_NODELABEL(name));),                    \
		    ())

DEFINE_REGULATOR_DEVICE(pdm_imu_pwr)
DEFINE_REGULATOR_DEVICE(vbat_pwr)

static const struct adc_dt_spec battery_adc =
	ADC_DT_SPEC_GET_BY_IDX(DT_PATH(zephyr_user), 0);

static const struct txing_redcon_ops *redcon_ops;
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

static uint8_t current_redcon = TXING_REDCON_IDLE;
static uint8_t redcon_state_payload[TXING_REDCON_STATE_PAYLOAD_SIZE] = {
	TXING_REDCON_PROTOCOL_VERSION,
	TXING_REDCON_IDLE,
};
static uint8_t power_measurement_payload[TXING_REDCON_POWER_MEASUREMENT_PAYLOAD_SIZE] = {
	TXING_REDCON_PROTOCOL_VERSION,
	0,
	0,
};
#if defined(CONFIG_REDCON_WEATHER_MEASUREMENT)
static uint8_t weather_measurement_payload[TXING_REDCON_WEATHER_MEASUREMENT_PAYLOAD_SIZE] = {
	TXING_REDCON_PROTOCOL_VERSION,
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
#endif

static struct gatt_payload redcon_state_value = {
	.data = redcon_state_payload,
	.len = sizeof(redcon_state_payload),
};
static struct gatt_payload power_measurement_value = {
	.data = power_measurement_payload,
	.len = sizeof(power_measurement_payload),
};
#if defined(CONFIG_REDCON_WEATHER_MEASUREMENT)
static struct gatt_payload weather_measurement_value = {
	.data = weather_measurement_payload,
	.len = sizeof(weather_measurement_payload),
};
#endif

static const struct bt_uuid_128 redcon_service_uuid =
	BT_UUID_INIT_128(REDCON_SERVICE_UUID_VAL);
static const struct bt_uuid_128 redcon_command_uuid =
	BT_UUID_INIT_128(REDCON_COMMAND_UUID_VAL);
static const struct bt_uuid_128 redcon_state_uuid =
	BT_UUID_INIT_128(REDCON_STATE_UUID_VAL);
static const struct bt_uuid_128 redcon_power_measurement_uuid =
	BT_UUID_INIT_128(REDCON_POWER_MEASUREMENT_UUID_VAL);
#if defined(CONFIG_REDCON_WEATHER_MEASUREMENT)
static const struct bt_uuid_128 redcon_weather_measurement_uuid =
	BT_UUID_INIT_128(REDCON_WEATHER_MEASUREMENT_UUID_VAL);
#endif

static struct bt_conn *connected_conn;
K_MUTEX_DEFINE(connected_conn_lock);

static int start_advertising(void);
static void cancel_idle_measurement_notifications(void);
static void schedule_idle_measurement_notification(void);
static void request_connection_params(struct bt_conn *conn);
static void suspend_battery_adc(void);

void txing_redcon_configure_output_inactive(const struct gpio_dt_spec *pin)
{
	if (pin != NULL && device_is_ready(pin->port)) {
		(void)gpio_pin_configure_dt(pin, GPIO_OUTPUT_INACTIVE);
	}
}

void txing_redcon_set_output_active(const struct gpio_dt_spec *pin, bool active)
{
	if (pin != NULL && device_is_ready(pin->port)) {
		(void)gpio_pin_set_dt(pin, active ? 1 : 0);
	}
}

static void set_wakeup_hardware_state(bool active)
{
	txing_redcon_set_output_active(redcon_ops->led, active);
	txing_redcon_set_output_active(redcon_ops->power, active);
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

static void enter_sleep_hardware_state(void)
{
	set_wakeup_hardware_state(false);
	suspend_battery_adc();
	disable_xiao_load_regulators();
}

static bool redcon_is_wakeup(uint8_t redcon)
{
	return redcon >= TXING_REDCON_LEVEL_1 && redcon < TXING_REDCON_IDLE;
}

static bool redcon_command_level_is_supported(uint8_t redcon)
{
	if (redcon < TXING_REDCON_LEVEL_1 || redcon > TXING_REDCON_IDLE) {
		return false;
	}
	return (CONFIG_REDCON_COMMAND_LEVELS_MASK & BIT(redcon)) != 0U;
}

static bool is_valid_device_name_byte(uint8_t value)
{
	return value >= 0x21U && value <= 0x7eU;
}

static bool set_device_name_from_bytes(const uint8_t *name, uint8_t len)
{
	if (len == 0U || len > CONFIG_BT_DEVICE_NAME_MAX ||
	    len > TXING_REDCON_BLE_ADV_MAX_NAME_LEN) {
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

static void encode_redcon_state(uint8_t redcon)
{
	redcon_state_payload[0] = TXING_REDCON_PROTOCOL_VERSION;
	redcon_state_payload[1] = redcon;
}

static void encode_power_measurement(uint16_t battery_mv)
{
	power_measurement_payload[0] = TXING_REDCON_PROTOCOL_VERSION;
	sys_put_le16(battery_mv, &power_measurement_payload[1]);
}

static void refresh_power_measurement_payload(void)
{
	const uint16_t battery_mv = sample_battery_mv();

	encode_power_measurement(battery_mv);
}

#if defined(CONFIG_REDCON_WEATHER_MEASUREMENT)
static int refresh_weather_measurement_payload(void)
{
	if (redcon_ops->sample_weather_measurement == NULL) {
		return -ENOTSUP;
	}
	return redcon_ops->sample_weather_measurement(weather_measurement_payload,
						      sizeof(weather_measurement_payload));
}
#endif

static uint16_t conn_interval_units_from_ms(uint16_t interval_ms)
{
	return (uint16_t)(((uint32_t)interval_ms * 4U + 2U) / 5U);
}

static uint16_t conn_supervision_units_from_ms(uint16_t supervision_ms)
{
	return (uint16_t)((uint32_t)supervision_ms / 10U);
}

static bool validate_connection_params(uint16_t interval_ms, uint16_t latency,
				       uint16_t supervision_ms)
{
	const uint16_t interval_units = conn_interval_units_from_ms(interval_ms);
	const uint16_t supervision_units =
		conn_supervision_units_from_ms(supervision_ms);
	const uint32_t minimum_supervision_ms =
		(uint32_t)interval_ms * (uint32_t)(latency + 1U) * 2U;

	if (interval_units < REDCON_CONN_INTERVAL_MIN_UNITS ||
	    interval_units > REDCON_CONN_INTERVAL_MAX_UNITS) {
		return false;
	}
	if (latency > REDCON_CONN_LATENCY_MAX) {
		return false;
	}
	if (supervision_units < REDCON_CONN_SUPERVISION_MIN_UNITS ||
	    supervision_units > REDCON_CONN_SUPERVISION_MAX_UNITS) {
		return false;
	}
	if ((uint32_t)supervision_ms <= minimum_supervision_ms) {
		return false;
	}
	return true;
}

static bool decode_redcon_command(const uint8_t *data, size_t len,
				  struct redcon_command *command)
{
	uint8_t redcon;

	if (data == NULL || command == NULL ||
	    len != TXING_REDCON_COMMAND_PAYLOAD_SIZE) {
		return false;
	}
	if (data[0] != TXING_REDCON_PROTOCOL_VERSION) {
		return false;
	}

	redcon = data[1];
	if (!redcon_command_level_is_supported(redcon)) {
		return false;
	}

	command->redcon = redcon;
	return true;
}

static void request_connection_params(struct bt_conn *conn)
{
	struct bt_le_conn_param params;

	if (conn == NULL) {
		return;
	}
	if (!validate_connection_params(CONFIG_REDCON_BLE_CONN_INTERVAL_MS,
					CONFIG_REDCON_BLE_CONN_LATENCY,
					CONFIG_REDCON_BLE_CONN_SUPERVISION_MS)) {
		return;
	}

	params.interval_min = conn_interval_units_from_ms(CONFIG_REDCON_BLE_CONN_INTERVAL_MS);
	params.interval_max = params.interval_min;
	params.latency = CONFIG_REDCON_BLE_CONN_LATENCY;
	params.timeout = conn_supervision_units_from_ms(CONFIG_REDCON_BLE_CONN_SUPERVISION_MS);
	(void)bt_conn_le_param_update(conn, &params);
}

static ssize_t read_state(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			  void *buf, uint16_t len, uint16_t offset)
{
	const struct gatt_payload *payload = attr->user_data;

	encode_redcon_state(current_redcon);
	return bt_gatt_attr_read(conn, attr, buf, len, offset, payload->data, payload->len);
}

static ssize_t read_power_measurement(struct bt_conn *conn, const struct bt_gatt_attr *attr,
				      void *buf, uint16_t len, uint16_t offset)
{
	const struct gatt_payload *payload = attr->user_data;

	refresh_power_measurement_payload();
	return bt_gatt_attr_read(conn, attr, buf, len, offset, payload->data, payload->len);
}

#if defined(CONFIG_REDCON_WEATHER_MEASUREMENT)
static ssize_t read_weather_measurement(struct bt_conn *conn, const struct bt_gatt_attr *attr,
					void *buf, uint16_t len, uint16_t offset)
{
	const struct gatt_payload *payload = attr->user_data;

	if (refresh_weather_measurement_payload() < 0) {
		return BT_GATT_ERR(BT_ATT_ERR_UNLIKELY);
	}
	return bt_gatt_attr_read(conn, attr, buf, len, offset, payload->data, payload->len);
}
#endif

static void notify_redcon_state(void);
static void notify_power_measurement(void);
#if defined(CONFIG_REDCON_WEATHER_MEASUREMENT)
static void notify_weather_measurement(void);
#endif

static void sample_and_notify_measurements(bool use_idle_hooks)
{
#if defined(CONFIG_REDCON_WEATHER_MEASUREMENT)
	int weather_err = -ENOTSUP;
#endif

	if (use_idle_hooks && redcon_ops->before_idle_measurement != NULL) {
		redcon_ops->before_idle_measurement();
	}
	refresh_power_measurement_payload();
#if defined(CONFIG_REDCON_WEATHER_MEASUREMENT)
	weather_err = refresh_weather_measurement_payload();
#endif
	if (use_idle_hooks && redcon_ops->after_idle_measurement != NULL) {
		redcon_ops->after_idle_measurement();
	}

	notify_power_measurement();
#if defined(CONFIG_REDCON_WEATHER_MEASUREMENT)
	if (weather_err == 0) {
		notify_weather_measurement();
	}
#endif
}

static void measurement_notify_work_handler(struct k_work *work)
{
	ARG_UNUSED(work);

	if (!redcon_is_wakeup(current_redcon)) {
		return;
	}

	sample_and_notify_measurements(false);
	(void)k_work_schedule(k_work_delayable_from_work(work),
			      K_SECONDS(CONFIG_REDCON_BLE_MEASUREMENT_NOTIFY_INTERVAL_SECONDS));
}

K_WORK_DELAYABLE_DEFINE(measurement_notify_work, measurement_notify_work_handler);

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

	ARG_UNUSED(work);

	if (current_redcon != TXING_REDCON_IDLE) {
		return;
	}

	conn = ref_connected_conn();
	if (conn == NULL) {
		return;
	}
	bt_conn_unref(conn);

	sample_and_notify_measurements(true);
	enter_sleep_hardware_state();
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

	if (current_redcon != TXING_REDCON_IDLE) {
		return;
	}

	conn = ref_connected_conn();
	if (conn == NULL) {
		return;
	}
	bt_conn_unref(conn);

	(void)k_work_schedule(
		&idle_measurement_notify_work,
		K_SECONDS(CONFIG_REDCON_BLE_IDLE_MEASUREMENT_NOTIFY_INTERVAL_SECONDS));
}

static void enter_redcon_wakeup(struct bt_conn *conn)
{
	cancel_idle_measurement_notifications();
	set_wakeup_hardware_state(true);
	request_connection_params(conn);
	notify_redcon_state();
	sample_and_notify_measurements(false);
	(void)k_work_reschedule(&measurement_notify_work,
				 K_SECONDS(CONFIG_REDCON_BLE_MEASUREMENT_NOTIFY_INTERVAL_SECONDS));
}

static void enter_redcon_idle(void)
{
	(void)k_work_cancel_delayable(&measurement_notify_work);
	enter_sleep_hardware_state();
	notify_redcon_state();
	sample_and_notify_measurements(false);
	enter_sleep_hardware_state();
	schedule_idle_measurement_notification();
}

static ssize_t write_command(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			     const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	struct redcon_command command;

	ARG_UNUSED(attr);
	ARG_UNUSED(flags);

	if (offset != 0U) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
	}
	if (!decode_redcon_command(buf, len, &command)) {
		return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
	}

	current_redcon = command.redcon;
	encode_redcon_state(current_redcon);
	if (redcon_is_wakeup(current_redcon)) {
		enter_redcon_wakeup(conn);
	} else {
		enter_redcon_idle();
	}

	return len;
}

BT_GATT_SERVICE_DEFINE(redcon_svc,
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
#if defined(CONFIG_REDCON_WEATHER_MEASUREMENT)
	BT_GATT_CHARACTERISTIC(&redcon_weather_measurement_uuid.uuid,
			       BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY, BT_GATT_PERM_READ,
			       read_weather_measurement, NULL, &weather_measurement_value),
	BT_GATT_CCC(NULL, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
#endif
);

static void notify_redcon_state(void)
{
	(void)bt_gatt_notify(NULL, &redcon_svc.attrs[4], redcon_state_payload,
			     sizeof(redcon_state_payload));
}

static void notify_power_measurement(void)
{
	(void)bt_gatt_notify(NULL, &redcon_svc.attrs[7], power_measurement_payload,
			     sizeof(power_measurement_payload));
}

#if defined(CONFIG_REDCON_WEATHER_MEASUREMENT)
static void notify_weather_measurement(void)
{
	(void)bt_gatt_notify(NULL, &redcon_svc.attrs[10], weather_measurement_payload,
			     sizeof(weather_measurement_payload));
}
#endif

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
	if (current_redcon == TXING_REDCON_IDLE) {
		schedule_idle_measurement_notification();
	}
}

static void disconnected(struct bt_conn *conn, uint8_t reason)
{
	ARG_UNUSED(conn);
	ARG_UNUSED(reason);

	cancel_idle_measurement_notifications();
	set_connected_conn(NULL);

	if (redcon_is_wakeup(current_redcon) &&
	    IS_ENABLED(CONFIG_REDCON_PRESERVE_LEVEL_ON_DISCONNECT)) {
		set_wakeup_hardware_state(true);
		encode_redcon_state(current_redcon);
		(void)k_work_reschedule(
			&measurement_notify_work,
			K_SECONDS(CONFIG_REDCON_BLE_MEASUREMENT_NOTIFY_INTERVAL_SECONDS));
	} else {
		current_redcon = TXING_REDCON_IDLE;
		(void)k_work_cancel_delayable(&measurement_notify_work);
		enter_sleep_hardware_state();
		encode_redcon_state(TXING_REDCON_IDLE);
	}
	k_work_submit(&advertise_work);
}

BT_CONN_CB_DEFINE(conn_callbacks) = {
	.connected = connected,
	.disconnected = disconnected,
};

int txing_redcon_run(const struct txing_redcon_ops *ops)
{
	int err;

	if (ops == NULL) {
		return -EINVAL;
	}
	redcon_ops = ops;

	(void)load_device_name_from_nve();
	if (redcon_ops->app_init != NULL) {
		redcon_ops->app_init();
	}

	txing_redcon_configure_output_inactive(redcon_ops->led);
	txing_redcon_configure_output_inactive(redcon_ops->power);
	enter_sleep_hardware_state();
	encode_redcon_state(current_redcon);

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
