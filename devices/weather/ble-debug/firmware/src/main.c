#include "weather_battery.h"
#include "weather_bme280.h"
#include "weather_protocol.h"

#include <ble.h>
#include <ble_gatt.h>
#include <ble_gap.h>
#include <bm/bluetooth/ble_adv_data.h>
#include <bm/softdevice_handler/nrf_sdh.h>
#include <bm/softdevice_handler/nrf_sdh_ble.h>
#include <hal/nrf_gpio.h>
#include <nrf_error.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/logging/log_ctrl.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

LOG_MODULE_REGISTER(txing_weather_ble_debug, CONFIG_TXING_WEATHER_BLE_DEBUG_LOG_LEVEL);

#define FACTORY_MAGIC 0x31575854u
#define FACTORY_VERSION 1u
#define FACTORY_THING_NAME_SIZE 26u
#define ADV_DATA_SIZE BLE_GAP_ADV_SET_DATA_SIZE_MAX

#define WEATHER_UUID_BASE                                                                      \
	{                                                                                      \
		0x00, 0xf1, 0xb8, 0xa2, 0xf0, 0x4f, 0x4b, 0x9f, 0x2d, 0x4d, 0x32, 0x7b,    \
			0x00, 0x00, 0xb4, 0xf6                                           \
	}
#define WEATHER_UUID_SERVICE 0xb000u
#define WEATHER_UUID_COMMAND 0xb001u
#define WEATHER_UUID_STATE 0xb002u
#define WEATHER_UUID_MEASUREMENT 0xb003u

#define XIAO_LED_PIN NRF_PIN_PORT_TO_PIN_NUMBER(0, 2)
#define XIAO_LED_ACTIVE_STATE 0u
/* XIAO D1. D0 maps to P1.04, which the BM board config also uses for UART TX. */
#define XIAO_POWER_PIN NRF_PIN_PORT_TO_PIN_NUMBER(5, 1)
#define XIAO_POWER_ACTIVE_STATE 1u
#define XIAO_POWER_DRIVE NRF_GPIO_PIN_H0H1

#define WEATHER_SAMPLE_INTERVAL_MS 1000u
#define WEATHER_DIAG_INTERVAL_MS 10000u
#define WEATHER_POWER_SETTLE_MS 100u
#define WEATHER_BME280_INIT_RETRY_MS 1000u

#define WEATHER_IDLE_CONN_INTERVAL_UNITS ((CONFIG_TXING_WEATHER_IDLE_CONN_INTERVAL_MS * 4u) / 5u)
#define WEATHER_IDLE_CONN_SUPERVISION_UNITS                                                  \
	(CONFIG_TXING_WEATHER_IDLE_CONN_SUPERVISION_TIMEOUT_MS / 10u)

_Static_assert((CONFIG_TXING_WEATHER_IDLE_CONN_INTERVAL_MS * 4u) % 5u == 0u,
	       "idle connection interval must map to exact BLE 1.25 ms units");
_Static_assert(CONFIG_TXING_WEATHER_IDLE_CONN_SUPERVISION_TIMEOUT_MS % 10u == 0u,
	       "idle supervision timeout must map to exact BLE 10 ms units");

struct weather_factory_data {
	uint32_t magic;
	uint8_t version;
	uint8_t thing_name_len;
	char thing_name[FACTORY_THING_NAME_SIZE];
	uint32_t crc32;
};

_Static_assert(sizeof(struct weather_factory_data) == 36, "factory data layout changed");

static uint8_t g_adv_handle = BLE_GAP_ADV_SET_HANDLE_NOT_SET;
static uint8_t g_adv_data_buf[ADV_DATA_SIZE];
static uint8_t g_scan_rsp_buf[ADV_DATA_SIZE];
static ble_gap_adv_data_t g_gap_adv_data;
static ble_gap_adv_params_t g_adv_params;

static uint16_t g_conn_handle = BLE_CONN_HANDLE_INVALID;
static uint8_t g_weather_uuid_type = BLE_UUID_TYPE_UNKNOWN;
static uint16_t g_weather_service_handle;
static ble_gatts_char_handles_t g_command_handles;
static ble_gatts_char_handles_t g_state_handles;
static ble_gatts_char_handles_t g_measurement_handles;

static struct weather_state g_state = {
	.redcon = WEATHER_REDCON_IDLE,
	.bme280_valid = false,
	.battery_mv = 0u,
};
static struct weather_measurement g_measurement;
static bool g_measurement_valid;
static bool g_idle_conn_params_requested;
static bool g_state_notify_enabled;
static bool g_measurement_notify_enabled;
static int64_t g_connected_at_ms;
static bool g_power_on;
static int64_t g_power_on_at_ms;
static int64_t g_next_bme280_init_attempt_ms;
static bool g_battery_ready;

