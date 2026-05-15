#![cfg_attr(
    not(all(feature = "greengrass-sdk", target_os = "linux")),
    allow(dead_code, unused_imports)
)]

use std::collections::{BTreeMap, BTreeSet, VecDeque};
#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
use std::sync::OnceLock;
use std::sync::{Arc, RwLock};
use std::time::Duration;

use anyhow::{Context, Result, anyhow, bail};
#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
use btleplug::api::{
    Central, Characteristic, Manager as _, Peripheral as _, ScanFilter, WriteType,
};
#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
use btleplug::platform::{Adapter, Manager, Peripheral};
#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
use futures::StreamExt;
#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
use tokio::sync::OnceCell;
use tokio::sync::{Semaphore, broadcast, mpsc};
use tokio::time::{Instant, MissedTickBehavior, interval, sleep, timeout};
use txing_rig_local_pubsub::LocalPubSubClient;
use uuid::Uuid;

use crate::ble_protocol::{
    ADAPTER_ID, Advertisement, BLE_CAPABILITY, CapabilitySample, DeviceKind, DeviceSpec,
    POWER_CAPABILITY, POWER_MEASUREMENT_UUID, PowerMeasurement, PowerState, REDCON_IDLE,
    ShadowUpdate, TXING_BLE_COMMAND_UUID, TXING_BLE_SERVICE_UUID, TXING_BLE_STATE_UUID,
    WEATHER_CAPABILITY, WEATHER_MEASUREMENT_UUID, WeatherMeasurement, WeatherState,
    advertisement_sample, capability_state_from_sample, encode_redcon_command, now_ms,
    offline_sample, parse_power_measurement, parse_power_state, parse_weather_measurement,
    parse_weather_state, power_state_sample, shadow_updates_from_sample, weather_state_sample,
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
const CONNECTED_STATE_REFRESH_INTERVAL_MS: u64 = 30_000;
const BLE_ADVERTISEMENT_BROADCAST_MIN_INTERVAL_MS: u64 = 1_000;
const BLE_CONNECT_RESET_DELAY_MS: u64 = 250;
const BLE_RETRY_MIN_DELAY_MS: u64 = 1_000;
const BLE_RETRY_MAX_DELAY_MS: u64 = 120_000;
const BLE_RETRY_JITTER_MAX_MS: u64 = 1_000;
const BLUEZ_IN_PROGRESS_RECONNECT_DELAY_MS: u64 = 10_000;
const BLUEZ_RESOURCE_EXHAUSTED_RECONNECT_DELAY_MS: u64 = 60_000;
const BLE_CONNECT_SESSION_MAX_TIMEOUT_MS: u64 = 20_000;
const BLE_DISCONNECT_TIMEOUT_MS: u64 = 2_000;
const BLE_PERIPHERAL_LOOKUP_POLL_MS: u64 = 200;
const BLE_COMMAND_CONNECT_RETRY_DELAY_MS: u64 = 1_000;
const BLE_SCANNER_PROPERTY_ERROR_LOG_INTERVAL_MS: u64 = 30_000;
const BLE_SCANNER_DEBUG_SUMMARY_INTERVAL_MS: u64 = 5_000;
const BLE_SCANNER_NO_TARGET_LOG_INTERVAL_MS: u64 = 30_000;
const BLE_SCANNER_EMPTY_CACHE_RESTART_INTERVAL_MS: u64 = 30_000;
const BLE_SCANNER_IN_PROGRESS_RECOVERY_ATTEMPTS: u32 = 3;
const BLE_SCANNER_IN_PROGRESS_RECOVERY_DELAY_MS: u64 = 500;
const BLE_SCANNER_ADAPTER_RESET_DELAY_MS: u64 = 1_000;
const BLE_SCANNER_DEBUG_SAMPLE_LIMIT: usize = 8;
const BLE_SCANNER_UNMANAGED_TXING_LOG_INTERVAL_MS: u64 = 30_000;
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
    pub local_ipc_socket: String,
    pub debug: bool,
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
            local_ipc_socket: String::new(),
            debug: false,
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

type SharedScannerTargets = Arc<RwLock<BTreeSet<String>>>;

struct RuntimeState {
    config: RuntimeConfig,
    advertisements: broadcast::Sender<Advertisement>,
    scanner_targets: SharedScannerTargets,
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
        scanner_targets: SharedScannerTargets,
        outbound_sender: mpsc::UnboundedSender<OutboundMessage>,
        shadow_sender: mpsc::UnboundedSender<ShadowUpdate>,
    ) -> Self {
        let connection_semaphore =
            (config.max_connections > 0).then(|| Arc::new(Semaphore::new(config.max_connections)));
        Self {
            config,
            advertisements,
            scanner_targets,
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
        let previous_names = scanner_targets_snapshot(&self.scanner_targets);
        if previous_names != wanted_names {
            eprintln!("BLE inventory targets updated targets={wanted_names:?}");
        }
        replace_scanner_targets(&self.scanner_targets, wanted_names.clone());

        let removed = self
            .sessions
            .keys()
            .filter(|thing_name| !wanted_names.contains(*thing_name))
            .cloned()
            .collect::<Vec<_>>();
        for thing_name in removed {
            if self.config.debug {
                eprintln!("debug: BLE inventory removed thing={thing_name}");
            }
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
            if self.config.debug {
                eprintln!(
                    "debug: BLE inventory added thing={thing_name} kind={:?}",
                    spec.kind
                );
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
    connect_failures: u32,
    offline_published: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ConnectOutcome {
    Connected,
    DeferredNoCapacity,
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
            connect_failures: 0,
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
        let mut connected_state_timer =
            interval(Duration::from_millis(CONNECTED_STATE_REFRESH_INTERVAL_MS));
        connected_state_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);

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
                _ = connected_state_timer.tick(), if self.connected.is_some() => {
                    self.publish_aggregate_state_heartbeat(now_ms())?;
                }
            }
        }
        Ok(())
    }

    async fn handle_advertisement(&mut self, advertisement: Advertisement) -> Result<()> {
        if !advertisement.matches_thing(&self.spec.thing_name) {
            return Ok(());
        }
        if self.config.debug {
            eprintln!(
                "debug: BLE advertisement matched thing={} address={} rssi={:?} serviceAdvertised={} seq={}",
                self.spec.thing_name,
                advertisement.address,
                advertisement.rssi,
                advertisement.has_txing_service(),
                advertisement.seq
            );
        }
        self.last_advertisement = Some(advertisement.clone());
        self.offline_published = false;

        if self.connected.is_some() {
            if self.config.debug {
                eprintln!(
                    "debug: BLE advertisement ignored because already connected thing={}",
                    self.spec.thing_name
                );
            }
            return Ok(());
        }
        let now = now_ms();
        if now < self.next_connect_after_ms {
            if self.config.debug {
                eprintln!(
                    "debug: BLE advertisement ignored during reconnect backoff thing={} retryAfterMs={}",
                    self.spec.thing_name, self.next_connect_after_ms
                );
            }
            return Ok(());
        }

        let seq = self.next_seq();
        self.publish_sample(advertisement_sample(&self.spec, &advertisement, seq))?;
        if !self.should_connect_from_advertisement() {
            if self.config.debug {
                eprintln!(
                    "debug: BLE advertisement did not trigger background connect thing={} lastRedcon={:?}",
                    self.spec.thing_name, self.last_redcon
                );
            }
            return Ok(());
        }
        match self.connect(false).await {
            Ok(ConnectOutcome::Connected) => self.reset_connect_backoff(),
            Ok(ConnectOutcome::DeferredNoCapacity) => {
                self.next_connect_after_ms = now_ms()
                    .saturating_add(self.config.reconnect_delay_ms.max(BLE_RETRY_MIN_DELAY_MS));
            }
            Err(err) => {
                let retry_delay_ms = self.record_connect_failure(&err);
                self.next_connect_after_ms = now_ms().saturating_add(retry_delay_ms);
                eprintln!(
                    "warning: BLE connect from advertisement failed thing={} address={} failureCount={} retryDelayMs={retry_delay_ms} retryAfterMs={} error={err:#}",
                    self.spec.thing_name,
                    advertisement.address,
                    self.connect_failures,
                    self.next_connect_after_ms
                );
            }
        }
        Ok(())
    }

    fn should_connect_from_advertisement(&self) -> bool {
        match self.spec.kind {
            DeviceKind::Power => self.last_redcon.is_none_or(|redcon| redcon < REDCON_IDLE),
            DeviceKind::Weather => true,
        }
    }

    fn connect_retry_delay_ms(&self, err: &anyhow::Error) -> u64 {
        let delay = self.connect_retry_base_delay_ms(err);
        let delay = bounded_retry_delay_ms(
            delay,
            self.connect_failures.saturating_add(1),
            BLE_RETRY_MAX_DELAY_MS,
        );
        delay
            .saturating_add(self.connect_retry_jitter_ms())
            .min(BLE_RETRY_MAX_DELAY_MS)
    }

    fn connect_retry_base_delay_ms(&self, err: &anyhow::Error) -> u64 {
        let message = format!("{err:#}");
        if ble_error_indicates_host_resource_exhaustion(&message) {
            self.config
                .reconnect_delay_ms
                .max(BLUEZ_RESOURCE_EXHAUSTED_RECONNECT_DELAY_MS)
        } else if ble_error_indicates_in_progress(&message) {
            self.config
                .reconnect_delay_ms
                .max(BLUEZ_IN_PROGRESS_RECONNECT_DELAY_MS)
        } else {
            self.config.reconnect_delay_ms.max(BLE_RETRY_MIN_DELAY_MS)
        }
    }

    fn connect_retry_jitter_ms(&self) -> u64 {
        stable_jitter_ms(&self.spec.thing_name, BLE_RETRY_JITTER_MAX_MS)
    }

    fn record_connect_failure(&mut self, err: &anyhow::Error) -> u64 {
        let retry_delay_ms = self.connect_retry_delay_ms(err);
        self.connect_failures = self.connect_failures.saturating_add(1);
        retry_delay_ms
    }

    fn reset_connect_backoff(&mut self) {
        self.connect_failures = 0;
        self.next_connect_after_ms = 0;
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

        if let Err(err) = self.connect_for_command(&command).await {
            let retry_delay_ms = self.record_connect_failure(&err);
            self.next_connect_after_ms = now_ms().saturating_add(retry_delay_ms);
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
            let retry_delay_ms = self.record_connect_failure(&err);
            self.next_connect_after_ms = now_ms().saturating_add(retry_delay_ms);
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
        self.reset_connect_backoff();
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

    async fn connect_for_command(&mut self, command: &CapabilityCommand) -> Result<()> {
        let retry_deadline_ms = command
            .deadline_ms
            .unwrap_or_else(|| now_ms().saturating_add(self.config.connect_timeout_ms));
        let mut attempt = 0u32;
        loop {
            attempt = attempt.saturating_add(1);
            match self.connect(true).await {
                Ok(ConnectOutcome::Connected) => return Ok(()),
                Ok(ConnectOutcome::DeferredNoCapacity) => {
                    bail!("BLE connection capacity is unavailable before command write")
                }
                Err(err) => {
                    let now = now_ms();
                    let can_retry = ble_command_connect_error_is_retryable(&err)
                        && now.saturating_add(BLE_COMMAND_CONNECT_RETRY_DELAY_MS)
                            < retry_deadline_ms;
                    if !can_retry {
                        return Err(err);
                    }
                    if self.config.debug {
                        eprintln!(
                            "debug: BLE command connect retry thing={} commandId={} attempt={} retryDelayMs={} error={err:#}",
                            self.spec.thing_name,
                            command.command_id,
                            attempt,
                            BLE_COMMAND_CONNECT_RETRY_DELAY_MS
                        );
                    }
                    sleep(Duration::from_millis(BLE_COMMAND_CONNECT_RETRY_DELAY_MS)).await;
                }
            }
        }
    }

    async fn connect(&mut self, wait_for_cap: bool) -> Result<ConnectOutcome> {
        if let Some(connected) = &self.connected {
            if connected.is_connected().await {
                return Ok(ConnectOutcome::Connected);
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
                Err(_) => return Ok(ConnectOutcome::DeferredNoCapacity),
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
        if self.connected.is_some() {
            Ok(ConnectOutcome::Connected)
        } else {
            bail!("BLE connected but initial state read did not complete")
        }
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
        self.reset_connect_backoff();
        self.offline_published = true;
        Ok(())
    }

    fn publish_aggregate_sample(&mut self, now: u64) -> Result<()> {
        let sample = self.aggregate_sample(now);
        self.publish_sample(sample)
    }

    fn publish_aggregate_state_heartbeat(&mut self, now: u64) -> Result<()> {
        let sample = self.aggregate_sample(now);
        self.publish_sample_without_shadow_updates(sample)
    }

    fn aggregate_sample(&mut self, now: u64) -> CapabilitySample {
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
        match self.spec.kind {
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
        }
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
        self.publish_sample_with_shadow_updates(sample, true)
    }

    fn publish_sample_without_shadow_updates(&self, sample: CapabilitySample) -> Result<()> {
        self.publish_sample_with_shadow_updates(sample, false)
    }

    fn publish_sample_with_shadow_updates(
        &self,
        sample: CapabilitySample,
        include_shadow_updates: bool,
    ) -> Result<()> {
        let state = capability_state_from_sample(&self.config.adapter_id, &sample);
        let topic = build_capability_state_topic(&state.thing_name, &self.config.adapter_id)?;
        let payload = state.to_vec()?;
        if self.config.debug {
            eprintln!(
                "debug: BLE capability state publish thing={} topic={} capabilities={} includeShadowUpdates={include_shadow_updates}",
                state.thing_name,
                topic,
                format_capability_map(&state.capabilities)
            );
        }
        self.outbound_sender
            .send(OutboundMessage { topic, payload })
            .map_err(|_| anyhow!("outbound local pub/sub channel is closed"))?;
        if !include_shadow_updates {
            return Ok(());
        }
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

fn bounded_retry_delay_ms(base_delay_ms: u64, failure_count: u32, max_delay_ms: u64) -> u64 {
    let base_delay_ms = base_delay_ms.max(BLE_RETRY_MIN_DELAY_MS);
    let exponent = failure_count.saturating_sub(1).min(6);
    base_delay_ms
        .saturating_mul(1u64 << exponent)
        .min(max_delay_ms)
}

fn stable_jitter_ms(key: &str, max_jitter_ms: u64) -> u64 {
    if max_jitter_ms == 0 {
        return 0;
    }
    key.bytes().fold(0u64, |accumulator, byte| {
        accumulator.wrapping_mul(33).wrapping_add(u64::from(byte))
    }) % (max_jitter_ms + 1)
}

fn ble_error_indicates_in_progress(message: &str) -> bool {
    message.contains("In Progress")
        || message.contains("InProgress")
        || message.contains("already in progress")
}

fn ble_error_indicates_no_discovery(message: &str) -> bool {
    message.contains("No discovery started")
}

fn ble_error_indicates_host_resource_exhaustion(message: &str) -> bool {
    message.contains("maximum number of active connections")
        || message.contains("LimitsExceeded")
        || message.contains("Too many open files")
}

fn ble_command_connect_error_is_retryable(err: &anyhow::Error) -> bool {
    let message = format!("{err:#}");
    message.contains("BLE peripheral lookup timed out")
        || message.contains("is not visible")
        || message.contains("BLE connect timed out")
        || message.contains("BLE connect session timed out")
        || message.contains("connect BLE peripheral")
        || message.contains("le-connection-abort-by-local")
        || ble_error_indicates_in_progress(&message)
}

fn replace_scanner_targets(scanner_targets: &SharedScannerTargets, wanted_names: BTreeSet<String>) {
    match scanner_targets.write() {
        Ok(mut targets) => *targets = wanted_names,
        Err(_) => eprintln!("warning: BLE scanner target set lock is poisoned"),
    }
}

fn scanner_targets_snapshot(scanner_targets: &SharedScannerTargets) -> BTreeSet<String> {
    match scanner_targets.read() {
        Ok(targets) => targets.clone(),
        Err(_) => {
            eprintln!("warning: BLE scanner target set lock is poisoned");
            BTreeSet::new()
        }
    }
}

fn should_publish_scanner_advertisement(
    identity_name: &str,
    target_names: &BTreeSet<String>,
    last_published_by_name: &BTreeMap<String, u64>,
    now: u64,
) -> bool {
    target_names.contains(identity_name)
        && last_published_by_name
            .get(identity_name)
            .is_none_or(|last_published| {
                now.saturating_sub(*last_published) >= BLE_ADVERTISEMENT_BROADCAST_MIN_INTERVAL_MS
            })
}

fn should_log_unmanaged_txing_advertisement(
    identity_name: &str,
    target_names: &BTreeSet<String>,
    last_logged_by_name: &mut BTreeMap<String, u64>,
    now: u64,
) -> bool {
    if target_names.contains(identity_name) {
        return false;
    }
    if last_logged_by_name
        .get(identity_name)
        .is_some_and(|last_logged| {
            now.saturating_sub(*last_logged) < BLE_SCANNER_UNMANAGED_TXING_LOG_INTERVAL_MS
        })
    {
        return false;
    }
    last_logged_by_name.insert(identity_name.to_string(), now);
    true
}

fn scanner_reported_identity_name(
    advertised_name: Option<String>,
    gap_local_name: Option<String>,
) -> Option<String> {
    advertised_name.or(gap_local_name)
}

fn ble_address_is_matchable(address: &str) -> bool {
    let address = address.trim();
    !address.is_empty() && address != "00:00:00:00:00:00"
}

fn connect_session_timeout_ms(connect_timeout_ms: u64) -> u64 {
    connect_timeout_ms
        .max(BLE_RETRY_MIN_DELAY_MS)
        .saturating_mul(2)
        .min(BLE_CONNECT_SESSION_MAX_TIMEOUT_MS)
}

fn scanner_advertisement_has_fresh_signal(rssi: Option<i16>) -> bool {
    let _ = rssi;
    true
}

fn format_capability_map(capabilities: &BTreeMap<String, bool>) -> String {
    capabilities
        .iter()
        .map(|(name, available)| format!("{name}={available}"))
        .collect::<Vec<_>>()
        .join(",")
}

#[derive(Debug, Default)]
struct ScannerDebugSummary {
    total: usize,
    named: usize,
    txing_service: usize,
    target: usize,
    fresh_target: usize,
    missing_name: usize,
    stale_target: usize,
    samples: Vec<String>,
}

impl ScannerDebugSummary {
    fn record(
        &mut self,
        address: &str,
        identity_name: Option<&str>,
        rssi: Option<i16>,
        service_advertised: bool,
        target_matches: bool,
        fresh_signal: bool,
    ) {
        self.total += 1;
        if identity_name.is_some() {
            self.named += 1;
        } else {
            self.missing_name += 1;
        }
        if service_advertised {
            self.txing_service += 1;
        }
        if target_matches {
            self.target += 1;
            if fresh_signal {
                self.fresh_target += 1;
            } else {
                self.stale_target += 1;
            }
        }

        if self.samples.len() < BLE_SCANNER_DEBUG_SAMPLE_LIMIT
            && (target_matches || service_advertised || identity_name.is_some())
        {
            self.samples.push(format!(
                "{}@{} rssi={rssi:?} txingService={service_advertised} fresh={fresh_signal}",
                identity_name.unwrap_or("<unnamed>"),
                address
            ));
        }
    }

    fn log_debug(&self, target_names: &BTreeSet<String>) {
        eprintln!(
            "debug: BLE scanner visibility total={} named={} txingService={} target={} freshTarget={} missingName={} staleTarget={} targets={target_names:?} samples=[{}]",
            self.total,
            self.named,
            self.txing_service,
            self.target,
            self.fresh_target,
            self.missing_name,
            self.stale_target,
            self.samples.join("; ")
        );
    }

    fn log_no_target_warning(&self, target_names: &BTreeSet<String>) {
        eprintln!(
            "warning: BLE scanner has no target advertisements total={} named={} txingService={} missingName={} targets={target_names:?} samples=[{}]",
            self.total,
            self.named,
            self.txing_service,
            self.missing_name,
            self.samples.join("; ")
        );
    }
}

#[derive(Debug, Clone)]
struct BleNotification {
    uuid: Uuid,
    payload: Vec<u8>,
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
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

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
impl ConnectedDevice {
    async fn connect(
        spec: &DeviceSpec,
        advertisement: &Advertisement,
        connect_timeout_ms: u64,
        permit: Option<tokio::sync::OwnedSemaphorePermit>,
    ) -> Result<Self> {
        let adapter = timeout(Duration::from_millis(connect_timeout_ms), default_adapter())
            .await
            .context("BLE adapter lookup timed out")??;
        let peripheral = timeout(
            Duration::from_millis(connect_timeout_ms),
            find_peripheral_until(
                &adapter,
                &advertisement.address,
                &spec.thing_name,
                connect_timeout_ms,
            ),
        )
        .await
        .context("BLE peripheral lookup timed out")??
        .ok_or_else(|| anyhow!("BLE peripheral {} is not visible", advertisement.address))?;
        let setup_result = timeout(
            Duration::from_millis(connect_session_timeout_ms(connect_timeout_ms)),
            async {
                clear_peripheral_connect_state(&peripheral).await;
                match timeout(
                    Duration::from_millis(connect_timeout_ms),
                    peripheral.connect(),
                )
                .await
                {
                    Ok(Ok(())) => {}
                    Ok(Err(err)) => {
                        disconnect_peripheral_with_timeout(&peripheral, "connect failure cleanup")
                            .await;
                        return Err(err).context("connect BLE peripheral");
                    }
                    Err(err) => {
                        disconnect_peripheral_with_timeout(&peripheral, "connect timeout cleanup")
                            .await;
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
                        disconnect_peripheral_with_timeout(
                            &peripheral,
                            "service discovery failure cleanup",
                        )
                        .await;
                        return Err(err).context("discover BLE services");
                    }
                    Err(err) => {
                        disconnect_peripheral_with_timeout(
                            &peripheral,
                            "service discovery timeout cleanup",
                        )
                        .await;
                        return Err(err).context("BLE service discovery timed out");
                    }
                }

                let notification_setup_result = async {
                    let characteristics = peripheral.characteristics();
                    let command_char =
                        find_characteristic(&characteristics, TXING_BLE_COMMAND_UUID)
                            .ok_or_else(|| anyhow!("BLE command characteristic is missing"))?;
                    let state_char = find_characteristic(&characteristics, TXING_BLE_STATE_UUID)
                        .ok_or_else(|| anyhow!("BLE state characteristic is missing"))?;
                    let power_measurement_char =
                        find_characteristic(&characteristics, POWER_MEASUREMENT_UUID).ok_or_else(
                            || anyhow!("BLE power measurement characteristic is missing"),
                        )?;
                    let weather_measurement_char = if spec.kind.supports_weather() {
                        Some(
                            find_characteristic(&characteristics, WEATHER_MEASUREMENT_UUID)
                                .ok_or_else(|| {
                                    anyhow!("BLE weather measurement characteristic is missing")
                                })?,
                        )
                    } else {
                        None
                    };

                    let notifications = timeout(
                        Duration::from_millis(connect_timeout_ms),
                        peripheral.notifications(),
                    )
                    .await
                    .context("open BLE notification stream timed out")?
                    .context("open BLE notification stream")?;
                    timeout(
                        Duration::from_millis(connect_timeout_ms),
                        peripheral.subscribe(&state_char),
                    )
                    .await
                    .context("subscribe BLE state notifications timed out")?
                    .context("subscribe BLE state notifications")?;
                    timeout(
                        Duration::from_millis(connect_timeout_ms),
                        peripheral.subscribe(&power_measurement_char),
                    )
                    .await
                    .context("subscribe BLE power measurement notifications timed out")?
                    .context("subscribe BLE power measurement notifications")?;
                    if let Some(characteristic) = &weather_measurement_char {
                        timeout(
                            Duration::from_millis(connect_timeout_ms),
                            peripheral.subscribe(characteristic),
                        )
                        .await
                        .context("subscribe BLE weather measurement notifications timed out")?
                        .context("subscribe BLE weather measurement notifications")?;
                    }
                    Ok((
                        command_char,
                        state_char,
                        power_measurement_char,
                        weather_measurement_char,
                        notifications,
                    ))
                }
                .await;
                let (
                    command_char,
                    state_char,
                    power_measurement_char,
                    weather_measurement_char,
                    mut notifications,
                ) = match notification_setup_result {
                    Ok(value) => value,
                    Err(err) => {
                        disconnect_peripheral_with_timeout(&peripheral, "connection setup cleanup")
                            .await;
                        return Err(err);
                    }
                };
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
                    peripheral: peripheral.clone(),
                    command_char,
                    state_char,
                    power_measurement_char,
                    weather_measurement_char,
                    notification_receiver,
                    notification_task,
                    address: advertisement.address.clone(),
                    _permit: permit,
                })
            },
        )
        .await;
        match setup_result {
            Ok(result) => result,
            Err(err) => {
                disconnect_peripheral_with_timeout(&peripheral, "connect session timeout cleanup")
                    .await;
                Err(err).context("BLE connect session timed out")
            }
        }
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

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
async fn clear_peripheral_connect_state(peripheral: &Peripheral) {
    if timeout(
        Duration::from_millis(BLE_DISCONNECT_TIMEOUT_MS),
        peripheral.disconnect(),
    )
    .await
    .is_err()
    {
        eprintln!("warning: BLE peripheral disconnect timed out reason=pre-connect reset");
    }
    sleep(Duration::from_millis(BLE_CONNECT_RESET_DELAY_MS)).await;
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
async fn disconnect_peripheral_with_timeout(peripheral: &Peripheral, reason: &str) {
    match timeout(
        Duration::from_millis(BLE_DISCONNECT_TIMEOUT_MS),
        peripheral.disconnect(),
    )
    .await
    {
        Ok(Ok(())) => {}
        Ok(Err(err)) => {
            eprintln!("warning: BLE peripheral disconnect failed reason={reason} error={err}");
        }
        Err(_) => {
            eprintln!("warning: BLE peripheral disconnect timed out reason={reason}");
        }
    }
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
impl Drop for ConnectedDevice {
    fn drop(&mut self) {
        self.notification_task.abort();
        let peripheral = self.peripheral.clone();
        let state_char = self.state_char.clone();
        let power_measurement_char = self.power_measurement_char.clone();
        let weather_measurement_char = self.weather_measurement_char.clone();
        tokio::spawn(async move {
            let connected = timeout(
                Duration::from_millis(BLE_DISCONNECT_TIMEOUT_MS),
                peripheral.is_connected(),
            )
            .await
            .ok()
            .and_then(Result::ok)
            .unwrap_or(false);
            if connected {
                let _ = timeout(
                    Duration::from_millis(BLE_DISCONNECT_TIMEOUT_MS),
                    peripheral.unsubscribe(&state_char),
                )
                .await;
                let _ = timeout(
                    Duration::from_millis(BLE_DISCONNECT_TIMEOUT_MS),
                    peripheral.unsubscribe(&power_measurement_char),
                )
                .await;
                if let Some(characteristic) = weather_measurement_char {
                    let _ = timeout(
                        Duration::from_millis(BLE_DISCONNECT_TIMEOUT_MS),
                        peripheral.unsubscribe(&characteristic),
                    )
                    .await;
                }
                disconnect_peripheral_with_timeout(&peripheral, "connected device drop").await;
            }
        });
    }
}

#[cfg(not(all(feature = "ble-real", any(target_os = "linux", target_os = "macos"))))]
struct ConnectedDevice {
    connected: bool,
}

#[cfg(not(all(feature = "ble-real", any(target_os = "linux", target_os = "macos"))))]
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

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
fn find_characteristic(
    characteristics: &BTreeSet<Characteristic>,
    uuid: Uuid,
) -> Option<Characteristic> {
    characteristics
        .iter()
        .find(|characteristic| characteristic.uuid == uuid)
        .cloned()
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
static DEFAULT_ADAPTER: OnceCell<Arc<Adapter>> = OnceCell::const_new();

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
async fn default_adapter() -> Result<Arc<Adapter>> {
    let adapter = DEFAULT_ADAPTER
        .get_or_try_init(|| async {
            let manager = Manager::new().await.context("create BLE manager")?;
            let adapters = manager.adapters().await.context("list BLE adapters")?;
            let adapter = adapters
                .into_iter()
                .next()
                .ok_or_else(|| anyhow!("no BLE adapter found"))?;
            Ok::<Arc<Adapter>, anyhow::Error>(Arc::new(adapter))
        })
        .await?;
    Ok(Arc::clone(adapter))
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
async fn find_peripheral(
    adapter: &Adapter,
    address: &str,
    thing_name: &str,
) -> Result<Option<Peripheral>> {
    let address_is_matchable = ble_address_is_matchable(address);
    for peripheral in adapter
        .peripherals()
        .await
        .context("list BLE peripherals")?
    {
        let properties = match peripheral.properties().await {
            Ok(Some(properties)) => properties,
            Ok(None) => continue,
            Err(_) => continue,
        };
        let advertisement_name = properties.advertisement_name.as_deref();
        let gap_local_name = properties.local_name.as_deref();
        if advertisement_name == Some(thing_name)
            || gap_local_name == Some(thing_name)
            || (address_is_matchable && properties.address.to_string() == address)
        {
            return Ok(Some(peripheral));
        }
    }
    Ok(None)
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
async fn find_peripheral_until(
    adapter: &Adapter,
    address: &str,
    thing_name: &str,
    timeout_ms: u64,
) -> Result<Option<Peripheral>> {
    let deadline = Instant::now() + Duration::from_millis(timeout_ms);
    loop {
        if let Some(peripheral) = find_peripheral(adapter, address, thing_name).await? {
            return Ok(Some(peripheral));
        }
        let now = Instant::now();
        if now >= deadline {
            return Ok(None);
        }
        sleep(
            deadline
                .saturating_duration_since(now)
                .min(Duration::from_millis(BLE_PERIPHERAL_LOOKUP_POLL_MS)),
        )
        .await;
    }
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
async fn run_scanner(
    config: RuntimeConfig,
    advertisements: broadcast::Sender<Advertisement>,
    scanner_targets: SharedScannerTargets,
) -> Result<()> {
    let mut failure_count = 0u32;
    loop {
        match run_scanner_once(&config, advertisements.clone(), scanner_targets.clone()).await {
            Ok(()) => return Ok(()),
            Err(err) => {
                failure_count = failure_count.saturating_add(1);
                let retry_delay_ms = scanner_retry_delay_ms(&config, failure_count, &err);
                eprintln!(
                    "warning: BLE scanner failed failureCount={failure_count} retryDelayMs={retry_delay_ms} error={err:#}"
                );
                sleep(Duration::from_millis(retry_delay_ms)).await;
            }
        }
    }
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
#[derive(Debug, Default)]
struct ScannerRunState {
    seq: u64,
    last_published_by_name: BTreeMap<String, u64>,
    last_unmanaged_txing_log_by_name: BTreeMap<String, u64>,
    last_logged_targets: BTreeSet<String>,
    last_no_target_log_ms: u64,
    last_empty_cache_restart_ms: u64,
    last_property_error_log_ms: u64,
    debug_summary: ScannerDebugSummary,
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
impl ScannerRunState {
    fn log_targets_if_changed(&mut self, config: &RuntimeConfig, target_names: &BTreeSet<String>) {
        if config.debug && target_names != &self.last_logged_targets {
            eprintln!("debug: BLE scanner targets={target_names:?}");
            self.last_logged_targets = target_names.clone();
        }
    }

    fn log_property_error(&mut self, message: impl std::fmt::Display) {
        let now = now_ms();
        if now.saturating_sub(self.last_property_error_log_ms)
            >= BLE_SCANNER_PROPERTY_ERROR_LOG_INTERVAL_MS
        {
            eprintln!(
                "warning: BLE scanner skipped unreadable peripheral properties error={message}"
            );
            self.last_property_error_log_ms = now;
        }
    }

    fn log_visibility_summary_if_needed(
        &mut self,
        config: &RuntimeConfig,
        target_names: &BTreeSet<String>,
    ) -> bool {
        if target_names.is_empty() {
            self.debug_summary = ScannerDebugSummary::default();
            return false;
        }
        let now = now_ms();
        let should_restart_empty_cache = self.debug_summary.total == 0
            && now.saturating_sub(self.last_empty_cache_restart_ms)
                >= BLE_SCANNER_EMPTY_CACHE_RESTART_INTERVAL_MS;
        if config.debug {
            self.debug_summary.log_debug(target_names);
            self.debug_summary = ScannerDebugSummary::default();
            if should_restart_empty_cache {
                self.last_empty_cache_restart_ms = now;
            }
            return should_restart_empty_cache;
        }
        if self.debug_summary.fresh_target > 0 {
            self.debug_summary = ScannerDebugSummary::default();
            return false;
        }
        if now.saturating_sub(self.last_no_target_log_ms) >= BLE_SCANNER_NO_TARGET_LOG_INTERVAL_MS {
            self.debug_summary.log_no_target_warning(target_names);
            self.last_no_target_log_ms = now;
        }
        self.debug_summary = ScannerDebugSummary::default();
        if should_restart_empty_cache {
            self.last_empty_cache_restart_ms = now;
        }
        should_restart_empty_cache
    }

    async fn process_peripheral(
        &mut self,
        config: &RuntimeConfig,
        advertisements: &broadcast::Sender<Advertisement>,
        target_names: &BTreeSet<String>,
        peripheral: &Peripheral,
        source: &str,
    ) -> Result<()> {
        let properties = match peripheral.properties().await {
            Ok(Some(properties)) => properties,
            Ok(None) => return Ok(()),
            Err(err) => {
                self.log_property_error(err);
                return Ok(());
            }
        };
        let address = properties.address.to_string();
        let gap_local_name = properties
            .local_name
            .clone()
            .filter(|value| !value.trim().is_empty());
        let advertised_name = properties
            .advertisement_name
            .clone()
            .filter(|value| !value.trim().is_empty());
        let identity_name =
            scanner_reported_identity_name(advertised_name.clone(), gap_local_name.clone());
        let target_matches = identity_name
            .as_deref()
            .is_some_and(|value| target_names.contains(value));
        let service_advertised = properties.services.contains(&TXING_BLE_SERVICE_UUID);
        let fresh_signal = scanner_advertisement_has_fresh_signal(properties.rssi);
        self.debug_summary.record(
            &address,
            identity_name.as_deref(),
            properties.rssi,
            service_advertised,
            target_matches,
            fresh_signal,
        );
        if config.debug && target_matches {
            eprintln!(
                "debug: BLE scanner candidate source={source} thing={} advertisedName={:?} gapLocalName={:?} address={} rssi={:?} serviceAdvertised={} freshSignal={fresh_signal}",
                identity_name.as_deref().unwrap_or("<unnamed>"),
                advertised_name.as_deref(),
                gap_local_name.as_deref(),
                address,
                properties.rssi,
                service_advertised
            );
        }
        if !fresh_signal {
            if config.debug && target_matches {
                eprintln!(
                    "debug: BLE scanner skipped likely cached candidate source={source} thing={} address={} reason=missing-rssi",
                    identity_name.as_deref().unwrap_or("<unnamed>"),
                    address
                );
            }
            return Ok(());
        }
        let Some(identity_name) = identity_name else {
            return Ok(());
        };
        let now = now_ms();
        if service_advertised
            && should_log_unmanaged_txing_advertisement(
                &identity_name,
                target_names,
                &mut self.last_unmanaged_txing_log_by_name,
                now,
            )
        {
            eprintln!(
                "warning: BLE scanner saw unmanaged Txing advertisement thing={} address={} rssi={:?} targets={target_names:?}",
                identity_name, address, properties.rssi
            );
        }
        if !should_publish_scanner_advertisement(
            &identity_name,
            target_names,
            &self.last_published_by_name,
            now,
        ) {
            if config.debug && target_matches {
                eprintln!(
                    "debug: BLE scanner skipped candidate source={source} thing={} address={} reason=throttled-or-not-target",
                    identity_name, address
                );
            }
            return Ok(());
        }
        self.last_published_by_name
            .insert(identity_name.clone(), now);
        self.seq += 1;
        let advertisement = Advertisement {
            address,
            identity_name: Some(identity_name.clone()),
            services: properties.services,
            rssi: properties.rssi,
            observed_at_ms: now,
            seq: self.seq,
        };
        if config.debug {
            eprintln!(
                "debug: BLE scanner published advertisement source={source} thing={} address={} rssi={:?} serviceAdvertised={} seq={}",
                identity_name,
                advertisement.address,
                advertisement.rssi,
                advertisement.has_txing_service(),
                self.seq
            );
        }
        let _ = advertisements.send(advertisement);
        Ok(())
    }
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
async fn run_scanner_once(
    config: &RuntimeConfig,
    advertisements: broadcast::Sender<Advertisement>,
    scanner_targets: SharedScannerTargets,
) -> Result<()> {
    let adapter = default_adapter().await?;
    start_scan_if_needed(&adapter).await?;
    if config.debug {
        eprintln!(
            "debug: BLE scanner active mode=poll pollIntervalMs={} debugSummaryIntervalMs={}",
            config.scan_interval_ms.max(1),
            BLE_SCANNER_DEBUG_SUMMARY_INTERVAL_MS
        );
    } else {
        eprintln!(
            "started BLE scanner mode=poll pollIntervalMs={}",
            config.scan_interval_ms.max(1)
        );
    }
    let mut state = ScannerRunState::default();
    let mut poll_timer = interval(Duration::from_millis(config.scan_interval_ms.max(1)));
    poll_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);
    poll_timer.tick().await;
    let mut visibility_summary_timer =
        interval(Duration::from_millis(BLE_SCANNER_DEBUG_SUMMARY_INTERVAL_MS));
    visibility_summary_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);
    visibility_summary_timer.tick().await;
    loop {
        tokio::select! {
            _ = poll_timer.tick() => {
                let target_names = scanner_targets_snapshot(&scanner_targets);
                state.log_targets_if_changed(config, &target_names);
                if target_names.is_empty() {
                    continue;
                }
                let peripherals = match adapter.peripherals().await {
                    Ok(peripherals) => peripherals,
                    Err(err) => {
                        state.log_property_error(format!("list BLE peripherals: {err}"));
                        continue;
                    }
                };
                for peripheral in peripherals {
                    state.process_peripheral(config, &advertisements, &target_names, &peripheral, "poll").await?;
                }
            }
            _ = visibility_summary_timer.tick() => {
                let target_names = scanner_targets_snapshot(&scanner_targets);
                if state.log_visibility_summary_if_needed(config, &target_names) {
                    eprintln!(
                        "warning: BLE scanner peripheral cache is empty while targets are configured; restarting BLE scan"
                    );
                    restart_scan(&adapter).await?;
                }
            }
        }
    }
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
async fn start_scan_if_needed(adapter: &Adapter) -> Result<()> {
    match adapter.start_scan(ScanFilter::default()).await {
        Ok(()) => Ok(()),
        Err(err) => {
            let message = err.to_string();
            if ble_error_indicates_in_progress(&message) {
                recover_in_progress_scan(adapter, message).await
            } else {
                Err(err).context("start BLE scan")
            }
        }
    }
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
async fn recover_in_progress_scan(adapter: &Adapter, mut last_message: String) -> Result<()> {
    eprintln!(
        "warning: BLE scanner start found discovery already in progress; resetting discovery session error={last_message}"
    );
    for attempt in 1..=BLE_SCANNER_IN_PROGRESS_RECOVERY_ATTEMPTS {
        stop_scan_for_restart(adapter).await;
        sleep(Duration::from_millis(
            BLE_SCANNER_IN_PROGRESS_RECOVERY_DELAY_MS.saturating_mul(u64::from(attempt)),
        ))
        .await;
        match adapter.start_scan(ScanFilter::default()).await {
            Ok(()) => {
                eprintln!("BLE scanner recovered from in-progress discovery attempt={attempt}");
                return Ok(());
            }
            Err(err) => {
                last_message = err.to_string();
                if !ble_error_indicates_in_progress(&last_message) {
                    return Err(err).context("start BLE scan after resetting discovery");
                }
            }
        }
    }
    if let Err(err) = reset_bluez_adapters_after_stale_discovery().await {
        eprintln!("warning: BLE scanner BlueZ adapter reset failed: {err:#}");
    } else {
        match adapter.start_scan(ScanFilter::default()).await {
            Ok(()) => {
                eprintln!("BLE scanner recovered after BlueZ adapter reset");
                return Ok(());
            }
            Err(err) => {
                last_message = err.to_string();
                if !ble_error_indicates_in_progress(&last_message) {
                    return Err(err).context("start BLE scan after BlueZ adapter reset");
                }
            }
        }
    }
    bail!("start BLE scan after resetting discovery: {last_message}")
}

#[cfg(all(feature = "ble-real", target_os = "linux"))]
async fn reset_bluez_adapters_after_stale_discovery() -> Result<()> {
    eprintln!("warning: BLE scanner power-cycling Bluetooth adapter through bluetoothctl");
    run_bluetoothctl_power("off").await?;
    sleep(Duration::from_millis(BLE_SCANNER_ADAPTER_RESET_DELAY_MS)).await;
    run_bluetoothctl_power("on").await
}

#[cfg(all(feature = "ble-real", not(target_os = "linux")))]
async fn reset_bluez_adapters_after_stale_discovery() -> Result<()> {
    bail!("BlueZ adapter reset is only available on Linux")
}

#[cfg(all(feature = "ble-real", target_os = "linux"))]
async fn run_bluetoothctl_power(state: &'static str) -> Result<()> {
    tokio::task::spawn_blocking(move || {
        let output = std::process::Command::new("bluetoothctl")
            .args(["power", state])
            .output()
            .with_context(|| format!("run bluetoothctl power {state}"))?;
        if output.status.success() {
            return Ok(());
        }
        bail!(
            "bluetoothctl power {state} failed status={} stdout={} stderr={}",
            output.status,
            String::from_utf8_lossy(&output.stdout).trim(),
            String::from_utf8_lossy(&output.stderr).trim()
        )
    })
    .await
    .context("join bluetoothctl power command")?
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
async fn restart_scan(adapter: &Adapter) -> Result<()> {
    stop_scan_for_restart(adapter).await;
    start_scan_if_needed(adapter).await
}

#[cfg(all(feature = "ble-real", any(target_os = "linux", target_os = "macos")))]
async fn stop_scan_for_restart(adapter: &Adapter) {
    if let Err(err) = adapter.stop_scan().await {
        let message = err.to_string();
        if !ble_error_indicates_no_discovery(&message) {
            eprintln!("warning: BLE scanner stop before restart failed: {message}");
        }
    }
}

fn scanner_retry_delay_ms(config: &RuntimeConfig, failure_count: u32, err: &anyhow::Error) -> u64 {
    let message = format!("{err:#}");
    let base_delay_ms = if ble_error_indicates_host_resource_exhaustion(&message) {
        config
            .reconnect_delay_ms
            .max(BLUEZ_RESOURCE_EXHAUSTED_RECONNECT_DELAY_MS)
    } else if ble_error_indicates_in_progress(&message) {
        config
            .reconnect_delay_ms
            .max(BLUEZ_IN_PROGRESS_RECONNECT_DELAY_MS)
    } else {
        config.reconnect_delay_ms.max(BLE_RETRY_MIN_DELAY_MS)
    };
    bounded_retry_delay_ms(base_delay_ms, failure_count, BLE_RETRY_MAX_DELAY_MS)
}

#[cfg(not(all(feature = "ble-real", any(target_os = "linux", target_os = "macos"))))]
async fn run_scanner(
    _config: RuntimeConfig,
    _advertisements: broadcast::Sender<Advertisement>,
    _scanner_targets: SharedScannerTargets,
) -> Result<()> {
    bail!("build with the ble-real feature to use the live BLE adapter")
}

pub async fn run_component_runtime(config: RuntimeConfig) -> Result<()> {
    if !config.local_ipc_socket.trim().is_empty() {
        return run_local_runtime(config).await;
    }
    #[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
    {
        run_greengrass_runtime(config).await
    }
    #[cfg(not(all(feature = "greengrass-sdk", target_os = "linux")))]
    {
        let _ = config;
        bail!(
            "build with --features greengrass-sdk on Linux to run the live Greengrass runtime, or pass --local-ipc-socket for local development"
        )
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
    let scanner_targets = Arc::new(RwLock::new(BTreeSet::new()));
    let (outbound_sender, mut outbound_receiver) = mpsc::unbounded_channel();
    let (shadow_sender, mut shadow_receiver) = mpsc::unbounded_channel();
    let mut runtime = RuntimeState::new(
        config.clone(),
        advertisements.clone(),
        scanner_targets.clone(),
        outbound_sender,
        shadow_sender,
    );

    let scanner_task = if config.no_ble {
        None
    } else {
        Some(tokio::spawn(run_scanner(
            config.clone(),
            advertisements,
            scanner_targets,
        )))
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

async fn run_local_runtime(config: RuntimeConfig) -> Result<()> {
    let socket = config.local_ipc_socket.clone();
    let mut local_client = LocalPubSubClient::connect(&socket).await?;
    local_client.subscribe(INVENTORY_TOPIC).await?;
    local_client
        .subscribe(format!("{CAPABILITY_COMMAND_TOPIC_PREFIX}/+"))
        .await?;
    let local_publisher = local_client.publisher();
    if config.debug {
        eprintln!(
            "debug: BLE local runtime started socket={} noBle={} heartbeatIntervalMs={} maxConnections={}",
            socket, config.no_ble, config.heartbeat_interval_ms, config.max_connections
        );
    }

    let (advertisements, _) = broadcast::channel(SCANNER_BUFFER);
    let scanner_targets = Arc::new(RwLock::new(BTreeSet::new()));
    let (outbound_sender, mut outbound_receiver) = mpsc::unbounded_channel();
    let (shadow_sender, mut shadow_receiver) = mpsc::unbounded_channel();
    let mut runtime = RuntimeState::new(
        config.clone(),
        advertisements.clone(),
        scanner_targets.clone(),
        outbound_sender,
        shadow_sender,
    );

    let scanner_task = if config.no_ble {
        None
    } else {
        Some(tokio::spawn(run_scanner(
            config.clone(),
            advertisements,
            scanner_targets,
        )))
    };
    let mut heartbeat_seq = 0u64;
    let mut heartbeat_timer = interval(Duration::from_millis(config.heartbeat_interval_ms.max(1)));
    heartbeat_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);
    let mut shadow_skip_logged = false;

    let result = loop {
        tokio::select! {
            _ = tokio::signal::ctrl_c() => break Ok(()),
            received = local_client.recv() => {
                match received {
                    Some(Ok(message)) => {
                        if let Err(err) = runtime.handle_local_message(message.topic, message.payload).await {
                            eprintln!("warning: BLE connectivity local IPC event failed: {err:#}");
                        }
                    }
                    Some(Err(message)) => eprintln!("warning: BLE connectivity local IPC broker error: {message}"),
                    None => break Err(anyhow!("local pub/sub socket closed")),
                }
            }
            Some(outbound) = outbound_receiver.recv() => {
                if let Err(err) = local_publisher.publish(&outbound.topic, &outbound.payload).await {
                    eprintln!("warning: BLE connectivity local IPC publish failed topic={}: {err:#}", outbound.topic);
                }
            }
            Some(update) = shadow_receiver.recv() => {
                if !shadow_skip_logged {
                    eprintln!(
                        "warning: BLE local runtime is not publishing AWS IoT shadow updates directly; first skipped topic={}",
                        update.topic
                    );
                    shadow_skip_logged = true;
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
                        if let Err(err) = local_publisher.publish(&topic, &payload).await {
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

    fn weather_spec() -> DeviceSpec {
        DeviceSpec {
            thing_name: "weather-1".to_string(),
            kind: DeviceKind::Weather,
        }
    }

    fn advertisement() -> Advertisement {
        Advertisement {
            address: "E4:7C:BC:45:9B:A2".to_string(),
            identity_name: Some("power-1".to_string()),
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
    fn unit_inventory_with_ble_power_uses_power_profile() {
        let unit = InventoryDevice {
            thing_name: "unit-1".to_string(),
            thing_type: "unit".to_string(),
            capabilities: vec![
                "sparkplug".to_string(),
                "ble".to_string(),
                "power".to_string(),
                "board".to_string(),
                "mcp".to_string(),
                "video".to_string(),
            ],
            redcon_command_levels: vec![4, 3],
            redcon_rules: BTreeMap::new(),
        };

        assert_eq!(
            device_spec_from_inventory(&unit),
            Some(DeviceSpec {
                thing_name: "unit-1".to_string(),
                kind: DeviceKind::Power,
            })
        );
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

    #[test]
    fn power_background_connects_only_until_idle_state_is_known() {
        let (sender, _receiver) = mpsc::unbounded_channel();
        let (shadow_sender, _shadow_receiver) = mpsc::unbounded_channel();
        let mut session = DeviceSession::new(
            power_spec(),
            RuntimeConfig::default(),
            sender,
            shadow_sender,
            None,
        );

        assert!(session.should_connect_from_advertisement());
        session.last_redcon = Some(REDCON_IDLE);
        assert!(!session.should_connect_from_advertisement());
        session.last_redcon = Some(REDCON_ACTIVE);
        assert!(session.should_connect_from_advertisement());
    }

    #[test]
    fn weather_background_connects_for_measurements() {
        let (sender, _receiver) = mpsc::unbounded_channel();
        let (shadow_sender, _shadow_receiver) = mpsc::unbounded_channel();
        let mut session = DeviceSession::new(
            weather_spec(),
            RuntimeConfig::default(),
            sender,
            shadow_sender,
            None,
        );
        session.last_redcon = Some(REDCON_IDLE);

        assert!(session.should_connect_from_advertisement());
    }

    #[test]
    fn transient_ble_command_connect_errors_are_retryable() {
        assert!(ble_command_connect_error_is_retryable(&anyhow!(
            "BLE peripheral E4:7C:BC:45:9B:A2 is not visible"
        )));
        assert!(ble_command_connect_error_is_retryable(&anyhow!(
            "connect BLE peripheral: le-connection-abort-by-local"
        )));
        assert!(!ble_command_connect_error_is_retryable(&anyhow!(
            "BLE command characteristic is missing"
        )));
    }

    #[cfg(not(all(feature = "ble-real", any(target_os = "linux", target_os = "macos"))))]
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

    #[cfg(not(all(feature = "ble-real", any(target_os = "linux", target_os = "macos"))))]
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

    #[cfg(not(all(feature = "ble-real", any(target_os = "linux", target_os = "macos"))))]
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

    #[cfg(not(all(feature = "ble-real", any(target_os = "linux", target_os = "macos"))))]
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

    #[cfg(not(all(feature = "ble-real", any(target_os = "linux", target_os = "macos"))))]
    #[tokio::test]
    async fn connected_state_heartbeat_refreshes_local_state_without_shadow_updates() {
        let (sender, mut receiver) = mpsc::unbounded_channel();
        let (shadow_sender, mut shadow_receiver) = mpsc::unbounded_channel();
        let mut session = DeviceSession::new(
            weather_spec(),
            RuntimeConfig::default(),
            sender,
            shadow_sender,
            None,
        );
        let now = now_ms();
        session.connected = Some(ConnectedDevice { connected: true });
        session.last_redcon = Some(REDCON_IDLE);
        session.last_power_measurement = Some(TimedMeasurement {
            value: PowerMeasurement {
                battery_mv: Some(3970),
            },
            observed_at_ms: now,
        });
        session.last_weather_measurement = Some(TimedMeasurement {
            value: WeatherMeasurement {
                measured_temperature: 21.5,
                measured_pressure: 100.1,
                measured_humidity: 44.0,
            },
            observed_at_ms: now,
        });

        session.publish_aggregate_state_heartbeat(now).unwrap();

        let outbound = receiver.recv().await.unwrap();
        let state: CapabilityState = serde_json::from_slice(&outbound.payload).unwrap();
        assert_eq!(state.thing_name, "weather-1");
        assert_eq!(state.capabilities.get("sparkplug"), Some(&true));
        assert_eq!(state.capabilities.get("ble"), Some(&true));
        assert_eq!(state.capabilities.get("power"), Some(&true));
        assert_eq!(state.capabilities.get("weather"), Some(&true));
        assert!(shadow_receiver.try_recv().is_err());
    }

    #[test]
    fn bluez_in_progress_uses_extended_retry_delay() {
        let (sender, _receiver) = mpsc::unbounded_channel();
        let (shadow_sender, _shadow_receiver) = mpsc::unbounded_channel();
        let mut config = RuntimeConfig::default();
        config.reconnect_delay_ms = 2_000;
        let session = DeviceSession::new(power_spec(), config, sender, shadow_sender, None);
        let jitter = session.connect_retry_jitter_ms();

        assert_eq!(
            session.connect_retry_delay_ms(&anyhow!("connect BLE peripheral: In Progress")),
            BLUEZ_IN_PROGRESS_RECONNECT_DELAY_MS + jitter
        );
        assert_eq!(
            session.connect_retry_delay_ms(&anyhow!("BLE connect timed out")),
            2_000 + jitter
        );
    }

    #[test]
    fn ble_resource_exhaustion_uses_slow_retry_delay() {
        let (sender, _receiver) = mpsc::unbounded_channel();
        let (shadow_sender, _shadow_receiver) = mpsc::unbounded_channel();
        let mut config = RuntimeConfig::default();
        config.reconnect_delay_ms = 2_000;
        let session = DeviceSession::new(power_spec(), config, sender, shadow_sender, None);
        let jitter = session.connect_retry_jitter_ms();

        assert_eq!(
            session.connect_retry_delay_ms(&anyhow!(
                "create BLE manager: The maximum number of active connections for UID 0 has been reached"
            )),
            BLUEZ_RESOURCE_EXHAUSTED_RECONNECT_DELAY_MS + jitter
        );
    }

    #[test]
    fn connect_failures_back_off_exponentially() {
        let (sender, _receiver) = mpsc::unbounded_channel();
        let (shadow_sender, _shadow_receiver) = mpsc::unbounded_channel();
        let mut config = RuntimeConfig::default();
        config.reconnect_delay_ms = 2_000;
        let mut session = DeviceSession::new(power_spec(), config, sender, shadow_sender, None);
        let jitter = session.connect_retry_jitter_ms();
        let err = anyhow!("BLE connect timed out");

        assert_eq!(session.record_connect_failure(&err), 2_000 + jitter);
        assert_eq!(session.record_connect_failure(&err), 4_000 + jitter);
        assert_eq!(session.connect_failures, 2);

        session.reset_connect_backoff();
        assert_eq!(session.connect_failures, 0);
    }

    #[test]
    fn scanner_retry_uses_backoff_for_host_resource_exhaustion() {
        let mut config = RuntimeConfig::default();
        config.reconnect_delay_ms = 2_000;

        assert_eq!(
            scanner_retry_delay_ms(
                &config,
                1,
                &anyhow!(
                    "create BLE manager: The maximum number of active connections for UID 0 has been reached"
                ),
            ),
            BLUEZ_RESOURCE_EXHAUSTED_RECONNECT_DELAY_MS
        );
    }

    #[test]
    fn scanner_treats_scan_already_active_as_in_progress() {
        assert!(ble_error_indicates_in_progress(
            "start BLE scan: Operation already in progress"
        ));
    }

    #[test]
    fn scanner_treats_missing_discovery_as_inactive() {
        assert!(ble_error_indicates_no_discovery("No discovery started"));
    }

    #[test]
    fn scanner_advertisement_filter_only_publishes_target_names_on_interval() {
        let target_names = BTreeSet::from(["unit-1".to_string()]);
        let mut last_published_by_name = BTreeMap::new();

        assert!(should_publish_scanner_advertisement(
            "unit-1",
            &target_names,
            &last_published_by_name,
            1_000,
        ));

        last_published_by_name.insert("unit-1".to_string(), 1_000);
        assert!(!should_publish_scanner_advertisement(
            "unit-1",
            &target_names,
            &last_published_by_name,
            1_500,
        ));
        assert!(should_publish_scanner_advertisement(
            "unit-1",
            &target_names,
            &last_published_by_name,
            2_000,
        ));
        assert!(!should_publish_scanner_advertisement(
            "other",
            &target_names,
            &last_published_by_name,
            2_000,
        ));
    }

    #[test]
    fn scanner_prefers_advertised_name_as_identity() {
        assert_eq!(
            scanner_reported_identity_name(
                Some("unit-current".to_string()),
                Some("power-stale".to_string())
            ),
            Some("unit-current".to_string())
        );
        assert_eq!(
            scanner_reported_identity_name(None, Some("unit-current".to_string())),
            Some("unit-current".to_string())
        );
    }

    #[test]
    fn unmanaged_txing_advertisement_warning_is_throttled_by_name() {
        let target_names = BTreeSet::from(["unit-1".to_string()]);
        let mut last_logged_by_name = BTreeMap::new();

        assert!(should_log_unmanaged_txing_advertisement(
            "weather-old",
            &target_names,
            &mut last_logged_by_name,
            1_000,
        ));
        assert!(!should_log_unmanaged_txing_advertisement(
            "weather-old",
            &target_names,
            &mut last_logged_by_name,
            2_000,
        ));
        assert!(!should_log_unmanaged_txing_advertisement(
            "unit-1",
            &target_names,
            &mut last_logged_by_name,
            40_000,
        ));
        assert!(should_log_unmanaged_txing_advertisement(
            "weather-old",
            &target_names,
            &mut last_logged_by_name,
            31_000,
        ));
    }

    #[test]
    fn macos_placeholder_ble_address_is_not_matchable_identity() {
        assert!(!ble_address_is_matchable("00:00:00:00:00:00"));
        assert!(ble_address_is_matchable("E4:7C:BC:45:9B:A2"));
    }

    #[test]
    fn ble_connect_session_timeout_is_bounded_below_state_ttl_window() {
        assert_eq!(connect_session_timeout_ms(8_000), 16_000);
        assert_eq!(
            connect_session_timeout_ms(60_000),
            BLE_CONNECT_SESSION_MAX_TIMEOUT_MS
        );
    }

    #[test]
    fn scanner_events_are_fresh_advertisement_evidence() {
        assert!(scanner_advertisement_has_fresh_signal(Some(-55)));
        assert!(scanner_advertisement_has_fresh_signal(None));
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
