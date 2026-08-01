#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/data/json.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/net/openthread.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/crc.h>
#include <zephyr/sys/util.h>

#include <openthread/coap.h>
#include <openthread/dataset.h>
#include <openthread/error.h>
#include <openthread/ip6.h>
#include <openthread/link.h>
#include <openthread/srp_client.h>
#include <openthread/thread.h>

LOG_MODULE_REGISTER(txing_power_nrf, LOG_LEVEL_INF);

#define TXING_PROTOCOL_VERSION 1
#define TXING_COAP_DEFAULT_PORT 5683
#define TXING_REDCON_ON 3
#define TXING_REDCON_OFF 4
#define TXN1_MAGIC "TXN1"
#define TXN1_VERSION 1
#define TXN1_HEADER_SIZE 10
#define TXN1_THING_NAME_SIZE 64
#define TXN1_DATASET_TLVS_SIZE 254
#define STATE_JSON_SIZE 160
#define REQUEST_JSON_SIZE 96
#define SED_TRANSITION_DELAY_MS 500
#define SED_REDCON_RESPONSE_GRACE_MS 100
#define SED_FALLBACK_GRACE_SECONDS 20
#define SED_RECOVERY_MAX_ATTEMPTS 3

BUILD_ASSERT(IS_ENABLED(CONFIG_OPENTHREAD_MTD_SED),
	     "power-nrf must build as a Thread Sleepy End Device");
BUILD_ASSERT(CONFIG_OPENTHREAD_POLL_PERIOD == 5000,
	     "power-nrf SED poll period must stay at 5000 ms");
BUILD_ASSERT(!(IS_ENABLED(CONFIG_TXING_POWER_NRF_SED_RECOVERY) &&
	       IS_ENABLED(CONFIG_TXING_POWER_NRF_RECEIVER_ON_DIAGNOSTICS)),
	     "SED-only recovery and receiver-on diagnostics are mutually exclusive");

static const struct gpio_dt_spec power_gpio = GPIO_DT_SPEC_GET(DT_ALIAS(power), gpios);
static const struct gpio_dt_spec led_gpio = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
#if DT_NODE_EXISTS(DT_NODELABEL(pmic_charger))
#define BATTERY_NODE DT_NODELABEL(pmic_charger)
static const struct device *const battery_sensor = DEVICE_DT_GET(BATTERY_NODE);
static bool battery_available;
#endif

struct factory_data {
	char thing_name[TXN1_THING_NAME_SIZE + 1];
	uint8_t dataset_tlvs[TXN1_DATASET_TLVS_SIZE];
	uint8_t dataset_tlvs_len;
	uint16_t coap_port;
	bool valid;
};

struct redcon_request {
	int version;
	int redcon;
};

static struct factory_data factory = {
	.thing_name = "power-nrf-unconfigured",
	.coap_port = TXING_COAP_DEFAULT_PORT,
};
static int redcon_level = TXING_REDCON_OFF;
static atomic_t srp_registration_accepted;
static atomic_t sed_mode_active;
static atomic_t receiver_on_when_idle;
static atomic_t recovery_pending;
static atomic_t recovery_attempts;
static atomic_t redcon_sleep_pending;

static const struct json_obj_descr redcon_request_descr[] = {
	JSON_OBJ_DESCR_PRIM(struct redcon_request, version, JSON_TOK_NUMBER),
	JSON_OBJ_DESCR_PRIM(struct redcon_request, redcon, JSON_TOK_NUMBER),
};

static otIp6Address srp_host_address;
static const uint8_t txt_type[] = "power-nrf";
static const uint8_t txt_proto[] = "1";
static const otDnsTxtEntry service_txt[] = {
	{.mKey = "type", .mValue = txt_type, .mValueLength = sizeof(txt_type) - 1},
	{.mKey = "pv", .mValue = txt_proto, .mValueLength = sizeof(txt_proto) - 1},
};
static otSrpClientService srp_service = {
	.mName = "_txing-coap._udp",
	.mInstanceName = factory.thing_name,
	.mTxtEntries = service_txt,
	.mPort = TXING_COAP_DEFAULT_PORT,
	.mPriority = 0,
	.mWeight = 0,
	.mNumTxtEntries = ARRAY_SIZE(service_txt),
};
static otCoapResource state_resource;
static otCoapResource redcon_resource;