static void sample_battery(void)
{
	if (!g_battery_ready) {
		return;
	}
	g_state.battery_mv = weather_battery_sample_mv();
}

static uint32_t crc32(const uint8_t *data, size_t size)
{
	uint32_t crc = 0xffffffffu;

	for (size_t i = 0; i < size; ++i) {
		crc ^= data[i];
		for (int bit = 0; bit < 8; ++bit) {
			const bool lsb = (crc & 1u) != 0u;

			crc >>= 1u;
			if (lsb) {
				crc ^= 0xedb88320u;
			}
		}
	}

	return crc ^ 0xffffffffu;
}

static bool read_factory_name(char *name, size_t name_size)
{
	const struct weather_factory_data *stored =
		(const struct weather_factory_data *)CONFIG_TXING_WEATHER_FACTORY_DATA_ADDR;
	const uint8_t *bytes = (const uint8_t *)stored;
	const size_t crc_len = sizeof(*stored) - sizeof(stored->crc32);

	if (name_size <= FACTORY_THING_NAME_SIZE) {
		return false;
	}
	if (stored->magic != FACTORY_MAGIC || stored->version != FACTORY_VERSION) {
		return false;
	}
	if (stored->thing_name_len == 0u || stored->thing_name_len > FACTORY_THING_NAME_SIZE) {
		return false;
	}
	if (crc32(bytes, crc_len) != stored->crc32) {
		return false;
	}

	for (uint8_t i = 0; i < stored->thing_name_len; ++i) {
		const char ch = stored->thing_name[i];

		if (ch < '!' || ch > '~') {
			return false;
		}
		name[i] = ch;
	}
	name[stored->thing_name_len] = '\0';
	return true;
}

static void power_set(bool on)
{
	const bool changed = g_power_on != on;

	nrf_gpio_pin_write(XIAO_LED_PIN, on ? XIAO_LED_ACTIVE_STATE : !XIAO_LED_ACTIVE_STATE);
	nrf_gpio_pin_write(XIAO_POWER_PIN,
			   on ? XIAO_POWER_ACTIVE_STATE : !XIAO_POWER_ACTIVE_STATE);

	if (on) {
		if (!g_power_on) {
			g_power_on_at_ms = k_uptime_get();
			g_next_bme280_init_attempt_ms = g_power_on_at_ms + WEATHER_POWER_SETTLE_MS;
		}
	} else {
		g_power_on_at_ms = 0;
		g_next_bme280_init_attempt_ms = 0;
		weather_bme280_reset();
	}
	g_power_on = on;
	if (changed) {
		LOG_INF("Power output enabled=%d pin=D1/P1.05 out=%u in=%u", g_power_on,
			nrf_gpio_pin_out_read(XIAO_POWER_PIN), nrf_gpio_pin_read(XIAO_POWER_PIN));
	}
}

static void power_init(void)
{
	nrf_gpio_pin_write(XIAO_LED_PIN, !XIAO_LED_ACTIVE_STATE);
	nrf_gpio_pin_write(XIAO_POWER_PIN, !XIAO_POWER_ACTIVE_STATE);
#if NRF_GPIO_HAS_SEL
	nrf_gpio_pin_control_select(XIAO_POWER_PIN, NRF_GPIO_PIN_SEL_GPIO);
#endif
	nrf_gpio_cfg_output(XIAO_LED_PIN);
	nrf_gpio_cfg(XIAO_POWER_PIN, NRF_GPIO_PIN_DIR_OUTPUT, NRF_GPIO_PIN_INPUT_CONNECT,
		     NRF_GPIO_PIN_NOPULL, XIAO_POWER_DRIVE, NRF_GPIO_PIN_NOSENSE);
	power_set(false);
}

static uint32_t set_gap_device_name(const char *name)
{
	ble_gap_conn_sec_mode_t write_sec;

	BLE_GAP_CONN_SEC_MODE_SET_NO_ACCESS(&write_sec);
	return sd_ble_gap_device_name_set(&write_sec, name, strlen(name));
}

