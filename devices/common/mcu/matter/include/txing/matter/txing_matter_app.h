/*
 * Copyright (c) 2026 txing contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "txing/matter/standard_clusters.h"

#include <lib/core/CHIPError.h>
#include <app/util/basic-types.h>

#include <cstddef>
#include <cstdint>

namespace txing::matter
{

struct MatterAppConfig {
	uint32_t measurement_interval_ms = 3000;
	chip::EndpointId power_source_endpoint = 0;
	const chip::EndpointId *identify_endpoints = nullptr;
	size_t identify_endpoint_count = 0;
};

class MatterDevice {
public:
	virtual ~MatterDevice() = default;

	virtual CHIP_ERROR InitHardware() = 0;
	virtual void BeforeSample() {}
	virtual void SampleAndPublish() = 0;
	virtual void AfterSample() {}
	virtual BatteryState ReadBatteryState() { return {}; }
};

CHIP_ERROR RunMatterApp(MatterDevice &device, const MatterAppConfig &config);

} // namespace txing::matter
