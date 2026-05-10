#![cfg_attr(
    not(all(feature = "greengrass-sdk", target_os = "linux")),
    allow(dead_code, unused_imports)
)]

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
use std::sync::OnceLock;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, anyhow, bail};
use gneiss_mqtt::client::{AsyncClient, AsyncClientHandle, ClientEvent, PublishResponse};
use gneiss_mqtt::mqtt::{PublishPacket, QualityOfService, SubscribePacket};
use gneiss_mqtt_aws::{AwsClientBuilder, WebsocketSigv4OptionsBuilder};
use tokio::sync::mpsc;
use tokio::time::{MissedTickBehavior, interval};
use txing_capability_protocol::{
    CAPABILITY_COMMAND_TOPIC_FILTER, COMMAND_ACCEPTED, COMMAND_FAILED, CapabilityCommand,
    CapabilityCommandResult, CapabilityCommandResultTarget, CapabilityHeartbeat, Inventory,
    build_capability_command_result_topic, build_capability_heartbeat_topic,
    build_capability_state_topic, command_deadline_expired, parse_capability_command_topic,
    topic_payload_thing_mismatch,
};

use crate::retained::{
    ADAPTER_ID, RETAINED_COMMAND_RESULT_FILTER, RETAINED_STATE_FILTER, RetainedCapabilityState,
    RetainedTopicKind, build_retained_command_topic, parse_retained_topic,
};

#[derive(Debug, Clone)]
pub struct RuntimeConfig {
    pub adapter_id: String,
    pub iot_endpoint: String,
    pub aws_region: String,
    pub client_id: String,
    pub heartbeat_interval_ms: u64,
    pub state_report_interval_ms: u64,
    pub keep_alive_seconds: u16,
}

