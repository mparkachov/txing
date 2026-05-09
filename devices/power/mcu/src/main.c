#include <errno.h>
#include <stdbool.h>
#include <stdint.h>

#include <zephyr/bluetooth/bluetooth.h>
#if POWER_ADV_CONNECTABLE
#include <zephyr/bluetooth/conn.h>
#endif
#if POWER_GATT
#include <zephyr/bluetooth/att.h>
#include <zephyr/bluetooth/gatt.h>
#endif
#include <zephyr/bluetooth/hci.h>
#include <zephyr/bluetooth/hci_vs.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#if POWER_GATT
#include <zephyr/drivers/adc.h>
#include <nrfx_saadc.h>
#endif
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/regulator.h>
#include <zephyr/kernel.h>
#include <zephyr/net_buf.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/util.h>

#ifndef POWER_ADV_INTERVAL
#define POWER_ADV_INTERVAL 0x4000
#endif

#ifndef POWER_ADV_TX_POWER_DBM
#define POWER_ADV_TX_POWER_DBM -46
#endif

#ifndef POWER_ADV_CONNECTABLE
#define POWER_ADV_CONNECTABLE 0
#endif

#ifndef POWER_ADV_SCANNABLE
#define POWER_ADV_SCANNABLE 0
#endif

#ifndef POWER_ADV_INCLUDE_UUID
#define POWER_ADV_INCLUDE_UUID 0
#endif

#ifndef POWER_GATT
#define POWER_GATT 0
#endif

#ifndef POWER_REDCON_CONN_INTERVAL_MS
#define POWER_REDCON_CONN_INTERVAL_MS 100U
#endif

#ifndef POWER_REDCON_CONN_LATENCY
#define POWER_REDCON_CONN_LATENCY 0U
#endif

#ifndef POWER_REDCON_CONN_SUPERVISION_MS
#define POWER_REDCON_CONN_SUPERVISION_MS 20000U
#endif

#ifndef POWER_REDCON_STATE_NOTIFY_INTERVAL_SECONDS
#define POWER_REDCON_STATE_NOTIFY_INTERVAL_SECONDS 10U
#endif

#ifndef POWER_REDCON_IDLE_DISCONNECT_DELAY_MS
#define POWER_REDCON_IDLE_DISCONNECT_DELAY_MS 500U
#endif

#ifndef POWER_REDCON_BATTERY_ADC_SETTLE_MS
#define POWER_REDCON_BATTERY_ADC_SETTLE_MS 100U
#endif

#if POWER_ADV_INCLUDE_UUID && !POWER_ADV_SCANNABLE
#error "REDCON service UUID requires scannable advertising so it can fit in scan response"
#endif

#if POWER_GATT && !POWER_ADV_CONNECTABLE
#error "REDCON GATT requires connectable advertising"
#endif

#if POWER_GATT && !POWER_ADV_INCLUDE_UUID
#error "REDCON GATT requires redcon service UUID advertising"
#endif

#if POWER_GATT &&                                                                  \
	(!DT_NODE_EXISTS(DT_PATH(zephyr_user)) ||                                      \
	 !DT_NODE_HAS_PROP(DT_PATH(zephyr_user), io_channels))
#error "REDCON GATT battery reporting requires zephyr,user io-channels"
#endif

