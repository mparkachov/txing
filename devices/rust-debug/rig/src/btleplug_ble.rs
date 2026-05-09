use std::collections::HashMap;
use std::pin::Pin;
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use btleplug::api::{
    Central, Characteristic, Manager as _, Peripheral as _, ScanFilter, ValueNotification,
    WriteType,
};
use btleplug::platform::{Adapter, Manager, Peripheral};
use futures::{Stream, StreamExt};
use tokio::sync::Mutex;

use crate::ble::{BleCentral, BleConnectConfig, TimedState};
use crate::error::{Result, RigError};
use crate::event::EventEmitter;
use crate::protocol::{
    decode_state, encode_command, redcon_command_uuid, redcon_service_uuid, redcon_state_uuid,
};

type NotificationStream = Pin<Box<dyn Stream<Item = ValueNotification> + Send>>;

#[derive(Default)]
pub struct BtleplugBleCentral {
    adapter: Option<Adapter>,
    peripheral: Option<Peripheral>,
    command_char: Option<Characteristic>,
    state_char: Option<Characteristic>,
    notifications: Option<Arc<Mutex<NotificationStream>>>,
    last_rssi_by_address: HashMap<String, i16>,
}

impl BtleplugBleCentral {
    pub fn new() -> Self {
        Self::default()
    }

    async fn adapter(&mut self) -> Result<Adapter> {
        if let Some(adapter) = &self.adapter {
            return Ok(adapter.clone());
        }
        let manager = Manager::new()
            .await
            .map_err(|err| RigError::new("ble", format!("failed to create BLE manager: {err}")))?;
        let adapters = manager
            .adapters()
            .await
            .map_err(|err| RigError::new("ble", format!("failed to list BLE adapters: {err}")))?;
        let adapter = adapters
            .into_iter()
            .next()
            .ok_or_else(|| RigError::new("ble", "no BLE adapter found"))?;
        self.adapter = Some(adapter.clone());
        Ok(adapter)
    }

    async fn discover_target(
        &mut self,
        config: &BleConnectConfig,
        events: &mut EventEmitter,
    ) -> Result<Peripheral> {
        let adapter = self.adapter().await?;
        adapter
            .start_scan(ScanFilter::default())
            .await
            .map_err(|err| RigError::new("discover", format!("failed to start BLE scan: {err}")))?;

        let service_uuid = redcon_service_uuid();
        let deadline = Instant::now() + config.scan_timeout;
        let mut found = None;
        while Instant::now() < deadline {
            let peripherals = adapter.peripherals().await.map_err(|err| {
                RigError::new("discover", format!("failed to list peripherals: {err}"))
            })?;
            for peripheral in peripherals {
                let Ok(Some(properties)) = peripheral.properties().await else {
                    continue;
                };
                let name = properties
                    .local_name
                    .clone()
                    .or_else(|| peripheral_name_blocking(&peripheral));
                let address = properties.address.to_string();
                if let Some(rssi) = properties.rssi {
                    self.last_rssi_by_address.insert(address.clone(), rssi);
                }
                let service_matches = properties.services.iter().any(|uuid| *uuid == service_uuid);
                let name_matches = name.as_deref() == Some(config.name.as_str());
                if name_matches {
                    let mut fields = vec![
                        ("name", name.clone().unwrap_or_else(|| config.name.clone())),
                        ("address", address.clone()),
                    ];
                    match properties
                        .rssi
                        .or_else(|| self.last_rssi_by_address.get(&address).copied())
                    {
                        Some(rssi) => {
                            fields.push(("rssi", rssi.to_string()));
                            fields.push((
                                "rssiSource",
                                if properties.rssi.is_some() {
                                    "advertisement"
                                } else {
                                    "cached"
                                }
                                .to_string(),
                            ));
                        }
                        None => {
                            fields.push(("rssiSource", "unavailable".to_string()));
                        }
                    }
                    fields.push((
                        "service",
                        if service_matches { "1" } else { "0" }.to_string(),
                    ));
                    events.emit("adv", &fields);
                }
                if name_matches && (!config.require_service || service_matches) {
                    found = Some(peripheral);
                    break;
                }
            }
            if found.is_some() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(250)).await;
        }
        let _ = adapter.stop_scan().await;
        found.ok_or_else(|| {
            let suffix = if config.require_service {
                " with REDCON service UUID"
            } else {
                ""
            };
            RigError::new(
                "discover",
                format!("no matching advertisement for {:?}{suffix}", config.name),
            )
        })
    }

    async fn cleanup_after_failed_attempt(&mut self) {
        if let Some(peripheral) = self.peripheral.take() {
            if peripheral.is_connected().await.unwrap_or(false) {
                let _ = peripheral.disconnect().await;
            }
        }
        self.command_char = None;
        self.state_char = None;
        self.notifications = None;
    }
}

