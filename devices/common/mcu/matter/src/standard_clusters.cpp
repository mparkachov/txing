/*
 * Copyright (c) 2026 txing contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "txing/matter/standard_clusters.h"

#include <app-common/zap-generated/attributes/Accessors.h>
#include <app-common/zap-generated/cluster-objects.h>
#include <lib/support/TypeTraits.h>

#include <zephyr/logging/log.h>

LOG_MODULE_DECLARE(app, CONFIG_CHIP_APP_LOG_LEVEL);

using namespace chip;
using namespace chip::app;

namespace txing::matter
{
namespace
{
constexpr int16_t kTemperatureMax = 0x7fff;
constexpr int16_t kTemperatureMin = 0x954d;
constexpr int16_t kTemperatureInvalid = 0x8000;
constexpr int16_t kPressureMax = 0x7fff;
constexpr int16_t kPressureMin = 0x8001;
constexpr int16_t kPressureInvalid = 0x8000;
constexpr uint16_t kHumidityMax = 0x2710;
constexpr uint16_t kHumidityMin = 0;
constexpr uint16_t kHumidityInvalid = 0xffff;

constexpr int16_t kMinimalOperatingVoltageMv = 3200;
constexpr int16_t kMaximalOperatingVoltageMv = 4050;
constexpr int16_t kWarningThresholdVoltageMv = 3450;
constexpr int16_t kCriticalThresholdVoltageMv = 3250;
constexpr uint8_t kMinBatteryPercentage = 0;
/* PowerSource BatPercentRemaining is expressed in half-percent units. */
constexpr uint8_t kMaxBatteryPercentage = 200;
constexpr uint32_t kBatteryCapacityUaH = 1350000;
constexpr uint32_t kAverageCurrentUa = CONFIG_TXING_MATTER_AVERAGE_CURRENT_CONSUMPTION_UA;
constexpr uint32_t kFullBatteryOperationTimeSeconds = kBatteryCapacityUaH / kAverageCurrentUa * 3600;

static_assert(kAverageCurrentUa > 0, "CONFIG_TXING_MATTER_AVERAGE_CURRENT_CONSUMPTION_UA must be > 0");

void LogSetFailure(const char *attribute, Protocols::InteractionModel::Status status)
{
	if (status != Protocols::InteractionModel::Status::Success) {
		LOG_ERR("Updating %s failed %x", attribute, to_underlying(status));
	}
}
} // namespace

void PublishTemperatureMeasurement(EndpointId endpoint, int32_t centi_celsius)
{
	int16_t value = static_cast<int16_t>(centi_celsius);
	if (centi_celsius > kTemperatureMax || centi_celsius < kTemperatureMin) {
		value = kTemperatureInvalid;
	}

	LogSetFailure("temperature measurement",
		      Clusters::TemperatureMeasurement::Attributes::MeasuredValue::Set(endpoint, value));
}

void PublishPressureMeasurement(EndpointId endpoint, int32_t deci_kpa)
{
	int16_t value = static_cast<int16_t>(deci_kpa);
	if (deci_kpa > kPressureMax || deci_kpa < kPressureMin) {
		value = kPressureInvalid;
	}

	LogSetFailure("pressure measurement",
		      Clusters::PressureMeasurement::Attributes::MeasuredValue::Set(endpoint, value));
}

void PublishRelativeHumidityMeasurement(EndpointId endpoint, int32_t centi_percent)
{
	uint16_t value = static_cast<uint16_t>(centi_percent);
	if (centi_percent > kHumidityMax || centi_percent < kHumidityMin) {
		value = kHumidityInvalid;
	}

	LogSetFailure("relative humidity measurement",
		      Clusters::RelativeHumidityMeasurement::Attributes::MeasuredValue::Set(endpoint, value));
}

void PublishPowerSource(EndpointId endpoint, const BatteryState &battery)
{
	int32_t voltage = battery.voltage_mv;
	uint8_t battery_percentage = 0;
	uint32_t battery_time_remaining = 0;
	Clusters::PowerSource::PowerSourceStatusEnum status = Clusters::PowerSource::PowerSourceStatusEnum::kUnavailable;
	Clusters::PowerSource::BatChargeLevelEnum charge_level = Clusters::PowerSource::BatChargeLevelEnum::kCritical;
	Clusters::PowerSource::BatChargeStateEnum charge_state =
		Clusters::PowerSource::BatChargeStateEnum::kIsNotCharging;

	if (voltage < 0) {
		voltage = 0;
	} else if (battery.present) {
		status = Clusters::PowerSource::PowerSourceStatusEnum::kActive;
	}

	if (voltage <= kMinimalOperatingVoltageMv) {
		battery_percentage = kMinBatteryPercentage;
	} else if (voltage >= kMaximalOperatingVoltageMv) {
		battery_percentage = kMaxBatteryPercentage;
	} else {
		battery_percentage = static_cast<uint8_t>(
			kMaxBatteryPercentage * (voltage - kMinimalOperatingVoltageMv) /
			(kMaximalOperatingVoltageMv - kMinimalOperatingVoltageMv));
	}

	battery_time_remaining = kFullBatteryOperationTimeSeconds * battery_percentage / kMaxBatteryPercentage;

	if (voltage < kCriticalThresholdVoltageMv) {
		charge_level = Clusters::PowerSource::BatChargeLevelEnum::kCritical;
	} else if (voltage < kWarningThresholdVoltageMv) {
		charge_level = Clusters::PowerSource::BatChargeLevelEnum::kWarning;
	} else {
		charge_level = Clusters::PowerSource::BatChargeLevelEnum::kOk;
	}

	if (battery.charging) {
		charge_state = Clusters::PowerSource::BatChargeStateEnum::kIsCharging;
	}

	LogSetFailure("battery voltage", Clusters::PowerSource::Attributes::BatVoltage::Set(endpoint, voltage));
	LogSetFailure("battery percentage",
		      Clusters::PowerSource::Attributes::BatPercentRemaining::Set(endpoint, battery_percentage));
	LogSetFailure("battery time remaining",
		      Clusters::PowerSource::Attributes::BatTimeRemaining::Set(endpoint, battery_time_remaining));
	LogSetFailure("battery charge level",
		      Clusters::PowerSource::Attributes::BatChargeLevel::Set(endpoint, charge_level));
	LogSetFailure("battery status", Clusters::PowerSource::Attributes::Status::Set(endpoint, status));
	LogSetFailure("battery present", Clusters::PowerSource::Attributes::BatPresent::Set(endpoint, battery.present));
	LogSetFailure("battery charge state",
		      Clusters::PowerSource::Attributes::BatChargeState::Set(endpoint, charge_state));
}

} // namespace txing::matter
