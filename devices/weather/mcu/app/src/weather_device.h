/*
 * Copyright (c) 2026 txing contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "txing/matter/txing_matter_app.h"

namespace txing::weather
{

class WeatherDevice final : public txing::matter::MatterDevice {
public:
	CHIP_ERROR InitHardware() override;
	void SampleAndPublish() override;
};

} // namespace txing::weather