#[async_trait]
impl BleCentral for BtleplugBleCentral {
    async fn connect(
        &mut self,
        config: &BleConnectConfig,
        events: &mut EventEmitter,
    ) -> Result<()> {
        let mut last_error = None;
        for attempt in 1..=config.connect_attempts {
            match self.connect_attempt(config, attempt, events).await {
                Ok(()) => return Ok(()),
                Err(err) => {
                    last_error = Some(err);
                    self.cleanup_after_failed_attempt().await;
                    if attempt < config.connect_attempts {
                        if let Some(err) = &last_error {
                            events.emit(
                                "connect-retry",
                                &[
                                    ("attempt", attempt.to_string()),
                                    ("attempts", config.connect_attempts.to_string()),
                                    ("message", err.message.clone()),
                                ],
                            );
                        }
                        tokio::time::sleep(config.retry_delay).await;
                    }
                }
            }
        }
        Err(last_error.unwrap_or_else(|| RigError::new("connect", "unknown connect failure")))
    }

    async fn is_connected(&self) -> bool {
        match &self.peripheral {
            None => false,
            Some(peripheral) => peripheral.is_connected().await.unwrap_or(false),
        }
    }

    async fn read_state(&mut self) -> Result<TimedState> {
        let peripheral = self
            .peripheral
            .as_ref()
            .ok_or_else(|| RigError::new("connect", "not connected"))?;
        let state_char = self
            .state_char
            .as_ref()
            .ok_or_else(|| RigError::new("services", "state characteristic missing"))?;
        let payload = peripheral
            .read(state_char)
            .await
            .map_err(|err| RigError::new("state", format!("failed to read state: {err}")))?;
        Ok(TimedState {
            received_at: Instant::now(),
            state: decode_state(&payload)?,
        })
    }

    async fn write_redcon(&mut self, redcon: u8, events: &mut EventEmitter) -> Result<Instant> {
        let peripheral = self
            .peripheral
            .as_ref()
            .ok_or_else(|| RigError::new("connect", "not connected"))?;
        let command_char = self
            .command_char
            .as_ref()
            .ok_or_else(|| RigError::new("services", "command characteristic missing"))?;
        let payload = encode_command(redcon);
        let started = Instant::now();
        peripheral
            .write(command_char, &payload, WriteType::WithResponse)
            .await
            .map_err(|err| RigError::new("command", format!("failed to write command: {err}")))?;
        let fields = vec![
            ("redcon", redcon.to_string()),
            ("payload", hex_lower(&payload)),
        ];
        events.emit("command", &fields);
        Ok(started)
    }

    async fn next_state(&mut self, timeout: Duration) -> Result<TimedState> {
        let notifications = self
            .notifications
            .as_ref()
            .ok_or_else(|| RigError::new("notify", "state notification stream is not active"))?
            .clone();
        let state_uuid = redcon_state_uuid();
        let fut = async {
            let mut stream = notifications.lock().await;
            loop {
                match stream.next().await {
                    Some(notification) if notification.uuid == state_uuid => {
                        return Ok(TimedState {
                            received_at: Instant::now(),
                            state: decode_state(&notification.value)?,
                        });
                    }
                    Some(_) => continue,
                    None => return Err(RigError::new("disconnect", "notification stream closed")),
                }
            }
        };
        tokio::time::timeout(timeout, fut)
            .await
            .map_err(|_| RigError::new("timeout", "state deadline expired"))?
    }