impl Default for RuntimeConfig {
    fn default() -> Self {
        Self {
            adapter_id: ADAPTER_ID.to_string(),
            iot_endpoint: String::new(),
            aws_region: String::new(),
            client_id: String::new(),
            heartbeat_interval_ms: 10_000,
            state_report_interval_ms: 10_000,
            keep_alive_seconds: 60,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OutboundMessage {
    pub topic: String,
    pub payload: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AwsPublish {
    pub topic: String,
    pub payload: Vec<u8>,
    pub retain: bool,
}

#[derive(Debug, Clone)]
pub enum RuntimeAction {
    PublishRetainedCommand {
        publish: AwsPublish,
        command: CapabilityCommand,
    },
}

#[derive(Debug, Clone)]
enum RuntimeEvent {
    LocalMessage { topic: String, payload: Vec<u8> },
    MqttPublish { topic: String, payload: Vec<u8> },
}

struct RuntimeState {
    config: RuntimeConfig,
    outbound_sender: mpsc::UnboundedSender<OutboundMessage>,
    managed_things: BTreeSet<String>,
    latest_states: BTreeMap<String, RetainedCapabilityState>,
    seq: u64,
}

impl RuntimeState {
    fn new(config: RuntimeConfig, outbound_sender: mpsc::UnboundedSender<OutboundMessage>) -> Self {
        Self {
            config,
            outbound_sender,
            managed_things: BTreeSet::new(),
            latest_states: BTreeMap::new(),
            seq: 0,
        }
    }

    fn handle_local_message(
        &mut self,
        topic: String,
        payload: Vec<u8>,
    ) -> Result<Vec<RuntimeAction>> {
        if topic == txing_capability_protocol::INVENTORY_TOPIC {
            let inventory = Inventory::from_slice(&payload)
                .with_context(|| format!("decode v2 inventory from topic {topic}"))?;
            self.handle_inventory(inventory)?;
            return Ok(Vec::new());
        }

        let Some(topic_thing_name) = parse_capability_command_topic(&topic) else {
            return Ok(Vec::new());
        };
        let command = CapabilityCommand::from_slice(&payload)
            .with_context(|| format!("decode v2 capability command from topic {topic}"))?;
        if command.thing_name != topic_thing_name {
            return Err(topic_payload_thing_mismatch(
                topic_thing_name,
                &command.thing_name,
            ));
        }
        self.handle_command(command)
    }

    fn handle_inventory(&mut self, inventory: Inventory) -> Result<()> {
        self.managed_things = inventory
            .devices
            .into_iter()
            .map(|device| device.thing_name)
            .collect();
        self.latest_states
            .retain(|thing_name, _| self.managed_things.contains(thing_name));
        self.refresh_latest_states(now_ms())?;
        Ok(())
    }

    fn handle_command(&mut self, command: CapabilityCommand) -> Result<Vec<RuntimeAction>> {
        if !self.managed_things.contains(&command.thing_name) {
            return Ok(Vec::new());
        }
        if command_deadline_expired(&command, now_ms()) {
            self.publish_command_result(
                &command,
                COMMAND_FAILED,
                Some(format!(
                    "AWS command deadline expired deadlineMs={:?}",
                    command.deadline_ms
                )),
                Some(command.target.redcon),
            )?;
            return Ok(Vec::new());
        }
        let publish = AwsPublish {
            topic: build_retained_command_topic(&command.thing_name)?,
            payload: command.to_vec()?,
            retain: true,
        };
        Ok(vec![RuntimeAction::PublishRetainedCommand {
            publish,
            command,
        }])
    }

    fn handle_retained_message(&mut self, topic: String, payload: Vec<u8>) -> Result<()> {
        let Some((topic_thing_name, kind)) = parse_retained_topic(&topic) else {
            return Ok(());
        };
        if !self.managed_things.contains(topic_thing_name) {
            return Ok(());
        }
        match kind {
            RetainedTopicKind::State => {
                let state = RetainedCapabilityState::from_slice(&payload)
                    .with_context(|| format!("decode retained capability state from {topic}"))?;
                if state.thing_name != topic_thing_name {
                    return Err(topic_payload_thing_mismatch(
                        topic_thing_name,
                        &state.thing_name,
                    ));
                }
                self.latest_states
                    .insert(state.thing_name.clone(), state.clone());
                self.publish_projected_state(&state, now_ms())?;
            }
            RetainedTopicKind::CommandResult => {
                let mut result =
                    CapabilityCommandResult::from_slice(&payload).with_context(|| {
                        format!("decode retained capability command result from {topic}")
                    })?;
                if result.thing_name != topic_thing_name {
                    return Err(topic_payload_thing_mismatch(
                        topic_thing_name,
                        &result.thing_name,
                    ));
                }
                result.adapter_id = self.config.adapter_id.clone();
                self.publish_command_result_payload(result)?;
            }
            RetainedTopicKind::Command => {}
        }
        Ok(())
    }

    fn publish_command_accepted(&mut self, command: &CapabilityCommand) -> Result<()> {
        self.publish_command_result(command, COMMAND_ACCEPTED, None, Some(command.target.redcon))
    }

    fn publish_command_failed(
        &mut self,
        command: &CapabilityCommand,
        message: String,
    ) -> Result<()> {
        self.publish_command_result(
            command,
            COMMAND_FAILED,
            Some(message),
            Some(command.target.redcon),
        )
    }

    fn publish_command_result(
        &mut self,
        command: &CapabilityCommand,
        status: &str,
        message: Option<String>,
        target_redcon: Option<u8>,
    ) -> Result<()> {
        let result = CapabilityCommandResult {
            schema_version: txing_capability_protocol::SCHEMA_VERSION.to_string(),
            adapter_id: self.config.adapter_id.clone(),
            command_id: command.command_id.clone(),
            thing_name: command.thing_name.clone(),
            status: status.to_string(),
            target: CapabilityCommandResultTarget {
                redcon: target_redcon,
            },
            message,
            observed_at_ms: now_ms(),
            seq: command.seq,
        };
        self.publish_command_result_payload(result)
    }

    fn publish_command_result_payload(&self, result: CapabilityCommandResult) -> Result<()> {
        let topic =
            build_capability_command_result_topic(&result.thing_name, &self.config.adapter_id)?;
        let payload = result.to_vec()?;
        self.publish_local(topic, payload)
    }

    fn publish_projected_state(
        &mut self,
        state: &RetainedCapabilityState,
        now_ms: u64,
    ) -> Result<()> {
        self.seq += 1;
        let Some(local_state) = state.to_local_state(&self.config.adapter_id, now_ms, self.seq)
        else {
            return Ok(());
        };
        let topic = build_capability_state_topic(&local_state.thing_name, &self.config.adapter_id)?;
        let payload = local_state.to_vec()?;
        self.publish_local(topic, payload)
    }

    fn refresh_latest_states(&mut self, now_ms: u64) -> Result<()> {
        for state in self.latest_states.values().cloned().collect::<Vec<_>>() {
            self.publish_projected_state(&state, now_ms)?;
        }
        Ok(())
    }

    fn publish_heartbeat(&mut self, now_ms: u64) -> Result<()> {
        self.seq += 1;
        let heartbeat = CapabilityHeartbeat::new(
            &self.config.adapter_id,
            txing_capability_protocol::HEARTBEAT_RUNNING,
            None,
            now_ms,
            self.seq,
        );
        let topic = build_capability_heartbeat_topic(&self.config.adapter_id)?;
        let payload = heartbeat.to_vec()?;
        self.publish_local(topic, payload)
    }

    fn publish_local(&self, topic: String, payload: Vec<u8>) -> Result<()> {
        self.outbound_sender
            .send(OutboundMessage { topic, payload })
            .map_err(|_| anyhow!("outbound local pub/sub channel is closed"))
    }
}

struct MqttSession {
    client: AsyncClientHandle,
}

impl MqttSession {
    async fn new(
        endpoint: &str,
        region: &str,
        client_id: &str,
        keep_alive_seconds: u16,
        event_sender: mpsc::UnboundedSender<RuntimeEvent>,
    ) -> Result<Self> {
        eprintln!("connecting AWS connectivity MQTT clientId={client_id}");
        let sigv4_options = WebsocketSigv4OptionsBuilder::new(region).await.build();
        let mut connect_options = gneiss_mqtt::client::config::ConnectOptions::builder();
        connect_options
            .with_client_id(client_id)
            .with_keep_alive_interval_seconds(Some(keep_alive_seconds));
        let client = AwsClientBuilder::new_websockets_with_sigv4(endpoint, sigv4_options, None)?
            .with_connect_options(connect_options.build())
            .build_tokio()?;
        let listener = Arc::new(move |event: Arc<ClientEvent>| {
            if let ClientEvent::PublishReceived(received) = event.as_ref() {
                let payload = received
                    .publish
                    .payload()
                    .map(|payload| payload.to_vec())
                    .unwrap_or_default();
                let _ = event_sender.send(RuntimeEvent::MqttPublish {
                    topic: received.publish.topic().to_string(),
                    payload,
                });
            }
        }) as Arc<gneiss_mqtt::client::ClientEventListenerCallback>;
        client.start(Some(listener))?;
        eprintln!("started AWS connectivity MQTT clientId={client_id}");
        Ok(Self { client })
    }

    async fn subscribe(&self, topic_filter: String) -> Result<()> {
        let subscribe = SubscribePacket::builder()
            .with_subscription_simple(topic_filter.clone(), QualityOfService::AtLeastOnce)
            .build();
        let suback = self.client.subscribe(subscribe, None).await?;
        if let Some(reason_code) = suback.reason_codes().first() {
            if !reason_code.is_success() {
                bail!("MQTT subscribe failed for {topic_filter}: {reason_code}");
            }
        }
        Ok(())
    }

    async fn publish_retained(&self, publish: AwsPublish) -> Result<()> {
        let packet = PublishPacket::builder(publish.topic.clone(), QualityOfService::AtLeastOnce)
            .with_payload(publish.payload)
            .with_retain(publish.retain)
            .build();
        let response = self.client.publish(packet, None).await?;
        if let PublishResponse::Qos1(puback) = response {
            if !puback.reason_code().is_success() {
                bail!(
                    "MQTT publish failed for {}: {}",
                    publish.topic,
                    puback.reason_code()
                );
            }
        }
        Ok(())
    }

    fn stop(&self) -> Result<()> {
        self.client.stop(None)?;
        self.client.close()?;
        Ok(())
    }
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

    let (event_sender, mut event_receiver) = mpsc::unbounded_channel();
    let local_sender = event_sender.clone();
    let local_callback = move |topic: &str, payload: gg_sdk::SubscribeToTopicPayload<'_>| {
        let payload = match payload {
            gg_sdk::SubscribeToTopicPayload::Binary(bytes) => bytes.to_vec(),
            gg_sdk::SubscribeToTopicPayload::Json(_) => {
                eprintln!("warning: ignoring JSON local pub/sub payload on topic={topic}");
                return;
            }
        };
        let _ = local_sender.send(RuntimeEvent::LocalMessage {
            topic: topic.to_string(),
            payload,
        });
    };
    let inventory_subscription = sdk
        .subscribe_to_topic(txing_capability_protocol::INVENTORY_TOPIC, &local_callback)
        .map_err(|err| anyhow!("failed to subscribe v2 inventory topic: {err:?}"))?;
    let command_subscription = sdk
        .subscribe_to_topic(CAPABILITY_COMMAND_TOPIC_FILTER, &local_callback)
        .map_err(|err| anyhow!("failed to subscribe v2 capability command topics: {err:?}"))?;

    let (outbound_sender, mut outbound_receiver) = mpsc::unbounded_channel();
    let mut runtime = RuntimeState::new(config.clone(), outbound_sender);
    let mqtt = MqttSession::new(
        &config.iot_endpoint,
        &config.aws_region,
        &config.client_id,
        config.keep_alive_seconds,
        event_sender.clone(),
    )
    .await?;
    mqtt.subscribe(RETAINED_STATE_FILTER.to_string()).await?;
    mqtt.subscribe(RETAINED_COMMAND_RESULT_FILTER.to_string())
        .await?;

    let mut heartbeat_timer = interval(Duration::from_millis(config.heartbeat_interval_ms.max(1)));
    heartbeat_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);
    let mut state_report_timer = interval(Duration::from_millis(
        config.state_report_interval_ms.max(1),
    ));
    state_report_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);

    let result = loop {
        tokio::select! {
            _ = tokio::signal::ctrl_c() => break Ok(()),
            Some(event) = event_receiver.recv() => {
                match event {
                    RuntimeEvent::LocalMessage { topic, payload } => {
                        match runtime.handle_local_message(topic, payload) {
                            Ok(actions) => {
                                for action in actions {
                                    let RuntimeAction::PublishRetainedCommand { publish, command } = action;
                                    match mqtt.publish_retained(publish).await {
                                        Ok(()) => {
                                            if let Err(err) = runtime.publish_command_accepted(&command) {
                                                eprintln!("warning: AWS connectivity accepted result failed: {err:#}");
                                            }
                                        }
                                        Err(err) => {
                                            if let Err(result_err) = runtime.publish_command_failed(&command, format!("retained AWS command publish failed: {err:#}")) {
                                                eprintln!("warning: AWS connectivity failed result failed: {result_err:#}");
                                            }
                                        }
                                    }
                                }
                            }
                            Err(err) => eprintln!("warning: AWS connectivity local event failed: {err:#}"),
                        }
                    }
                    RuntimeEvent::MqttPublish { topic, payload } => {
                        if let Err(err) = runtime.handle_retained_message(topic, payload) {
                            eprintln!("warning: AWS connectivity retained event failed: {err:#}");
                        }
                    }
                }
            }
            Some(outbound) = outbound_receiver.recv() => {
                if let Err(err) = publish_local(&outbound.topic, &outbound.payload).await {
                    eprintln!("warning: AWS connectivity local publish failed topic={}: {err:#}", outbound.topic);
                }
            }
            _ = heartbeat_timer.tick() => {
                if let Err(err) = runtime.publish_heartbeat(now_ms()) {
                    eprintln!("warning: AWS connectivity heartbeat publish failed: {err:#}");
                }
            }
            _ = state_report_timer.tick() => {
                if let Err(err) = runtime.refresh_latest_states(now_ms()) {
                    eprintln!("warning: AWS connectivity state refresh failed: {err:#}");
                }
            }
        }
    };

    drop(command_subscription);
    drop(inventory_subscription);
    mqtt.stop()?;
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

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .try_into()
        .unwrap_or(u64::MAX)
}

#[cfg(test)]
mod tests {
    use super::*;
    use txing_capability_protocol::{
        CapabilityCommandTarget, CapabilityState, InventoryDevice, MetricValue, SCHEMA_VERSION,
    };

