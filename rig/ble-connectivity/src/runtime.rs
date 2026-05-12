#![cfg_attr(
    not(all(feature = "greengrass-sdk", target_os = "linux")),
    allow(dead_code, unused_imports)
)]

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::sync::Arc;
#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
use std::sync::OnceLock;
use std::time::Duration;

use anyhow::{Context, Result, anyhow, bail};
#[cfg(all(feature = "ble-real", target_os = "linux"))]
use btleplug::api::{
    Central, Characteristic, Manager as _, Peripheral as _, ScanFilter, WriteType,
};
#[cfg(all(feature = "ble-real", target_os = "linux"))]
use btleplug::platform::{Adapter, Manager, Peripheral};
#[cfg(all(feature = "ble-real", target_os = "linux"))]
use futures::StreamExt;
use tokio::sync::{Semaphore, broadcast, mpsc};
use tokio::time::{MissedTickBehavior, interval, timeout};
use uuid::Uuid;

use crate::ble_protocol::{
    ADAPTER_ID, Advertisement, BLE_CAPABILITY, CapabilitySample, DeviceKind, DeviceSpec,
    POWER_CAPABILITY, POWER_MEASUREMENT_UUID, PowerMeasurement, PowerState, REDCON_IDLE,
    ShadowUpdate, TXING_BLE_COMMAND_UUID, TXING_BLE_STATE_UUID, WEATHER_CAPABILITY,
    WEATHER_MEASUREMENT_UUID, WeatherMeasurement, WeatherState, advertisement_sample,
    capability_state_from_sample, encode_redcon_command, now_ms, offline_sample,
    parse_power_measurement, parse_power_state, parse_weather_measurement, parse_weather_state,
    power_state_sample, shadow_updates_from_sample, weather_state_sample,
};
use txing_capability_protocol::{
    CAPABILITY_COMMAND_TOPIC_PREFIX, COMMAND_ACCEPTED, COMMAND_FAILED, COMMAND_SUCCEEDED,
    CapabilityCommand, CapabilityCommandResult, CapabilityHeartbeat, INVENTORY_TOPIC, Inventory,
    build_capability_command_result_topic, build_capability_heartbeat_topic,
    build_capability_state_topic, command_deadline_expired, normalize_ble_target_redcon,
    parse_capability_command_topic,
};

const SCANNER_BUFFER: usize = 256;
const SCAN_POLL_INTERVAL_MS: u64 = 500;
const STALE_CHECK_INTERVAL_MS: u64 = 500;
const NOTIFICATION_DRAIN_INTERVAL_MS: u64 = 100;
const SHADOW_PUBLISH_INTERVAL_MS: u64 = 500;
const SHADOW_PUBLISH_RETRY_LOG_INTERVAL_MS: u64 = 10_000;
const REDCON_ACTIVE_MEASUREMENT_STALE_MS: u64 = 20_000;
const REDCON_IDLE_MEASUREMENT_STALE_MS: u64 = 120_000;

