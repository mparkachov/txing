#include <ble.h>
#include <ble_gap.h>
#include <bm/bluetooth/ble_adv_data.h>
#include <bm/softdevice_handler/nrf_sdh.h>
#include <bm/softdevice_handler/nrf_sdh_ble.h>
#include <nrf_error.h>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/logging/log_ctrl.h>

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

LOG_MODULE_REGISTER(txing_weather_bm_adv, CONFIG_TXING_WEATHER_BM_ADV_LOG_LEVEL);

#define FACTORY_MAGIC 0x31575854u
#define FACTORY_VERSION 1u
#define FACTORY_THING_NAME_SIZE 26u
#define ADV_DATA_SIZE BLE_GAP_ADV_SET_DATA_SIZE_MAX

struct weather_factory_data {
	uint32_t magic;
	uint8_t version;
	uint8_t thing_name_len;
	char thing_name[FACTORY_THING_NAME_SIZE];
	uint32_t crc32;
};

_Static_assert(sizeof(struct weather_factory_data) == 36, "factory data layout changed");

static uint8_t adv_handle = BLE_GAP_ADV_SET_HANDLE_NOT_SET;
static uint8_t adv_data_buf[ADV_DATA_SIZE];
static uint8_t scan_rsp_buf[ADV_DATA_SIZE];
static ble_gap_adv_data_t gap_adv_data;
static ble_gap_adv_params_t adv_params;

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

static uint32_t set_gap_device_name(const char *name)
{
	ble_gap_conn_sec_mode_t write_sec;

	BLE_GAP_CONN_SEC_MODE_SET_NO_ACCESS(&write_sec);
	return sd_ble_gap_device_name_set(&write_sec, name, strlen(name));
}

static uint32_t start_advertising(void)
{
	uint32_t nrf_err;
	uint16_t adv_len = sizeof(adv_data_buf);
	uint16_t scan_rsp_len = sizeof(scan_rsp_buf);
	struct ble_adv_data adv_data = {
		.name_type = BLE_ADV_DATA_FULL_NAME,
		.flags = BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE,
	};
	struct ble_adv_data scan_rsp = {0};

	nrf_err = ble_adv_data_encode(&adv_data, adv_data_buf, &adv_len);
	if (nrf_err != NRF_SUCCESS) {
		return nrf_err;
	}
	LOG_HEXDUMP_INF(adv_data_buf, adv_len, "Encoded advertising data");

	nrf_err = ble_adv_data_encode(&scan_rsp, scan_rsp_buf, &scan_rsp_len);
	if (nrf_err != NRF_SUCCESS) {
		return nrf_err;
	}
	LOG_HEXDUMP_INF(scan_rsp_buf, scan_rsp_len, "Encoded scan response data");

	memset(&gap_adv_data, 0, sizeof(gap_adv_data));
	gap_adv_data.adv_data.p_data = adv_data_buf;
	gap_adv_data.adv_data.len = adv_len;
	gap_adv_data.scan_rsp_data.p_data = scan_rsp_buf;
	gap_adv_data.scan_rsp_data.len = scan_rsp_len;

	memset(&adv_params, 0, sizeof(adv_params));
	adv_params.properties.type = BLE_GAP_ADV_TYPE_CONNECTABLE_SCANNABLE_UNDIRECTED;
	adv_params.interval = CONFIG_TXING_WEATHER_ADV_INTERVAL_625US;
	adv_params.duration = 0;
	adv_params.filter_policy = BLE_GAP_ADV_FP_ANY;
	adv_params.scan_req_notification = 1;

	nrf_err = sd_ble_gap_adv_set_configure(&adv_handle, &gap_adv_data, &adv_params);
	if (nrf_err != NRF_SUCCESS) {
		return nrf_err;
	}

	nrf_err = sd_ble_gap_tx_power_set(BLE_GAP_TX_POWER_ROLE_ADV, adv_handle,
					  CONFIG_TXING_WEATHER_ADV_TX_POWER_DBM);
	if (nrf_err != NRF_SUCCESS) {
		LOG_WRN("Failed to set advertising TX power %d dBm, nrf_error %#x",
			CONFIG_TXING_WEATHER_ADV_TX_POWER_DBM, nrf_err);
	}

	return sd_ble_gap_adv_start(adv_handle, CONFIG_NRF_SDH_BLE_CONN_TAG);
}

static void on_ble_evt(const ble_evt_t *evt, void *ctx)
{
	(void)ctx;

	switch (evt->header.evt_id) {
	case BLE_GAP_EVT_CONNECTED:
		LOG_INF("Peer connected");
		break;
	case BLE_GAP_EVT_DISCONNECTED: {
		LOG_INF("Peer disconnected; restarting advertising");
		uint32_t nrf_err = start_advertising();
		if (nrf_err != NRF_SUCCESS) {
			LOG_ERR("Failed to restart advertising, nrf_error %#x", nrf_err);
		}
		break;
	}
	case BLE_GAP_EVT_SCAN_REQ_REPORT: {
		const ble_gap_evt_scan_req_report_t *report = &evt->evt.gap_evt.params.scan_req_report;

		LOG_INF("Scan request received rssi=%d peer=%02x:%02x:%02x:%02x:%02x:%02x",
			report->rssi, report->peer_addr.addr[5], report->peer_addr.addr[4],
			report->peer_addr.addr[3], report->peer_addr.addr[2],
			report->peer_addr.addr[1], report->peer_addr.addr[0]);
		break;
	}
	default:
		break;
	}
}
NRF_SDH_BLE_OBSERVER(sdh_ble, on_ble_evt, NULL, USER_LOW);

int main(void)
{
	int err;
	uint32_t nrf_err;
	char local_name[FACTORY_THING_NAME_SIZE + 1];
	bool factory_ok;
	bool softdevice_enabled = false;
	bool ble_enabled = false;
	bool gap_name_set = false;
	bool advertising_started = false;

	LOG_INF("txing weather bare-metal advertising-only firmware started");

	factory_ok = read_factory_name(local_name, sizeof(local_name));
	if (!factory_ok) {
		strncpy(local_name, CONFIG_TXING_WEATHER_INVALID_NAME, sizeof(local_name) - 1u);
		local_name[sizeof(local_name) - 1u] = '\0';
		LOG_WRN("Factory data invalid; advertising fallback name %s", local_name);
	} else {
		LOG_INF("Factory thing name %s", local_name);
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

	nrf_err = start_advertising();
	if (nrf_err != NRF_SUCCESS) {
		LOG_ERR("Failed to start advertising, nrf_error %#x", nrf_err);
		goto idle;
	}
	advertising_started = true;

	LOG_INF("Advertising as %s", local_name);

idle:
	while (true) {
		LOG_INF("diag name=%s factory_ok=%d softdevice=%d ble=%d gap_name=%d adv=%d handle=%u",
			local_name, factory_ok, softdevice_enabled, ble_enabled, gap_name_set,
			advertising_started, adv_handle);
		log_flush();
		k_sleep(K_SECONDS(2));
	}

	return 0;
}
