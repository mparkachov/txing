/*
 * Copyright (c) 2026 txing contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <app/util/basic-types.h>

#include <cstdint>

namespace txing::matter
{

struct BatteryState {
	int32_t voltage_mv = 3500;
	bool present = true;
	bool charging = false;
};

void PublishTemperatureMeasurement(chip::EndpointId endpoint, int32_t centi_celsius);
void PublishPressureMeasurement(chip::EndpointId endpoint, int32_t deci_kpa);
void PublishRelativeHumidityMeasurement(chip::EndpointId endpoint, int32_t centi_percent);
void PublishPowerSource(chip::EndpointId endpoint, const BatteryState &battery);

} // namespace txing::matter