#define REDCON_SERVICE_UUID_VAL                                                             \
	BT_UUID_128_ENCODE(0xf6b4b000, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define REDCON_COMMAND_UUID_VAL                                                             \
	BT_UUID_128_ENCODE(0xf6b4b001, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define REDCON_STATE_UUID_VAL                                                               \
	BT_UUID_128_ENCODE(0xf6b4b002, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)

#define REDCON_PROTOCOL_VERSION 1U
#define REDCON_ACTIVE 3U
#define REDCON_IDLE 4U
#define REDCON_STATE_PAYLOAD_SIZE 4U
#define REDCON_COMMAND_PAYLOAD_SIZE 2U
#define REDCON_CONN_INTERVAL_MIN_UNITS 6U
#define REDCON_CONN_INTERVAL_MAX_UNITS 3200U
#define REDCON_CONN_LATENCY_MAX 499U
#define REDCON_CONN_SUPERVISION_MIN_UNITS 10U
#define REDCON_CONN_SUPERVISION_MAX_UNITS 3200U

#if POWER_ADV_CONNECTABLE
#define POWER_ADV_OPTIONS BT_LE_ADV_OPT_CONN
#elif POWER_ADV_SCANNABLE
#define POWER_ADV_OPTIONS BT_LE_ADV_OPT_SCANNABLE
#else
#define POWER_ADV_OPTIONS 0
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

#if POWER_GATT
static const struct adc_dt_spec battery_adc =
	ADC_DT_SPEC_GET_BY_IDX(DT_PATH(zephyr_user), 0);
#endif

static const struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
};

#if POWER_ADV_INCLUDE_UUID
static const struct bt_data sd[] = {
	BT_DATA_BYTES(BT_DATA_UUID128_ALL, REDCON_SERVICE_UUID_VAL),
};
#endif

static const struct bt_le_adv_param adv_params =
	BT_LE_ADV_PARAM_INIT(POWER_ADV_OPTIONS, POWER_ADV_INTERVAL,
			     POWER_ADV_INTERVAL, NULL);

static int start_advertising(void);
static void disable_xiao_load_regulators(void);
static void enter_ble_idle_hardware_state(void);

#if POWER_GATT
struct gatt_payload {
	uint8_t *data;
	size_t len;
};

struct redcon_command {
	uint8_t redcon;
};

static uint8_t current_redcon = REDCON_IDLE;
static uint8_t redcon_state_payload[REDCON_STATE_PAYLOAD_SIZE] = {
	REDCON_PROTOCOL_VERSION,
	REDCON_IDLE,
	0,
	0,
};
static struct gatt_payload redcon_state_value = {
	.data = redcon_state_payload,
	.len = sizeof(redcon_state_payload),
};

static const struct bt_uuid_128 redcon_service_uuid =
	BT_UUID_INIT_128(REDCON_SERVICE_UUID_VAL);
static const struct bt_uuid_128 redcon_command_uuid =
	BT_UUID_INIT_128(REDCON_COMMAND_UUID_VAL);
static const struct bt_uuid_128 redcon_state_uuid =
	BT_UUID_INIT_128(REDCON_STATE_UUID_VAL);

static void set_redcon_power(bool active);
static void suspend_battery_adc(void);
static void cancel_idle_disconnect(void);
static void schedule_idle_disconnect(struct bt_conn *conn);
static void request_connection_params(struct bt_conn *conn);

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
		k_sleep(K_MSEC(POWER_REDCON_BATTERY_ADC_SETTLE_MS));
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

static void encode_redcon_state(uint8_t redcon, uint16_t battery_mv)
{
	redcon_state_payload[0] = REDCON_PROTOCOL_VERSION;
	redcon_state_payload[1] = redcon;
	sys_put_le16(battery_mv, &redcon_state_payload[2]);
}

static void refresh_redcon_payloads(void)
{
	const uint16_t battery_mv = sample_battery_mv();

	encode_redcon_state(current_redcon, battery_mv);
}

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
	    len != REDCON_COMMAND_PAYLOAD_SIZE) {
		return false;
	}
	if (data[0] != REDCON_PROTOCOL_VERSION) {
		return false;
	}

	redcon = data[1];
	if (redcon != REDCON_ACTIVE && redcon != REDCON_IDLE) {
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
	if (!validate_connection_params(POWER_REDCON_CONN_INTERVAL_MS,
					POWER_REDCON_CONN_LATENCY,
					POWER_REDCON_CONN_SUPERVISION_MS)) {
		return;
	}

	params.interval_min = conn_interval_units_from_ms(POWER_REDCON_CONN_INTERVAL_MS);
	params.interval_max = params.interval_min;
	params.latency = POWER_REDCON_CONN_LATENCY;
	params.timeout = conn_supervision_units_from_ms(POWER_REDCON_CONN_SUPERVISION_MS);
	(void)bt_conn_le_param_update(conn, &params);
}