#[derive(Debug, Clone)]
pub struct RuntimeConfig {
    pub adapter_id: String,
    pub scan_interval_ms: u64,
    pub presence_timeout_ms: u64,
    pub reconnect_delay_ms: u64,
    pub connect_timeout_ms: u64,
    pub command_timeout_ms: u64,
    pub heartbeat_interval_ms: u64,
    pub max_connections: usize,
    pub no_ble: bool,
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self {
            adapter_id: ADAPTER_ID.to_string(),
            scan_interval_ms: SCAN_POLL_INTERVAL_MS,
            presence_timeout_ms: 20_000,
            reconnect_delay_ms: 2_000,
            connect_timeout_ms: 8_000,
            command_timeout_ms: 8_000,
            heartbeat_interval_ms: 10_000,
            max_connections: 0,
            no_ble: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OutboundMessage {
    pub topic: String,
    pub payload: Vec<u8>,
}

#[derive(Debug, Default)]
struct PendingShadowUpdates {
    updates: BTreeMap<String, ShadowUpdate>,
    order: VecDeque<String>,
}

impl PendingShadowUpdates {
    fn push(&mut self, update: ShadowUpdate) {
        if !self.updates.contains_key(&update.topic) {
            self.order.push_back(update.topic.clone());
        }
        self.updates.insert(update.topic.clone(), update);
    }

    fn pop(&mut self) -> Option<ShadowUpdate> {
        while let Some(topic) = self.order.pop_front() {
            if let Some(update) = self.updates.remove(&topic) {
                return Some(update);
            }
        }
        None
    }

    fn is_empty(&self) -> bool {
        self.updates.is_empty()
    }

    fn len(&self) -> usize {
        self.updates.len()
    }
}

#[derive(Debug, Clone)]
enum LocalEvent {
    Message { topic: String, payload: Vec<u8> },
}

#[derive(Debug)]
struct ManagedSession {
    command_sender: mpsc::UnboundedSender<CapabilityCommand>,
    task: tokio::task::JoinHandle<()>,
}

struct RuntimeState {
    config: RuntimeConfig,
    advertisements: broadcast::Sender<Advertisement>,
    outbound_sender: mpsc::UnboundedSender<OutboundMessage>,
    shadow_sender: mpsc::UnboundedSender<ShadowUpdate>,
    connection_semaphore: Option<Arc<Semaphore>>,
    sessions: BTreeMap<String, ManagedSession>,
    device_specs: BTreeMap<String, DeviceSpec>,
}

impl RuntimeState {
    fn new(
        config: RuntimeConfig,
        advertisements: broadcast::Sender<Advertisement>,
        outbound_sender: mpsc::UnboundedSender<OutboundMessage>,
        shadow_sender: mpsc::UnboundedSender<ShadowUpdate>,
    ) -> Self {
        let connection_semaphore =
            (config.max_connections > 0).then(|| Arc::new(Semaphore::new(config.max_connections)));
        Self {
            config,
            advertisements,
            outbound_sender,
            shadow_sender,
            connection_semaphore,
            sessions: BTreeMap::new(),
            device_specs: BTreeMap::new(),
        }
    }

    async fn handle_local_message(&mut self, topic: String, payload: Vec<u8>) -> Result<()> {
        if topic == INVENTORY_TOPIC {
            let inventory = Inventory::from_slice(&payload)
                .with_context(|| format!("decode v2 inventory from topic {topic}"))?;
            self.reconcile_inventory(inventory).await?;
            return Ok(());
        }

        let Some(topic_thing_name) = parse_capability_command_topic(&topic) else {
            return Ok(());
        };
        let command = CapabilityCommand::from_slice(&payload)
            .with_context(|| format!("decode v2 capability command from topic {topic}"))?;
        if command.thing_name != topic_thing_name {
            bail!(
                "command topic thingName {topic_thing_name} differs from payload thingName {}",
                command.thing_name
            );
        }
        self.handle_command(command).await
    }

    async fn reconcile_inventory(&mut self, inventory: Inventory) -> Result<()> {
        let wanted = inventory
            .devices
            .iter()
            .filter_map(device_spec_from_inventory)
            .map(|spec| (spec.thing_name.clone(), spec))
            .collect::<BTreeMap<_, _>>();
        let wanted_names = wanted.keys().cloned().collect::<BTreeSet<_>>();

        let removed = self
            .sessions
            .keys()
            .filter(|thing_name| !wanted_names.contains(*thing_name))
            .cloned()
            .collect::<Vec<_>>();
        for thing_name in removed {
            if let Some(session) = self.sessions.remove(&thing_name) {
                session.task.abort();
                let _ = session.task.await;
            }
            self.device_specs.remove(&thing_name);
        }

        for (thing_name, spec) in wanted {
            self.device_specs.insert(thing_name.clone(), spec.clone());
            if self.sessions.contains_key(&thing_name) {
                continue;
            }
            let (command_sender, command_receiver) = mpsc::unbounded_channel();
            let task = tokio::spawn(run_device_session(
                spec,
                self.config.clone(),
                self.advertisements.subscribe(),
                command_receiver,
                self.outbound_sender.clone(),
                self.shadow_sender.clone(),
                self.connection_semaphore.clone(),
            ));
            self.sessions.insert(
                thing_name,
                ManagedSession {
                    command_sender,
                    task,
                },
            );
        }
        Ok(())
    }

    async fn handle_command(&self, command: CapabilityCommand) -> Result<()> {
        if !self.device_specs.contains_key(&command.thing_name) {
            return Ok(());
        }
        if command_deadline_expired(&command, now_ms()) {
            publish_command_result(
                &self.config.adapter_id,
                &self.outbound_sender,
                &command,
                COMMAND_FAILED,
                Some(format!(
                    "BLE command deadline expired deadlineMs={:?}",
                    command.deadline_ms
                )),
                Some(command.target.redcon),
            )?;
            return Ok(());
        }
        let Some(session) = self.sessions.get(&command.thing_name) else {
            publish_command_result(
                &self.config.adapter_id,
                &self.outbound_sender,
                &command,
                COMMAND_FAILED,
                Some("BLE thing is not in active inventory".to_string()),
                Some(command.target.redcon),
            )?;
            return Ok(());
        };
        publish_command_result(
            &self.config.adapter_id,
            &self.outbound_sender,
            &command,
            COMMAND_ACCEPTED,
            None,
            Some(command.target.redcon),
        )?;
        session
            .command_sender
            .send(command)
            .map_err(|_| anyhow!("BLE device session command channel is closed"))?;
        Ok(())
    }

    async fn shutdown(&mut self) {
        for (_, session) in std::mem::take(&mut self.sessions) {
            session.task.abort();
            let _ = session.task.await;
        }
    }
}

fn device_spec_from_inventory(
    device: &txing_capability_protocol::InventoryDevice,
) -> Option<DeviceSpec> {
    if !device.has_capability(BLE_CAPABILITY) {
        return None;
    }
    let kind = if device.has_capability(WEATHER_CAPABILITY) {
        DeviceKind::Weather
    } else if device.has_capability(POWER_CAPABILITY) {
        DeviceKind::Power
    } else {
        return None;
    };
    Some(DeviceSpec {
        thing_name: device.thing_name.clone(),
        kind,
    })
}

async fn run_device_session(
    spec: DeviceSpec,
    config: RuntimeConfig,
    mut advertisements: broadcast::Receiver<Advertisement>,
    mut commands: mpsc::UnboundedReceiver<CapabilityCommand>,
    outbound_sender: mpsc::UnboundedSender<OutboundMessage>,
    shadow_sender: mpsc::UnboundedSender<ShadowUpdate>,
    connection_semaphore: Option<Arc<Semaphore>>,
) {
    let mut session = DeviceSession::new(
        spec,
        config,
        outbound_sender,
        shadow_sender,
        connection_semaphore,
    );
    if let Err(err) = session.run(&mut advertisements, &mut commands).await {
        eprintln!(
            "warning: BLE device session ended thing={} error={err:#}",
            session.spec.thing_name
        );
    }
}

struct DeviceSession {
    spec: DeviceSpec,
    config: RuntimeConfig,
    outbound_sender: mpsc::UnboundedSender<OutboundMessage>,
    shadow_sender: mpsc::UnboundedSender<ShadowUpdate>,
    connection_semaphore: Option<Arc<Semaphore>>,
    seq: u64,
    last_advertisement: Option<Advertisement>,
    last_redcon: Option<u8>,
    last_power_measurement: Option<TimedMeasurement<PowerMeasurement>>,
    last_weather_measurement: Option<TimedMeasurement<WeatherMeasurement>>,
    connected: Option<ConnectedDevice>,
    next_connect_after_ms: u64,
    offline_published: bool,
}

#[derive(Debug, Clone)]
struct TimedMeasurement<T> {
    value: T,
    observed_at_ms: u64,
}

impl DeviceSession {
    fn new(
        spec: DeviceSpec,
        config: RuntimeConfig,
        outbound_sender: mpsc::UnboundedSender<OutboundMessage>,
        shadow_sender: mpsc::UnboundedSender<ShadowUpdate>,
        connection_semaphore: Option<Arc<Semaphore>>,
    ) -> Self {
        Self {
            spec,
            config,
            outbound_sender,
            shadow_sender,
            connection_semaphore,
            seq: 0,
            last_advertisement: None,
            last_redcon: None,
            last_power_measurement: None,
            last_weather_measurement: None,
            connected: None,
            next_connect_after_ms: 0,
            offline_published: false,
        }
    }

    async fn run(
        &mut self,
        advertisements: &mut broadcast::Receiver<Advertisement>,
        commands: &mut mpsc::UnboundedReceiver<CapabilityCommand>,
    ) -> Result<()> {
        if self.config.no_ble {
            self.publish_offline().await?;
            while let Some(command) = commands.recv().await {
                publish_command_result(
                    &self.config.adapter_id,
                    &self.outbound_sender,
                    &command,
                    COMMAND_FAILED,
                    Some("BLE is disabled for this component instance".to_string()),
                    Some(command.target.redcon),
                )?;
            }
            return Ok(());
        }

        let mut stale_timer = interval(Duration::from_millis(STALE_CHECK_INTERVAL_MS));
        stale_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);
        let mut notification_timer =
            interval(Duration::from_millis(NOTIFICATION_DRAIN_INTERVAL_MS));
        notification_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);

        loop {
            tokio::select! {
                received = advertisements.recv() => {
                    match received {
                        Ok(advertisement) => self.handle_advertisement(advertisement).await?,
                        Err(broadcast::error::RecvError::Lagged(skipped)) => {
                            eprintln!("warning: BLE advertisement receiver lagged thing={} skipped={skipped}", self.spec.thing_name);
                        }
                        Err(broadcast::error::RecvError::Closed) => break,
                    }
                }
                Some(command) = commands.recv() => {
                    self.handle_command(command).await?;
                }
                _ = stale_timer.tick() => {
                    self.check_stale().await?;
                }
                _ = notification_timer.tick(), if self.connected.is_some() => {
                    self.drain_notifications().await?;
                }
            }
        }
        Ok(())
    }

    async fn handle_advertisement(&mut self, advertisement: Advertisement) -> Result<()> {
        if !advertisement.matches_thing(&self.spec.thing_name) {
            return Ok(());
        }
        self.last_advertisement = Some(advertisement.clone());
        self.offline_published = false;

        if self.connected.is_some() {
            return Ok(());
        }
        let now = now_ms();
        if now < self.next_connect_after_ms {
            return Ok(());
        }

        let seq = self.next_seq();
        self.publish_sample(advertisement_sample(&self.spec, &advertisement, seq))?;
        match self.connect(false).await {
            Ok(()) => {
                self.next_connect_after_ms = 0;
            }
            Err(err) => {
                self.next_connect_after_ms =
                    now_ms().saturating_add(self.config.reconnect_delay_ms);
                eprintln!(
                    "warning: BLE connect from advertisement failed thing={} address={} retryAfterMs={} error={err:#}",
                    self.spec.thing_name, advertisement.address, self.next_connect_after_ms
                );
            }
        }
        Ok(())
    }

