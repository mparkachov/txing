#include <errno.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/hci.h>
#include <zephyr/bluetooth/hci_vs.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
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

#ifndef BLE_DEBUG_ADV_SCANNABLE
#define BLE_DEBUG_ADV_SCANNABLE 0
#endif

#ifndef BLE_DEBUG_ADV_INCLUDE_UUID
#define BLE_DEBUG_ADV_INCLUDE_UUID 0
#endif

#if BLE_DEBUG_ADV_INCLUDE_UUID && !BLE_DEBUG_ADV_SCANNABLE
#error "Weather service UUID requires scannable advertising so it can fit in scan response"
#endif

#define WEATHER_SERVICE_UUID_VAL                                                             \
	BT_UUID_128_ENCODE(0xf6b4b000, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)

#if BLE_DEBUG_ADV_SCANNABLE
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

static void configure_output_inactive(const struct gpio_dt_spec *pin)
{
	if (device_is_ready(pin->port)) {
		(void)gpio_pin_configure_dt(pin, GPIO_OUTPUT_INACTIVE);
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

#if BLE_DEBUG_ADV_INCLUDE_UUID
	err = bt_le_adv_start(&adv_params, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
#else
	err = bt_le_adv_start(&adv_params, ad, ARRAY_SIZE(ad), NULL, 0);
#endif
	if (err < 0) {
		return err;
	}

	while (true) {
		k_sleep(K_FOREVER);
	}

	return 0;
}
