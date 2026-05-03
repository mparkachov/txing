/*
 * Copyright (c) 2026 txing contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "weather_device.h"

#include "txing/matter/standard_clusters.h"

#include <platform/CHIPDeviceLayer.h>

#include <cerrno>

#include <zephyr/drivers/sensor.h>
#include <zephyr/logging/log.h>

LOG_MODULE_DECLARE(app, CONFIG_CHIP_APP_LOG_LEVEL);

namespace txing::weather
{
namespace
{
constexpr chip::EndpointId kTemperatureEndpoint = 1;
constexpr chip::EndpointId kHumidityEndpoint = 2;
constexpr chip::EndpointId kPressureEndpoint = 3;

const device *sBme280Sensor = DEVICE_DT_GET_ONE(bosch_bme280);

int32_t ToCentiUnits(const sensor_value &value)
{
	return value.val1 * 100 + value.val2 / 10000;
}

int32_t ToDeciUnits(const sensor_value &value)
{
	return value.val1 * 10 + value.val2 / 100000;
}
} // namespace

CHIP_ERROR WeatherDevice::InitHardware()
{
	if (!device_is_ready(sBme280Sensor)) {
		LOG_ERR("BME280 sensor device not ready");
		return chip::System::MapErrorZephyr(-ENODEV);
	}

	return CHIP_NO_ERROR;
}

void WeatherDevice::SampleAndPublish()
{
	int result = sensor_sample_fetch(sBme280Sensor);
	if (result != 0) {
		LOG_ERR("Fetching data from BME280 sensor failed with: %d", result);
		return;
	}

	sensor_value temperature;
	result = sensor_channel_get(sBme280Sensor, SENSOR_CHAN_AMBIENT_TEMP, &temperature);
	if (result == 0) {
		LOG_DBG("New temperature measurement %d.%06d C", temperature.val1, temperature.val2);
		txing::matter::PublishTemperatureMeasurement(kTemperatureEndpoint, ToCentiUnits(temperature));
	} else {
		LOG_ERR("Getting temperature measurement data from BME280 failed with: %d", result);
	}

	sensor_value pressure;
	result = sensor_channel_get(sBme280Sensor, SENSOR_CHAN_PRESS, &pressure);
	if (result == 0) {
		LOG_DBG("New pressure measurement %d.%06d kPa", pressure.val1, pressure.val2);
		txing::matter::PublishPressureMeasurement(kPressureEndpoint, ToDeciUnits(pressure));
	} else {
		LOG_ERR("Getting pressure measurement data from BME280 failed with: %d", result);
	}

	sensor_value humidity;
	result = sensor_channel_get(sBme280Sensor, SENSOR_CHAN_HUMIDITY, &humidity);
	if (result == 0) {
		LOG_DBG("New humidity measurement %d.%06d %%RH", humidity.val1, humidity.val2);
		txing::matter::PublishRelativeHumidityMeasurement(kHumidityEndpoint, ToCentiUnits(humidity));
	} else {
		LOG_ERR("Getting humidity measurement data from BME280 failed with: %d", result);
	}
}

} // namespace txing::weather