static uint32_t add_weather_characteristic(uint16_t uuid, bool can_read, bool can_write,
					   bool can_notify, const uint8_t *initial_value,
					   uint16_t initial_len, uint16_t max_len,
					   ble_gatts_char_handles_t *handles)
{
	ble_uuid_t char_uuid = {
		.type = g_weather_uuid_type,
		.uuid = uuid,
	};
	ble_gatts_char_md_t char_md = {0};
	ble_gatts_attr_md_t cccd_md = {0};
	ble_gatts_attr_md_t attr_md = {0};
	ble_gatts_attr_t attr = {0};

	char_md.char_props.read = can_read;
	char_md.char_props.write = can_write;
	char_md.char_props.notify = can_notify;

	if (can_notify) {
		BLE_GAP_CONN_SEC_MODE_SET_OPEN(&cccd_md.read_perm);
		BLE_GAP_CONN_SEC_MODE_SET_OPEN(&cccd_md.write_perm);
		cccd_md.vloc = BLE_GATTS_VLOC_STACK;
		char_md.p_cccd_md = &cccd_md;
	}

	if (can_read) {
		BLE_GAP_CONN_SEC_MODE_SET_OPEN(&attr_md.read_perm);
	} else {
		BLE_GAP_CONN_SEC_MODE_SET_NO_ACCESS(&attr_md.read_perm);
	}
	if (can_write) {
		BLE_GAP_CONN_SEC_MODE_SET_OPEN(&attr_md.write_perm);
	} else {
		BLE_GAP_CONN_SEC_MODE_SET_NO_ACCESS(&attr_md.write_perm);
	}
	attr_md.vloc = BLE_GATTS_VLOC_STACK;

	attr.p_uuid = &char_uuid;
	attr.p_attr_md = &attr_md;
	attr.p_value = (uint8_t *)initial_value;
	attr.init_len = initial_len;
	attr.max_len = max_len;

	return sd_ble_gatts_characteristic_add(g_weather_service_handle, &char_md, &attr,
					       handles);
}

static void encode_current_state(uint8_t payload[WEATHER_STATE_PAYLOAD_SIZE])
{
	weather_encode_state(&g_state, payload);
}

static uint32_t update_gatt_value(uint16_t value_handle, uint8_t *payload, uint16_t len)
{
	ble_gatts_value_t value = {
		.len = len,
		.p_value = payload,
	};

	return sd_ble_gatts_value_set(g_conn_handle, value_handle, &value);
}

static void notify_value(uint16_t value_handle, uint8_t *payload, uint16_t len)
{
	uint32_t nrf_err;
	ble_gatts_hvx_params_t hvx = {
		.handle = value_handle,
		.type = BLE_GATT_HVX_NOTIFICATION,
		.p_len = &len,
		.p_data = payload,
	};

	if (g_conn_handle == BLE_CONN_HANDLE_INVALID) {
		return;
	}

	nrf_err = sd_ble_gatts_hvx(g_conn_handle, &hvx);
	if (nrf_err != NRF_SUCCESS && nrf_err != NRF_ERROR_INVALID_STATE &&
	    nrf_err != NRF_ERROR_RESOURCES && nrf_err != NRF_ERROR_BUSY) {
		LOG_DBG("Failed to notify handle=%u, nrf_error %#x", value_handle, nrf_err);
	}
}

static void publish_state(bool notify)
{
	uint8_t payload[WEATHER_STATE_PAYLOAD_SIZE];
	uint32_t nrf_err;

	encode_current_state(payload);
	nrf_err = update_gatt_value(g_state_handles.value_handle, payload, sizeof(payload));
	if (nrf_err != NRF_SUCCESS) {
		LOG_DBG("Failed to update state value, nrf_error %#x", nrf_err);
	}
	if (notify) {
		notify_value(g_state_handles.value_handle, payload, sizeof(payload));
	}
}

static void publish_measurement(bool notify)
{
	uint8_t payload[WEATHER_MEASUREMENT_PAYLOAD_SIZE];
	uint32_t nrf_err;

	if (!g_measurement_valid) {
		return;
	}

	weather_encode_measurement(&g_measurement, payload);
	nrf_err = update_gatt_value(g_measurement_handles.value_handle, payload, sizeof(payload));
	if (nrf_err != NRF_SUCCESS) {
		LOG_DBG("Failed to update measurement value, nrf_error %#x", nrf_err);
	}
	if (notify) {
		notify_value(g_measurement_handles.value_handle, payload, sizeof(payload));
	}
}

