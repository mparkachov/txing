/*
 * Copyright (c) 2026 txing contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "weather_device.h"

#include "txing/matter/txing_matter_app.h"

#include <array>
#include <cstdlib>

#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(app, CONFIG_CHIP_APP_LOG_LEVEL);

int main()
{
	static txing::weather::WeatherDevice weather_device;
	static constexpr std::array<chip::EndpointId, 3> kIdentifyEndpoints = { 1, 2, 3 };

	const txing::matter::MatterAppConfig config{
		3000,
		0,
		kIdentifyEndpoints.data(),
		kIdentifyEndpoints.size(),
	};

	CHIP_ERROR err = txing::matter::RunMatterApp(weather_device, config);
	LOG_ERR("Exited with code %" CHIP_ERROR_FORMAT, err.Format());
	return err == CHIP_NO_ERROR ? EXIT_SUCCESS : EXIT_FAILURE;
}
