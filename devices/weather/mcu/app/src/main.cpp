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
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/kernel.h>

#include <array>
#include <cstring>
#include <cstdint>
#include <cstddef>

namespace
{
constexpr char kInvalidName[] = "TxingWeatherInvalid";
constexpr std::uint16_t kIdleConnInterval = 800; // 1000 ms in 1.25 ms units.
constexpr std::uint16_t kIdleConnLatency = 4;
constexpr std::uint16_t kIdleSupervisionTimeout = 1200; // 12 seconds.

#define TXING_WEATHER_SERVICE_UUID_VAL BT_UUID_128_ENCODE(0xf6b4b000, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define TXING_WEATHER_COMMAND_UUID_VAL BT_UUID_128_ENCODE(0xf6b4b001, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define TXING_WEATHER_STATE_UUID_VAL BT_UUID_128_ENCODE(0xf6b4b002, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)
#define TXING_WEATHER_MEASUREMENT_UUID_VAL BT_UUID_128_ENCODE(0xf6b4b003, 0x7b32, 0x4d2d, 0x9f4b, 0x4ff0a2b8f100)

const bt_uuid_128 kWeatherServiceUuid = BT_UUID_INIT_128(TXING_WEATHER_SERVICE_UUID_VAL);
const bt_uuid_128 kWeatherCommandUuid = BT_UUID_INIT_128(TXING_WEATHER_COMMAND_UUID_VAL);
const bt_uuid_128 kWeatherStateUuid = BT_UUID_INIT_128(TXING_WEATHER_STATE_UUID_VAL);
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

struct RuntimeState
{
	std::uint8_t redcon = txing::weather::kRedconIdle;
	bool bme280_valid = false;
	std::uint16_t battery_mv = 0;
	txing::weather::MeasurementReport measurement{};
};

RuntimeState gRuntime{};
bt_conn *gConnection = nullptr;
extern const bt_gatt_attr attr_weather_service[];

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

txing::weather::StateReport current_state_report()
{
	return txing::weather::StateReport{
		.redcon = gRuntime.redcon,
		.active = gRuntime.redcon < txing::weather::kRedconIdle,
		.bme280_valid = gRuntime.bme280_valid,
		.battery_mv = gRuntime.battery_mv,
	};
}

void notify_state()
{
	if (gConnection == nullptr) {
		return;
	}
	std::array<std::uint8_t, 5> payload{};
	const std::size_t size = txing::weather::EncodeStateReport(
		current_state_report(),
		payload.data(),
		payload.size()
	);
	if (size > 0) {
		bt_gatt_notify(gConnection, &attr_weather_service[4], payload.data(), size);
	}
}

void notify_measurement()
{
	if (gConnection == nullptr || !gRuntime.bme280_valid) {
		return;
	}
	std::array<std::uint8_t, 13> payload{};
	const std::size_t size = txing::weather::EncodeMeasurementReport(
		gRuntime.measurement,
		payload.data(),
		payload.size()
	);
	if (size > 0) {
		bt_gatt_notify(gConnection, &attr_weather_service[7], payload.data(), size);
	}
}

void set_redcon(std::uint8_t redcon)
{
	gRuntime.redcon = redcon == txing::weather::kRedconIdle
		? txing::weather::kRedconIdle
		: txing::weather::kRedconActive;
	if (gRuntime.redcon == txing::weather::kRedconIdle) {
		gRuntime.bme280_valid = false;
	}
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
	gRuntime.measurement.temperature_centi_c = sensor_value_to_centi(temperature);
	gRuntime.measurement.pressure_pa = pressure_value_to_pa(pressure);
	gRuntime.measurement.humidity_centi_percent = static_cast<std::uint16_t>(
		sensor_value_to_centi(humidity)
	);
	gRuntime.measurement.battery_mv = gRuntime.battery_mv;
	gRuntime.bme280_valid = true;
	return true;
}

ssize_t read_state(bt_conn *conn, const bt_gatt_attr *attr, void *buf, std::uint16_t len, std::uint16_t offset)
{
	(void)attr;
	std::array<std::uint8_t, 5> payload{};
	const std::size_t size = txing::weather::EncodeStateReport(
		current_state_report(),
		payload.data(),
		payload.size()
	);
	return bt_gatt_attr_read(conn, attr, buf, len, offset, payload.data(), size);
}

ssize_t read_measurement(bt_conn *conn, const bt_gatt_attr *attr, void *buf, std::uint16_t len, std::uint16_t offset)
{
	(void)attr;
	std::array<std::uint8_t, 13> payload{};
	const std::size_t size = txing::weather::EncodeMeasurementReport(
		gRuntime.measurement,
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
	return len;
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
	BT_GATT_CCC(nullptr, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	BT_GATT_CHARACTERISTIC(
		&kWeatherMeasurementUuid.uuid,
		BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
		BT_GATT_PERM_READ,
		read_measurement,
		nullptr,
		nullptr
	),
	BT_GATT_CCC(nullptr, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE)
);

void connected(bt_conn *conn, std::uint8_t err)
{
	if (err != 0) {
		return;
	}
	if (gConnection != nullptr) {
		bt_conn_unref(gConnection);
	}
	gConnection = bt_conn_ref(conn);
	const bt_le_conn_param params = {
		.interval_min = kIdleConnInterval,
		.interval_max = kIdleConnInterval,
		.latency = kIdleConnLatency,
		.timeout = kIdleSupervisionTimeout,
	};
	bt_conn_le_param_update(conn, &params);
}

void disconnected(bt_conn *conn, std::uint8_t reason)
{
	(void)conn;
	(void)reason;
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
		if (gRuntime.redcon < txing::weather::kRedconIdle && sample_bme280()) {
			notify_measurement();
		}
		k_sleep(K_SECONDS(1));
	}
}
