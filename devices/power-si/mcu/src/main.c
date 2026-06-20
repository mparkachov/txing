#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/data/json.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/net/openthread.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/sys/crc.h>
#include <zephyr/sys/util.h>

#include <openthread/coap.h>
#include <openthread/dataset.h>
#include <openthread/ip6.h>
#include <openthread/srp_client.h>
#include <openthread/thread.h>

LOG_MODULE_REGISTER(txing_power_si, LOG_LEVEL_INF);

#define TXING_PROTOCOL_VERSION 1
#define TXING_COAP_DEFAULT_PORT 5683
#define TXING_REDCON_ON 3
#define TXING_REDCON_OFF 4
#define TXT1_MAGIC "TXT1"
#define TXT1_VERSION 1
#define TXT1_HEADER_SIZE 10
#define TXT1_THING_NAME_SIZE 64
#define TXT1_DATASET_TLVS_SIZE 254
#define STATE_JSON_SIZE 160
#define REQUEST_JSON_SIZE 96

static const struct gpio_dt_spec power_gpio = GPIO_DT_SPEC_GET(DT_ALIAS(power), gpios);
static const struct gpio_dt_spec led_gpio = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);

struct factory_data {
	char thing_name[TXT1_THING_NAME_SIZE + 1];
	uint8_t dataset_tlvs[TXT1_DATASET_TLVS_SIZE];
	uint8_t dataset_tlvs_len;
	uint16_t coap_port;
	bool valid;
};

struct redcon_request {
	int version;
	int redcon;
};

static struct factory_data factory = {
	.thing_name = "power-si-unconfigured",
	.coap_port = TXING_COAP_DEFAULT_PORT,
};
static int redcon_level = TXING_REDCON_OFF;

static const struct json_obj_descr redcon_request_descr[] = {
	JSON_OBJ_DESCR_PRIM(struct redcon_request, version, JSON_TOK_NUMBER),
	JSON_OBJ_DESCR_PRIM(struct redcon_request, redcon, JSON_TOK_NUMBER),
};

static const uint8_t txt_type[] = "power-si";
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

static uint16_t u16_le(const uint8_t *value)
{
	return value[0] | ((uint16_t)value[1] << 8);
}

static int load_factory_data(void)
{
	const struct flash_area *area;
	uint8_t header[TXT1_HEADER_SIZE];
	uint8_t payload[TXT1_HEADER_SIZE + TXT1_THING_NAME_SIZE + TXT1_DATASET_TLVS_SIZE];
	uint8_t name_len;
	uint16_t dataset_len;
	uint16_t port;
	uint32_t expected_crc;
	uint32_t actual_crc;
	size_t payload_len;
	int rc;

	rc = flash_area_open(PARTITION_ID(txing_factory_partition), &area);
	if (rc != 0) {
		LOG_ERR("TXT1 factory partition open failed: %d", rc);
		return rc;
	}

	rc = flash_area_read(area, 0, header, sizeof(header));
	if (rc != 0) {
		LOG_ERR("TXT1 header read failed: %d", rc);
		goto out;
	}
	if (memcmp(header, TXT1_MAGIC, 4) != 0 || header[4] != TXT1_VERSION) {
		rc = -EINVAL;
		goto out;
	}

	name_len = header[5];
	dataset_len = u16_le(&header[6]);
	port = u16_le(&header[8]);
	if (name_len == 0 || name_len > TXT1_THING_NAME_SIZE ||
	    dataset_len == 0 || dataset_len > TXT1_DATASET_TLVS_SIZE ||
	    port == 0) {
		rc = -EINVAL;
		goto out;
	}

	payload_len = TXT1_HEADER_SIZE + name_len + dataset_len;
	memcpy(payload, header, sizeof(header));
	rc = flash_area_read(area, TXT1_HEADER_SIZE, payload + TXT1_HEADER_SIZE,
			     name_len + dataset_len);
	if (rc != 0) {
		LOG_ERR("TXT1 payload read failed: %d", rc);
		goto out;
	}
	rc = flash_area_read(area, payload_len, &expected_crc, sizeof(expected_crc));
	if (rc != 0) {
		LOG_ERR("TXT1 CRC read failed: %d", rc);
		goto out;
	}
	actual_crc = crc32_ieee(payload, payload_len);
	if (actual_crc != expected_crc) {
		LOG_ERR("TXT1 CRC mismatch");
		rc = -EINVAL;
		goto out;
	}

	memcpy(factory.thing_name, payload + TXT1_HEADER_SIZE, name_len);
	factory.thing_name[name_len] = '\0';
	memcpy(factory.dataset_tlvs, payload + TXT1_HEADER_SIZE + name_len, dataset_len);
	factory.dataset_tlvs_len = dataset_len;
	factory.coap_port = port;
	factory.valid = true;
	LOG_INF("loaded TXT1 factory data for %s", factory.thing_name);

out:
	flash_area_close(area);
	return rc;
}

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

static int format_state(char *buffer, size_t size)
{
	return snprintk(buffer, size,
			"{\"version\":%d,\"thingName\":\"%s\",\"redcon\":%d,\"batteryMv\":null}",
			TXING_PROTOCOL_VERSION, factory.thing_name, redcon_level);
}

static otCoapType response_type(const otMessage *request)
{
	return otCoapMessageGetType(request) == OT_COAP_TYPE_CONFIRMABLE ?
		       OT_COAP_TYPE_ACKNOWLEDGMENT :
		       OT_COAP_TYPE_NON_CONFIRMABLE;
}