    async fn handle_command(&mut self, command: CapabilityCommand) -> Result<()> {
        if command_deadline_expired(&command, now_ms()) {
            publish_command_result(
                &self.config.adapter_id,
                &self.outbound_sender,
                &command,
                COMMAND_FAILED,
                Some(format!(
                    "BLE command deadline expired deadlineMs={:?}",
                    command.deadline_ms
                )),
                Some(command.target.redcon),
            )?;
            return Ok(());
        }

        if self.spec.kind == DeviceKind::Weather && command.target.redcon != REDCON_IDLE {
            publish_command_result(
                &self.config.adapter_id,
                &self.outbound_sender,
                &command,
                COMMAND_FAILED,
                Some(format!(
                    "weather BLE only supports REDCON 4, got {}",
                    command.target.redcon
                )),
                Some(command.target.redcon),
            )?;
            return Ok(());
        }

        let target_redcon = match normalize_ble_target_redcon(command.target.redcon) {
            Ok(value) => value,
            Err(err) => {
                publish_command_result(
                    &self.config.adapter_id,
                    &self.outbound_sender,
                    &command,
                    COMMAND_FAILED,
                    Some(err.to_string()),
                    Some(command.target.redcon),
                )?;
                return Ok(());
            }
        };

        if let Err(err) = self.connect(true).await {
            publish_command_result(
                &self.config.adapter_id,
                &self.outbound_sender,
                &command,
                COMMAND_FAILED,
                Some(format!(
                    "BLE connection failed before command write: {err:#}"
                )),
                Some(command.target.redcon),
            )?;
            return Ok(());
        }

        let Some(connected) = self.connected.as_mut() else {
            publish_command_result(
                &self.config.adapter_id,
                &self.outbound_sender,
                &command,
                COMMAND_FAILED,
                Some("BLE connection is unavailable".to_string()),
                Some(command.target.redcon),
            )?;
            return Ok(());
        };

        if let Err(err) = connected
            .write_redcon(target_redcon, self.config.command_timeout_ms)
            .await
        {
            self.connected = None;
            publish_command_result(
                &self.config.adapter_id,
                &self.outbound_sender,
                &command,
                COMMAND_FAILED,
                Some(format!("BLE command write failed: {err:#}")),
                Some(command.target.redcon),
            )?;
            return Ok(());
        }

        self.last_redcon = Some(target_redcon);
        self.seed_connected_state().await?;
        publish_command_result(
            &self.config.adapter_id,
            &self.outbound_sender,
            &command,
            COMMAND_SUCCEEDED,
            None,
            Some(command.target.redcon),
        )?;
        Ok(())
    }

    async fn connect(&mut self, wait_for_cap: bool) -> Result<()> {
        if let Some(connected) = &self.connected {
            if connected.is_connected().await {
                return Ok(());
            }
        }
        self.connected = None;
        let advertisement = self.last_advertisement.clone().ok_or_else(|| {
            anyhow!(
                "no BLE advertisement has been observed for {}",
                self.spec.thing_name
            )
        })?;
        if !self.advertisement_is_fresh(&advertisement) {
            bail!(
                "last BLE advertisement for {} is stale",
                self.spec.thing_name
            );
        }
        let permit = match self.connection_semaphore.clone() {
            Some(semaphore) if wait_for_cap => Some(semaphore.acquire_owned().await?),
            Some(semaphore) => match semaphore.try_acquire_owned() {
                Ok(permit) => Some(permit),
                Err(_) => return Ok(()),
            },
            None => None,
        };
        let connected = ConnectedDevice::connect(
            &self.spec,
            &advertisement,
            self.config.connect_timeout_ms,
            permit,
        )
        .await?;
        self.connected = Some(connected);
        self.seed_connected_state().await?;
        Ok(())
    }

    async fn seed_connected_state(&mut self) -> Result<()> {
        let Some(connected) = self.connected.as_mut() else {
            return Ok(());
        };
        if !connected.is_connected().await {
            self.connected = None;
            self.check_stale().await?;
            return Ok(());
        }

        let now = now_ms();
        match self.spec.kind {
            DeviceKind::Power => {
                match connected
                    .read_power_state(self.config.command_timeout_ms)
                    .await
                {
                    Ok(state) => {
                        self.last_redcon = Some(state.redcon);
                    }
                    Err(err) => {
                        eprintln!(
                            "warning: BLE power state read failed thing={} error={err:#}",
                            self.spec.thing_name
                        );
                        self.connected = None;
                        return Ok(());
                    }
                }
                match connected
                    .read_power_measurement(self.config.command_timeout_ms)
                    .await
                {
                    Ok(measurement) => {
                        self.last_power_measurement = Some(TimedMeasurement {
                            value: measurement,
                            observed_at_ms: now,
                        });
                    }
                    Err(err) => {
                        eprintln!(
                            "warning: BLE power measurement read failed thing={} error={err:#}",
                            self.spec.thing_name
                        );
                        self.last_power_measurement = None;
                    }
                }
            }
            DeviceKind::Weather => {
                match connected
                    .read_weather_state(self.config.command_timeout_ms)
                    .await
                {
                    Ok(state) => {
                        self.last_redcon = Some(state.redcon);
                    }
                    Err(err) => {
                        eprintln!(
                            "warning: BLE weather state read failed thing={} error={err:#}",
                            self.spec.thing_name
                        );
                        self.connected = None;
                        return Ok(());
                    }
                }
                match connected
                    .read_power_measurement(self.config.command_timeout_ms)
                    .await
                {
                    Ok(measurement) => {
                        self.last_power_measurement = Some(TimedMeasurement {
                            value: measurement,
                            observed_at_ms: now,
                        });
                    }
                    Err(err) => {
                        eprintln!(
                            "warning: BLE weather power measurement read failed thing={} error={err:#}",
                            self.spec.thing_name
                        );
                        self.last_power_measurement = None;
                    }
                }
                match connected
                    .read_weather_measurement(self.config.command_timeout_ms)
                    .await
                {
                    Ok(measurement) => {
                        self.last_weather_measurement = Some(TimedMeasurement {
                            value: measurement,
                            observed_at_ms: now,
                        });
                    }
                    Err(err) => {
                        eprintln!(
                            "warning: BLE weather measurement read failed thing={} error={err:#}",
                            self.spec.thing_name
                        );
                        self.last_weather_measurement = None;
                    }
                }
            }
        }
        self.publish_aggregate_sample(now)?;
        Ok(())
    }

    async fn drain_notifications(&mut self) -> Result<()> {
        let Some(connected) = self.connected.as_mut() else {
            return Ok(());
        };
        if !connected.is_connected().await {
            self.connected = None;
            self.check_stale().await?;
            return Ok(());
        }
        let notifications = connected.drain_notifications();
        for notification in notifications {
            self.handle_notification(notification)?;
        }
        Ok(())
    }

