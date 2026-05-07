#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/hwinfo.h>
#include <zephyr/drivers/regulator.h>
#include <zephyr/kernel.h>
#include <zephyr/pm/device.h>
#include <zephyr/sys/poweroff.h>
#include <zephyr/sys/util.h>

static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
static const struct gpio_dt_spec power = GPIO_DT_SPEC_GET(DT_ALIAS(power), gpios);

#define DEFINE_REGULATOR_DEVICE(name)                                                \
	COND_CODE_1(DT_NODE_HAS_STATUS(DT_NODELABEL(name), okay),                    \
		    (static const struct device *const name##_reg =                  \
			     DEVICE_DT_GET(DT_NODELABEL(name));),                    \
		    ())

DEFINE_REGULATOR_DEVICE(pdm_imu_pwr)
DEFINE_REGULATOR_DEVICE(rfsw_pwr)
DEFINE_REGULATOR_DEVICE(vbat_pwr)

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
#if DT_NODE_HAS_STATUS(DT_NODELABEL(rfsw_pwr), okay)
	disable_regulator(rfsw_pwr_reg);
#endif
#if DT_NODE_HAS_STATUS(DT_NODELABEL(vbat_pwr), okay)
	disable_regulator(vbat_pwr_reg);
#endif
}

static void suspend_console(void)
{
#if DT_HAS_CHOSEN(zephyr_console)
	const struct device *const console = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));

	if (device_is_ready(console)) {
		(void)pm_device_action_run(console, PM_DEVICE_ACTION_SUSPEND);
	}
#endif
}

int main(void)
{
	(void)gpio_pin_configure_dt(&led, GPIO_OUTPUT_ACTIVE);
	(void)gpio_pin_configure_dt(&power, GPIO_OUTPUT_ACTIVE);
	k_sleep(K_SECONDS(5));

	(void)gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE);
	(void)gpio_pin_configure_dt(&power, GPIO_OUTPUT_INACTIVE);
	disable_xiao_load_regulators();
	suspend_console();
	hwinfo_clear_reset_cause();
	sys_poweroff();

	return 0;
}