    fn command(redcon: u8) -> CapabilityCommand {
        CapabilityCommand {
            schema_version: SCHEMA_VERSION.to_string(),
            command_id: "cmd-1".to_string(),
            thing_name: "time-1".to_string(),
            target: CapabilityCommandTarget { redcon },
            reason: "test".to_string(),
            issued_at_ms: 1,
            deadline_ms: None,
            seq: 7,
        }
    }

    fn inventory() -> Inventory {
        Inventory {
            schema_version: SCHEMA_VERSION.to_string(),
            manager_id: "dev.txing.rig.SparkplugManager".to_string(),
            devices: vec![InventoryDevice {
                thing_name: "time-1".to_string(),
                thing_type: "time".to_string(),
                capabilities: vec!["sparkplug".to_string(), "time".to_string()],
                redcon_command_levels: vec![4, 3, 2, 1],
                redcon_rules: BTreeMap::new(),
            }],
            seq: 1,
            issued_at_ms: 1,
        }
    }

    fn runtime() -> (RuntimeState, mpsc::UnboundedReceiver<OutboundMessage>) {
        let (sender, receiver) = mpsc::unbounded_channel();
        let mut runtime = RuntimeState::new(RuntimeConfig::default(), sender);
        runtime.handle_inventory(inventory()).unwrap();
        (runtime, receiver)
    }