static void send_response(otMessage *request, const otMessageInfo *request_info,
			  otCoapCode code, const char *payload)
{
	otInstance *ot = openthread_get_default_instance();
	otMessage *response;
	otError error;

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
	int len = format_state(json, sizeof(json));

	if (len < 0 || len >= sizeof(json)) {
		send_response(request, request_info, OT_COAP_CODE_INTERNAL_ERROR, NULL);
		return;
	}
	send_response(request, request_info, code, json);
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

static bool parse_redcon_request(otMessage *message, struct redcon_request *request)
{
	char json[REQUEST_JSON_SIZE];
	uint16_t offset = otMessageGetOffset(message);
	uint16_t len = otMessageGetLength(message) - offset;
	int ret;

	if (len == 0 || len >= sizeof(json)) {
		return false;
	}
	if (otMessageRead(message, offset, json, len) != len) {
		return false;
	}
	json[len] = '\0';
	ret = json_obj_parse(json, len, redcon_request_descr, ARRAY_SIZE(redcon_request_descr), request);
	return ret == (BIT(0) | BIT(1));
}

static void redcon_handler(void *context, otMessage *message, const otMessageInfo *message_info)
{
	struct redcon_request request = {0};

	ARG_UNUSED(context);

	if (otCoapMessageGetCode(message) != OT_COAP_CODE_PUT) {
		send_response(message, message_info, OT_COAP_CODE_METHOD_NOT_ALLOWED, NULL);
		return;
	}
	if (!parse_redcon_request(message, &request) ||
	    request.version != TXING_PROTOCOL_VERSION ||
	    (request.redcon != TXING_REDCON_ON && request.redcon != TXING_REDCON_OFF)) {
		send_response(message, message_info, OT_COAP_CODE_BAD_REQUEST, NULL);
		return;
	}
	if (set_outputs_for_redcon(request.redcon) != 0) {
		send_response(message, message_info, OT_COAP_CODE_INTERNAL_ERROR, NULL);
		return;
	}
	send_state_response(message, message_info, OT_COAP_CODE_CHANGED);
}

static int start_coap(otInstance *ot)
{
	otError error;

	state_resource.mUriPath = "txing/v1/state";
	state_resource.mHandler = state_handler;
	redcon_resource.mUriPath = "txing/v1/redcon";
	redcon_resource.mHandler = redcon_handler;

	error = otCoapStart(ot, factory.coap_port);
	if (error != OT_ERROR_NONE) {
		LOG_ERR("CoAP start failed: %d", error);
		return -EIO;
	}
	otCoapAddResource(ot, &state_resource);
	otCoapAddResource(ot, &redcon_resource);
	return 0;
}

static int start_srp(otInstance *ot)
{
	otError error;

	srp_service.mInstanceName = factory.thing_name;
	srp_service.mPort = factory.coap_port;

	error = otSrpClientSetHostName(ot, factory.thing_name);
	if (error != OT_ERROR_NONE) {
		LOG_ERR("SRP host name failed: %d", error);
		return -EIO;
	}
	error = otSrpClientEnableAutoHostAddress(ot);
	if (error != OT_ERROR_NONE) {
		LOG_ERR("SRP auto address failed: %d", error);
		return -EIO;
	}
	error = otSrpClientAddService(ot, &srp_service);
	if (error != OT_ERROR_NONE && error != OT_ERROR_ALREADY) {
		LOG_ERR("SRP service add failed: %d", error);
		return -EIO;
	}
	otSrpClientEnableAutoStartMode(ot, NULL, NULL);
	return 0;
}

static int start_thread(otInstance *ot)
{
	otOperationalDatasetTlvs dataset = {0};
	otError error;

	if (!factory.valid) {
		LOG_ERR("missing valid TXT1 factory data; Thread not started");
		return -EINVAL;
	}
	memcpy(dataset.mTlvs, factory.dataset_tlvs, factory.dataset_tlvs_len);
	dataset.mLength = factory.dataset_tlvs_len;
	error = otDatasetSetActiveTlvs(ot, &dataset);
	if (error != OT_ERROR_NONE) {
		LOG_ERR("Thread dataset set failed: %d", error);
		return -EIO;
	}
	error = otIp6SetEnabled(ot, true);
	if (error != OT_ERROR_NONE) {
		LOG_ERR("Thread IPv6 enable failed: %d", error);
		return -EIO;
	}
	error = otThreadSetEnabled(ot, true);
	if (error != OT_ERROR_NONE) {
		LOG_ERR("Thread enable failed: %d", error);
		return -EIO;
	}
	return 0;
}

int main(void)
{
	otInstance *ot;
	int rc;

	rc = load_factory_data();
	if (rc != 0) {
		LOG_WRN("valid TXT1 data is required before Thread services can start");
	}
	rc = init_outputs();
	if (rc != 0) {
		LOG_ERR("GPIO init failed: %d", rc);
		return rc;
	}
	ot = openthread_get_default_instance();
	if (ot == NULL) {
		LOG_ERR("OpenThread instance unavailable");
		return -ENODEV;
	}
	if (start_thread(ot) != 0 || start_coap(ot) != 0 || start_srp(ot) != 0) {
		LOG_ERR("power-si Thread services did not start");
	}

	while (true) {
		k_sleep(K_SECONDS(60));
	}
	return 0;
}