    fn handle_notification(&mut self, notification: BleNotification) -> Result<()> {
        let now = now_ms();
        if notification.uuid == TXING_BLE_STATE_UUID {
            match self.spec.kind {
                DeviceKind::Power => match parse_power_state(&notification.payload) {
                    Ok(state) => self.last_redcon = Some(state.redcon),
                    Err(err) => eprintln!(
                        "warning: BLE power state notification ignored thing={} error={err:#}",
                        self.spec.thing_name
                    ),
                },
                DeviceKind::Weather => match parse_weather_state(&notification.payload) {
                    Ok(state) => self.last_redcon = Some(state.redcon),
                    Err(err) => eprintln!(
                        "warning: BLE weather state notification ignored thing={} error={err:#}",
                        self.spec.thing_name
                    ),
                },
            }
            self.publish_aggregate_sample(now)?;
            return Ok(());
        }
        if notification.uuid == POWER_MEASUREMENT_UUID {
            match parse_power_measurement(&notification.payload) {
                Ok(measurement) => {
                    self.last_power_measurement = Some(TimedMeasurement {
                        value: measurement,
                        observed_at_ms: now,
                    });
                    self.publish_aggregate_sample(now)?;
                }
                Err(err) => eprintln!(
                    "warning: BLE power measurement notification ignored thing={} error={err:#}",
                    self.spec.thing_name
                ),
            }
            return Ok(());
        }
        if notification.uuid == WEATHER_MEASUREMENT_UUID && self.spec.kind.supports_weather() {
            match parse_weather_measurement(&notification.payload) {
                Ok(measurement) => {
                    self.last_weather_measurement = Some(TimedMeasurement {
                        value: measurement,
                        observed_at_ms: now,
                    });
                    self.publish_aggregate_sample(now)?;
                }
                Err(err) => eprintln!(
                    "warning: BLE weather measurement notification ignored thing={} error={err:#}",
                    self.spec.thing_name
                ),
            }
        }
        Ok(())
    }

    async fn check_stale(&mut self) -> Result<()> {
        let now = now_ms();
        if self.connected.is_some() {
            let mut changed = false;
            if self.power_measurement_stale(now) {
                self.last_power_measurement = None;
                changed = true;
            }
            if self.weather_measurement_stale(now) {
                self.last_weather_measurement = None;
                changed = true;
            }
            if changed {
                self.publish_aggregate_sample(now)?;
            }
            return Ok(());
        }
        let fresh = self
            .last_advertisement
            .as_ref()
            .is_some_and(|advertisement| self.advertisement_is_fresh(advertisement));
        if fresh {
            return Ok(());
        }
        if !self.offline_published {
            self.publish_offline().await?;
        }
        Ok(())
    }

    async fn publish_offline(&mut self) -> Result<()> {
        self.last_redcon = None;
        self.last_power_measurement = None;
        self.last_weather_measurement = None;
        let seq = self.next_seq();
        let sample = offline_sample(&self.spec, seq, now_ms());
        self.publish_sample(sample)?;
        self.offline_published = true;
        Ok(())
    }

    fn publish_aggregate_sample(&mut self, now: u64) -> Result<()> {
        let address = self
            .connected
            .as_ref()
            .map(ConnectedDevice::address)
            .or_else(|| {
                self.last_advertisement
                    .as_ref()
                    .map(|advertisement| advertisement.address.clone())
            });
        let redcon = self.last_redcon.unwrap_or(REDCON_IDLE);
        let power_measurement = self
            .last_power_measurement
            .as_ref()
            .filter(|measurement| {
                now.saturating_sub(measurement.observed_at_ms) <= self.measurement_stale_ms()
            })
            .map(|measurement| measurement.value.clone());
        let weather_measurement = self
            .last_weather_measurement
            .as_ref()
            .filter(|measurement| {
                now.saturating_sub(measurement.observed_at_ms) <= self.measurement_stale_ms()
            })
            .map(|measurement| measurement.value.clone());
        let seq = self.next_seq();
        let sample = match self.spec.kind {
            DeviceKind::Power => power_state_sample(
                &self.spec,
                redcon,
                power_measurement.as_ref(),
                address,
                seq,
                now,
            ),
            DeviceKind::Weather => weather_state_sample(
                &self.spec,
                redcon,
                power_measurement.as_ref(),
                weather_measurement,
                address,
                seq,
                now,
            ),
        };
        self.publish_sample(sample)
    }

    fn power_measurement_stale(&self, now: u64) -> bool {
        self.last_power_measurement
            .as_ref()
            .is_some_and(|measurement| {
                now.saturating_sub(measurement.observed_at_ms) > self.measurement_stale_ms()
            })
    }

    fn weather_measurement_stale(&self, now: u64) -> bool {
        self.last_weather_measurement
            .as_ref()
            .is_some_and(|measurement| {
                now.saturating_sub(measurement.observed_at_ms) > self.measurement_stale_ms()
            })
    }

    fn measurement_stale_ms(&self) -> u64 {
        if self.last_redcon.unwrap_or(REDCON_IDLE) < REDCON_IDLE {
            REDCON_ACTIVE_MEASUREMENT_STALE_MS
        } else {
            REDCON_IDLE_MEASUREMENT_STALE_MS
        }
    }

    fn publish_sample(&self, sample: CapabilitySample) -> Result<()> {
        let state = capability_state_from_sample(&self.config.adapter_id, &sample);
        let topic = build_capability_state_topic(&state.thing_name, &self.config.adapter_id)?;
        let payload = state.to_vec()?;
        self.outbound_sender
            .send(OutboundMessage { topic, payload })
            .map_err(|_| anyhow!("outbound local pub/sub channel is closed"))?;
        for update in shadow_updates_from_sample(&sample)? {
            if self.shadow_sender.send(update).is_err() {
                eprintln!(
                    "warning: BLE shadow update channel is closed thing={}",
                    sample.thing_name
                );
            }
        }
        Ok(())
    }

    fn advertisement_is_fresh(&self, advertisement: &Advertisement) -> bool {
        now_ms().saturating_sub(advertisement.observed_at_ms) <= self.config.presence_timeout_ms
    }

    fn next_seq(&mut self) -> u64 {
        self.seq += 1;
        self.seq
    }
}

fn publish_command_result(
    adapter_id: &str,
    outbound_sender: &mpsc::UnboundedSender<OutboundMessage>,
    command: &CapabilityCommand,
    status: &str,
    message: Option<String>,
    target_redcon: Option<u8>,
) -> Result<()> {
    let result = CapabilityCommandResult {
        schema_version: txing_capability_protocol::SCHEMA_VERSION.to_string(),
        adapter_id: adapter_id.to_string(),
        command_id: command.command_id.clone(),
        thing_name: command.thing_name.clone(),
        status: status.to_string(),
        target: txing_capability_protocol::CapabilityCommandResultTarget {
            redcon: target_redcon,
        },
        message,
        observed_at_ms: now_ms(),
        seq: command.seq,
    };
    let topic = build_capability_command_result_topic(&command.thing_name, adapter_id)?;
    let payload = result.to_vec()?;
    outbound_sender
        .send(OutboundMessage { topic, payload })
        .map_err(|_| anyhow!("outbound local pub/sub channel is closed"))
}

#[derive(Debug, Clone)]
struct BleNotification {
    uuid: Uuid,
    payload: Vec<u8>,
}