static uint32_t weather_service_init(void)
{
	uint32_t nrf_err;
	ble_uuid128_t base_uuid = {
		.uuid128 = WEATHER_UUID_BASE,
	};
	ble_uuid_t service_uuid;
	uint8_t command_init[WEATHER_COMMAND_PAYLOAD_SIZE] = { WEATHER_PROTOCOL_VERSION,
							       WEATHER_REDCON_IDLE };
	uint8_t state_init[WEATHER_STATE_PAYLOAD_SIZE];
	uint8_t measurement_init[WEATHER_MEASUREMENT_PAYLOAD_SIZE] = {0};

	nrf_err = sd_ble_uuid_vs_add(&base_uuid, &g_weather_uuid_type);
	if (nrf_err != NRF_SUCCESS) {
		return nrf_err;
	}

	service_uuid.type = g_weather_uuid_type;
	service_uuid.uuid = WEATHER_UUID_SERVICE;
	nrf_err = sd_ble_gatts_service_add(BLE_GATTS_SRVC_TYPE_PRIMARY, &service_uuid,
					   &g_weather_service_handle);
	if (nrf_err != NRF_SUCCESS) {
		return nrf_err;
	}

	nrf_err = add_weather_characteristic(WEATHER_UUID_COMMAND, false, true, false,
					     command_init, sizeof(command_init),
					     sizeof(command_init), &g_command_handles);
	if (nrf_err != NRF_SUCCESS) {
		return nrf_err;
	}

	encode_current_state(state_init);
	nrf_err = add_weather_characteristic(WEATHER_UUID_STATE, true, false, true, state_init,
					     sizeof(state_init), sizeof(state_init),
					     &g_state_handles);
	if (nrf_err != NRF_SUCCESS) {
		return nrf_err;
	}

	nrf_err = add_weather_characteristic(WEATHER_UUID_MEASUREMENT, true, false, true,
					     measurement_init, sizeof(measurement_init),
					     sizeof(measurement_init), &g_measurement_handles);
	if (nrf_err != NRF_SUCCESS) {
		return nrf_err;
	}

	return NRF_SUCCESS;
}

static uint32_t start_advertising(void)
{
	uint32_t nrf_err;
	uint16_t adv_len = sizeof(g_adv_data_buf);
	uint16_t scan_rsp_len = sizeof(g_scan_rsp_buf);
	ble_uuid_t service_uuid = {
		.type = g_weather_uuid_type,
		.uuid = WEATHER_UUID_SERVICE,
	};
	struct ble_adv_data adv_data = {
		.name_type = BLE_ADV_DATA_FULL_NAME,
		.flags = BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE,
	};
	struct ble_adv_data scan_rsp = {
		.uuid_lists.complete.uuid = &service_uuid,
		.uuid_lists.complete.len = 1u,
	};

	nrf_err = ble_adv_data_encode(&adv_data, g_adv_data_buf, &adv_len);
	if (nrf_err != NRF_SUCCESS) {
		return nrf_err;
	}
	LOG_HEXDUMP_INF(g_adv_data_buf, adv_len, "Encoded advertising data");

	nrf_err = ble_adv_data_encode(&scan_rsp, g_scan_rsp_buf, &scan_rsp_len);
	if (nrf_err != NRF_SUCCESS) {
		return nrf_err;
	}
	LOG_HEXDUMP_INF(g_scan_rsp_buf, scan_rsp_len, "Encoded scan response data");

	memset(&g_gap_adv_data, 0, sizeof(g_gap_adv_data));
	g_gap_adv_data.adv_data.p_data = g_adv_data_buf;
	g_gap_adv_data.adv_data.len = adv_len;
	g_gap_adv_data.scan_rsp_data.p_data = g_scan_rsp_buf;
	g_gap_adv_data.scan_rsp_data.len = scan_rsp_len;

	memset(&g_adv_params, 0, sizeof(g_adv_params));
	g_adv_params.properties.type = BLE_GAP_ADV_TYPE_CONNECTABLE_SCANNABLE_UNDIRECTED;
	g_adv_params.interval = CONFIG_TXING_WEATHER_ADV_INTERVAL_625US;
	g_adv_params.duration = 0;
	g_adv_params.filter_policy = BLE_GAP_ADV_FP_ANY;
	g_adv_params.scan_req_notification = 1;

	nrf_err = sd_ble_gap_adv_set_configure(&g_adv_handle, &g_gap_adv_data, &g_adv_params);
	if (nrf_err != NRF_SUCCESS) {
		return nrf_err;
	}

	nrf_err = sd_ble_gap_tx_power_set(BLE_GAP_TX_POWER_ROLE_ADV, g_adv_handle,
					  CONFIG_TXING_WEATHER_ADV_TX_POWER_DBM);
	if (nrf_err != NRF_SUCCESS) {
		LOG_WRN("Failed to set advertising TX power %d dBm, nrf_error %#x",
			CONFIG_TXING_WEATHER_ADV_TX_POWER_DBM, nrf_err);
	}

	return sd_ble_gap_adv_start(g_adv_handle, CONFIG_NRF_SDH_BLE_CONN_TAG);
}

