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
#include <zephyr/psa/key_ids.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/sys/crc.h>
#include <zephyr/sys/printk.h>
#include <zephyr/sys/util.h>

#include <openthread/coap.h>
#include <openthread/dataset.h>
#include <openthread/error.h>
#include <openthread/ip6.h>
#include <openthread/platform/crypto.h>
#include <openthread/srp_client.h>
#include <openthread/thread.h>
#include <psa/crypto.h>

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

static otIp6Address srp_host_address;
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
static void thread_state_changed(uint32_t flags, void *context);
static void srp_client_callback(otError error, const otSrpClientHostInfo *host_info,
				const otSrpClientService *services,
				const otSrpClientService *removed_services, void *context);
static void srp_autostart_callback(const otSockAddr *server, void *context);
static struct openthread_state_changed_callback thread_state_cb = {
	.otCallback = thread_state_changed,
};

#if DT_NODE_EXISTS(DT_NODELABEL(txing_factory_partition))
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
#else
static int load_factory_data(void)
{
	LOG_ERR("TXT1 factory partition is not configured");
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

	openthread_mutex_lock();
	error = otCoapStart(ot, factory.coap_port);
	if (error != OT_ERROR_NONE) {
		openthread_mutex_unlock();
		LOG_ERR("CoAP start failed: %d", error);
		return -EIO;
	}
	otCoapAddResource(ot, &state_resource);
	otCoapAddResource(ot, &redcon_resource);
	openthread_mutex_unlock();
	LOG_INF("CoAP service started on port %u", factory.coap_port);
	return 0;
}

static otError set_srp_host_address(otInstance *ot)
{
	const otIp6Address *mesh_local_eid = otThreadGetMeshLocalEid(ot);
	char address_string[OT_IP6_ADDRESS_STRING_SIZE];

	if (mesh_local_eid == NULL) {
		return OT_ERROR_INVALID_STATE;
	}

	memcpy(&srp_host_address, mesh_local_eid, sizeof(srp_host_address));
	otIp6AddressToString(&srp_host_address, address_string, sizeof(address_string));
	LOG_INF("SRP host address set to mesh-local EID %s", address_string);
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
	if (error != OT_ERROR_NONE) {
		openthread_mutex_unlock();
		LOG_ERR("SRP host name failed: %d", error);
		return -EIO;
	}
	error = set_srp_host_address(ot);
	if (error != OT_ERROR_NONE) {
		openthread_mutex_unlock();
		LOG_ERR("SRP host address failed: %d", error);
		return -EIO;
	}
	error = otSrpClientAddService(ot, &srp_service);
	if (error != OT_ERROR_NONE && error != OT_ERROR_ALREADY) {
		openthread_mutex_unlock();
		LOG_ERR("SRP service add failed: %d", error);
		return -EIO;
	}
	otSrpClientEnableAutoStartMode(ot, srp_autostart_callback, ot);
	openthread_mutex_unlock();
	LOG_INF("SRP service requested: %s.%s.default.service.arpa",
		factory.thing_name, srp_service.mName);
	return 0;
}

static void log_srp_host(const otSrpClientHostInfo *host_info)
{
	const char *name;

	if (host_info == NULL) {
		LOG_INF("SRP host: unavailable");
		return;
	}

	name = host_info->mName == NULL ? "(unset)" : host_info->mName;
	LOG_INF("SRP host %s state=%s autoAddress=%u addresses=%u",
		name, otSrpClientItemStateToString(host_info->mState),
		host_info->mAutoAddress, host_info->mNumAddresses);
	for (uint8_t i = 0; i < host_info->mNumAddresses; i++) {
		char address_string[OT_IP6_ADDRESS_STRING_SIZE];

		otIp6AddressToString(&host_info->mAddresses[i], address_string,
				     sizeof(address_string));
		LOG_INF("SRP host address[%u]=%s", i, address_string);
	}
}

static void log_srp_services(const char *label, const otSrpClientService *services)
{
	const otSrpClientService *service;

	if (services == NULL) {
		LOG_INF("SRP %s services: none", label);
		return;
	}

	for (service = services; service != NULL; service = service->mNext) {
		LOG_INF("SRP %s service %s.%s state=%s port=%u", label,
			service->mInstanceName == NULL ? "(unset)" : service->mInstanceName,
			service->mName == NULL ? "(unset)" : service->mName,
			otSrpClientItemStateToString(service->mState), service->mPort);
	}
}