#[cfg(all(feature = "ble-real", target_os = "linux"))]
struct ConnectedDevice {
    peripheral: Peripheral,
    command_char: Characteristic,
    state_char: Characteristic,
    power_measurement_char: Characteristic,
    weather_measurement_char: Option<Characteristic>,
    notification_receiver: mpsc::UnboundedReceiver<BleNotification>,
    notification_task: tokio::task::JoinHandle<()>,
    address: String,
    _permit: Option<tokio::sync::OwnedSemaphorePermit>,
}

#[cfg(all(feature = "ble-real", target_os = "linux"))]
impl ConnectedDevice {
    async fn connect(
        spec: &DeviceSpec,
        advertisement: &Advertisement,
        connect_timeout_ms: u64,
        permit: Option<tokio::sync::OwnedSemaphorePermit>,
    ) -> Result<Self> {
        let adapter = default_adapter().await?;
        let peripheral = find_peripheral(&adapter, &advertisement.address, &spec.thing_name)
            .await?
            .ok_or_else(|| anyhow!("BLE peripheral {} is not visible", advertisement.address))?;
        match timeout(
            Duration::from_millis(connect_timeout_ms),
            peripheral.connect(),
        )
        .await
        {
            Ok(Ok(())) => {}
            Ok(Err(err)) => {
                let _ = peripheral.disconnect().await;
                return Err(err).context("connect BLE peripheral");
            }
            Err(err) => {
                let _ = peripheral.disconnect().await;
                return Err(err).context("BLE connect timed out");
            }
        }
        match timeout(
            Duration::from_millis(connect_timeout_ms),
            peripheral.discover_services(),
        )
        .await
        {
            Ok(Ok(())) => {}
            Ok(Err(err)) => {
                let _ = peripheral.disconnect().await;
                return Err(err).context("discover BLE services");
            }
            Err(err) => {
                let _ = peripheral.disconnect().await;
                return Err(err).context("BLE service discovery timed out");
            }
        }

        let characteristics = peripheral.characteristics();
        let command_char = find_characteristic(&characteristics, TXING_BLE_COMMAND_UUID)
            .ok_or_else(|| anyhow!("BLE command characteristic is missing"))?;
        let state_char = find_characteristic(&characteristics, TXING_BLE_STATE_UUID)
            .ok_or_else(|| anyhow!("BLE state characteristic is missing"))?;
        let power_measurement_char = find_characteristic(&characteristics, POWER_MEASUREMENT_UUID)
            .ok_or_else(|| anyhow!("BLE power measurement characteristic is missing"))?;
        let weather_measurement_char = if spec.kind.supports_weather() {
            Some(
                find_characteristic(&characteristics, WEATHER_MEASUREMENT_UUID)
                    .ok_or_else(|| anyhow!("BLE weather measurement characteristic is missing"))?,
            )
        } else {
            None
        };

        let mut notifications = peripheral
            .notifications()
            .await
            .context("open BLE notification stream")?;
        peripheral
            .subscribe(&state_char)
            .await
            .context("subscribe BLE state notifications")?;
        peripheral
            .subscribe(&power_measurement_char)
            .await
            .context("subscribe BLE power measurement notifications")?;
        if let Some(characteristic) = &weather_measurement_char {
            peripheral
                .subscribe(characteristic)
                .await
                .context("subscribe BLE weather measurement notifications")?;
        }
        let (notification_sender, notification_receiver) = mpsc::unbounded_channel();
        let notification_task = tokio::spawn(async move {
            while let Some(notification) = notifications.next().await {
                if notification_sender
                    .send(BleNotification {
                        uuid: notification.uuid,
                        payload: notification.value,
                    })
                    .is_err()
                {
                    break;
                }
            }
        });

        eprintln!(
            "connected BLE thing={} address={} serviceAdvertised={}",
            spec.thing_name,
            advertisement.address,
            advertisement.has_txing_service()
        );
        Ok(Self {
            peripheral,
            command_char,
            state_char,
            power_measurement_char,
            weather_measurement_char,
            notification_receiver,
            notification_task,
            address: advertisement.address.clone(),
            _permit: permit,
        })
    }

    async fn is_connected(&self) -> bool {
        self.peripheral.is_connected().await.unwrap_or(false)
    }

    fn address(&self) -> String {
        self.address.clone()
    }

    async fn write_redcon(&self, target_redcon: u8, command_timeout_ms: u64) -> Result<()> {
        let payload = encode_redcon_command(target_redcon)?;
        timeout(
            Duration::from_millis(command_timeout_ms),
            self.peripheral
                .write(&self.command_char, &payload, WriteType::WithResponse),
        )
        .await
        .context("BLE command write timed out")?
        .context("write BLE REDCON command")
    }

    async fn read_power_state(&self, command_timeout_ms: u64) -> Result<PowerState> {
        let payload = timeout(
            Duration::from_millis(command_timeout_ms),
            self.peripheral.read(&self.state_char),
        )
        .await
        .context("BLE power state read timed out")?
        .context("read BLE power state")?;
        parse_power_state(&payload)
    }

    async fn read_power_measurement(&self, command_timeout_ms: u64) -> Result<PowerMeasurement> {
        let payload = timeout(
            Duration::from_millis(command_timeout_ms),
            self.peripheral.read(&self.power_measurement_char),
        )
        .await
        .context("BLE power measurement read timed out")?
        .context("read BLE power measurement")?;
        parse_power_measurement(&payload)
    }

    async fn read_weather_state(&self, command_timeout_ms: u64) -> Result<WeatherState> {
        let payload = timeout(
            Duration::from_millis(command_timeout_ms),
            self.peripheral.read(&self.state_char),
        )
        .await
        .context("BLE weather state read timed out")?
        .context("read BLE weather state")?;
        parse_weather_state(&payload)
    }

    async fn read_weather_measurement(
        &self,
        command_timeout_ms: u64,
    ) -> Result<WeatherMeasurement> {
        let measurement_char = self
            .weather_measurement_char
            .as_ref()
            .ok_or_else(|| anyhow!("BLE weather measurement characteristic is missing"))?;
        let payload = timeout(
            Duration::from_millis(command_timeout_ms),
            self.peripheral.read(measurement_char),
        )
        .await
        .context("BLE weather measurement read timed out")?
        .context("read BLE weather measurement")?;
        parse_weather_measurement(&payload)
    }

    fn drain_notifications(&mut self) -> Vec<BleNotification> {
        let mut notifications = Vec::new();
        while let Ok(notification) = self.notification_receiver.try_recv() {
            notifications.push(notification);
        }
        notifications
    }
}

#[cfg(all(feature = "ble-real", target_os = "linux"))]
impl Drop for ConnectedDevice {
    fn drop(&mut self) {
        self.notification_task.abort();
        let peripheral = self.peripheral.clone();
        let state_char = self.state_char.clone();
        let power_measurement_char = self.power_measurement_char.clone();
        let weather_measurement_char = self.weather_measurement_char.clone();
        tokio::spawn(async move {
            if peripheral.is_connected().await.unwrap_or(false) {
                let _ = peripheral.unsubscribe(&state_char).await;
                let _ = peripheral.unsubscribe(&power_measurement_char).await;
                if let Some(characteristic) = weather_measurement_char {
                    let _ = peripheral.unsubscribe(&characteristic).await;
                }
                let _ = peripheral.disconnect().await;
            }
        });
    }
}

