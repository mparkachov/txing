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

LOG_MODULE_REGISTER(txing_weather_bm, CONFIG_TXING_WEATHER_BM_LOG_LEVEL);

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

#define WEATHER_SAMPLE_INTERVAL_MS 1000u
#define WEATHER_DIAG_INTERVAL_MS 10000u

#define WEATHER_CONN_INTERVAL_1000_MS 800u
#define WEATHER_CONN_LATENCY 4u
#define WEATHER_CONN_SUPERVISION_12S 1200u

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

static void led_set(bool on)
{
	nrf_gpio_pin_write(XIAO_LED_PIN, on ? XIAO_LED_ACTIVE_STATE : !XIAO_LED_ACTIVE_STATE);
}

static void led_init(void)
{
	nrf_gpio_cfg_output(XIAO_LED_PIN);
	led_set(false);
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

static void request_connected_idle_params(uint16_t conn_handle)
{
	ble_gap_conn_params_t params = {
		.min_conn_interval = WEATHER_CONN_INTERVAL_1000_MS,
		.max_conn_interval = WEATHER_CONN_INTERVAL_1000_MS,
		.slave_latency = WEATHER_CONN_LATENCY,
		.conn_sup_timeout = WEATHER_CONN_SUPERVISION_12S,
	};
	uint32_t nrf_err = sd_ble_gap_conn_param_update(conn_handle, &params);

	if (nrf_err != NRF_SUCCESS) {
		LOG_DBG("Failed to request connection params, nrf_error %#x", nrf_err);
	}
}

static void set_redcon(uint8_t redcon, bool notify)
{
	const bool active = redcon < WEATHER_REDCON_IDLE;

	g_state.redcon = redcon;
	if (!active) {
		g_state.bme280_valid = false;
		g_measurement_valid = false;
	}
	led_set(active);
	publish_state(notify);
	LOG_INF("Weather state redcon=%u active=%d bme280_valid=%d", g_state.redcon, active,
		g_state.bme280_valid);
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

static void handle_ble_evt(const ble_evt_t *evt, void *ctx)
{
	uint32_t nrf_err;

	(void)ctx;

	switch (evt->header.evt_id) {
	case BLE_GAP_EVT_CONNECTED:
		g_conn_handle = evt->evt.gap_evt.conn_handle;
		LOG_INF("Peer connected");
		nrf_err = sd_ble_gatts_sys_attr_set(g_conn_handle, NULL, 0, 0);
		if (nrf_err != NRF_SUCCESS) {
			LOG_DBG("Failed to set system attributes, nrf_error %#x", nrf_err);
		}
		request_connected_idle_params(g_conn_handle);
		publish_state(false);
		publish_measurement(false);
		break;

	case BLE_GAP_EVT_DISCONNECTED:
		LOG_INF("Peer disconnected; restarting advertising");
		set_redcon(WEATHER_REDCON_IDLE, false);
		g_conn_handle = BLE_CONN_HANDLE_INVALID;
		nrf_err = start_advertising();
		if (nrf_err != NRF_SUCCESS) {
			LOG_ERR("Failed to restart advertising, nrf_error %#x", nrf_err);
		}
		break;

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
		handle_command_write(&evt->evt.gatts_evt.params.write);
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

	default:
		break;
	}
}
NRF_SDH_BLE_OBSERVER(sdh_ble, handle_ble_evt, NULL, USER_LOW);

static void sample_weather_if_active(void)
{
	struct weather_bme280_sample sample;
	int err;

	if (g_conn_handle == BLE_CONN_HANDLE_INVALID || g_state.redcon >= WEATHER_REDCON_IDLE) {
		return;
	}
	if (!weather_bme280_ready()) {
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
	LOG_INF("Weather sample temp_centi=%d pressure_pa=%u humidity_centi=%u",
		g_measurement.temperature_centi_c, g_measurement.pressure_pa,
		g_measurement.humidity_centi_percent);
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
	int bme280_err;
	int64_t next_sample_ms;
	int64_t next_diag_ms;

	LOG_INF("txing weather bare-metal connected-idle firmware started");

	factory_ok = read_factory_name(local_name, sizeof(local_name));
	if (!factory_ok) {
		strncpy(local_name, CONFIG_TXING_WEATHER_INVALID_NAME, sizeof(local_name) - 1u);
		local_name[sizeof(local_name) - 1u] = '\0';
		LOG_WRN("Factory data invalid; advertising fallback name %s", local_name);
	} else {
		LOG_INF("Factory thing name %s", local_name);
	}

	led_init();
	LOG_INF("XIAO LED initialized");

	bme280_err = weather_bme280_init();
	if (bme280_err != 0) {
		LOG_WRN("BME280 unavailable err=%d", bme280_err);
	} else {
		LOG_INF("BME280 initialized");
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

	while (true) {
		const int64_t now_ms = k_uptime_get();

		if (now_ms >= next_sample_ms) {
			next_sample_ms = now_ms + WEATHER_SAMPLE_INTERVAL_MS;
			sample_weather_if_active();
		}
		if (now_ms >= next_diag_ms) {
			next_diag_ms = now_ms + WEATHER_DIAG_INTERVAL_MS;
			LOG_INF("diag name=%s factory_ok=%d softdevice=%d ble=%d gap_name=%d service=%d adv=%d conn=%u redcon=%u bme280=%d",
				local_name, factory_ok, softdevice_enabled, ble_enabled, gap_name_set,
				service_started, advertising_started, g_conn_handle, g_state.redcon,
				weather_bme280_ready());
		}
		log_flush();
		k_sleep(K_MSEC(100));
	}

	return 0;
}