static void srp_client_callback(otError error, const otSrpClientHostInfo *host_info,
				const otSrpClientService *services,
				const otSrpClientService *removed_services, void *context)
{
	ARG_UNUSED(context);

	if (error == OT_ERROR_NONE) {
		LOG_INF("SRP update accepted");
	} else {
		LOG_WRN("SRP update failed: %s (%d)", otThreadErrorToString(error), error);
	}

	log_srp_host(host_info);
	log_srp_services("active", services);
	log_srp_services("removed", removed_services);
}

static void srp_autostart_callback(const otSockAddr *server, void *context)
{
	char server_string[OT_IP6_SOCK_ADDR_STRING_SIZE];

	ARG_UNUSED(context);

	if (server == NULL) {
		LOG_WRN("SRP auto-start stopped: no server in Thread network data");
		return;
	}

	otIp6SockAddrToString(server, server_string, sizeof(server_string));
	LOG_INF("SRP auto-start selected server %s", server_string);
}

static int configure_thread_device_mode(otInstance *ot)
{
	otLinkModeConfig link_mode;
	otError error;

	link_mode = otThreadGetLinkMode(ot);
	link_mode.mRxOnWhenIdle = true;
	link_mode.mDeviceType = false;
	link_mode.mNetworkData = true;

	error = otThreadSetLinkMode(ot, link_mode);
	if (error != OT_ERROR_NONE) {
		LOG_ERR("Thread link mode failed: %d", error);
		return -EIO;
	}

	LOG_INF("Thread receiver-on MTD mode configured: rxOnWhenIdle=1 fullNetworkData=1");
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

	openthread_mutex_lock();
	error = otDatasetSetActiveTlvs(ot, &dataset);
	if (error != OT_ERROR_NONE) {
		openthread_mutex_unlock();
		LOG_ERR("Thread dataset set failed: %d", error);
		return -EIO;
	}
	LOG_INF("Thread active dataset accepted: %u TLV bytes", factory.dataset_tlvs_len);
	if (configure_thread_device_mode(ot) != 0) {
		openthread_mutex_unlock();
		return -EIO;
	}
	error = otIp6SetEnabled(ot, true);
	if (error != OT_ERROR_NONE) {
		openthread_mutex_unlock();
		LOG_ERR("Thread IPv6 enable failed: %d", error);
		return -EIO;
	}
	LOG_INF("Thread IPv6 interface enabled");
	error = otThreadSetEnabled(ot, true);
	if (error != OT_ERROR_NONE) {
		openthread_mutex_unlock();
		LOG_ERR("Thread enable failed: %d", error);
		return -EIO;
	}
	LOG_INF("Thread protocol enabled");
	openthread_mutex_unlock();
	return 0;
}

static void thread_state_changed(uint32_t flags, void *context)
{
	otInstance *ot = context;

	LOG_INF("Thread state flags=0x%08x role=%s", flags,
		otThreadDeviceRoleToString(otThreadGetDeviceRole(ot)));
}

static void register_thread_state_logger(otInstance *ot)
{
	thread_state_cb.user_data = ot;
	if (openthread_state_changed_callback_register(&thread_state_cb) != 0) {
		LOG_WRN("Thread state logger registration failed");
	}
}

#if defined(CONFIG_TXING_POWER_SI_SRP_PSA_DIAGNOSTICS)
static const char *psa_status_label(psa_status_t status)
{
	switch (status) {
	case PSA_SUCCESS:
		return "SUCCESS";
	case PSA_ERROR_ALREADY_EXISTS:
		return "ALREADY_EXISTS";
	case PSA_ERROR_BUFFER_TOO_SMALL:
		return "BUFFER_TOO_SMALL";
	case PSA_ERROR_DOES_NOT_EXIST:
		return "DOES_NOT_EXIST";
	case PSA_ERROR_INVALID_ARGUMENT:
		return "INVALID_ARGUMENT";
	case PSA_ERROR_INVALID_HANDLE:
		return "INVALID_HANDLE";
	case PSA_ERROR_INSUFFICIENT_MEMORY:
		return "INSUFFICIENT_MEMORY";
	case PSA_ERROR_NOT_PERMITTED:
		return "NOT_PERMITTED";
	case PSA_ERROR_NOT_SUPPORTED:
		return "NOT_SUPPORTED";
	case PSA_ERROR_STORAGE_FAILURE:
		return "STORAGE_FAILURE";
	default:
		return "OTHER";
	}
}