#[cfg(not(all(feature = "ble-real", target_os = "linux")))]
struct ConnectedDevice {
    connected: bool,
}

#[cfg(not(all(feature = "ble-real", target_os = "linux")))]
impl ConnectedDevice {
    async fn connect(
        _spec: &DeviceSpec,
        _advertisement: &Advertisement,
        _connect_timeout_ms: u64,
        _permit: Option<tokio::sync::OwnedSemaphorePermit>,
    ) -> Result<Self> {
        bail!("build with the ble-real feature to use the live BLE adapter")
    }

    async fn is_connected(&self) -> bool {
        self.connected
    }

    fn address(&self) -> String {
        String::new()
    }

    async fn write_redcon(&self, _target_redcon: u8, _command_timeout_ms: u64) -> Result<()> {
        bail!("build with the ble-real feature to use the live BLE adapter")
    }

    async fn read_power_state(&self, _command_timeout_ms: u64) -> Result<PowerState> {
        bail!("build with the ble-real feature to use the live BLE adapter")
    }

    async fn read_power_measurement(&self, _command_timeout_ms: u64) -> Result<PowerMeasurement> {
        bail!("build with the ble-real feature to use the live BLE adapter")
    }

    async fn read_weather_state(&self, _command_timeout_ms: u64) -> Result<WeatherState> {
        bail!("build with the ble-real feature to use the live BLE adapter")
    }

    async fn read_weather_measurement(
        &self,
        _command_timeout_ms: u64,
    ) -> Result<WeatherMeasurement> {
        bail!("build with the ble-real feature to use the live BLE adapter")
    }

    fn drain_notifications(&mut self) -> Vec<BleNotification> {
        Vec::new()
    }
}

#[cfg(all(feature = "ble-real", target_os = "linux"))]
fn find_characteristic(
    characteristics: &BTreeSet<Characteristic>,
    uuid: Uuid,
) -> Option<Characteristic> {
    characteristics
        .iter()
        .find(|characteristic| characteristic.uuid == uuid)
        .cloned()
}

#[cfg(all(feature = "ble-real", target_os = "linux"))]
async fn default_adapter() -> Result<Adapter> {
    let manager = Manager::new().await.context("create BLE manager")?;
    let adapters = manager.adapters().await.context("list BLE adapters")?;
    adapters
        .into_iter()
        .next()
        .ok_or_else(|| anyhow!("no BLE adapter found"))
}

#[cfg(all(feature = "ble-real", target_os = "linux"))]
async fn find_peripheral(
    adapter: &Adapter,
    address: &str,
    thing_name: &str,
) -> Result<Option<Peripheral>> {
    for peripheral in adapter
        .peripherals()
        .await
        .context("list BLE peripherals")?
    {
        let Some(properties) = peripheral
            .properties()
            .await
            .context("read BLE properties")?
        else {
            continue;
        };
        if properties.address.to_string() == address
            || properties.local_name.as_deref() == Some(thing_name)
        {
            return Ok(Some(peripheral));
        }
    }
    Ok(None)
}

#[cfg(all(feature = "ble-real", target_os = "linux"))]
async fn run_scanner(
    config: RuntimeConfig,
    advertisements: broadcast::Sender<Advertisement>,
) -> Result<()> {
    let adapter = default_adapter().await?;
    adapter
        .start_scan(ScanFilter::default())
        .await
        .context("start BLE scan")?;
    let mut seq = 0u64;
    let mut timer = interval(Duration::from_millis(config.scan_interval_ms.max(100)));
    timer.set_missed_tick_behavior(MissedTickBehavior::Skip);
    loop {
        timer.tick().await;
        for peripheral in adapter
            .peripherals()
            .await
            .context("list BLE peripherals")?
        {
            let Some(properties) = peripheral
                .properties()
                .await
                .context("read BLE properties")?
            else {
                continue;
            };
            let address = properties.address.to_string();
            let local_name = properties
                .local_name
                .clone()
                .filter(|value| !value.trim().is_empty());
            if local_name.is_none() {
                continue;
            }
            seq += 1;
            let advertisement = Advertisement {
                address,
                local_name,
                services: properties.services,
                rssi: properties.rssi,
                observed_at_ms: now_ms(),
                seq,
            };
            let _ = advertisements.send(advertisement);
        }
    }
}

#[cfg(not(all(feature = "ble-real", target_os = "linux")))]
async fn run_scanner(
    _config: RuntimeConfig,
    _advertisements: broadcast::Sender<Advertisement>,
) -> Result<()> {
    bail!("build with the ble-real feature to use the live BLE adapter")
}

pub async fn run_component_runtime(config: RuntimeConfig) -> Result<()> {
    #[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
    {
        run_greengrass_runtime(config).await
    }
    #[cfg(not(all(feature = "greengrass-sdk", target_os = "linux")))]
    {
        let _ = config;
        bail!("build with --features greengrass-sdk on Linux to run the live Greengrass runtime")
    }
}