static ssize_t read_state(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			  void *buf, uint16_t len, uint16_t offset)
{
	const struct gatt_payload *payload = attr->user_data;

	refresh_redcon_payloads();
	return bt_gatt_attr_read(conn, attr, buf, len, offset, payload->data, payload->len);
}

static void notify_redcon_state(void);

static void state_notify_work_handler(struct k_work *work)
{
	ARG_UNUSED(work);

	if (current_redcon != REDCON_ACTIVE) {
		return;
	}

	refresh_redcon_payloads();
	notify_redcon_state();
	(void)k_work_schedule(k_work_delayable_from_work(work),
			      K_SECONDS(POWER_REDCON_STATE_NOTIFY_INTERVAL_SECONDS));
}

K_WORK_DELAYABLE_DEFINE(state_notify_work, state_notify_work_handler);

static struct bt_conn *idle_disconnect_conn;

static void idle_disconnect_work_handler(struct k_work *work)
{
	struct bt_conn *conn = idle_disconnect_conn;

	ARG_UNUSED(work);

	idle_disconnect_conn = NULL;
	if (conn == NULL) {
		return;
	}

	(void)bt_conn_disconnect(conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);
	bt_conn_unref(conn);
}

K_WORK_DELAYABLE_DEFINE(idle_disconnect_work, idle_disconnect_work_handler);

static void cancel_idle_disconnect(void)
{
	(void)k_work_cancel_delayable(&idle_disconnect_work);
	if (idle_disconnect_conn != NULL) {
		bt_conn_unref(idle_disconnect_conn);
		idle_disconnect_conn = NULL;
	}
}

static void schedule_idle_disconnect(struct bt_conn *conn)
{
	cancel_idle_disconnect();
	if (conn == NULL) {
		return;
	}

	idle_disconnect_conn = bt_conn_ref(conn);
	(void)k_work_schedule(&idle_disconnect_work,
			      K_MSEC(POWER_REDCON_IDLE_DISCONNECT_DELAY_MS));
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
	if (current_redcon == REDCON_ACTIVE) {
		cancel_idle_disconnect();
		set_redcon_power(true);
		request_connection_params(conn);
		refresh_redcon_payloads();
		notify_redcon_state();
		(void)k_work_reschedule(&state_notify_work,
					 K_SECONDS(POWER_REDCON_STATE_NOTIFY_INTERVAL_SECONDS));
	} else {
		enter_ble_idle_hardware_state();
		refresh_redcon_payloads();
		notify_redcon_state();
		enter_ble_idle_hardware_state();
		schedule_idle_disconnect(conn);
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
);

static void notify_redcon_state(void)
{
	(void)bt_gatt_notify(NULL, &redcon_svc.attrs[4], redcon_state_payload,
			     sizeof(redcon_state_payload));
}
#endif

static void configure_output_inactive(const struct gpio_dt_spec *pin)
{
	if (device_is_ready(pin->port)) {
		(void)gpio_pin_configure_dt(pin, GPIO_OUTPUT_INACTIVE);
	}
}

#if POWER_GATT
static void set_output_active(const struct gpio_dt_spec *pin, bool active)
{
	if (device_is_ready(pin->port)) {
		(void)gpio_pin_set_dt(pin, active ? 1 : 0);
	}
}

static void set_redcon_power(bool active)
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

static void enter_ble_idle_hardware_state(void)
{
#if POWER_GATT
	set_redcon_power(false);
	(void)k_work_cancel_delayable(&state_notify_work);
	suspend_battery_adc();
#endif
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
#if POWER_ADV_INCLUDE_UUID
	return bt_le_adv_start(&adv_params, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
#else
	return bt_le_adv_start(&adv_params, ad, ARRAY_SIZE(ad), NULL, 0);
#endif
}

#if POWER_ADV_CONNECTABLE
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
#if POWER_GATT
	current_redcon = REDCON_IDLE;
	cancel_idle_disconnect();
	enter_ble_idle_hardware_state();
	encode_redcon_state(REDCON_IDLE, 0U);
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
	enter_ble_idle_hardware_state();

	err = bt_enable(NULL);
	if (err < 0) {
		return err;
	}

	err = set_adv_tx_power(POWER_ADV_TX_POWER_DBM);
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
