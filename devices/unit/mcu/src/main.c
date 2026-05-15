#include <zephyr/devicetree.h>
#include <zephyr/drivers/gpio.h>

#include <txing_redcon.h>

static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
static const struct gpio_dt_spec power = GPIO_DT_SPEC_GET(DT_ALIAS(power), gpios);

static const struct txing_redcon_ops redcon_ops = {
	.led = &led,
	.power = &power,
};

int main(void)
{
	return txing_redcon_run(&redcon_ops);
}
