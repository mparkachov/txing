/*
 * Copyright (c) 2026 txing contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "weather_ble_protocol.h"
#include "weather_factory_data.h"

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/regulator.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>
#include <nrfx_saadc.h>

#include <array>
#include <cstring>
#include <cstdint>
#include <cstddef>

namespace
{
constexpr char kInvalidName[] = "TxingWeatherInvalid";
constexpr std::uint16_t kSetupConnIntervalMin = 24; // 30 ms in 1.25 ms units.
constexpr std::uint16_t kSetupConnIntervalMax = 40; // 50 ms in 1.25 ms units.
constexpr std::uint16_t kSetupConnLatency = 0;
constexpr std::uint16_t kSetupSupervisionTimeout = 400; // 4 seconds.
constexpr std::uint16_t kIdleConnInterval = 800; // 1000 ms in 1.25 ms units.
constexpr std::uint16_t kIdleConnLatency = 4;
constexpr std::uint16_t kIdleSupervisionTimeout = 1200; // 12 seconds.
constexpr int kIdleConnParamFallbackDelaySeconds = 30;
constexpr int kActiveMeasurementIntervalSeconds = 10;
constexpr int kIdleMeasurementIntervalSeconds = 60;

#define TXING_WEATHER_SERVICE_UUID_VAL BT_UUID_128_ENCODE(0xf6b4b000, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define TXING_WEATHER_COMMAND_UUID_VAL BT_UUID_128_ENCODE(0xf6b4b001, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define TXING_WEATHER_STATE_UUID_VAL BT_UUID_128_ENCODE(0xf6b4b002, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define TXING_POWER_MEASUREMENT_UUID_VAL BT_UUID_128_ENCODE(0xf6b4b003, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define TXING_WEATHER_MEASUREMENT_UUID_VAL BT_UUID_128_ENCODE(0xf6b4b004, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)

const bt_uuid_128 kWeatherServiceUuid = BT_UUID_INIT_128(TXING_WEATHER_SERVICE_UUID_VAL);
const bt_uuid_128 kWeatherCommandUuid = BT_UUID_INIT_128(TXING_WEATHER_COMMAND_UUID_VAL);
const bt_uuid_128 kWeatherStateUuid = BT_UUID_INIT_128(TXING_WEATHER_STATE_UUID_VAL);
const bt_uuid_128 kPowerMeasurementUuid = BT_UUID_INIT_128(TXING_POWER_MEASUREMENT_UUID_VAL);
const bt_uuid_128 kWeatherMeasurementUuid = BT_UUID_INIT_128(TXING_WEATHER_MEASUREMENT_UUID_VAL);

#if DT_NODE_HAS_STATUS(DT_ALIAS(led0), okay)
constexpr bool kHasLed = true;
const gpio_dt_spec kLed = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
#else
constexpr bool kHasLed = false;
#endif

#if DT_HAS_COMPAT_STATUS_OKAY(bosch_bme280)
const device *const kBme280 = DEVICE_DT_GET_ONE(bosch_bme280);
#else
const device *const kBme280 = nullptr;
#endif

#if DT_NODE_EXISTS(DT_PATH(zephyr_user)) && DT_NODE_HAS_PROP(DT_PATH(zephyr_user), io_channels)
constexpr bool kHasBatteryAdc = true;
const adc_dt_spec kBatteryAdc = ADC_DT_SPEC_GET_BY_IDX(DT_PATH(zephyr_user), 0);
#else
constexpr bool kHasBatteryAdc = false;
#endif

#if DT_NODE_HAS_STATUS(DT_NODELABEL(vbat_pwr), okay)
const device *const kVbatRegulator = DEVICE_DT_GET(DT_NODELABEL(vbat_pwr));
#else
const device *const kVbatRegulator = nullptr;
#endif

struct RuntimeState
{
	std::uint8_t redcon = txing::weather::kRedconIdle;
	std::uint16_t battery_mv = 0;
	txing::weather::WeatherMeasurementReport weather_measurement{};
};

RuntimeState gRuntime{};
bt_conn *gConnection = nullptr;
extern const bt_gatt_attr attr_weather_service[];
bool gIdleConnParamsRequested = false;
bool gStateNotifyEnabled = false;
bool gPowerMeasurementNotifyEnabled = false;
bool gWeatherMeasurementNotifyEnabled = false;
k_work_delayable gIdleConnParamWork{};
k_work_delayable gMeasurementWork{};

void schedule_measurement_now();

std::int32_t sensor_value_to_centi(const sensor_value &value)
{
	return static_cast<std::int32_t>(value.val1 * 100 + value.val2 / 10000);
}

std::uint32_t pressure_value_to_pa(const sensor_value &value)
{
	const std::int64_t micro_kpa = static_cast<std::int64_t>(value.val1) * 1000000 + value.val2;
	const std::int64_t pa = micro_kpa / 1000;
	return pa < 0 ? 0 : static_cast<std::uint32_t>(pa);
}

void set_led(bool on)
{
	if constexpr (kHasLed) {
		if (device_is_ready(kLed.port)) {
			gpio_pin_set_dt(&kLed, on ? 1 : 0);
		}
	}
}

void request_connected_setup_params()
{
	if (gConnection == nullptr) {
		return;
	}

	const bt_le_conn_param params = {
		.interval_min = kSetupConnIntervalMin,
		.interval_max = kSetupConnIntervalMax,
		.latency = kSetupConnLatency,
		.timeout = kSetupSupervisionTimeout,
	};
	(void)bt_conn_le_param_update(gConnection, &params);
}

void request_connected_idle_params()
{
	if (gConnection == nullptr || gIdleConnParamsRequested) {
		return;
	}

	const bt_le_conn_param params = {
		.interval_min = kIdleConnInterval,
		.interval_max = kIdleConnInterval,
		.latency = kIdleConnLatency,
		.timeout = kIdleSupervisionTimeout,
	};
	const int err = bt_conn_le_param_update(gConnection, &params);
	if (err != 0) {
		return;
	}
	gIdleConnParamsRequested = true;
}

void request_idle_params_if_gatt_ready()
{
	if (gStateNotifyEnabled && gPowerMeasurementNotifyEnabled && gWeatherMeasurementNotifyEnabled) {
		request_connected_idle_params();
	}
}

void idle_conn_param_work_handler(k_work *work)
{
	(void)work;
	request_connected_idle_params();
}

void resume_battery_adc()
{
	if (!nrfx_saadc_init_check()) {
		(void)nrfx_saadc_init(0);
	}
}

void suspend_battery_adc()
{
	if (nrfx_saadc_init_check()) {
		nrfx_saadc_uninit();
	}
}

std::uint16_t sample_battery_mv()
{
	if constexpr (!kHasBatteryAdc) {
		return 0;
	} else {
#if DT_NODE_EXISTS(DT_PATH(zephyr_user)) && DT_NODE_HAS_PROP(DT_PATH(zephyr_user), io_channels)
		std::uint16_t buf = 0;
		std::uint16_t result = 0;
		std::int32_t val_mv = 0;
		adc_sequence sequence = {
			.buffer = &buf,
			.buffer_size = sizeof(buf),
		};

		if (!adc_is_ready_dt(&kBatteryAdc)) {
			suspend_battery_adc();
			return 0;
		}

		resume_battery_adc();

		if (kVbatRegulator != nullptr && device_is_ready(kVbatRegulator)) {
			(void)regulator_enable(kVbatRegulator);
			k_sleep(K_MSEC(100));
		}

		int err = adc_channel_setup_dt(&kBatteryAdc);
		if (err < 0) {
			goto out;
		}

		(void)adc_sequence_init_dt(&kBatteryAdc, &sequence);
		err = adc_read_dt(&kBatteryAdc, &sequence);
		if (err < 0) {
			goto out;
		}

		if (kBatteryAdc.channel_cfg.differential) {
			val_mv = static_cast<std::int32_t>(static_cast<std::int16_t>(buf));
		} else {
			val_mv = static_cast<std::int32_t>(buf);
		}

		err = adc_raw_to_millivolts_dt(&kBatteryAdc, &val_mv);
		if (err < 0 || val_mv < 0) {
			goto out;
		}

		val_mv *= 2;
		if (val_mv > UINT16_MAX) {
			val_mv = UINT16_MAX;
		}
		result = static_cast<std::uint16_t>(val_mv);

out:
		if (kVbatRegulator != nullptr && device_is_ready(kVbatRegulator)) {
			(void)regulator_disable(kVbatRegulator);
		}
		suspend_battery_adc();
		return result;
#endif
	}
}

txing::weather::StateReport current_state_report()
{
	return txing::weather::StateReport{
		.redcon = gRuntime.redcon,
	};
}

void notify_state()
{
	if (gConnection == nullptr) {
		return;
	}
	std::array<std::uint8_t, 2> payload{};
	const std::size_t size = txing::weather::EncodeStateReport(
		current_state_report(),
		payload.data(),
		payload.size()
	);
	if (size > 0) {
		bt_gatt_notify(gConnection, &attr_weather_service[4], payload.data(), size);
	}
}

void notify_power_measurement()
{
	if (gConnection == nullptr) {
		return;
	}
	txing::weather::PowerMeasurementReport measurement{
		.battery_mv = gRuntime.battery_mv,
	};
	std::array<std::uint8_t, 3> payload{};
	const std::size_t size = txing::weather::EncodePowerMeasurementReport(
		measurement,
		payload.data(),
		payload.size()
	);
	if (size > 0) {
		bt_gatt_notify(gConnection, &attr_weather_service[7], payload.data(), size);
	}
}

void notify_weather_measurement()
{
	if (gConnection == nullptr) {
		return;
	}
	std::array<std::uint8_t, 11> payload{};
	const std::size_t size = txing::weather::EncodeWeatherMeasurementReport(
		gRuntime.weather_measurement,
		payload.data(),
		payload.size()
	);
	if (size > 0) {
		bt_gatt_notify(gConnection, &attr_weather_service[10], payload.data(), size);
	}
}

void set_redcon(std::uint8_t redcon)
{
	gRuntime.redcon = redcon == txing::weather::kRedconIdle
		? txing::weather::kRedconIdle
		: txing::weather::kRedconActive;
	set_led(gRuntime.redcon < txing::weather::kRedconIdle);
	notify_state();
}

bool sample_bme280()
{
	if (kBme280 == nullptr || !device_is_ready(kBme280)) {
		return false;
	}
	if (sensor_sample_fetch(kBme280) != 0) {
		return false;
	}
	sensor_value temperature{};
	sensor_value pressure{};
	sensor_value humidity{};
	if (sensor_channel_get(kBme280, SENSOR_CHAN_AMBIENT_TEMP, &temperature) != 0 ||
	    sensor_channel_get(kBme280, SENSOR_CHAN_PRESS, &pressure) != 0 ||
	    sensor_channel_get(kBme280, SENSOR_CHAN_HUMIDITY, &humidity) != 0) {
		return false;
	}
	gRuntime.weather_measurement.temperature_centi_c = sensor_value_to_centi(temperature);
	gRuntime.weather_measurement.pressure_pa = pressure_value_to_pa(pressure);
	gRuntime.weather_measurement.humidity_centi_percent = static_cast<std::uint16_t>(
		sensor_value_to_centi(humidity)
	);
	return true;
}

ssize_t read_state(bt_conn *conn, const bt_gatt_attr *attr, void *buf, std::uint16_t len, std::uint16_t offset)
{
	(void)attr;
	std::array<std::uint8_t, 2> payload{};
	const std::size_t size = txing::weather::EncodeStateReport(
		current_state_report(),
		payload.data(),
		payload.size()
	);
	return bt_gatt_attr_read(conn, attr, buf, len, offset, payload.data(), size);
}

ssize_t read_power_measurement(bt_conn *conn, const bt_gatt_attr *attr, void *buf, std::uint16_t len, std::uint16_t offset)
{
	(void)attr;
	gRuntime.battery_mv = sample_battery_mv();
	txing::weather::PowerMeasurementReport measurement{
		.battery_mv = gRuntime.battery_mv,
	};
	std::array<std::uint8_t, 3> payload{};
	const std::size_t size = txing::weather::EncodePowerMeasurementReport(
		measurement,
		payload.data(),
		payload.size()
	);
	return bt_gatt_attr_read(conn, attr, buf, len, offset, payload.data(), size);
}

ssize_t read_weather_measurement(bt_conn *conn, const bt_gatt_attr *attr, void *buf, std::uint16_t len, std::uint16_t offset)
{
	(void)attr;
	(void)sample_bme280();
	std::array<std::uint8_t, 11> payload{};
	const std::size_t size = txing::weather::EncodeWeatherMeasurementReport(
		gRuntime.weather_measurement,
		payload.data(),
		payload.size()
	);
	return bt_gatt_attr_read(conn, attr, buf, len, offset, payload.data(), size);
}

ssize_t write_command(
	bt_conn *conn,
	const bt_gatt_attr *attr,
	const void *buf,
	std::uint16_t len,
	std::uint16_t offset,
	std::uint8_t flags
)
{
	(void)conn;
	(void)attr;
	(void)flags;
	if (offset != 0) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
	}
	txing::weather::Command command{};
	if (!txing::weather::DecodeCommand(static_cast<const std::uint8_t *>(buf), len, command)) {
		return BT_GATT_ERR(BT_ATT_ERR_VALUE_NOT_ALLOWED);
	}
	set_redcon(command.target_redcon);
	schedule_measurement_now();
	return len;
}

void state_ccc_changed(const bt_gatt_attr *attr, std::uint16_t value)
{
	(void)attr;
	gStateNotifyEnabled = (value & BT_GATT_CCC_NOTIFY) != 0;
	request_idle_params_if_gatt_ready();
}

void power_measurement_ccc_changed(const bt_gatt_attr *attr, std::uint16_t value)
{
	(void)attr;
	gPowerMeasurementNotifyEnabled = (value & BT_GATT_CCC_NOTIFY) != 0;
	request_idle_params_if_gatt_ready();
}

void weather_measurement_ccc_changed(const bt_gatt_attr *attr, std::uint16_t value)
{
	(void)attr;
	gWeatherMeasurementNotifyEnabled = (value & BT_GATT_CCC_NOTIFY) != 0;
	request_idle_params_if_gatt_ready();
}

BT_GATT_SERVICE_DEFINE(weather_service,
	BT_GATT_PRIMARY_SERVICE(&kWeatherServiceUuid.uuid),
	BT_GATT_CHARACTERISTIC(
		&kWeatherCommandUuid.uuid,
		BT_GATT_CHRC_WRITE,
		BT_GATT_PERM_WRITE,
		nullptr,
		write_command,
		nullptr
	),
	BT_GATT_CHARACTERISTIC(
		&kWeatherStateUuid.uuid,
		BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
		BT_GATT_PERM_READ,
		read_state,
		nullptr,
		nullptr
	),
	BT_GATT_CCC(state_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	BT_GATT_CHARACTERISTIC(
		&kPowerMeasurementUuid.uuid,
		BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
		BT_GATT_PERM_READ,
		read_power_measurement,
		nullptr,
		nullptr
	),
	BT_GATT_CCC(power_measurement_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	BT_GATT_CHARACTERISTIC(
		&kWeatherMeasurementUuid.uuid,
		BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
		BT_GATT_PERM_READ,
		read_weather_measurement,
		nullptr,
		nullptr
	),
	BT_GATT_CCC(weather_measurement_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE)
);

void measurement_work_handler(k_work *work)
{
	(void)work;
	if (gConnection == nullptr) {
		return;
	}
	gRuntime.battery_mv = sample_battery_mv();
	notify_power_measurement();
	if (sample_bme280()) {
		notify_weather_measurement();
	}
	const int interval = gRuntime.redcon < txing::weather::kRedconIdle
		? kActiveMeasurementIntervalSeconds
		: kIdleMeasurementIntervalSeconds;
	k_work_reschedule(&gMeasurementWork, K_SECONDS(interval));
}

void schedule_measurement_now()
{
	k_work_reschedule(&gMeasurementWork, K_NO_WAIT);
}

void connected(bt_conn *conn, std::uint8_t err)
{
	if (err != 0) {
		return;
	}
	if (gConnection != nullptr) {
		bt_conn_unref(gConnection);
	}
	gConnection = bt_conn_ref(conn);
	gIdleConnParamsRequested = false;
	gStateNotifyEnabled = false;
	gPowerMeasurementNotifyEnabled = false;
	gWeatherMeasurementNotifyEnabled = false;
	request_connected_setup_params();
	k_work_reschedule(&gIdleConnParamWork, K_SECONDS(kIdleConnParamFallbackDelaySeconds));
	schedule_measurement_now();
}

void disconnected(bt_conn *conn, std::uint8_t reason)
{
	(void)conn;
	(void)reason;
	k_work_cancel_delayable(&gIdleConnParamWork);
	gIdleConnParamsRequested = false;
	gStateNotifyEnabled = false;
	gPowerMeasurementNotifyEnabled = false;
	gWeatherMeasurementNotifyEnabled = false;
	k_work_cancel_delayable(&gMeasurementWork);
	if (gConnection != nullptr) {
		bt_conn_unref(gConnection);
		gConnection = nullptr;
	}
	set_redcon(txing::weather::kRedconIdle);
}

BT_CONN_CB_DEFINE(conn_callbacks) = {
	.connected = connected,
	.disconnected = disconnected,
};

int start_valid_advertising(const txing::weather::FactoryData &factory)
{
	const char *name = factory.thing_name.data();
	const std::size_t name_len = std::strlen(name);
	const bt_data ad[] = {
		BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
		BT_DATA(BT_DATA_NAME_COMPLETE, name, static_cast<std::uint8_t>(name_len)),
	};
	const bt_data sd[] = {
		BT_DATA_BYTES(BT_DATA_UUID128_ALL, TXING_WEATHER_SERVICE_UUID_VAL),
	};
	return bt_le_adv_start(BT_LE_ADV_CONN_FAST_1, ad, ARRAY_SIZE(ad), sd, ARRAY_SIZE(sd));
}

int start_invalid_advertising()
{
	const bt_data ad[] = {
		BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
		BT_DATA(BT_DATA_NAME_COMPLETE, kInvalidName, sizeof(kInvalidName) - 1),
	};
	return bt_le_adv_start(BT_LE_ADV_NCONN, ad, ARRAY_SIZE(ad), nullptr, 0);
}
} // namespace

int main()
{
	txing::weather::FactoryData factory{};
	const bool factory_valid = txing::weather::ReadFactoryData(factory);

	if constexpr (kHasLed) {
		if (device_is_ready(kLed.port)) {
			gpio_pin_configure_dt(&kLed, GPIO_OUTPUT_INACTIVE);
		}
	}
	const int err = bt_enable(nullptr);
	if (err != 0) {
		return err;
	}
	k_work_init_delayable(&gIdleConnParamWork, idle_conn_param_work_handler);
	k_work_init_delayable(&gMeasurementWork, measurement_work_handler);
	if (!factory_valid) {
		start_invalid_advertising();
		for (;;) {
			k_sleep(K_FOREVER);
		}
	}
	if (start_valid_advertising(factory) != 0) {
		return 2;
	}
	for (;;) {
		k_sleep(K_FOREVER);
	}
}