static void log_psa_status(const char *operation, psa_status_t status)
{
	LOG_INF("SRP PSA %s status=%ld (%s)", operation, (long)status,
		psa_status_label(status));
}

static void log_psa_key_attributes(psa_key_id_t key_id)
{
	psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;
	psa_status_t status;

	status = psa_get_key_attributes(key_id, &attributes);
	log_psa_status("get-key-attributes", status);
	if (status == PSA_SUCCESS) {
		LOG_INF("SRP PSA key id=0x%08lx type=0x%lx bits=%u usage=0x%lx alg=0x%lx lifetime=0x%lx",
			(unsigned long)key_id,
			(unsigned long)psa_get_key_type(&attributes),
			(unsigned int)psa_get_key_bits(&attributes),
			(unsigned long)psa_get_key_usage_flags(&attributes),
			(unsigned long)psa_get_key_algorithm(&attributes),
			(unsigned long)psa_get_key_lifetime(&attributes));
	}
	psa_reset_key_attributes(&attributes);
}

static void probe_psa_key_operations(psa_key_id_t key_id, const char *label)
{
	uint8_t public_key[1 + OT_CRYPTO_ECDSA_PUBLIC_KEY_SIZE];
	uint8_t hash[OT_CRYPTO_SHA256_HASH_SIZE] = {0};
	uint8_t signature[OT_CRYPTO_ECDSA_SIGNATURE_SIZE];
	size_t length = 0;
	psa_status_t status;

	status = psa_export_public_key(key_id, public_key, sizeof(public_key), &length);
	LOG_INF("SRP PSA %s export-public status=%ld (%s) length=%u", label,
		(long)status, psa_status_label(status), (unsigned int)length);

	status = psa_sign_hash(key_id, PSA_ALG_DETERMINISTIC_ECDSA(PSA_ALG_SHA_256),
			       hash, sizeof(hash), signature, sizeof(signature), &length);
	LOG_INF("SRP PSA %s sign-hash status=%ld (%s) length=%u", label,
		(long)status, psa_status_label(status), (unsigned int)length);
}

static void probe_volatile_psa_key(void)
{
	psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;
	psa_key_id_t key_id = PSA_KEY_ID_NULL;
	psa_status_t status;

	psa_set_key_usage_flags(&attributes,
				PSA_KEY_USAGE_VERIFY_HASH | PSA_KEY_USAGE_SIGN_HASH);
	psa_set_key_algorithm(&attributes, PSA_ALG_DETERMINISTIC_ECDSA(PSA_ALG_SHA_256));
	psa_set_key_type(&attributes, PSA_KEY_TYPE_ECC_KEY_PAIR(PSA_ECC_FAMILY_SECP_R1));
	psa_set_key_bits(&attributes, 256);

	status = psa_generate_key(&attributes, &key_id);
	log_psa_status("volatile-generate", status);
	if (status == PSA_SUCCESS) {
		probe_psa_key_operations(key_id, "volatile");
		log_psa_status("volatile-destroy", psa_destroy_key(key_id));
	}
	psa_reset_key_attributes(&attributes);
}

static void log_srp_psa_diagnostics(void)
{
	const psa_key_id_t key_id =
		(psa_key_id_t)ZEPHYR_PSA_OPENTHREAD_KEY_ID_RANGE_BEGIN + 7;
	otError error;

	LOG_INF("SRP PSA diagnostics start keyRef=0x%08lx", (unsigned long)key_id);
	probe_volatile_psa_key();
	log_psa_key_attributes(key_id);

	error = otPlatCryptoEcdsaGenerateAndImportKey((otCryptoKeyRef)key_id);
	LOG_INF("SRP PSA persistent generate/import result=%s (%d)",
		otThreadErrorToString(error), error);
	log_psa_key_attributes(key_id);
	probe_psa_key_operations(key_id, "persistent");
}
#else
static void log_srp_psa_diagnostics(void)
{
}
#endif

int main(void)
{
	otInstance *ot;
	int rc;

	printk("txing power-si boot\n");

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
	register_thread_state_logger(ot);
	log_srp_psa_diagnostics();
	if (start_thread(ot) != 0 || start_coap(ot) != 0 || start_srp(ot) != 0) {
		LOG_ERR("power-si Thread services did not start");
	}

	while (true) {
		k_sleep(K_SECONDS(60));
	}
	return 0;
}
