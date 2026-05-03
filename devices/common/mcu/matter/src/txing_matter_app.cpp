/*
 * Copyright (c) 2026 txing contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#include "txing/matter/txing_matter_app.h"

#include "app/matter_init.h"
#include "app/task_executor.h"
#include "board/board.h"
#include "board/led_widget.h"
#include "clusters/identify.h"

#include <app/DefaultTimerDelegate.h>
#include <lib/support/CodeUtils.h>
#include <platform/CHIPDeviceLayer.h>

#ifdef CONFIG_USB_DEVICE_STACK
#include <zephyr/usb/usb_device.h>
#endif

#include <array>
#include <cstdlib>
#include <new>
#include <type_traits>

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_DECLARE(app, CONFIG_CHIP_APP_LOG_LEVEL);

using namespace chip;

namespace txing::matter
{
namespace
{
constexpr size_t kMaxIdentifyEndpoints = 4;
constexpr size_t kIdentifyTimerIntervalMs = 500;
constexpr auto kIdentifyType = app::Clusters::Identify::IdentifyTypeEnum::kLightOutput;

MatterDevice *sDevice = nullptr;
MatterAppConfig sConfig;
k_timer sMeasurementsTimer;
k_timer sIdentifyTimer;
Nrf::LEDWidget *sRedLED = nullptr;
Nrf::LEDWidget *sGreenLED = nullptr;
Nrf::LEDWidget *sBlueLED = nullptr;
app::DefaultTimerDelegate sTimerDelegate;

class IdentifyDelegate final : public app::Clusters::IdentifyDelegate {
public:
	void OnIdentifyStart(app::Clusters::IdentifyCluster &cluster) override
	{
		Nrf::PostTask([] { Nrf::GetBoard().GetLED(Nrf::DeviceLeds::LED2).Blink(Nrf::LedConsts::kIdentifyBlinkRate_ms); });
	}

	void OnIdentifyStop(app::Clusters::IdentifyCluster &cluster) override
	{
		Nrf::PostTask([] { Nrf::GetBoard().GetLED(Nrf::DeviceLeds::LED2).Set(false); });
	}

	void OnTriggerEffect(app::Clusters::IdentifyCluster &cluster) override {}

	bool IsTriggerEffectEnabled() const override { return false; }
};

IdentifyDelegate sIdentifyDelegate;

using IdentifyCluster = Nrf::Matter::IdentifyCluster;
std::array<std::aligned_storage_t<sizeof(IdentifyCluster), alignof(IdentifyCluster)>, kMaxIdentifyEndpoints>
	sIdentifyStorage;
std::array<IdentifyCluster *, kMaxIdentifyEndpoints> sIdentifyClusters = {};

void UpdateLedState()
{
	if (!sGreenLED || !sBlueLED || !sRedLED) {
		return;
	}

	sGreenLED->Set(false);
	sBlueLED->Set(false);
	sRedLED->Set(false);

	switch (Nrf::GetBoard().GetDeviceState()) {
	case Nrf::DeviceState::DeviceAdvertisingBLE:
		sBlueLED->Blink(Nrf::LedConsts::StatusLed::Disconnected::kOn_ms,
				Nrf::LedConsts::StatusLed::Disconnected::kOff_ms);
		break;
	case Nrf::DeviceState::DeviceDisconnected:
		sGreenLED->Blink(Nrf::LedConsts::StatusLed::Disconnected::kOn_ms,
				 Nrf::LedConsts::StatusLed::Disconnected::kOff_ms);
		break;
	case Nrf::DeviceState::DeviceConnectedBLE:
		sBlueLED->Blink(Nrf::LedConsts::StatusLed::BleConnected::kOn_ms,
				Nrf::LedConsts::StatusLed::BleConnected::kOff_ms);
		break;
	case Nrf::DeviceState::DeviceProvisioned:
		sRedLED->Blink(Nrf::LedConsts::StatusLed::Disconnected::kOn_ms,
			       Nrf::LedConsts::StatusLed::Disconnected::kOff_ms);
		sBlueLED->Blink(Nrf::LedConsts::StatusLed::Disconnected::kOn_ms,
				Nrf::LedConsts::StatusLed::Disconnected::kOff_ms);
		break;
	default:
		break;
	}
}

void MeasurementsTimerHandler()
{
	if (sDevice == nullptr) {
		return;
	}

	sDevice->BeforeSample();
	sDevice->SampleAndPublish();
	PublishPowerSource(sConfig.power_source_endpoint, sDevice->ReadBatteryState());
	sDevice->AfterSample();
}

CHIP_ERROR EnableUsbIfConfigured()
{
#ifdef CONFIG_USB_DEVICE_STACK
	CHIP_ERROR err = System::MapErrorZephyr(usb_enable(nullptr));
	if (err != CHIP_NO_ERROR) {
		LOG_ERR("Failed to initialize USB device");
	}
	return err;
#else
	return CHIP_NO_ERROR;
#endif
}

CHIP_ERROR InitIdentifyClusters(const MatterAppConfig &config)
{
	if (config.identify_endpoint_count > kMaxIdentifyEndpoints) {
		LOG_ERR("Too many identify endpoints: %u", static_cast<unsigned>(config.identify_endpoint_count));
		return CHIP_ERROR_INVALID_ARGUMENT;
	}

	for (size_t i = 0; i < config.identify_endpoint_count; ++i) {
		void *storage = &sIdentifyStorage[i];
		sIdentifyClusters[i] = new (storage)
			IdentifyCluster(config.identify_endpoints[i], sIdentifyDelegate, sTimerDelegate, kIdentifyType);
		ReturnErrorOnFailure(sIdentifyClusters[i]->Init());
	}

	return CHIP_NO_ERROR;
}

CHIP_ERROR InitMatterApp(MatterDevice &device, const MatterAppConfig &config)
{
	ReturnErrorOnFailure(EnableUsbIfConfigured());
	ReturnErrorOnFailure(Nrf::Matter::PrepareServer());

	sRedLED = &Nrf::GetBoard().GetLED(Nrf::DeviceLeds::LED1);
	sGreenLED = &Nrf::GetBoard().GetLED(Nrf::DeviceLeds::LED2);
	sBlueLED = &Nrf::GetBoard().GetLED(Nrf::DeviceLeds::LED3);

	if (!Nrf::GetBoard().Init(nullptr, UpdateLedState)) {
		LOG_ERR("User interface initialization failed");
		return CHIP_ERROR_INCORRECT_STATE;
	}

	ReturnErrorOnFailure(Nrf::Matter::RegisterEventHandler(Nrf::Board::DefaultMatterEventHandler, 0));
	ReturnErrorOnFailure(device.InitHardware());
	ReturnErrorOnFailure(InitIdentifyClusters(config));

	k_timer_init(&sMeasurementsTimer, [](k_timer *) { Nrf::PostTask([] { MeasurementsTimerHandler(); }); }, nullptr);
	k_timer_init(&sIdentifyTimer, [](k_timer *) {}, nullptr);
	k_timer_start(&sMeasurementsTimer, K_MSEC(config.measurement_interval_ms), K_MSEC(config.measurement_interval_ms));

	return Nrf::Matter::StartServer();
}
} // namespace

CHIP_ERROR RunMatterApp(MatterDevice &device, const MatterAppConfig &config)
{
	sDevice = &device;
	sConfig = config;

	CHIP_ERROR err = InitMatterApp(device, config);
	if (err != CHIP_NO_ERROR) {
		LOG_ERR("Matter app initialization failed: %" CHIP_ERROR_FORMAT, err.Format());
		return err;
	}

	while (true) {
		Nrf::DispatchNextTask();
	}

	return CHIP_NO_ERROR;
}

} // namespace txing::matter