    #[test]
    fn inventory_filters_commands_to_managed_things() {
        let (mut runtime, _receiver) = runtime();
        let actions = runtime.handle_command(command(3)).unwrap();

        assert_eq!(actions.len(), 1);
        let RuntimeAction::PublishRetainedCommand { publish, .. } = &actions[0];
        assert_eq!(publish.topic, "txings/time-1/capability/v2/command");
        assert!(publish.retain);
    }

    #[test]
    fn command_publish_success_publishes_accepted_result() {
        let (mut runtime, mut receiver) = runtime();

        runtime.publish_command_accepted(&command(3)).unwrap();

        let outbound = receiver.try_recv().unwrap();
        assert_eq!(
            outbound.topic,
            "dev/txing/rig/v2/capability/command-result/time-1/dev.txing.rig.AwsConnectivity"
        );
        let result = CapabilityCommandResult::from_slice(&outbound.payload).unwrap();
        assert_eq!(result.status, COMMAND_ACCEPTED);
        assert_eq!(result.target.redcon, Some(3));
    }

    #[test]
    fn retained_state_forwards_with_local_adapter_id() {
        let (mut runtime, mut receiver) = runtime();
        let retained = RetainedCapabilityState {
            schema_version: SCHEMA_VERSION.to_string(),
            adapter_id: "time-lambda".to_string(),
            thing_name: "time-1".to_string(),
            capabilities: BTreeMap::from([("sparkplug".to_string(), true)]),
            metrics: BTreeMap::from([("mode".to_string(), MetricValue::string("active"))]),
            observed_at_ms: 10,
            seq: 1,
            expires_at_ms: None,
            expired_capabilities: None,
            expired_metrics: None,
        };
        let payload = serde_json::to_vec(&retained).unwrap();

        runtime
            .handle_retained_message("txings/time-1/capability/v2/state".to_string(), payload)
            .unwrap();

        let outbound = receiver.try_recv().unwrap();
        let state = CapabilityState::from_slice(&outbound.payload).unwrap();
        assert_eq!(state.adapter_id, ADAPTER_ID);
        assert_eq!(state.thing_name, "time-1");
    }