#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
async fn run_greengrass_runtime(config: RuntimeConfig) -> Result<()> {
    validate_greengrass_ipc_environment()?;
    let sdk = gg_sdk::Sdk::init();
    GREENGRASS_SDK
        .set(sdk)
        .map_err(|_| anyhow!("Greengrass SDK was already initialized"))?;
    sdk.connect()
        .map_err(|err| anyhow!("failed to connect Greengrass IPC: {err:?}"))?;
    sdk.update_state(gg_sdk::ComponentState::Running)
        .map_err(|err| anyhow!("failed to update Greengrass component state: {err:?}"))?;

    let (local_sender, mut local_receiver) = mpsc::unbounded_channel();
    let local_callback = move |topic: &str, payload: gg_sdk::SubscribeToTopicPayload<'_>| {
        let payload = match payload {
            gg_sdk::SubscribeToTopicPayload::Binary(bytes) => bytes.to_vec(),
            gg_sdk::SubscribeToTopicPayload::Json(_) => {
                eprintln!("warning: ignoring JSON local pub/sub payload on topic={topic}");
                return;
            }
        };
        let _ = local_sender.send(LocalEvent::Message {
            topic: topic.to_string(),
            payload,
        });
    };
    let inventory_subscription = sdk
        .subscribe_to_topic(INVENTORY_TOPIC, &local_callback)
        .map_err(|err| anyhow!("failed to subscribe v2 inventory topic: {err:?}"))?;
    let command_subscription = sdk
        .subscribe_to_topic(
            &format!("{CAPABILITY_COMMAND_TOPIC_PREFIX}/+"),
            &local_callback,
        )
        .map_err(|err| anyhow!("failed to subscribe v2 capability command topics: {err:?}"))?;

    let (advertisements, _) = broadcast::channel(SCANNER_BUFFER);
    let (outbound_sender, mut outbound_receiver) = mpsc::unbounded_channel();
    let (shadow_sender, mut shadow_receiver) = mpsc::unbounded_channel();
    let mut runtime = RuntimeState::new(
        config.clone(),
        advertisements.clone(),
        outbound_sender,
        shadow_sender,
    );

    let scanner_task = if config.no_ble {
        None
    } else {
        Some(tokio::spawn(run_scanner(config.clone(), advertisements)))
    };
    let mut heartbeat_seq = 0u64;
    let mut heartbeat_timer = interval(Duration::from_millis(config.heartbeat_interval_ms.max(1)));
    heartbeat_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);
    let mut pending_shadow_updates = PendingShadowUpdates::default();
    let mut shadow_publish_timer = interval(Duration::from_millis(SHADOW_PUBLISH_INTERVAL_MS));
    shadow_publish_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);
    let mut last_shadow_publish_error_log_ms = 0u64;

    let result = loop {
        tokio::select! {
            _ = tokio::signal::ctrl_c() => break Ok(()),
            Some(event) = local_receiver.recv() => {
                let LocalEvent::Message { topic, payload } = event;
                if let Err(err) = runtime.handle_local_message(topic, payload).await {
                    eprintln!("warning: BLE connectivity local event failed: {err:#}");
                }
            }
            Some(outbound) = outbound_receiver.recv() => {
                if let Err(err) = publish_local(&outbound.topic, &outbound.payload).await {
                    eprintln!("warning: BLE connectivity local publish failed topic={}: {err:#}", outbound.topic);
                }
            }
            Some(update) = shadow_receiver.recv() => {
                pending_shadow_updates.push(update);
            }
            _ = shadow_publish_timer.tick(), if !pending_shadow_updates.is_empty() => {
                if let Some(update) = pending_shadow_updates.pop() {
                    if let Err(err) = publish_iot_core(&update.topic, &update.payload).await {
                        let failed_topic = update.topic.clone();
                        let pending_count = pending_shadow_updates.len() + 1;
                        pending_shadow_updates.push(update);
                        let now = now_ms();
                        if now.saturating_sub(last_shadow_publish_error_log_ms)
                            >= SHADOW_PUBLISH_RETRY_LOG_INTERVAL_MS
                        {
                            eprintln!(
                                "warning: BLE shadow publish failed topic={}: {err:#}; will retry latest pending updates count={pending_count}",
                                failed_topic
                            );
                            last_shadow_publish_error_log_ms = now;
                        }
                    }
                }
            }
            _ = heartbeat_timer.tick() => {
                heartbeat_seq += 1;
                let heartbeat = CapabilityHeartbeat::new(
                    &config.adapter_id,
                    txing_capability_protocol::HEARTBEAT_RUNNING,
                    None,
                    now_ms(),
                    heartbeat_seq,
                );
                match heartbeat.to_vec().and_then(|payload| {
                    Ok((build_capability_heartbeat_topic(&config.adapter_id)?, payload))
                }) {
                    Ok((topic, payload)) => {
                        if let Err(err) = publish_local(&topic, &payload).await {
                            eprintln!("warning: BLE heartbeat publish failed: {err:#}");
                        }
                    }
                    Err(err) => eprintln!("warning: BLE heartbeat build failed: {err:#}"),
                }
            }
        }
    };

    runtime.shutdown().await;
    if let Some(scanner_task) = scanner_task {
        scanner_task.abort();
        let _ = scanner_task.await;
    }
    drop(command_subscription);
    drop(inventory_subscription);
    result
}

#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
async fn publish_local(topic: &str, payload: &[u8]) -> Result<()> {
    let sdk = *GREENGRASS_SDK
        .get()
        .ok_or_else(|| anyhow!("Greengrass SDK is not initialized"))?;
    sdk.publish_to_topic_binary(topic, payload)
        .map_err(|err| anyhow!("failed to publish local topic {topic}: {err:?}"))
}

#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
async fn publish_iot_core(topic: &str, payload: &[u8]) -> Result<()> {
    let sdk = *GREENGRASS_SDK
        .get()
        .ok_or_else(|| anyhow!("Greengrass SDK is not initialized"))?;
    sdk.publish_to_iot_core(topic, payload, gg_sdk::Qos::AtMostOnce)
        .map_err(|err| anyhow!("failed to publish AWS IoT Core topic {topic}: {err:?}"))
}

#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
static GREENGRASS_SDK: OnceLock<gg_sdk::Sdk> = OnceLock::new();

