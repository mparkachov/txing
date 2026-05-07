#include <errno.h>
#include <stdbool.h>
#include <stdint.h>

#include <zephyr/bluetooth/bluetooth.h>
#if BLE_DEBUG_ADV_CONNECTABLE
#include <zephyr/bluetooth/conn.h>
#endif
#if BLE_DEBUG_GATT
#include <zephyr/bluetooth/att.h>
#include <zephyr/bluetooth/gatt.h>
#endif
#include <zephyr/bluetooth/hci.h>
#include <zephyr/bluetooth/hci_vs.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#if BLE_DEBUG_GATT
#include <zephyr/drivers/adc.h>
#endif
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/regulator.h>
#include <zephyr/kernel.h>
#include <zephyr/net_buf.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>

#ifndef BLE_DEBUG_ADV_INTERVAL
#define BLE_DEBUG_ADV_INTERVAL 0x4000
#endif

#ifndef BLE_DEBUG_ADV_TX_POWER_DBM
#define BLE_DEBUG_ADV_TX_POWER_DBM -46
#endif

#ifndef BLE_DEBUG_ADV_CONNECTABLE
#define BLE_DEBUG_ADV_CONNECTABLE 0
#endif

#ifndef BLE_DEBUG_ADV_SCANNABLE
#define BLE_DEBUG_ADV_SCANNABLE 0
#endif

#ifndef BLE_DEBUG_ADV_INCLUDE_UUID
#define BLE_DEBUG_ADV_INCLUDE_UUID 0
#endif

#ifndef BLE_DEBUG_GATT
#define BLE_DEBUG_GATT 0
#endif

#if BLE_DEBUG_ADV_INCLUDE_UUID && !BLE_DEBUG_ADV_SCANNABLE
#error "Weather service UUID requires scannable advertising so it can fit in scan response"
#endif

#if BLE_DEBUG_GATT && !BLE_DEBUG_ADV_CONNECTABLE
#error "Weather GATT requires connectable advertising"
#endif

#if BLE_DEBUG_GATT && !BLE_DEBUG_ADV_INCLUDE_UUID
#error "Weather GATT requires weather service UUID advertising"
#endif

#if BLE_DEBUG_GATT &&                                                                  \
	(!DT_NODE_EXISTS(DT_PATH(zephyr_user)) ||                                      \
	 !DT_NODE_HAS_PROP(DT_PATH(zephyr_user), io_channels))
#error "Weather GATT battery reporting requires zephyr,user io-channels"
#endif

#define WEATHER_SERVICE_UUID_VAL                                                             \
	BT_UUID_128_ENCODE(0xf6b4b000, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define WEATHER_COMMAND_UUID_VAL                                                             \
	BT_UUID_128_ENCODE(0xf6b4b001, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define WEATHER_STATE_UUID_VAL                                                               \
	BT_UUID_128_ENCODE(0xf6b4b002, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)

#define WEATHER_PROTOCOL_VERSION 1U
#define WEATHER_REDCON_ACTIVE 3U
#define WEATHER_REDCON_IDLE 4U
#define WEATHER_STATE_FLAG_ACTIVE 0x01U
#define WEATHER_STATE_PAYLOAD_SIZE 5U
#define WEATHER_BATTERY_ADC_SETTLE_MS 100U
#define WEATHER_STATE_NOTIFY_INTERVAL_SECONDS 10U

#if BLE_DEBUG_ADV_CONNECTABLE
#define BLE_DEBUG_ADV_OPTIONS BT_LE_ADV_OPT_CONN
#elif BLE_DEBUG_ADV_SCANNABLE
#define BLE_DEBUG_ADV_OPTIONS BT_LE_ADV_OPT_SCANNABLE
#else
#define BLE_DEBUG_ADV_OPTIONS 0
#endif

static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
static const struct gpio_dt_spec power = GPIO_DT_SPEC_GET(DT_ALIAS(power), gpios);

#define DEFINE_REGULATOR_DEVICE(name)                                                \
	COND_CODE_1(DT_NODE_HAS_STATUS(DT_NODELABEL(name), okay),                    \
		    (static const struct device *const name##_reg =                  \
			     DEVICE_DT_GET(DT_NODELABEL(name));),                    \
		    ())

DEFINE_REGULATOR_DEVICE(pdm_imu_pwr)
DEFINE_REGULATOR_DEVICE(vbat_pwr)

#if BLE_DEBUG_GATT
static const struct adc_dt_spec battery_adc =
	ADC_DT_SPEC_GET_BY_IDX(DT_PATH(zephyr_user), 0);
#endif

static const struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
};

#if BLE_DEBUG_ADV_INCLUDE_UUID
static const struct bt_data sd[] = {
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, WEATHER_SERVICE_UUID_VAL),
};
#endif