    #[test]
    fn retained_command_result_forwards_to_local_ipc() {
        let (mut runtime, mut receiver) = runtime();
        let result = CapabilityCommandResult {
            schema_version: SCHEMA_VERSION.to_string(),
            adapter_id: "time-lambda".to_string(),
            command_id: "cmd-1".to_string(),
            thing_name: "time-1".to_string(),
            status: txing_capability_protocol::COMMAND_SUCCEEDED.to_string(),
            target: CapabilityCommandResultTarget { redcon: Some(4) },
            message: None,
            observed_at_ms: 10,
            seq: 7,
        };

        runtime
            .handle_retained_message(
                "txings/time-1/capability/v2/command-result".to_string(),
                result.to_vec().unwrap(),
            )
            .unwrap();

        let outbound = receiver.try_recv().unwrap();
        assert_eq!(
            outbound.topic,
            "dev/txing/rig/v2/capability/command-result/time-1/dev.txing.rig.AwsConnectivity"
        );
    }

    #[test]
    fn heartbeat_publishes_local_status() {
        let (mut runtime, mut receiver) = runtime();

        runtime.publish_heartbeat(1000).unwrap();

        let outbound = receiver.try_recv().unwrap();
        assert_eq!(
            outbound.topic,
            "dev/txing/rig/v2/capability/heartbeat/dev.txing.rig.AwsConnectivity"
        );
        let heartbeat = CapabilityHeartbeat::from_slice(&outbound.payload).unwrap();
        assert_eq!(
            heartbeat.status,
            txing_capability_protocol::HEARTBEAT_RUNNING
        );
    }
}