static void thread_state_changed(uint32_t flags, void *context);
static void srp_client_callback(otError error, const otSrpClientHostInfo *host_info,
				const otSrpClientService *services,
				const otSrpClientService *removed_services, void *context);
static void srp_autostart_callback(const otSockAddr *server, void *context);
static void sed_transition_work_handler(struct k_work *work);
static void redcon_sleep_work_handler(struct k_work *work);
static void recovery_work_handler(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(sed_transition_work, sed_transition_work_handler);
static K_WORK_DELAYABLE_DEFINE(redcon_sleep_work, redcon_sleep_work_handler);
static K_WORK_DELAYABLE_DEFINE(recovery_work, recovery_work_handler);
static struct openthread_state_changed_callback thread_state_cb = {
	.otCallback = thread_state_changed,
};

static uint16_t u16_le(const uint8_t *value)
{
	return value[0] | ((uint16_t)value[1] << 8);
}

static uint32_t u32_le(const uint8_t *value)
{
	return (uint32_t)value[0] | ((uint32_t)value[1] << 8) |
	       ((uint32_t)value[2] << 16) | ((uint32_t)value[3] << 24);
}

static bool thing_name_is_valid(const uint8_t *name, size_t length)
{
	if (length == 0 || length > TXN1_THING_NAME_SIZE) {
		return false;
	}
	for (size_t index = 0; index < length; ++index) {
		if (name[index] < '!' || name[index] > '~') {
			return false;
		}
	}
	return true;
}

#if DT_NODE_EXISTS(DT_NODELABEL(txing_factory_partition))
static int load_factory_data(void)
{
	const struct flash_area *area;
	uint8_t header[TXN1_HEADER_SIZE];
	uint8_t payload[TXN1_HEADER_SIZE + TXN1_THING_NAME_SIZE + TXN1_DATASET_TLVS_SIZE];
	uint8_t crc_bytes[sizeof(uint32_t)];
	uint8_t name_len;
	uint16_t dataset_len;
	uint16_t port;
	uint32_t expected_crc;
	uint32_t actual_crc;
	size_t payload_len;
	int rc;

	rc = flash_area_open(PARTITION_ID(txing_factory_partition), &area);
	if (rc != 0) {
		LOG_ERR("TXN1 factory partition open failed: %d", rc);
		return rc;
	}
	rc = flash_area_read(area, 0, header, sizeof(header));
	if (rc != 0) {
		LOG_ERR("TXN1 header read failed: %d", rc);
		goto out;
	}
	if (memcmp(header, TXN1_MAGIC, 4) != 0 || header[4] != TXN1_VERSION) {
		rc = -EINVAL;
		goto out;
	}
	name_len = header[5];
	dataset_len = u16_le(&header[6]);
	port = u16_le(&header[8]);
	if (name_len == 0 || name_len > TXN1_THING_NAME_SIZE || dataset_len == 0 ||
	    dataset_len > TXN1_DATASET_TLVS_SIZE || port == 0) {
		rc = -EINVAL;
		goto out;
	}
	payload_len = TXN1_HEADER_SIZE + name_len + dataset_len;
	memcpy(payload, header, sizeof(header));
	rc = flash_area_read(area, TXN1_HEADER_SIZE, payload + TXN1_HEADER_SIZE,
			     name_len + dataset_len);
	if (rc != 0) {
		LOG_ERR("TXN1 payload read failed: %d", rc);
		goto out;
	}
	if (!thing_name_is_valid(payload + TXN1_HEADER_SIZE, name_len)) {
		rc = -EINVAL;
		goto out;
	}
	rc = flash_area_read(area, payload_len, crc_bytes, sizeof(crc_bytes));
	if (rc != 0) {
		LOG_ERR("TXN1 CRC read failed: %d", rc);
		goto out;
	}
	expected_crc = u32_le(crc_bytes);
	actual_crc = crc32_ieee(payload, payload_len);
	if (actual_crc != expected_crc) {
		LOG_ERR("TXN1 CRC mismatch");
		rc = -EINVAL;
		goto out;
	}
	memcpy(factory.thing_name, payload + TXN1_HEADER_SIZE, name_len);
	factory.thing_name[name_len] = '\0';
	memcpy(factory.dataset_tlvs, payload + TXN1_HEADER_SIZE + name_len, dataset_len);
	factory.dataset_tlvs_len = dataset_len;
	factory.coap_port = port;
	factory.valid = true;
	LOG_INF("loaded TXN1 factory data for %s", factory.thing_name);

out:
	flash_area_close(area);
	return rc;
}
#else
static int load_factory_data(void)
{
	LOG_ERR("TXN1 factory partition is not configured");
	return -ENOENT;
}
#endif

static int set_outputs_for_redcon(int level)
{
	bool enabled = (level == TXING_REDCON_ON);
	int rc;

	rc = gpio_pin_set_dt(&power_gpio, enabled ? 1 : 0);
	if (rc != 0) {
		return rc;
	}
	rc = gpio_pin_set_dt(&led_gpio, enabled ? 1 : 0);
	if (rc != 0) {
		(void)gpio_pin_set_dt(&power_gpio, redcon_level == TXING_REDCON_ON ? 1 : 0);
		return rc;
	}
	redcon_level = level;
	return 0;
}

static int init_outputs(void)
{
	int rc;

	if (!gpio_is_ready_dt(&power_gpio) || !gpio_is_ready_dt(&led_gpio)) {
		return -ENODEV;
	}
	rc = gpio_pin_configure_dt(&power_gpio, GPIO_OUTPUT_INACTIVE);
	if (rc != 0) {
		return rc;
	}
	rc = gpio_pin_configure_dt(&led_gpio, GPIO_OUTPUT_INACTIVE);
	if (rc != 0) {
		return rc;
	}
	return set_outputs_for_redcon(TXING_REDCON_OFF);
}

static int init_battery(void)
{
#if DT_NODE_EXISTS(DT_NODELABEL(pmic_charger))
	if (!device_is_ready(battery_sensor)) {
		return -ENODEV;
	}
	battery_available = true;
	return 0;
#else
	return -ENODEV;
#endif
}

static bool sample_battery_mv(uint16_t *battery_mv)
{
#if DT_NODE_EXISTS(DT_NODELABEL(pmic_charger))
	struct sensor_value voltage;
	int64_t millivolts;

	if (!battery_available ||
	    sensor_sample_fetch_chan(battery_sensor, SENSOR_CHAN_GAUGE_VOLTAGE) != 0 ||
	    sensor_channel_get(battery_sensor, SENSOR_CHAN_GAUGE_VOLTAGE, &voltage) != 0) {
		return false;
	}

	/* The nPM1300 charger sensor supplies the battery voltage directly. */
	millivolts = sensor_value_to_milli(&voltage);
	if (millivolts < 0 || millivolts > UINT16_MAX) {
		return false;
	}
	*battery_mv = (uint16_t)millivolts;
	return true;
#else
	ARG_UNUSED(battery_mv);
	return false;
#endif
}

static int format_state(char *buffer, size_t size)
{
	uint16_t battery_mv;

	if (sample_battery_mv(&battery_mv)) {
		return snprintk(buffer, size,
				"{\"version\":%d,\"thingName\":\"%s\",\"redcon\":%d,\"batteryMv\":%u}",
				TXING_PROTOCOL_VERSION, factory.thing_name, redcon_level, battery_mv);
	}
	return snprintk(buffer, size,
			"{\"version\":%d,\"thingName\":\"%s\",\"redcon\":%d,\"batteryMv\":null}",
			TXING_PROTOCOL_VERSION, factory.thing_name, redcon_level);
}

static otCoapType response_type(const otMessage *request)
{
	return otCoapMessageGetType(request) == OT_COAP_TYPE_CONFIRMABLE ?
		       OT_COAP_TYPE_ACKNOWLEDGMENT : OT_COAP_TYPE_NON_CONFIRMABLE;
}

static void send_response(otMessage *request, const otMessageInfo *request_info,
			  otCoapCode code, const char *payload)
{
	otInstance *ot = openthread_get_default_instance();
	otMessage *response;
	otError error;

	if (ot == NULL) {
		return;
	}
	response = otCoapNewMessage(ot, NULL);
	if (response == NULL) {
		LOG_ERR("CoAP response allocation failed");
		return;
	}
	error = otCoapMessageInitResponse(response, request, response_type(request), code);
	if (error != OT_ERROR_NONE) {
		goto fail;
	}
	if (payload != NULL) {
		error = otCoapMessageAppendContentFormatOption(
			response, OT_COAP_OPTION_CONTENT_FORMAT_JSON);
		if (error != OT_ERROR_NONE) {
			goto fail;
		}
		error = otCoapMessageSetPayloadMarker(response);
		if (error != OT_ERROR_NONE) {
			goto fail;
		}
		error = otMessageAppend(response, payload, strlen(payload));
		if (error != OT_ERROR_NONE) {
			goto fail;
		}
	}
	error = otCoapSendResponse(ot, response, request_info);
	if (error == OT_ERROR_NONE) {
		return;
	}
fail:
	LOG_ERR("CoAP response send failed: %d", error);
	otMessageFree(response);
}

static void send_state_response(otMessage *request, const otMessageInfo *request_info,
				otCoapCode code)
{
	char json[STATE_JSON_SIZE];
	int length = format_state(json, sizeof(json));

	if (length < 0 || length >= sizeof(json)) {
		send_response(request, request_info, OT_COAP_CODE_INTERNAL_ERROR, NULL);
		return;
	}
	send_response(request, request_info, code, json);
}

static bool parse_redcon_request(otMessage *message, struct redcon_request *request)
{
	char json[REQUEST_JSON_SIZE];
	uint16_t offset = otMessageGetOffset(message);
	uint16_t length = otMessageGetLength(message) - offset;
	int result;

	if (length == 0 || length >= sizeof(json) ||
	    otMessageRead(message, offset, json, length) != length) {
		return false;
	}
	json[length] = '\0';
	result = json_obj_parse(json, length, redcon_request_descr,
				ARRAY_SIZE(redcon_request_descr), request);
	return result == (BIT(0) | BIT(1));
}

static int configure_thread_mode_locked(otInstance *ot, bool receiver_on)
{
	otLinkModeConfig link_mode = otThreadGetLinkMode(ot);
	otError error;

	link_mode.mRxOnWhenIdle = receiver_on;
	link_mode.mDeviceType = false;
	link_mode.mNetworkData = true;
	error = otThreadSetLinkMode(ot, link_mode);
	if (error != OT_ERROR_NONE) {
		LOG_ERR("Thread link mode failed: %d", error);
		return -EIO;
	}
	error = otLinkSetPollPeriod(ot, CONFIG_OPENTHREAD_POLL_PERIOD);
	if (error != OT_ERROR_NONE) {
		LOG_ERR("Thread poll period failed: %d", error);
		return -EIO;
	}
	atomic_set(&receiver_on_when_idle, receiver_on ? 1 : 0);
	return 0;
}

static int restart_thread_mode_locked(otInstance *ot, bool receiver_on)
{
	otError error = otThreadSetEnabled(ot, false);
	int rc;

	if (error != OT_ERROR_NONE && error != OT_ERROR_INVALID_STATE) {
		return -EIO;
	}
	rc = configure_thread_mode_locked(ot, receiver_on);
	if (rc != 0) {
		return rc;
	}
	error = otThreadSetEnabled(ot, true);
	return error == OT_ERROR_NONE ? 0 : -EIO;
}

static void redcon_handler(void *context, otMessage *message, const otMessageInfo *message_info)
{
	struct redcon_request request = {0};
	int previous_redcon;
	otInstance *ot;

	ARG_UNUSED(context);
	if (otCoapMessageGetCode(message) != OT_COAP_CODE_PUT) {
		send_response(message, message_info, OT_COAP_CODE_METHOD_NOT_ALLOWED, NULL);
		return;
	}
	if (!parse_redcon_request(message, &request) || request.version != TXING_PROTOCOL_VERSION ||
	    (request.redcon != TXING_REDCON_ON && request.redcon != TXING_REDCON_OFF)) {
		send_response(message, message_info, OT_COAP_CODE_BAD_REQUEST, NULL);
		return;
	}
	previous_redcon = redcon_level;
	if (set_outputs_for_redcon(request.redcon) != 0) {
		send_response(message, message_info, OT_COAP_CODE_INTERNAL_ERROR, NULL);
		return;
	}
	if (request.redcon == TXING_REDCON_ON) {
		(void)k_work_cancel_delayable(&sed_transition_work);
		atomic_set(&redcon_sleep_pending, 0);
		(void)k_work_cancel_delayable(&redcon_sleep_work);
		ot = openthread_get_default_instance();
		if (ot == NULL || configure_thread_mode_locked(ot, true) != 0) {
			LOG_ERR("REDCON 3 receiver-on Thread transition failed");
			(void)set_outputs_for_redcon(previous_redcon);
			send_response(message, message_info, OT_COAP_CODE_INTERNAL_ERROR, NULL);
			return;
		}
		LOG_INF("REDCON 3 enabled D1 and led0; Thread mode rn");
		send_state_response(message, message_info, OT_COAP_CODE_CHANGED);
		return;
	}

	/* The response must leave while the parent link remains receiver-on. */
	atomic_set(&redcon_sleep_pending, 1);
	send_state_response(message, message_info, OT_COAP_CODE_CHANGED);
	(void)k_work_schedule(&redcon_sleep_work, K_MSEC(SED_REDCON_RESPONSE_GRACE_MS));
}

static void state_handler(void *context, otMessage *message, const otMessageInfo *message_info)
{
	ARG_UNUSED(context);
	if (otCoapMessageGetCode(message) != OT_COAP_CODE_GET) {
		send_response(message, message_info, OT_COAP_CODE_METHOD_NOT_ALLOWED, NULL);
		return;
	}
	send_state_response(message, message_info, OT_COAP_CODE_CONTENT);
}

static int start_coap(otInstance *ot)
{
	otError error;

	state_resource.mUriPath = "txing/v1/state";
	state_resource.mHandler = state_handler;
	redcon_resource.mUriPath = "txing/v1/redcon";
	redcon_resource.mHandler = redcon_handler;
	openthread_mutex_lock();
	error = otCoapStart(ot, factory.coap_port);
	if (error == OT_ERROR_NONE) {
		otCoapAddResource(ot, &state_resource);
		otCoapAddResource(ot, &redcon_resource);
	}
	openthread_mutex_unlock();
	if (error != OT_ERROR_NONE) {
		LOG_ERR("CoAP start failed: %d", error);
		return -EIO;
	}
	return 0;
}

static otError set_srp_host_address(otInstance *ot)
{
	const otIp6Address *mesh_local_eid = otThreadGetMeshLocalEid(ot);

	if (mesh_local_eid == NULL) {
		return OT_ERROR_INVALID_STATE;
	}
	memcpy(&srp_host_address, mesh_local_eid, sizeof(srp_host_address));
	return otSrpClientSetHostAddresses(ot, &srp_host_address, 1);
}

static int start_srp(otInstance *ot)
{
	otError error;

	srp_service.mInstanceName = factory.thing_name;
	srp_service.mPort = factory.coap_port;
	openthread_mutex_lock();
	otSrpClientSetCallback(ot, srp_client_callback, ot);
	error = otSrpClientSetHostName(ot, factory.thing_name);
	if (error == OT_ERROR_NONE) {
		error = set_srp_host_address(ot);
	}
	if (error == OT_ERROR_NONE) {
		error = otSrpClientAddService(ot, &srp_service);
	}
	if (error == OT_ERROR_NONE || error == OT_ERROR_ALREADY) {
		otSrpClientEnableAutoStartMode(ot, srp_autostart_callback, ot);
	}
	openthread_mutex_unlock();
	if (error != OT_ERROR_NONE && error != OT_ERROR_ALREADY) {
		LOG_ERR("SRP service start failed: %d", error);
		return -EIO;
	}
	return 0;
}

static void srp_autostart_callback(const otSockAddr *server, void *context)
{
	ARG_UNUSED(context);
	if (server == NULL) {
		LOG_WRN("SRP auto-start has no server");
	}
}

static void srp_client_callback(otError error, const otSrpClientHostInfo *host_info,
				const otSrpClientService *services,
				const otSrpClientService *removed_services, void *context)
{
	ARG_UNUSED(host_info);
	ARG_UNUSED(services);
	ARG_UNUSED(removed_services);
	ARG_UNUSED(context);
	if (error != OT_ERROR_NONE) {
		LOG_WRN("SRP registration failed: %d", error);
		return;
	}
	atomic_set(&srp_registration_accepted, 1);
	if (redcon_level == TXING_REDCON_OFF && atomic_get(&sed_mode_active) == 0) {
		(void)k_work_schedule(&sed_transition_work, K_MSEC(SED_TRANSITION_DELAY_MS));
	}
}

static void sed_transition_work_handler(struct k_work *work)
{
	otInstance *ot;
	otDeviceRole role;
	int rc;

	ARG_UNUSED(work);
	if (atomic_get(&srp_registration_accepted) == 0 || redcon_level != TXING_REDCON_OFF ||
	    atomic_get(&sed_mode_active) != 0) {
		return;
	}
	ot = openthread_get_default_instance();
	if (ot == NULL) {
		(void)k_work_schedule(&sed_transition_work, K_SECONDS(1));
		return;
	}
	openthread_mutex_lock();
	role = otThreadGetDeviceRole(ot);
	rc = role == OT_DEVICE_ROLE_CHILD ? configure_thread_mode_locked(ot, false) : -EAGAIN;
	openthread_mutex_unlock();
	if (rc != 0) {
		(void)k_work_schedule(&sed_transition_work, K_SECONDS(1));
		return;
	}
	atomic_set(&sed_mode_active, 1);
	atomic_set(&recovery_attempts, 0);
	(void)k_work_schedule(&recovery_work, K_SECONDS(SED_FALLBACK_GRACE_SECONDS));
	LOG_INF("SRP accepted; Thread mode n with poll period %u ms", CONFIG_OPENTHREAD_POLL_PERIOD);
}

static void redcon_sleep_work_handler(struct k_work *work)
{
	otInstance *ot;
	int rc;

	ARG_UNUSED(work);
	if (!atomic_cas(&redcon_sleep_pending, 1, 0)) {
		return;
	}
	ot = openthread_get_default_instance();
	if (ot == NULL) {
		LOG_ERR("REDCON 4 SED transition failed: OpenThread unavailable");
		return;
	}
	openthread_mutex_lock();
	rc = configure_thread_mode_locked(ot, false);
	openthread_mutex_unlock();
	if (rc == 0) {
		atomic_set(&sed_mode_active, 1);
		atomic_set(&recovery_attempts, 0);
		(void)k_work_schedule(&recovery_work, K_SECONDS(SED_FALLBACK_GRACE_SECONDS));
		LOG_INF("REDCON 4 disabled D1 and led0; Thread mode n");
	}
}

static void schedule_recovery(void)
{
	if (atomic_get(&sed_mode_active) == 0 || atomic_get(&recovery_pending) != 0) {
		return;
	}
#if IS_ENABLED(CONFIG_TXING_POWER_NRF_SED_RECOVERY)
	if (atomic_get(&receiver_on_when_idle) != 0 ||
	    atomic_get(&recovery_attempts) >= SED_RECOVERY_MAX_ATTEMPTS) {
		return;
	}
#endif
	atomic_set(&recovery_pending, 1);
	(void)k_work_schedule(&recovery_work, K_SECONDS(SED_FALLBACK_GRACE_SECONDS));
}

static void recovery_work_handler(struct k_work *work)
{
	otInstance *ot;
	otDeviceRole role;
	otLinkModeConfig link_mode;
	bool expected_receiver_on;
	int rc;

	ARG_UNUSED(work);
	atomic_set(&recovery_pending, 0);
	if (atomic_get(&sed_mode_active) == 0) {
		return;
	}
	ot = openthread_get_default_instance();
	if (ot == NULL) {
		schedule_recovery();
		return;
	}
	openthread_mutex_lock();
	role = otThreadGetDeviceRole(ot);
	link_mode = otThreadGetLinkMode(ot);
	expected_receiver_on = atomic_get(&receiver_on_when_idle) != 0;
	if (role == OT_DEVICE_ROLE_CHILD && link_mode.mRxOnWhenIdle == expected_receiver_on) {
		openthread_mutex_unlock();
		atomic_set(&recovery_attempts, 0);
		return;
	}

#if IS_ENABLED(CONFIG_TXING_POWER_NRF_SED_RECOVERY)
	if (expected_receiver_on || atomic_get(&recovery_attempts) >= SED_RECOVERY_MAX_ATTEMPTS) {
		openthread_mutex_unlock();
		return;
	}
	atomic_inc(&recovery_attempts);
	rc = restart_thread_mode_locked(ot, false);
#elif IS_ENABLED(CONFIG_TXING_POWER_NRF_RECEIVER_ON_DIAGNOSTICS)
	rc = restart_thread_mode_locked(ot, true);
#else
	rc = -EOPNOTSUPP;
#endif
	openthread_mutex_unlock();
	if (rc != 0) {
		schedule_recovery();
	}
}

static int start_thread(otInstance *ot)
{
	otOperationalDatasetTlvs dataset = {0};
	otError error;

	if (!factory.valid) {
		LOG_ERR("valid TXN1 factory data is required before Thread startup");
		return -EINVAL;
	}
	memcpy(dataset.mTlvs, factory.dataset_tlvs, factory.dataset_tlvs_len);
	dataset.mLength = factory.dataset_tlvs_len;
	openthread_mutex_lock();
	error = otDatasetSetActiveTlvs(ot, &dataset);
	if (error == OT_ERROR_NONE) {
		error = configure_thread_mode_locked(ot, true) == 0 ? OT_ERROR_NONE : OT_ERROR_FAILED;
	}
	if (error == OT_ERROR_NONE) {
		error = otIp6SetEnabled(ot, true);
	}
	if (error == OT_ERROR_NONE) {
		error = otThreadSetEnabled(ot, true);
	}
	openthread_mutex_unlock();
	if (error != OT_ERROR_NONE) {
		LOG_ERR("Thread bootstrap start failed: %d", error);
		return -EIO;
	}
	atomic_set(&srp_registration_accepted, 0);
	atomic_set(&sed_mode_active, 0);
	atomic_set(&recovery_attempts, 0);
	return 0;
}

static void thread_state_changed(uint32_t flags, void *context)
{
	ARG_UNUSED(flags);
	ARG_UNUSED(context);
	if (atomic_get(&sed_mode_active) != 0) {
		schedule_recovery();
	}
}

static void register_thread_state_callback(otInstance *ot)
{
	thread_state_cb.user_data = ot;
	if (openthread_state_changed_callback_register(&thread_state_cb) != 0) {
		LOG_WRN("Thread state callback registration failed");
	}
}

int main(void)
{
	otInstance *ot;
	int rc;

	rc = init_outputs();
	if (rc != 0) {
		LOG_ERR("D1 and led0 initialization failed: %d", rc);
		return rc;
	}
	rc = load_factory_data();
	if (rc != 0) {
		LOG_ERR("TXN1 factory data load failed: %d", rc);
		return rc;
	}
	rc = init_battery();
	if (rc != 0) {
		LOG_WRN("nPM1300 battery measurement unavailable: %d", rc);
	}
	ot = openthread_get_default_instance();
	if (ot == NULL) {
		return -ENODEV;
	}
	register_thread_state_callback(ot);
	if (start_thread(ot) != 0 || start_coap(ot) != 0 || start_srp(ot) != 0) {
		return -EIO;
	}
	while (true) {
		k_sleep(K_SECONDS(60));
	}
	return 0;
}