static const struct bt_le_adv_param adv_params =
	BT_LE_ADV_PARAM_INIT(BLE_DEBUG_ADV_OPTIONS, BLE_DEBUG_ADV_INTERVAL,
			     BLE_DEBUG_ADV_INTERVAL, NULL);

static int start_advertising(void);

#if BLE_DEBUG_GATT
struct gatt_payload {
	uint8_t *data;
	size_t len;
};

static uint8_t current_redcon = WEATHER_REDCON_IDLE;
static uint8_t weather_state_payload[WEATHER_STATE_PAYLOAD_SIZE] = {
	WEATHER_PROTOCOL_VERSION,
	WEATHER_REDCON_IDLE,
	0,
	0,
	0,
};
static struct gatt_payload weather_state_value = {
	.data = weather_state_payload,
	.len = sizeof(weather_state_payload),
};

static const struct bt_uuid_128 weather_service_uuid =
	BT_UUID_INIT_128(WEATHER_SERVICE_UUID_VAL);
static const struct bt_uuid_128 weather_command_uuid =
	BT_UUID_INIT_128(WEATHER_COMMAND_UUID_VAL);
static const struct bt_uuid_128 weather_state_uuid =
	BT_UUID_INIT_128(WEATHER_STATE_UUID_VAL);

static void set_weather_power(bool active);

static uint16_t sample_battery_mv(void)
{
	uint16_t buf;
	int32_t val_mv;
	struct adc_sequence sequence = {
		.buffer = &buf,
		.buffer_size = sizeof(buf),
	};
	int err;

	if (!adc_is_ready_dt(&battery_adc)) {
		return 0U;
	}

#if DT_NODE_HAS_STATUS(DT_NODELABEL(vbat_pwr), okay)
	if (device_is_ready(vbat_pwr_reg)) {
		(void)regulator_enable(vbat_pwr_reg);
		k_sleep(K_MSEC(WEATHER_BATTERY_ADC_SETTLE_MS));
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

#if DT_NODE_HAS_STATUS(DT_NODELABEL(vbat_pwr), okay)
	if (device_is_ready(vbat_pwr_reg)) {
		(void)regulator_disable(vbat_pwr_reg);
	}
#endif
	return (uint16_t)val_mv;

out:
#if DT_NODE_HAS_STATUS(DT_NODELABEL(vbat_pwr), okay)
	if (device_is_ready(vbat_pwr_reg)) {
		(void)regulator_disable(vbat_pwr_reg);
	}
#endif
	return 0U;
}

static void encode_weather_state(uint8_t redcon, uint16_t battery_mv)
{
	uint8_t flags = 0U;

	if (redcon < WEATHER_REDCON_IDLE) {
		flags |= WEATHER_STATE_FLAG_ACTIVE;
	}

	weather_state_payload[0] = WEATHER_PROTOCOL_VERSION;
	weather_state_payload[1] = redcon;
	weather_state_payload[2] = flags;
	sys_put_le16(battery_mv, &weather_state_payload[3]);
}

static void refresh_weather_payloads(void)
{
	const uint16_t battery_mv = sample_battery_mv();

	encode_weather_state(current_redcon, battery_mv);
}

static bool decode_weather_command(const uint8_t *data, size_t len, uint8_t *target_redcon)
{
	uint8_t redcon;

	if (data == NULL || target_redcon == NULL || len < 2U) {
		return false;
	}
	if (data[0] != WEATHER_PROTOCOL_VERSION) {
		return false;
	}

	redcon = data[1];
	if (redcon == 1U || redcon == 2U) {
		redcon = WEATHER_REDCON_ACTIVE;
	}
	if (redcon != WEATHER_REDCON_ACTIVE && redcon != WEATHER_REDCON_IDLE) {
		return false;
	}

	*target_redcon = redcon;
	return true;
}

static ssize_t read_state(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			  void *buf, uint16_t len, uint16_t offset)
{
	const struct gatt_payload *payload = attr->user_data;

	refresh_weather_payloads();
	return bt_gatt_attr_read(conn, attr, buf, len, offset, payload->data, payload->len);
}

static void notify_weather_state(void);

static void state_notify_work_handler(struct k_work *work)
{
	ARG_UNUSED(work);

	if (current_redcon != WEATHER_REDCON_ACTIVE) {
		return;
	}

	refresh_weather_payloads();
	notify_weather_state();
	(void)k_work_schedule(k_work_delayable_from_work(work),
			      K_SECONDS(WEATHER_STATE_NOTIFY_INTERVAL_SECONDS));
}

K_WORK_DELAYABLE_DEFINE(state_notify_work, state_notify_work_handler);

static ssize_t write_command(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			     const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	uint8_t target_redcon;

	ARG_UNUSED(conn);
	ARG_UNUSED(attr);
	ARG_UNUSED(flags);

	if (offset != 0U) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
	}
	if (!decode_weather_command(buf, len, &target_redcon)) {
		return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
	}

	current_redcon = target_redcon;
	set_weather_power(current_redcon == WEATHER_REDCON_ACTIVE);
	refresh_weather_payloads();
	notify_weather_state();
	if (current_redcon == WEATHER_REDCON_ACTIVE) {
		(void)k_work_reschedule(&state_notify_work,
					 K_SECONDS(WEATHER_STATE_NOTIFY_INTERVAL_SECONDS));
	} else {
		(void)k_work_cancel_delayable(&state_notify_work);
	}

	return len;
}