#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
fn validate_greengrass_ipc_environment() -> Result<()> {
    const IPC_SOCKET_ENV: &str = "AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT";
    const IPC_AUTH_TOKEN_ENV: &str = "SVCUID";
    let socket_path = std::env::var_os(IPC_SOCKET_ENV).filter(|value| !value.is_empty());
    let auth_token = std::env::var_os(IPC_AUTH_TOKEN_ENV).filter(|value| !value.is_empty());

    let mut missing = Vec::new();
    if socket_path.is_none() {
        missing.push(IPC_SOCKET_ENV);
    }
    if auth_token.is_none() {
        missing.push(IPC_AUTH_TOKEN_ENV);
    }
    if !missing.is_empty() {
        bail!(
            "missing Greengrass IPC environment variable(s): {}",
            missing.join(", ")
        );
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ble_protocol::REDCON_ACTIVE;
    use txing_capability_protocol::{
        CapabilityCommandTarget, CapabilityState, InventoryDevice, SCHEMA_VERSION,
        build_capability_state_topic,
    };

    fn inventory_device(thing_name: &str, capabilities: &[&str]) -> InventoryDevice {
        InventoryDevice {
            thing_name: thing_name.to_string(),
            thing_type: capabilities.last().unwrap_or(&"unknown").to_string(),
            capabilities: capabilities.iter().map(|value| value.to_string()).collect(),
            redcon_command_levels: vec![4, 3],
            redcon_rules: BTreeMap::new(),
        }
    }

    fn power_spec() -> DeviceSpec {
        DeviceSpec {
            thing_name: "power-1".to_string(),
            kind: DeviceKind::Power,
        }
    }

    fn advertisement() -> Advertisement {
        Advertisement {
            address: "E4:7C:BC:45:9B:A2".to_string(),
            local_name: Some("power-1".to_string()),
            services: Vec::new(),
            rssi: Some(-55),
            observed_at_ms: now_ms(),
            seq: 1,
        }
    }

    #[test]
    fn inventory_filter_selects_power_and_weather_only() {
        let power = inventory_device("power-1", &["sparkplug", "ble", "power"]);
        let weather = inventory_device("weather-1", &["sparkplug", "ble", "power", "weather"]);
        let time = inventory_device("time-1", &["sparkplug", "time", "mcp"]);

        assert_eq!(
            device_spec_from_inventory(&power),
            Some(DeviceSpec {
                thing_name: "power-1".to_string(),
                kind: DeviceKind::Power,
            })
        );
        assert_eq!(
            device_spec_from_inventory(&weather),
            Some(DeviceSpec {
                thing_name: "weather-1".to_string(),
                kind: DeviceKind::Weather,
            })
        );
        assert_eq!(device_spec_from_inventory(&time), None);
    }

    #[test]
    fn pending_shadow_updates_coalesce_by_topic_and_retry_after_other_topics() {
        let mut pending = PendingShadowUpdates::default();

        pending.push(ShadowUpdate {
            topic: "topic/a".to_string(),
            payload: b"old-a".to_vec(),
        });
        pending.push(ShadowUpdate {
            topic: "topic/b".to_string(),
            payload: b"b".to_vec(),
        });
        pending.push(ShadowUpdate {
            topic: "topic/a".to_string(),
            payload: b"new-a".to_vec(),
        });

        assert_eq!(pending.len(), 2);
        let failed = pending.pop().unwrap();
        assert_eq!(failed.topic, "topic/a");
        assert_eq!(failed.payload, b"new-a");
        pending.push(failed);

        let next = pending.pop().unwrap();
        assert_eq!(next.topic, "topic/b");
        let retried = pending.pop().unwrap();
        assert_eq!(retried.topic, "topic/a");
        assert!(pending.is_empty());
    }

    #[tokio::test]
    async fn weather_command_rejects_redcon_three_before_ble_write() {
        let (sender, mut receiver) = mpsc::unbounded_channel();
        let (shadow_sender, _shadow_receiver) = mpsc::unbounded_channel();
        let mut session = DeviceSession::new(
            DeviceSpec {
                thing_name: "weather-1".to_string(),
                kind: DeviceKind::Weather,
            },
            RuntimeConfig::default(),
            sender,
            shadow_sender,
            None,
        );
        let command = CapabilityCommand {
            schema_version: SCHEMA_VERSION.to_string(),
            command_id: "cmd-weather-3".to_string(),
            thing_name: "weather-1".to_string(),
            target: CapabilityCommandTarget { redcon: 3 },
            reason: "test".to_string(),
            issued_at_ms: 1,
            deadline_ms: None,
            seq: 11,
        };

        session.handle_command(command).await.unwrap();

        let outbound = receiver.recv().await.unwrap();
        let result: txing_capability_protocol::CapabilityCommandResult =
            serde_json::from_slice(&outbound.payload).unwrap();
        assert_eq!(result.status, COMMAND_FAILED);
        assert_eq!(result.target.redcon, Some(3));
        assert!(result.message.unwrap().contains("only supports REDCON 4"));
    }

    #[tokio::test]
    async fn connected_session_does_not_downgrade_state_from_advertisement() {
        let (sender, mut receiver) = mpsc::unbounded_channel();
        let (shadow_sender, mut shadow_receiver) = mpsc::unbounded_channel();
        let mut session = DeviceSession::new(
            power_spec(),
            RuntimeConfig::default(),
            sender,
            shadow_sender,
            None,
        );
        session.connected = Some(ConnectedDevice { connected: true });

        session.handle_advertisement(advertisement()).await.unwrap();

        assert!(receiver.try_recv().is_err());
        assert!(shadow_receiver.try_recv().is_err());
        assert!(session.connected.is_some());
        assert!(session.last_advertisement.is_some());
    }

    #[tokio::test]
    async fn disconnected_session_reports_advertisement_availability() {
        let (sender, mut receiver) = mpsc::unbounded_channel();
        let (shadow_sender, mut shadow_receiver) = mpsc::unbounded_channel();
        let mut config = RuntimeConfig::default();
        config.reconnect_delay_ms = 0;
        let mut session = DeviceSession::new(power_spec(), config, sender, shadow_sender, None);

        session.handle_advertisement(advertisement()).await.unwrap();

        let outbound = receiver.recv().await.unwrap();
        let state: CapabilityState = serde_json::from_slice(&outbound.payload).unwrap();
        assert_eq!(state.thing_name, "power-1");
        assert_eq!(state.capabilities.get("sparkplug"), Some(&true));
        assert_eq!(state.capabilities.get("ble"), Some(&true));
        assert_eq!(state.capabilities.get("power"), Some(&false));
        assert!(state.metrics.is_empty());

        let shadow = shadow_receiver.recv().await.unwrap();
        assert_eq!(shadow.topic, "$aws/things/power-1/shadow/name/ble/update");
        let payload: serde_json::Value = serde_json::from_slice(&shadow.payload).unwrap();
        assert_eq!(
            payload["state"]["reported"]["bleAddress"],
            serde_json::Value::from("E4:7C:BC:45:9B:A2")
        );
    }

    #[tokio::test]
    async fn shadow_publish_channel_failure_does_not_block_local_state() {
        let (sender, mut receiver) = mpsc::unbounded_channel();
        let (shadow_sender, shadow_receiver) = mpsc::unbounded_channel();
        drop(shadow_receiver);
        let mut config = RuntimeConfig::default();
        config.reconnect_delay_ms = 0;
        let mut session = DeviceSession::new(power_spec(), config, sender, shadow_sender, None);

        session.handle_advertisement(advertisement()).await.unwrap();

        let outbound = receiver.recv().await.unwrap();
        let state: CapabilityState = serde_json::from_slice(&outbound.payload).unwrap();
        assert_eq!(state.thing_name, "power-1");
        assert_eq!(state.capabilities.get("ble"), Some(&true));
    }

    #[tokio::test]
    async fn stale_power_measurement_clears_power_capability_and_shadow() {
        let (sender, mut receiver) = mpsc::unbounded_channel();
        let (shadow_sender, mut shadow_receiver) = mpsc::unbounded_channel();
        let mut session = DeviceSession::new(
            power_spec(),
            RuntimeConfig::default(),
            sender,
            shadow_sender,
            None,
        );
        session.connected = Some(ConnectedDevice { connected: true });
        session.last_redcon = Some(REDCON_ACTIVE);
        session.last_power_measurement = Some(TimedMeasurement {
            value: PowerMeasurement {
                battery_mv: Some(3970),
            },
            observed_at_ms: now_ms().saturating_sub(REDCON_ACTIVE_MEASUREMENT_STALE_MS + 1),
        });

        session.check_stale().await.unwrap();

        let outbound = receiver.recv().await.unwrap();
        let state: CapabilityState = serde_json::from_slice(&outbound.payload).unwrap();
        assert_eq!(state.capabilities.get("power"), Some(&false));

        let _ble_shadow = shadow_receiver.recv().await.unwrap();
        let power_shadow = shadow_receiver.recv().await.unwrap();
        assert_eq!(
            power_shadow.topic,
            "$aws/things/power-1/shadow/name/power/update"
        );
        let payload: serde_json::Value = serde_json::from_slice(&power_shadow.payload).unwrap();
        assert!(payload["state"]["reported"]["batteryMv"].is_null());
    }

    #[tokio::test]
    async fn command_result_topics_use_component_adapter_id() {
        let (sender, mut receiver) = mpsc::unbounded_channel();
        let command = CapabilityCommand {
            schema_version: SCHEMA_VERSION.to_string(),
            command_id: "cmd-1".to_string(),
            thing_name: "power-1".to_string(),
            target: CapabilityCommandTarget { redcon: 1 },
            reason: "test".to_string(),
            issued_at_ms: 1,
            deadline_ms: None,
            seq: 9,
        };

        publish_command_result(
            ADAPTER_ID,
            &sender,
            &command,
            COMMAND_ACCEPTED,
            None,
            Some(command.target.redcon),
        )
        .unwrap();
        let outbound = receiver.recv().await.unwrap();

        assert_eq!(
            outbound.topic,
            "dev/txing/rig/v2/capability/command-result/power-1/dev.txing.rig.BleConnectivity"
        );
        assert!(
            String::from_utf8(outbound.payload)
                .unwrap()
                .contains("\"redcon\":1")
        );
    }

    #[test]
    fn state_topic_builder_allows_component_adapter_id() {
        assert_eq!(
            build_capability_state_topic("weather-1", ADAPTER_ID).unwrap(),
            "dev/txing/rig/v2/capability/state/weather-1/dev.txing.rig.BleConnectivity"
        );
    }
}