static bool request_connected_idle_params(uint16_t conn_handle)
{
	ble_gap_conn_params_t params = {
		.min_conn_interval = WEATHER_IDLE_CONN_INTERVAL_UNITS,
		.max_conn_interval = WEATHER_IDLE_CONN_INTERVAL_UNITS,
		.slave_latency = CONFIG_TXING_WEATHER_IDLE_CONN_LATENCY,
		.conn_sup_timeout = WEATHER_IDLE_CONN_SUPERVISION_UNITS,
	};
	uint32_t nrf_err = sd_ble_gap_conn_param_update(conn_handle, &params);

	if (nrf_err != NRF_SUCCESS) {
		LOG_DBG("Failed to request connection params, nrf_error %#x", nrf_err);
		return false;
	}
	LOG_INF("Requested debug idle params interval=%ums latency=%u supervision=%ums",
		CONFIG_TXING_WEATHER_IDLE_CONN_INTERVAL_MS,
		CONFIG_TXING_WEATHER_IDLE_CONN_LATENCY,
		CONFIG_TXING_WEATHER_IDLE_CONN_SUPERVISION_TIMEOUT_MS);
	return true;
}

static void request_idle_params_if_ready(void)
{
	const int64_t elapsed_ms = k_uptime_get() - g_connected_at_ms;

	if (g_conn_handle == BLE_CONN_HANDLE_INVALID || g_idle_conn_params_requested) {
		return;
	}
	if (CONFIG_TXING_WEATHER_IDLE_CONN_PARAM_INITIAL_DELAY_MS >= 0 &&
	    elapsed_ms >= CONFIG_TXING_WEATHER_IDLE_CONN_PARAM_INITIAL_DELAY_MS) {
		g_idle_conn_params_requested = request_connected_idle_params(g_conn_handle);
		return;
	}
	if (elapsed_ms < CONFIG_TXING_WEATHER_IDLE_CONN_PARAM_FALLBACK_DELAY_MS) {
		return;
	}
	g_idle_conn_params_requested = request_connected_idle_params(g_conn_handle);
}

static void request_idle_params_if_gatt_ready(void)
{
	if (g_conn_handle == BLE_CONN_HANDLE_INVALID || g_idle_conn_params_requested) {
		return;
	}
	if (!g_state_notify_enabled || !g_measurement_notify_enabled) {
		return;
	}
	g_idle_conn_params_requested = request_connected_idle_params(g_conn_handle);
}

static void set_redcon(uint8_t redcon, bool notify)
{
	const bool active = redcon < WEATHER_REDCON_IDLE;

	g_state.redcon = redcon;
	if (!active) {
		g_state.bme280_valid = false;
		g_measurement_valid = false;
	}
	power_set(active);
	publish_state(notify);
	LOG_INF("Weather state redcon=%u active=%d power=%d bme280_valid=%d", g_state.redcon,
		active, g_power_on, g_state.bme280_valid);
}

static void handle_command_write(const ble_gatts_evt_write_t *write)
{
	uint8_t target_redcon;

	if (write->handle != g_command_handles.value_handle) {
		return;
	}
	if (!weather_decode_command(write->data, write->len, &target_redcon)) {
		LOG_WRN("Ignoring invalid weather command len=%u", write->len);
		return;
	}

	LOG_INF("Weather command target redcon=%u", target_redcon);
	set_redcon(target_redcon, true);
}

static bool cccd_notify_enabled(const ble_gatts_evt_write_t *write)
{
	uint16_t cccd_value;

	if (write->len < 2u) {
		return false;
	}
	cccd_value = (uint16_t)write->data[0] | ((uint16_t)write->data[1] << 8u);
	return (cccd_value & BLE_GATT_HVX_NOTIFICATION) != 0u;
}

static void handle_cccd_write(const ble_gatts_evt_write_t *write)
{
	if (write->handle == g_state_handles.cccd_handle) {
		g_state_notify_enabled = cccd_notify_enabled(write);
		LOG_INF("State notifications enabled=%d", g_state_notify_enabled);
		request_idle_params_if_gatt_ready();
	} else if (write->handle == g_measurement_handles.cccd_handle) {
		g_measurement_notify_enabled = cccd_notify_enabled(write);
		LOG_INF("Measurement notifications enabled=%d", g_measurement_notify_enabled);
		request_idle_params_if_gatt_ready();
	}
}