BT_GATT_SERVICE_DEFINE(weather_svc,
	BT_GATT_PRIMARY_SERVICE(&weather_service_uuid),
	BT_GATT_CHARACTERISTIC(&weather_command_uuid.uuid, BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_WRITE, NULL, write_command, NULL),
	BT_GATT_CHARACTERISTIC(&weather_state_uuid.uuid, BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_READ, read_state, NULL, &weather_state_value),
	BT_GATT_CCC(NULL, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
);

static void notify_weather_state(void)
{
	(void)bt_gatt_notify(NULL, &weather_svc.attrs[4], weather_state_payload,
			     sizeof(weather_state_payload));
}
#endif

static void configure_output_inactive(const struct gpio_dt_spec *pin)
{
	if (device_is_ready(pin->port)) {
		(void)gpio_pin_configure_dt(pin, GPIO_OUTPUT_INACTIVE);
	}
}

#if BLE_DEBUG_GATT
static void set_output_active(const struct gpio_dt_spec *pin, bool active)
{
	if (device_is_ready(pin->port)) {
		(void)gpio_pin_set_dt(pin, active ? 1 : 0);
	}
}

static void set_weather_power(bool active)
{
	set_output_active(&led, active);
	set_output_active(&power, active);
}
#endif

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
#if BLE_DEBUG_ADV_INCLUDE_UUID
	return bt_le_adv_start(&adv_params, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
#else
	return bt_le_adv_start(&adv_params, ad, ARRAY_SIZE(ad), NULL, 0);
#endif
}

#if BLE_DEBUG_ADV_CONNECTABLE
static void advertise_work_handler(struct k_work *work)
{
	ARG_UNUSED(work);
	(void)start_advertising();
}

K_WORK_DEFINE(advertise_work, advertise_work_handler);

static void connected(struct bt_conn *conn, uint8_t err)
{
	ARG_UNUSED(conn);

	if (err != 0U) {
		k_work_submit(&advertise_work);
	}
}

static void disconnected(struct bt_conn *conn, uint8_t reason)
{
	ARG_UNUSED(conn);
	ARG_UNUSED(reason);
#if BLE_DEBUG_GATT
	current_redcon = WEATHER_REDCON_IDLE;
	set_weather_power(false);
	(void)k_work_cancel_delayable(&state_notify_work);
	encode_weather_state(WEATHER_REDCON_IDLE, 0U);
#endif
	k_work_submit(&advertise_work);
}

BT_CONN_CB_DEFINE(conn_callbacks) = {
	.connected = connected,
	.disconnected = disconnected,
};
#endif

int main(void)
{
	int err;

	configure_output_inactive(&led);
	configure_output_inactive(&power);
	disable_xiao_load_regulators();

	err = bt_enable(NULL);
	if (err < 0) {
		return err;
	}

	err = set_adv_tx_power(BLE_DEBUG_ADV_TX_POWER_DBM);
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