    async fn wait_for_disconnect(&mut self, timeout: Duration) -> Result<()> {
        let Some(peripheral) = self.peripheral.as_ref().cloned() else {
            return Ok(());
        };
        let deadline = Instant::now() + timeout;
        while Instant::now() < deadline {
            if !peripheral.is_connected().await.unwrap_or(false) {
                self.peripheral = None;
                return Ok(());
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        Err(RigError::new(
            "sleep",
            "device did not disconnect after REDCON 4",
        ))
    }

    async fn close(&mut self) -> Result<()> {
        if let (Some(peripheral), Some(state_char)) = (&self.peripheral, &self.state_char) {
            let _ = peripheral.unsubscribe(state_char).await;
        }
        if let Some(peripheral) = self.peripheral.take() {
            if peripheral.is_connected().await.unwrap_or(false) {
                peripheral
                    .disconnect()
                    .await
                    .map_err(|err| RigError::new("disconnect", err.to_string()))?;
            }
        }
        self.command_char = None;
        self.state_char = None;
        self.notifications = None;
        Ok(())
    }
}

impl BtleplugBleCentral {
    async fn connect_attempt(
        &mut self,
        config: &BleConnectConfig,
        attempt: u32,
        events: &mut EventEmitter,
    ) -> Result<()> {
        let peripheral = self.discover_target(config, events).await?;
        let address = peripheral
            .properties()
            .await
            .ok()
            .flatten()
            .map(|properties| properties.address.to_string())
            .unwrap_or_else(|| "unknown".to_string());
        let started = Instant::now();
        tokio::time::timeout(config.connect_timeout, peripheral.connect())
            .await
            .map_err(|_| RigError::new("connect", "connect timeout expired"))?
            .map_err(|err| RigError::new("connect", format!("connect failed: {err}")))?;
        events.emit(
            "connected",
            &[
                ("name", config.name.clone()),
                ("address", address),
                ("os", std::env::consts::OS.to_string()),
                ("backend", backend_name().to_string()),
                ("attempt", attempt.to_string()),
                ("connectMs", started.elapsed().as_millis().to_string()),
                ("sinceStartMs", "0".to_string()),
            ],
        );

        let services_started = Instant::now();
        peripheral
            .discover_services()
            .await
            .map_err(|err| RigError::new("services", format!("service discovery failed: {err}")))?;
        let characteristics = peripheral.characteristics();
        let command_uuid = redcon_command_uuid();
        let state_uuid = redcon_state_uuid();
        let command_char = characteristics
            .iter()
            .find(|characteristic| characteristic.uuid == command_uuid)
            .cloned();
        let state_char = characteristics
            .iter()
            .find(|characteristic| characteristic.uuid == state_uuid)
            .cloned();
        events.emit(
            "services",
            &[
                ("command", (command_char.is_some() as u8).to_string()),
                ("state", (state_char.is_some() as u8).to_string()),
                (
                    "servicesMs",
                    services_started.elapsed().as_millis().to_string(),
                ),
            ],
        );
        let command_char = command_char.ok_or_else(|| {
            RigError::new("services", "required command characteristic is missing")
        })?;
        let state_char = state_char
            .ok_or_else(|| RigError::new("services", "required state characteristic is missing"))?;
        let notifications = peripheral
            .notifications()
            .await
            .map_err(|err| RigError::new("notify", format!("notification stream failed: {err}")))?;
        peripheral
            .subscribe(&state_char)
            .await
            .map_err(|err| RigError::new("notify", format!("failed to subscribe state: {err}")))?;
        events.emit(
            "notify",
            &[
                ("characteristic", "state".to_string()),
                ("enabled", "1".to_string()),
            ],
        );
        self.peripheral = Some(peripheral);
        self.command_char = Some(command_char);
        self.state_char = Some(state_char);
        self.notifications = Some(Arc::new(Mutex::new(Box::pin(notifications))));
        let _ = self.read_state().await?;
        Ok(())
    }
}

fn backend_name() -> &'static str {
    match std::env::consts::OS {
        "macos" => "corebluetooth",
        "linux" => "bluez",
        other => other,
    }
}

fn peripheral_name_blocking(_peripheral: &Peripheral) -> Option<String> {
    None
}

fn hex_lower(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