static void handle_ble_evt(const ble_evt_t *evt, void *ctx)
{
	uint32_t nrf_err;

	(void)ctx;

	switch (evt->header.evt_id) {
	case BLE_GAP_EVT_CONNECTED: {
		const ble_gap_conn_params_t *params =
			&evt->evt.gap_evt.params.connected.conn_params;

		g_conn_handle = evt->evt.gap_evt.conn_handle;
		g_connected_at_ms = k_uptime_get();
		g_idle_conn_params_requested = false;
		g_state_notify_enabled = false;
		g_measurement_notify_enabled = false;
			LOG_INF("Peer connected; initial interval=%u..%u latency=%u supervision=%u; requesting connected-idle params after %ums or when GATT is ready",
				params->min_conn_interval, params->max_conn_interval,
				params->slave_latency, params->conn_sup_timeout,
				CONFIG_TXING_WEATHER_IDLE_CONN_PARAM_INITIAL_DELAY_MS);
		nrf_err = sd_ble_gatts_sys_attr_set(g_conn_handle, NULL, 0, 0);
		if (nrf_err != NRF_SUCCESS) {
			LOG_DBG("Failed to set system attributes, nrf_error %#x", nrf_err);
		}
		publish_state(false);
		publish_measurement(false);
		break;
	}

	case BLE_GAP_EVT_DISCONNECTED:
		LOG_INF("Peer disconnected reason=%#x; restarting advertising",
			evt->evt.gap_evt.params.disconnected.reason);
		set_redcon(WEATHER_REDCON_IDLE, false);
		g_conn_handle = BLE_CONN_HANDLE_INVALID;
		g_idle_conn_params_requested = false;
		g_state_notify_enabled = false;
		g_measurement_notify_enabled = false;
		nrf_err = start_advertising();
		if (nrf_err != NRF_SUCCESS) {
			LOG_ERR("Failed to restart advertising, nrf_error %#x", nrf_err);
		}
		break;

	case BLE_GAP_EVT_CONN_PARAM_UPDATE: {
		const ble_gap_conn_params_t *params =
			&evt->evt.gap_evt.params.conn_param_update.conn_params;

		LOG_INF("Connection params updated interval=%u..%u latency=%u supervision=%u",
			params->min_conn_interval, params->max_conn_interval,
			params->slave_latency, params->conn_sup_timeout);
		break;
	}

	case BLE_GAP_EVT_SEC_PARAMS_REQUEST:
		nrf_err = sd_ble_gap_sec_params_reply(evt->evt.gap_evt.conn_handle,
						      BLE_GAP_SEC_STATUS_PAIRING_NOT_SUPP, NULL,
						      NULL);
		if (nrf_err != NRF_SUCCESS) {
			LOG_WRN("Failed to reject pairing request, nrf_error %#x", nrf_err);
		} else {
			LOG_INF("Rejected peer pairing request");
		}
		break;

	case BLE_GAP_EVT_PHY_UPDATE_REQUEST: {
		const ble_gap_phys_t phys = {
			.tx_phys = BLE_GAP_PHY_AUTO,
			.rx_phys = BLE_GAP_PHY_AUTO,
		};

		nrf_err = sd_ble_gap_phy_update(evt->evt.gap_evt.conn_handle, &phys);
		if (nrf_err != NRF_SUCCESS) {
			LOG_WRN("Failed to reply to PHY update request, nrf_error %#x", nrf_err);
		} else {
			LOG_INF("Replied to PHY update request");
		}
		break;
	}

	case BLE_GAP_EVT_PHY_UPDATE:
		LOG_INF("PHY updated status=%#x tx=%u rx=%u",
			evt->evt.gap_evt.params.phy_update.status,
			evt->evt.gap_evt.params.phy_update.tx_phy,
			evt->evt.gap_evt.params.phy_update.rx_phy);
		break;

	case BLE_GAP_EVT_DATA_LENGTH_UPDATE_REQUEST:
		nrf_err = sd_ble_gap_data_length_update(evt->evt.gap_evt.conn_handle, NULL, NULL);
		if (nrf_err != NRF_SUCCESS) {
			LOG_WRN("Failed to reply to data length update request, nrf_error %#x",
				nrf_err);
		} else {
			LOG_INF("Replied to data length update request");
		}
		break;

	case BLE_GAP_EVT_DATA_LENGTH_UPDATE: {
		const ble_gap_data_length_params_t *params =
			&evt->evt.gap_evt.params.data_length_update.effective_params;

		LOG_INF("Data length updated tx_octets=%u rx_octets=%u tx_time_us=%u rx_time_us=%u",
			params->max_tx_octets, params->max_rx_octets, params->max_tx_time_us,
			params->max_rx_time_us);
		break;
	}

	case BLE_GAP_EVT_SCAN_REQ_REPORT: {
		const ble_gap_evt_scan_req_report_t *report =
			&evt->evt.gap_evt.params.scan_req_report;

		LOG_INF("Scan request received rssi=%d peer=%02x:%02x:%02x:%02x:%02x:%02x",
			report->rssi, report->peer_addr.addr[5], report->peer_addr.addr[4],
			report->peer_addr.addr[3], report->peer_addr.addr[2],
			report->peer_addr.addr[1], report->peer_addr.addr[0]);
		break;
	}

	case BLE_GATTS_EVT_WRITE:
		LOG_INF("GATTS write handle=%u len=%u op=%u",
			evt->evt.gatts_evt.params.write.handle,
			evt->evt.gatts_evt.params.write.len,
			evt->evt.gatts_evt.params.write.op);
		handle_cccd_write(&evt->evt.gatts_evt.params.write);
		handle_command_write(&evt->evt.gatts_evt.params.write);
		break;

	case BLE_GATTS_EVT_HVN_TX_COMPLETE:
		LOG_DBG("GATTS HVN TX complete count=%u",
			evt->evt.gatts_evt.params.hvn_tx_complete.count);
		break;

	case BLE_GATTS_EVT_SYS_ATTR_MISSING:
		nrf_err = sd_ble_gatts_sys_attr_set(evt->evt.gatts_evt.conn_handle, NULL, 0, 0);
		if (nrf_err != NRF_SUCCESS) {
			LOG_DBG("Failed to set missing system attributes, nrf_error %#x", nrf_err);
		}
		break;

	case BLE_GATTS_EVT_EXCHANGE_MTU_REQUEST: {
		const uint16_t client_rx_mtu =
			evt->evt.gatts_evt.params.exchange_mtu_request.client_rx_mtu;

		nrf_err = sd_ble_gatts_exchange_mtu_reply(evt->evt.gatts_evt.conn_handle,
							  BLE_GATT_ATT_MTU_DEFAULT);
		if (nrf_err != NRF_SUCCESS) {
			LOG_DBG("Failed to reply to ATT MTU request, nrf_error %#x", nrf_err);
		} else {
			LOG_INF("ATT MTU exchange client_rx=%u server_rx=%u", client_rx_mtu,
				BLE_GATT_ATT_MTU_DEFAULT);
		}
		break;
	}

	case BLE_GATTC_EVT_TIMEOUT:
		(void)sd_ble_gap_disconnect(evt->evt.gattc_evt.conn_handle,
					    BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
		break;

	case BLE_GATTS_EVT_TIMEOUT:
		(void)sd_ble_gap_disconnect(evt->evt.gatts_evt.conn_handle,
					    BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION);
		break;

	case BLE_EVT_USER_MEM_REQUEST:
		nrf_err = sd_ble_user_mem_reply(evt->evt.common_evt.conn_handle, NULL);
		if (nrf_err != NRF_SUCCESS) {
			LOG_WRN("Failed to reply to user memory request, nrf_error %#x", nrf_err);
		}
		break;

	default:
		break;
	}
}
NRF_SDH_BLE_OBSERVER(sdh_ble, handle_ble_evt, NULL, USER_LOW);

static bool ensure_bme280_ready(void)
{
	const int64_t now_ms = k_uptime_get();
	int err;

	if (!g_power_on) {
		return false;
	}
	if (weather_bme280_ready()) {
		return true;
	}
	if (now_ms < g_next_bme280_init_attempt_ms) {
		return false;
	}

	g_next_bme280_init_attempt_ms = now_ms + WEATHER_BME280_INIT_RETRY_MS;
	err = weather_bme280_init();
	if (err != 0) {
		LOG_WRN("BME280 unavailable after power on err=%d", err);
		return false;
	}

	g_next_bme280_init_attempt_ms = 0;
	LOG_INF("BME280 initialized after power on");
	return true;
}

static void sample_weather_if_active(void)
{
	struct weather_bme280_sample sample;
	int err;

	if (g_conn_handle == BLE_CONN_HANDLE_INVALID || g_state.redcon >= WEATHER_REDCON_IDLE) {
		return;
	}
	sample_battery();
	if (!ensure_bme280_ready()) {
		g_state.bme280_valid = false;
		publish_state(true);
		return;
	}

	err = weather_bme280_sample(&sample);
	if (err != 0) {
		g_state.bme280_valid = false;
		LOG_WRN("BME280 sample failed err=%d", err);
		publish_state(true);
		return;
	}

	g_measurement.temperature_centi_c = sample.temperature_centi_c;
	g_measurement.pressure_pa = sample.pressure_pa;
	g_measurement.humidity_centi_percent = sample.humidity_centi_percent;
	g_measurement.battery_mv = g_state.battery_mv;
	g_measurement_valid = true;
	g_state.bme280_valid = true;

	publish_state(true);
	publish_measurement(true);
	LOG_INF("Weather sample temp_centi=%d pressure_pa=%u humidity_centi=%u battery_mv=%u",
		g_measurement.temperature_centi_c, g_measurement.pressure_pa,
		g_measurement.humidity_centi_percent, g_measurement.battery_mv);
}

int main(void)
{
	int err;
	uint32_t nrf_err;
	char local_name[FACTORY_THING_NAME_SIZE + 1];
	bool factory_ok;
	bool softdevice_enabled = false;
	bool ble_enabled = false;
	bool gap_name_set = false;
	bool service_started = false;
	bool advertising_started = false;
	int64_t next_sample_ms;
	int64_t next_diag_ms;
	int64_t next_battery_ms;

	LOG_INF("txing weather BLE debug SoftDevice connected-idle firmware started");
	LOG_INF("Debug BLE params interval=%ums latency=%u supervision=%ums fallback_delay=%ums",
		CONFIG_TXING_WEATHER_IDLE_CONN_INTERVAL_MS,
		CONFIG_TXING_WEATHER_IDLE_CONN_LATENCY,
		CONFIG_TXING_WEATHER_IDLE_CONN_SUPERVISION_TIMEOUT_MS,
		CONFIG_TXING_WEATHER_IDLE_CONN_PARAM_FALLBACK_DELAY_MS);

	factory_ok = read_factory_name(local_name, sizeof(local_name));
	if (!factory_ok) {
		strncpy(local_name, CONFIG_TXING_WEATHER_INVALID_NAME, sizeof(local_name) - 1u);
		local_name[sizeof(local_name) - 1u] = '\0';
		LOG_WRN("Factory data invalid; advertising fallback name %s", local_name);
	} else {
		LOG_INF("Factory thing name %s", local_name);
	}

	power_init();
	LOG_INF("Power output initialized pin=D1/P1.05 active=%u mirrored_to_user_led=1",
		XIAO_POWER_ACTIVE_STATE);
	LOG_INF("BME280 initializes only after power is enabled");
	err = weather_battery_init();
	if (err != 0) {
		LOG_WRN("Battery ADC unavailable err=%d", err);
	} else {
		g_battery_ready = true;
		sample_battery();
		LOG_INF("Battery measurement initialized mv=%u", g_state.battery_mv);
	}

	err = nrf_sdh_enable_request();
	if (err) {
		LOG_ERR("Failed to enable SoftDevice, err %d", err);
		goto idle;
	}
	softdevice_enabled = true;
	LOG_INF("SoftDevice enabled");

	err = nrf_sdh_ble_enable(CONFIG_NRF_SDH_BLE_CONN_TAG);
	if (err) {
		LOG_ERR("Failed to enable BLE, err %d", err);
		goto idle;
	}
	ble_enabled = true;
	LOG_INF("BLE enabled");

	nrf_err = set_gap_device_name(local_name);
	if (nrf_err != NRF_SUCCESS) {
		LOG_ERR("Failed to set GAP device name, nrf_error %#x", nrf_err);
		goto idle;
	}
	gap_name_set = true;
	LOG_INF("GAP device name set");

	nrf_err = weather_service_init();
	if (nrf_err != NRF_SUCCESS) {
		LOG_ERR("Failed to initialize weather GATT service, nrf_error %#x", nrf_err);
		goto idle;
	}
	service_started = true;
	LOG_INF("Weather GATT service initialized");

	nrf_err = start_advertising();
	if (nrf_err != NRF_SUCCESS) {
		LOG_ERR("Failed to start advertising, nrf_error %#x", nrf_err);
		goto idle;
	}
	advertising_started = true;

	LOG_INF("Advertising as %s", local_name);

idle:
	next_sample_ms = k_uptime_get() + WEATHER_SAMPLE_INTERVAL_MS;
	next_diag_ms = k_uptime_get() + WEATHER_DIAG_INTERVAL_MS;
	next_battery_ms = k_uptime_get() + WEATHER_DIAG_INTERVAL_MS;

	while (true) {
		const int64_t now_ms = k_uptime_get();

		if (now_ms >= next_battery_ms) {
			next_battery_ms = now_ms + WEATHER_DIAG_INTERVAL_MS;
			sample_battery();
			if (g_conn_handle != BLE_CONN_HANDLE_INVALID) {
				publish_state(true);
			}
		}
		if (now_ms >= next_sample_ms) {
			next_sample_ms = now_ms + WEATHER_SAMPLE_INTERVAL_MS;
			sample_weather_if_active();
		}
		request_idle_params_if_ready();
		if (now_ms >= next_diag_ms) {
			next_diag_ms = now_ms + WEATHER_DIAG_INTERVAL_MS;
			LOG_INF("diag name=%s factory_ok=%d softdevice=%d ble=%d gap_name=%d service=%d adv=%d conn=%u redcon=%u power=%d bme280=%d battery_mv=%u",
				local_name, factory_ok, softdevice_enabled, ble_enabled, gap_name_set,
				service_started, advertising_started, g_conn_handle, g_state.redcon,
				g_power_on, weather_bme280_ready(), g_state.battery_mv);
		}
		log_flush();
		k_sleep(K_MSEC(100));
	}

	return 0;
}
