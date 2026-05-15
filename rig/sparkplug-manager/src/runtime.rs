#![cfg_attr(
    not(all(feature = "greengrass-sdk", target_os = "linux")),
    allow(dead_code, unused_imports)
)]

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
use std::sync::OnceLock;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail};
use aws_config::BehaviorVersion;
use gneiss_mqtt::client::{AsyncClient, AsyncClientHandle, ClientEvent, PublishResponse};
use gneiss_mqtt::mqtt::{PublishPacket, QualityOfService, SubscribePacket};
use gneiss_mqtt_aws::{AwsClientBuilder, WebsocketSigv4OptionsBuilder};
use serde::Deserialize;
use tokio::sync::mpsc;
use tokio::time::{MissedTickBehavior, interval, sleep};
use txing_rig_local_pubsub::LocalPubSubClient;

use crate::catalog::{TypeCatalogDevice, parse_string_list, reconstruct_type_record};
use crate::manager::{
    DevicePublication, DeviceRuntimeState, command_from_dcmd, command_result_metrics,
    device_session_spec, graceful_device_death, graceful_node_death, node_client_id,
    node_session_spec,
};
use crate::sparkplug;
use txing_capability_protocol::{
    CAPABILITY_COMMAND_RESULT_TOPIC_PREFIX, CAPABILITY_HEARTBEAT_TOPIC_PREFIX,
    CAPABILITY_STATE_TOPIC_PREFIX, CapabilityCommandResult, CapabilityHeartbeat, CapabilityState,
    INVENTORY_TOPIC, Inventory, MetricValue, build_capability_command_topic,
    parse_capability_command_result_topic, parse_capability_heartbeat_topic,
    parse_capability_state_topic,
};

const MANAGER_ID: &str = "dev.txing.rig.SparkplugManager";
const THING_INDEX_NAME: &str = "AWS_Things";
const TYPE_CATALOG_ROOT: &str = "/txing/town";
const MQTT_KEEP_ALIVE_SECONDS: u16 = 60;
const NODE_BDSEQ: u64 = 1;
const DEVICE_PUBLISH_TICK_SECONDS: u64 = 2;
const DEFAULT_COMMAND_DEADLINE_MS: u64 = 60_000;
const STARTUP_RETRY_INITIAL_DELAY_MS: u64 = 1_000;
const STARTUP_RETRY_MAX_DELAY_MS: u64 = 60_000;
const BOARD_RETAINED_CAPABILITY_STATE_FILTER: &str = "txings/+/capability/v2/state";
const BOARD_RETAINED_CAPABILITIES: [&str; 3] = ["board", "mcp", "video"];

#[derive(Debug, Clone)]
pub struct RuntimeConfig {
    pub rig_id: String,
    pub town_id: String,
    pub aws_region: String,
    pub iot_endpoint: String,
    pub inventory_interval_seconds: u64,
    pub command_deadline_ms: u64,
    pub local_ipc_socket: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OutboundMessage {
    pub topic: String,
    pub payload: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ThingRegistration {
    thing_name: String,
    thing_type: String,
    rig_id: Option<String>,
    town_id: Option<String>,
    capabilities: Option<Vec<String>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct RegistryInventory {
    rig_type: String,
    devices: Vec<txing_capability_protocol::InventoryDevice>,
}

#[derive(Debug, Clone, PartialEq, Deserialize)]
struct RetainedCapabilityStatePayload {
    #[serde(rename = "schemaVersion")]
    schema_version: String,
    #[serde(rename = "adapterId")]
    adapter_id: String,
    #[serde(rename = "thingName")]
    thing_name: String,
    capabilities: BTreeMap<String, bool>,
    #[serde(default)]
    metrics: BTreeMap<String, MetricValue>,
    #[serde(rename = "observedAtMs", default)]
    observed_at_ms: u64,
    #[serde(default)]
    seq: u64,
}

impl RetainedCapabilityStatePayload {
    fn into_capability_state(self) -> Result<CapabilityState> {
        let state = CapabilityState {
            schema_version: self.schema_version,
            adapter_id: self.adapter_id,
            thing_name: self.thing_name,
            capabilities: self.capabilities,
            metrics: self.metrics,
            observed_at_ms: self.observed_at_ms,
            seq: self.seq,
        };
        state.validate()?;
        Ok(state)
    }
}

#[derive(Debug, Clone)]
enum RuntimeEvent {
    LocalMessage { topic: String, payload: Vec<u8> },
    MqttPublish { topic: String, payload: Vec<u8> },
}

struct AwsRegistryClient {
    iot: aws_sdk_iot::Client,
    ssm: aws_sdk_ssm::Client,
}

impl AwsRegistryClient {
    fn new(iot: aws_sdk_iot::Client, ssm: aws_sdk_ssm::Client) -> Self {
        Self { iot, ssm }
    }

    async fn describe_endpoint(&self) -> Result<String> {
        let response = self
            .iot
            .describe_endpoint()
            .endpoint_type("iot:Data-ATS")
            .send()
            .await
            .context("describe AWS IoT Data-ATS endpoint")?;
        let endpoint = response
            .endpoint_address()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .ok_or_else(|| {
                anyhow::anyhow!("AWS IoT DescribeEndpoint returned no endpointAddress")
            })?;
        Ok(endpoint.to_string())
    }

    async fn load_inventory(&self, rig_id: &str) -> Result<RegistryInventory> {
        let rig = self.describe_thing(rig_id).await?;
        let rig_type = rig.thing_type;
        let thing_names = self.list_rig_thing_names(rig_id).await?;
        let mut devices = Vec::new();
        let mut type_cache: BTreeMap<String, TypeCatalogDevice> = BTreeMap::new();
        for thing_name in thing_names {
            let registration = match self.describe_thing(&thing_name).await {
                Ok(registration) => registration,
                Err(err) => {
                    eprintln!(
                        "warning: skipping thing={thing_name} from fleet index rig={rig_id}: {err:#}"
                    );
                    continue;
                }
            };
            if !is_managed_device_registration(&registration, rig_id) {
                continue;
            }
            let type_record = match type_cache.get(&registration.thing_type) {
                Some(record) => record.clone(),
                None => {
                    let record = match self
                        .load_device_type(&rig_type, &registration.thing_type)
                        .await
                    {
                        Ok(record) => record,
                        Err(err) => {
                            eprintln!(
                                "warning: skipping thing={} type={} because type catalog record is unavailable: {err:#}",
                                registration.thing_name, registration.thing_type
                            );
                            continue;
                        }
                    };
                    type_cache.insert(registration.thing_type.clone(), record.clone());
                    record
                }
            };
            if type_record.redcon_rules.is_empty() {
                eprintln!(
                    "warning: skipping thing={} type={} because redconRules are not defined for v2 capability runtime",
                    registration.thing_name, registration.thing_type
                );
                continue;
            }
            let capabilities = match validate_registration_capabilities(&registration, &type_record)
            {
                Ok(capabilities) => capabilities,
                Err(err) => {
                    eprintln!(
                        "warning: skipping thing={} type={} because capabilities attribute is invalid: {err:#}",
                        registration.thing_name, registration.thing_type
                    );
                    continue;
                }
            };
            devices.push(
                type_record
                    .to_inventory_device_with_capabilities(registration.thing_name, capabilities),
            );
        }
        devices.sort_by(|left, right| left.thing_name.cmp(&right.thing_name));
        Ok(RegistryInventory { rig_type, devices })
    }

    async fn list_rig_thing_names(&self, rig_id: &str) -> Result<Vec<String>> {
        let query = format!("attributes.rigId:{rig_id} AND attributes.townId:*");
        let mut next_token = None;
        let mut names = BTreeSet::new();
        loop {
            let response = self
                .iot
                .search_index()
                .index_name(THING_INDEX_NAME)
                .query_string(&query)
                .max_results(100)
                .set_next_token(next_token.take())
                .send()
                .await
                .with_context(|| format!("search AWS IoT fleet index for rig {rig_id}"))?;
            for thing in response.things() {
                if let Some(name) = thing
                    .thing_name()
                    .map(str::trim)
                    .filter(|value| !value.is_empty())
                {
                    names.insert(name.to_string());
                }
            }
            next_token = response.next_token().map(ToString::to_string);
            if next_token.is_none() {
                break;
            }
        }
        Ok(names.into_iter().collect())
    }

    async fn describe_thing(&self, thing_name: &str) -> Result<ThingRegistration> {
        let response = self
            .iot
            .describe_thing()
            .thing_name(thing_name)
            .send()
            .await
            .with_context(|| format!("describe AWS IoT thing {thing_name}"))?;
        let thing_type = response
            .thing_type_name()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .ok_or_else(|| anyhow::anyhow!("thing {thing_name} is missing thingTypeName"))?
            .to_string();
        let attributes = response.attributes();
        let capabilities = attributes
            .and_then(|items| normalize_attribute(items.get("capabilities")))
            .map(|value| parse_string_list(&value))
            .transpose()
            .with_context(|| format!("parse capabilities attribute on thing {thing_name}"))?;
        Ok(ThingRegistration {
            thing_name: thing_name.to_string(),
            thing_type,
            rig_id: attributes.and_then(|items| normalize_attribute(items.get("rigId"))),
            town_id: attributes.and_then(|items| normalize_attribute(items.get("townId"))),
            capabilities,
        })
    }

    async fn load_device_type(
        &self,
        rig_type: &str,
        device_type: &str,
    ) -> Result<TypeCatalogDevice> {
        let path = format!("{TYPE_CATALOG_ROOT}/{rig_type}/{device_type}");
        let mut next_token = None;
        let mut parameters = Vec::new();
        loop {
            let response = self
                .ssm
                .get_parameters_by_path()
                .path(&path)
                .recursive(true)
                .with_decryption(false)
                .max_results(10)
                .set_next_token(next_token.take())
                .send()
                .await
                .with_context(|| format!("read SSM type catalog path {path}"))?;
            for parameter in response.parameters() {
                let Some(name) = parameter.name() else {
                    continue;
                };
                let Some(value) = parameter.value() else {
                    continue;
                };
                parameters.push((name.to_string(), value.to_string()));
            }
            next_token = response.next_token().map(ToString::to_string);
            if next_token.is_none() {
                break;
            }
        }
        reconstruct_type_record(&parameters)
            .with_context(|| format!("reconstruct SSM type catalog record {path}"))
    }
}

fn normalize_attribute(value: Option<&String>) -> Option<String> {
    value
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
}

fn is_managed_device_registration(registration: &ThingRegistration, rig_id: &str) -> bool {
    registration.thing_name != rig_id && registration.rig_id.as_deref() == Some(rig_id)
}

fn validate_registration_capabilities(
    registration: &ThingRegistration,
    type_record: &TypeCatalogDevice,
) -> Result<Vec<String>> {
    let capabilities = registration
        .capabilities
        .as_ref()
        .ok_or_else(|| anyhow::anyhow!("missing capabilities attribute"))?;
    if capabilities != &type_record.capabilities {
        bail!(
            "thing capabilities [{}] do not match type catalog capabilities [{}]",
            capabilities.join(","),
            type_record.capabilities.join(",")
        );
    }
    Ok(capabilities.clone())
}

struct MqttSession {
    client: AsyncClientHandle,
    seq: u64,
}

impl MqttSession {
    async fn new(
        endpoint: &str,
        region: &str,
        spec: crate::manager::MqttSessionSpec,
        event_sender: Option<mpsc::UnboundedSender<RuntimeEvent>>,
    ) -> Result<Self> {
        let client_id = spec.client_id.clone();
        let will_topic = spec.will.topic.clone();
        eprintln!("connecting Sparkplug MQTT clientId={client_id} willTopic={will_topic}");
        let sigv4_options = WebsocketSigv4OptionsBuilder::new(region).await.build();
        let will = PublishPacket::builder(spec.will.topic.clone(), QualityOfService::AtLeastOnce)
            .with_payload(spec.will.payload)
            .build();
        let mut connect_options = gneiss_mqtt::client::config::ConnectOptions::builder();
        connect_options
            .with_client_id(&client_id)
            .with_keep_alive_interval_seconds(Some(MQTT_KEEP_ALIVE_SECONDS))
            .with_will(will);
        let client = AwsClientBuilder::new_websockets_with_sigv4(endpoint, sigv4_options, None)?
            .with_connect_options(connect_options.build())
            .build_tokio()?;
        let listener = event_sender.map(|sender| {
            Arc::new(move |event: Arc<ClientEvent>| {
                if let ClientEvent::PublishReceived(received) = event.as_ref() {
                    let payload = received
                        .publish
                        .payload()
                        .map(|payload| payload.to_vec())
                        .unwrap_or_default();
                    let _ = sender.send(RuntimeEvent::MqttPublish {
                        topic: received.publish.topic().to_string(),
                        payload,
                    });
                }
            }) as Arc<gneiss_mqtt::client::ClientEventListenerCallback>
        });
        client.start(listener)?;
        eprintln!("started Sparkplug MQTT clientId={client_id}");
        Ok(Self { client, seq: 0 })
    }

    fn next_seq(&mut self) -> u64 {
        let seq = self.seq;
        self.seq = (self.seq + 1) % 256;
        seq
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

    async fn publish(&self, topic: String, payload: Vec<u8>) -> Result<()> {
        let publish = PublishPacket::builder(topic.clone(), QualityOfService::AtLeastOnce)
            .with_payload(payload)
            .build();
        let response = self.client.publish(publish, None).await?;
        if let PublishResponse::Qos1(puback) = response {
            if !puback.reason_code().is_success() {
                bail!("MQTT publish failed for {topic}: {}", puback.reason_code());
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

struct ManagedDevice {
    state: DeviceRuntimeState,
    session: Option<MqttSession>,
}

struct SparkplugRuntime {
    config: RuntimeConfig,
    registry: AwsRegistryClient,
    devices: BTreeMap<String, ManagedDevice>,
    node_session: Option<MqttSession>,
    inventory_seq: u64,
    node_seq: u64,
    node_born: bool,
    command_seq: u64,
    event_sender: mpsc::UnboundedSender<RuntimeEvent>,
    outbound_sender: mpsc::UnboundedSender<OutboundMessage>,
}

impl SparkplugRuntime {
    fn new(
        config: RuntimeConfig,
        registry: AwsRegistryClient,
        event_sender: mpsc::UnboundedSender<RuntimeEvent>,
        outbound_sender: mpsc::UnboundedSender<OutboundMessage>,
    ) -> Self {
        Self {
            config,
            registry,
            devices: BTreeMap::new(),
            node_session: None,
            inventory_seq: 0,
            node_seq: 0,
            node_born: false,
            command_seq: 0,
            event_sender,
            outbound_sender,
        }
    }

    fn next_node_seq(&mut self) -> u64 {
        let seq = self.node_seq;
        self.node_seq = (self.node_seq + 1) % 256;
        seq
    }

    fn next_command_id(&mut self, thing_name: &str) -> String {
        self.command_seq += 1;
        format!("dcmd-{thing_name}-{}", self.command_seq)
    }

    async fn connect_node(&mut self) -> Result<()> {
        if self.node_session.is_some() {
            return Ok(());
        }
        let spec = node_session_spec(
            &self.config.town_id,
            &self.config.rig_id,
            &node_client_id(&self.config.rig_id),
            NODE_BDSEQ,
            now_ms(),
        )?;
        let node_session = MqttSession::new(
            &self.config.iot_endpoint,
            &self.config.aws_region,
            spec,
            Some(self.event_sender.clone()),
        )
        .await?;
        let dcmd_filter =
            sparkplug::build_device_topic(&self.config.town_id, "DCMD", &self.config.rig_id, "+");
        node_session.subscribe(dcmd_filter).await?;
        node_session
            .subscribe(BOARD_RETAINED_CAPABILITY_STATE_FILTER.to_string())
            .await?;
        self.node_session = Some(node_session);
        Ok(())
    }

    async fn publish_node_birth(&mut self) -> Result<()> {
        let topic =
            sparkplug::build_node_topic(&self.config.town_id, "NBIRTH", &self.config.rig_id);
        let seq = self.next_node_seq();
        let payload = sparkplug::build_node_birth_payload(1, NODE_BDSEQ, seq, now_ms())?;
        self.node_session()?
            .publish(topic, payload)
            .await
            .context("publish Sparkplug NBIRTH")?;
        self.node_born = true;
        Ok(())
    }

    async fn publish_node_death(&mut self) -> Result<()> {
        if !self.node_born {
            return Ok(());
        }
        let (topic, payload) = graceful_node_death(
            &self.config.town_id,
            &self.config.rig_id,
            NODE_BDSEQ,
            now_ms(),
        )?;
        self.node_session()?
            .publish(topic, payload)
            .await
            .context("publish Sparkplug NDEATH")?;
        self.node_born = false;
        Ok(())
    }

    fn node_session(&self) -> Result<&MqttSession> {
        self.node_session
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("Sparkplug node MQTT session is not connected"))
    }

    async fn refresh_inventory(&mut self) -> Result<()> {
        let previous_names = self.devices.keys().cloned().collect::<BTreeSet<_>>();
        let inventory = self.registry.load_inventory(&self.config.rig_id).await?;
        let next_names = inventory
            .devices
            .iter()
            .map(|device| device.thing_name.clone())
            .collect::<BTreeSet<_>>();

        let removed = self
            .devices
            .keys()
            .filter(|thing_name| !next_names.contains(*thing_name))
            .cloned()
            .collect::<Vec<_>>();
        for thing_name in removed {
            if let Some(device) = self.devices.remove(&thing_name) {
                self.shutdown_device(device, true).await?;
            }
        }

        for inventory_device in inventory.devices {
            self.devices
                .entry(inventory_device.thing_name.clone())
                .and_modify(|device| device.state.replace_inventory(inventory_device.clone()))
                .or_insert_with(|| ManagedDevice {
                    state: DeviceRuntimeState::new(inventory_device),
                    session: None,
                });
        }
        if previous_names != next_names {
            eprintln!(
                "Sparkplug inventory updated rigId={} devices={next_names:?}",
                self.config.rig_id
            );
        }
        Ok(())
    }

    async fn publish_inventory(&mut self) -> Result<()> {
        self.inventory_seq += 1;
        let devices = self
            .devices
            .values()
            .map(|device| device.state.inventory().clone())
            .collect::<Vec<_>>();
        let inventory = Inventory::new(MANAGER_ID, devices, self.inventory_seq, now_ms());
        self.publish_local(INVENTORY_TOPIC.to_string(), inventory.to_vec()?)
    }

    async fn handle_local_message(&mut self, topic: String, payload: Vec<u8>) -> Result<()> {
        if let Some((topic_thing_name, topic_adapter_id)) = parse_capability_state_topic(&topic) {
            let state = CapabilityState::from_slice(&payload)
                .with_context(|| format!("decode capability state from local topic {topic}"))?;
            validate_state_topic_payload(topic_thing_name, topic_adapter_id, &state)?;
            if let Some(device) = self.devices.get_mut(&state.thing_name) {
                device.state.observe_state(state)?;
            }
            self.publish_device_changes().await?;
            return Ok(());
        }
        if let Some((topic_thing_name, topic_adapter_id)) =
            parse_capability_command_result_topic(&topic)
        {
            let result = CapabilityCommandResult::from_slice(&payload).with_context(|| {
                format!("decode capability command result from local topic {topic}")
            })?;
            validate_result_topic_payload(topic_thing_name, topic_adapter_id, &result)?;
            self.handle_command_result(result).await?;
            return Ok(());
        }
        if let Some(topic_adapter_id) = parse_capability_heartbeat_topic(&topic) {
            let heartbeat = CapabilityHeartbeat::from_slice(&payload)
                .with_context(|| format!("decode capability heartbeat from local topic {topic}"))?;
            validate_heartbeat_topic_payload(topic_adapter_id, &heartbeat)?;
        }
        Ok(())
    }

    async fn handle_command_result(&mut self, result: CapabilityCommandResult) -> Result<()> {
        result.validate()?;
        let Some(device) = self.devices.get_mut(&result.thing_name) else {
            return Ok(());
        };
        let Some(session) = device.session.as_mut() else {
            return Ok(());
        };
        let snapshot = device.state.snapshot(now_ms());
        if !snapshot.sparkplug_available {
            return Ok(());
        }
        let redcon = snapshot.redcon.unwrap_or(4);
        let seq = session.next_seq();
        let topic = sparkplug::build_device_topic(
            &self.config.town_id,
            "DDATA",
            &self.config.rig_id,
            &result.thing_name,
        );
        let payload = sparkplug::build_device_report_payload(
            redcon,
            seq,
            now_ms(),
            command_result_metrics(&result)?,
        )?;
        session.publish(topic, payload).await?;
        Ok(())
    }

    async fn handle_mqtt_publish(&mut self, topic: String, payload: Vec<u8>) -> Result<()> {
        if let Some(topic_thing_name) = parse_retained_capability_state_topic(&topic) {
            let Some(state) = decode_retained_capability_state_payload(&topic, &payload) else {
                return Ok(());
            };
            if let Err(err) = validate_retained_state_topic_payload(topic_thing_name, &state) {
                eprintln!(
                    "warning: ignoring invalid board-owned retained capability state topic={topic}: {err:#}"
                );
                return Ok(());
            }
            if !state_has_board_owned_capability(&state) {
                return Ok(());
            }
            if let Some(device) = self.devices.get_mut(&state.thing_name) {
                device.state.observe_state(state)?;
            }
            self.publish_device_changes().await?;
            return Ok(());
        }

        let Some(thing_name) = parse_dcmd_topic(&topic, &self.config.town_id, &self.config.rig_id)
        else {
            return Ok(());
        };
        if !self.devices.contains_key(thing_name) {
            return Ok(());
        }
        let command_id = self.next_command_id(thing_name);
        let issued_at_ms = now_ms();
        let deadline_ms = if self.config.command_deadline_ms > 0 {
            Some(
                issued_at_ms
                    .checked_add(self.config.command_deadline_ms)
                    .ok_or_else(|| anyhow::anyhow!("command deadline overflow"))?,
            )
        } else {
            None
        };
        let Some(command) =
            command_from_dcmd(thing_name, &payload, command_id, issued_at_ms, deadline_ms)?
        else {
            return Ok(());
        };
        let command_topic = build_capability_command_topic(thing_name)?;
        self.publish_local(command_topic, command.to_vec()?)
    }

    fn publish_local(&self, topic: String, payload: Vec<u8>) -> Result<()> {
        self.outbound_sender
            .send(OutboundMessage { topic, payload })
            .map_err(|_| anyhow::anyhow!("outbound local pub/sub channel is closed"))
    }

    async fn publish_device_changes(&mut self) -> Result<()> {
        let now = now_ms();
        let names = self.devices.keys().cloned().collect::<Vec<_>>();
        for thing_name in names {
            let publication = {
                let device = self
                    .devices
                    .get_mut(&thing_name)
                    .expect("device name came from devices map");
                device.state.decide_publication(now)?
            };
            match publication {
                DevicePublication::Birth { redcon, metrics } => {
                    self.publish_device_report(&thing_name, "DBIRTH", redcon, metrics)
                        .await?;
                }
                DevicePublication::Data { redcon, metrics } => {
                    self.publish_device_report(&thing_name, "DDATA", redcon, metrics)
                        .await?;
                }
                DevicePublication::Death => {
                    self.publish_device_death(&thing_name).await?;
                }
                DevicePublication::None => {}
            }
        }
        Ok(())
    }

    async fn publish_device_report(
        &mut self,
        thing_name: &str,
        message_type: &str,
        redcon: u8,
        metrics: Vec<sparkplug::Metric>,
    ) -> Result<()> {
        self.ensure_device_session(thing_name).await?;
        let device = self
            .devices
            .get_mut(thing_name)
            .ok_or_else(|| anyhow::anyhow!("managed device {thing_name} is missing"))?;
        let session = device
            .session
            .as_mut()
            .ok_or_else(|| anyhow::anyhow!("device MQTT session for {thing_name} is missing"))?;
        let seq = session.next_seq();
        let topic = sparkplug::build_device_topic(
            &self.config.town_id,
            message_type,
            &self.config.rig_id,
            thing_name,
        );
        let payload = sparkplug::build_device_report_payload(redcon, seq, now_ms(), metrics)?;
        session.publish(topic, payload).await
    }

    async fn ensure_device_session(&mut self, thing_name: &str) -> Result<()> {
        let device = self
            .devices
            .get_mut(thing_name)
            .ok_or_else(|| anyhow::anyhow!("managed device {thing_name} is missing"))?;
        if device.session.is_some() {
            return Ok(());
        }
        let spec = device_session_spec(
            &self.config.town_id,
            &self.config.rig_id,
            thing_name,
            now_ms(),
        )?;
        let session = MqttSession::new(
            &self.config.iot_endpoint,
            &self.config.aws_region,
            spec,
            None,
        )
        .await?;
        device.session = Some(session);
        Ok(())
    }

    async fn publish_device_death(&mut self, thing_name: &str) -> Result<()> {
        let Some(device) = self.devices.get_mut(thing_name) else {
            return Ok(());
        };
        let Some(mut session) = device.session.take() else {
            return Ok(());
        };
        let seq = session.next_seq();
        let (topic, payload) = graceful_device_death(
            &self.config.town_id,
            &self.config.rig_id,
            thing_name,
            seq,
            now_ms(),
        )?;
        session.publish(topic, payload).await?;
        session.stop()?;
        Ok(())
    }

    async fn shutdown_device(
        &mut self,
        mut device: ManagedDevice,
        explicit_death: bool,
    ) -> Result<()> {
        if let Some(mut session) = device.session.take() {
            if explicit_death {
                let thing_name = device.state.inventory().thing_name.clone();
                let seq = session.next_seq();
                let (topic, payload) = graceful_device_death(
                    &self.config.town_id,
                    &self.config.rig_id,
                    &thing_name,
                    seq,
                    now_ms(),
                )?;
                session.publish(topic, payload).await?;
            }
            session.stop()?;
        }
        Ok(())
    }

    async fn shutdown(&mut self) -> Result<()> {
        let names = self.devices.keys().cloned().collect::<Vec<_>>();
        for thing_name in names {
            self.publish_device_death(&thing_name).await?;
        }
        self.publish_node_death().await?;
        if let Some(session) = self.node_session.take() {
            session.stop()?;
        }
        Ok(())
    }
}

pub async fn run_runtime(mut config: RuntimeConfig) -> Result<()> {
    if config.command_deadline_ms == 0 {
        config.command_deadline_ms = DEFAULT_COMMAND_DEADLINE_MS;
    }

    if !config.local_ipc_socket.trim().is_empty() {
        return run_local_runtime(config).await;
    }

    #[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
    {
        return run_greengrass_runtime(config).await;
    }
    #[cfg(not(all(feature = "greengrass-sdk", target_os = "linux")))]
    {
        let _ = config;
        bail!(
            "build with --features greengrass-sdk on Linux to run the live Greengrass runtime, or pass --local-ipc-socket for local development"
        )
    }
}

async fn prepare_runtime_config(
    mut config: RuntimeConfig,
) -> Result<(RuntimeConfig, AwsRegistryClient)> {
    let aws_config = aws_config::load_defaults(BehaviorVersion::latest()).await;
    let registry = AwsRegistryClient::new(
        aws_sdk_iot::Client::new(&aws_config),
        aws_sdk_ssm::Client::new(&aws_config),
    );
    if config.iot_endpoint.trim().is_empty() {
        config.iot_endpoint = registry.describe_endpoint().await?;
    }
    if config.aws_region.trim().is_empty() {
        config.aws_region = aws_config
            .region()
            .map(ToString::to_string)
            .ok_or_else(|| anyhow::anyhow!("AWS region is required"))?;
    }
    if config.rig_id.trim().is_empty() {
        config.rig_id = resolve_greengrass_thing_name()?;
    }
    if config.town_id.trim().is_empty() {
        let rig = registry.describe_thing(&config.rig_id).await?;
        config.town_id = rig.town_id.ok_or_else(|| {
            anyhow::anyhow!(
                "rig thing {} is missing townId attribute; pass --town-id or fix the thing registration",
                config.rig_id
            )
        })?;
    }
    Ok((config, registry))
}

async fn prepare_runtime_config_with_retry(
    config: RuntimeConfig,
    runtime_label: &str,
) -> Result<(RuntimeConfig, AwsRegistryClient)> {
    let mut failure_count = 0u32;
    loop {
        match prepare_runtime_config(config.clone()).await {
            Ok(result) => {
                if failure_count > 0 {
                    eprintln!(
                        "Sparkplug {runtime_label} config recovered after failureCount={failure_count}"
                    );
                }
                return Ok(result);
            }
            Err(err) => {
                failure_count = failure_count.saturating_add(1);
                let retry_delay_ms = startup_retry_delay_ms(failure_count);
                eprintln!(
                    "warning: Sparkplug {runtime_label} config failed failureCount={failure_count} retryDelayMs={retry_delay_ms} error={err:#}"
                );
                sleep(Duration::from_millis(retry_delay_ms)).await;
            }
        }
    }
}

async fn initialize_sparkplug_with_retry(runtime: &mut SparkplugRuntime) -> Result<()> {
    let mut failure_count = 0u32;
    loop {
        match initialize_sparkplug(runtime).await {
            Ok(()) => {
                if failure_count > 0 {
                    eprintln!("Sparkplug startup recovered after failureCount={failure_count}");
                }
                return Ok(());
            }
            Err(err) => {
                failure_count = failure_count.saturating_add(1);
                let retry_delay_ms = startup_retry_delay_ms(failure_count);
                eprintln!(
                    "warning: Sparkplug startup failed failureCount={failure_count} retryDelayMs={retry_delay_ms} error={err:#}"
                );
                sleep(Duration::from_millis(retry_delay_ms)).await;
            }
        }
    }
}

async fn initialize_sparkplug(runtime: &mut SparkplugRuntime) -> Result<()> {
    runtime.refresh_inventory().await?;
    runtime.connect_node().await?;
    runtime.publish_node_birth().await?;
    runtime.publish_inventory().await
}

fn startup_retry_delay_ms(failure_count: u32) -> u64 {
    let shift = failure_count.saturating_sub(1).min(16);
    STARTUP_RETRY_INITIAL_DELAY_MS
        .saturating_mul(1_u64 << shift)
        .min(STARTUP_RETRY_MAX_DELAY_MS)
}

#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
async fn run_greengrass_runtime(config: RuntimeConfig) -> Result<()> {
    validate_greengrass_ipc_environment()?;
    let (config, registry) = prepare_runtime_config_with_retry(config, "runtime").await?;
    eprintln!(
        "resolved Sparkplug runtime rigId={} townId={} inventoryIntervalSeconds={} commandDeadlineMs={}",
        config.rig_id,
        config.town_id,
        config.inventory_interval_seconds,
        config.command_deadline_ms
    );

    let (event_sender, mut event_receiver) = mpsc::unbounded_channel();
    let (outbound_sender, mut outbound_receiver) = mpsc::unbounded_channel();
    let mut runtime = SparkplugRuntime::new(
        config.clone(),
        registry,
        event_sender.clone(),
        outbound_sender,
    );

    let sdk = gg_sdk::Sdk::init();
    GREENGRASS_SDK
        .set(sdk)
        .map_err(|_| anyhow::anyhow!("Greengrass SDK was already initialized"))?;
    sdk.connect()
        .map_err(|err| anyhow::anyhow!("failed to connect Greengrass IPC: {err:?}"))?;
    sdk.update_state(gg_sdk::ComponentState::Running)
        .map_err(|err| anyhow::anyhow!("failed to update Greengrass component state: {err:?}"))?;

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
    let state_subscription = sdk
        .subscribe_to_topic(
            &format!("{CAPABILITY_STATE_TOPIC_PREFIX}/#"),
            &local_callback,
        )
        .map_err(|err| anyhow::anyhow!("failed to subscribe capability state topics: {err:?}"))?;
    let result_subscription = sdk
        .subscribe_to_topic(
            &format!("{CAPABILITY_COMMAND_RESULT_TOPIC_PREFIX}/#"),
            &local_callback,
        )
        .map_err(|err| {
            anyhow::anyhow!("failed to subscribe capability command result topics: {err:?}")
        })?;
    let heartbeat_subscription = sdk
        .subscribe_to_topic(
            &format!("{CAPABILITY_HEARTBEAT_TOPIC_PREFIX}/#"),
            &local_callback,
        )
        .map_err(|err| {
            anyhow::anyhow!("failed to subscribe capability heartbeat topics: {err:?}")
        })?;

    initialize_sparkplug_with_retry(&mut runtime).await?;

    let mut inventory_timer = interval(Duration::from_secs(
        config.inventory_interval_seconds.max(1),
    ));
    inventory_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);
    let mut publish_timer = interval(Duration::from_secs(DEVICE_PUBLISH_TICK_SECONDS));
    publish_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);

    let result = loop {
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {
                break Ok(());
            }
            _ = inventory_timer.tick() => {
                if let Err(err) = runtime.refresh_inventory().await {
                    eprintln!("warning: inventory refresh failed: {err:#}");
                } else if let Err(err) = runtime.publish_inventory().await {
                    eprintln!("warning: inventory publish failed: {err:#}");
                }
            }
            _ = publish_timer.tick() => {
                if let Err(err) = runtime.publish_device_changes().await {
                    eprintln!("warning: device publish tick failed: {err:#}");
                }
            }
            Some(event) = event_receiver.recv() => {
                let result = match event {
                    RuntimeEvent::LocalMessage { topic, payload } => runtime.handle_local_message(topic, payload).await,
                    RuntimeEvent::MqttPublish { topic, payload } => runtime.handle_mqtt_publish(topic, payload).await,
                };
                if let Err(err) = result {
                    eprintln!("warning: runtime event failed: {err:#}");
                }
            }
            Some(outbound) = outbound_receiver.recv() => {
                if let Err(err) = publish_greengrass_local(&outbound.topic, &outbound.payload).await {
                    eprintln!("warning: Sparkplug manager local publish failed topic={}: {err:#}", outbound.topic);
                }
            }
        }
    };

    let shutdown_result = runtime.shutdown().await;
    drop(heartbeat_subscription);
    drop(result_subscription);
    drop(state_subscription);
    result.and(shutdown_result)
}

async fn run_local_runtime(config: RuntimeConfig) -> Result<()> {
    let socket = config.local_ipc_socket.clone();
    let (config, registry) = prepare_runtime_config_with_retry(config, "local runtime").await?;
    eprintln!(
        "resolved Sparkplug local runtime rigId={} townId={} inventoryIntervalSeconds={} commandDeadlineMs={}",
        config.rig_id,
        config.town_id,
        config.inventory_interval_seconds,
        config.command_deadline_ms
    );
    let (event_sender, mut event_receiver) = mpsc::unbounded_channel();
    let (outbound_sender, mut outbound_receiver) = mpsc::unbounded_channel();
    let mut runtime =
        SparkplugRuntime::new(config.clone(), registry, event_sender, outbound_sender);

    let mut local_client = LocalPubSubClient::connect(&socket).await?;
    local_client
        .subscribe(format!("{CAPABILITY_STATE_TOPIC_PREFIX}/#"))
        .await?;
    local_client
        .subscribe(format!("{CAPABILITY_COMMAND_RESULT_TOPIC_PREFIX}/#"))
        .await?;
    local_client
        .subscribe(format!("{CAPABILITY_HEARTBEAT_TOPIC_PREFIX}/#"))
        .await?;
    let local_publisher = local_client.publisher();

    initialize_sparkplug_with_retry(&mut runtime).await?;

    let mut inventory_timer = interval(Duration::from_secs(
        config.inventory_interval_seconds.max(1),
    ));
    inventory_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);
    let mut publish_timer = interval(Duration::from_secs(DEVICE_PUBLISH_TICK_SECONDS));
    publish_timer.set_missed_tick_behavior(MissedTickBehavior::Skip);

    let result = loop {
        tokio::select! {
            _ = tokio::signal::ctrl_c() => break Ok(()),
            received = local_client.recv() => {
                match received {
                    Some(Ok(message)) => {
                        if let Err(err) = runtime.handle_local_message(message.topic, message.payload).await {
                            eprintln!("warning: Sparkplug local IPC event failed: {err:#}");
                        }
                    }
                    Some(Err(message)) => eprintln!("warning: Sparkplug local IPC broker error: {message}"),
                    None => break Err(anyhow::anyhow!("local pub/sub socket closed")),
                }
            }
            Some(event) = event_receiver.recv() => {
                let RuntimeEvent::MqttPublish { topic, payload } = event else {
                    continue;
                };
                if let Err(err) = runtime.handle_mqtt_publish(topic, payload).await {
                    eprintln!("warning: Sparkplug MQTT event failed: {err:#}");
                }
            }
            Some(outbound) = outbound_receiver.recv() => {
                if let Err(err) = local_publisher.publish(&outbound.topic, &outbound.payload).await {
                    eprintln!("warning: Sparkplug local IPC publish failed topic={}: {err:#}", outbound.topic);
                }
            }
            _ = inventory_timer.tick() => {
                if let Err(err) = runtime.refresh_inventory().await {
                    eprintln!("warning: inventory refresh failed: {err:#}");
                } else if let Err(err) = runtime.publish_inventory().await {
                    eprintln!("warning: inventory publish failed: {err:#}");
                }
            }
            _ = publish_timer.tick() => {
                if let Err(err) = runtime.publish_device_changes().await {
                    eprintln!("warning: device publish tick failed: {err:#}");
                }
            }
        }
    };

    let shutdown_result = runtime.shutdown().await;
    result.and(shutdown_result)
}

#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
async fn publish_greengrass_local(topic: &str, payload: &[u8]) -> Result<()> {
    let sdk = *GREENGRASS_SDK
        .get()
        .ok_or_else(|| anyhow::anyhow!("Greengrass SDK is not initialized"))?;
    sdk.publish_to_topic_binary(topic, payload)
        .map_err(|err| anyhow::anyhow!("failed to publish local topic {topic}: {err:?}"))
}

#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
static GREENGRASS_SDK: OnceLock<gg_sdk::Sdk> = OnceLock::new();

fn resolve_greengrass_thing_name() -> Result<String> {
    for name in [
        "TXING_RIG_ID",
        "AWS_IOT_THING_NAME",
        "THING_NAME",
        "AWS_GREENGRASS_THING_NAME",
        "GGC_THING_NAME",
    ] {
        if let Some(value) = nonempty_env(name) {
            return Ok(value);
        }
    }
    if let Some(value) = greengrass_config_thing_name("/etc/greengrass/config.yaml") {
        return Ok(value);
    }
    bail!(
        "rig id is required; pass --rig-id, set TXING_RIG_ID, or run under Greengrass with /etc/greengrass/config.yaml"
    )
}

fn nonempty_env(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn greengrass_config_thing_name(path: &str) -> Option<String> {
    let contents = std::fs::read_to_string(path).ok()?;
    contents.lines().find_map(|line| {
        let trimmed = line.trim();
        let value = trimmed.strip_prefix("thingName:")?;
        normalize_yaml_scalar(value)
    })
}

fn normalize_yaml_scalar(value: &str) -> Option<String> {
    let value = value
        .trim()
        .trim_matches('"')
        .trim_matches('\'')
        .trim()
        .to_string();
    (!value.is_empty()).then_some(value)
}

fn parse_dcmd_topic<'a>(topic: &'a str, town_id: &str, rig_id: &str) -> Option<&'a str> {
    let prefix = format!(
        "{}/{}/DCMD/{}/",
        sparkplug::SPARKPLUG_NAMESPACE,
        town_id,
        rig_id
    );
    let thing_name = topic.strip_prefix(&prefix)?;
    (!thing_name.is_empty() && !thing_name.contains('/')).then_some(thing_name)
}

fn parse_retained_capability_state_topic(topic: &str) -> Option<&str> {
    let mut parts = topic.split('/');
    if parts.next()? != "txings" {
        return None;
    }
    let thing_name = parts.next()?;
    if thing_name.is_empty()
        || parts.next()? != "capability"
        || parts.next()? != "v2"
        || parts.next()? != "state"
        || parts.next().is_some()
    {
        return None;
    }
    Some(thing_name)
}

fn decode_retained_capability_state_payload(
    topic: &str,
    payload: &[u8],
) -> Option<CapabilityState> {
    match serde_json::from_slice::<RetainedCapabilityStatePayload>(payload).and_then(|state| {
        state
            .into_capability_state()
            .map_err(serde::de::Error::custom)
    }) {
        Ok(state) => Some(state),
        Err(err) => {
            eprintln!(
                "warning: ignoring invalid board-owned retained capability state topic={topic}: {err:#}"
            );
            None
        }
    }
}

fn state_has_board_owned_capability(state: &CapabilityState) -> bool {
    state
        .capabilities
        .keys()
        .any(|capability| BOARD_RETAINED_CAPABILITIES.contains(&capability.as_str()))
}

fn validate_retained_state_topic_payload(
    topic_thing_name: &str,
    state: &CapabilityState,
) -> Result<()> {
    if state.thing_name != topic_thing_name {
        bail!(
            "retained capability state topic thingName {topic_thing_name} differs from payload thingName {}",
            state.thing_name
        );
    }
    Ok(())
}

fn validate_state_topic_payload(
    topic_thing_name: &str,
    topic_adapter_id: &str,
    state: &CapabilityState,
) -> Result<()> {
    if state.thing_name != topic_thing_name {
        bail!(
            "capability state topic thingName {topic_thing_name} differs from payload thingName {}",
            state.thing_name
        );
    }
    if state.adapter_id != topic_adapter_id {
        bail!(
            "capability state topic adapterId {topic_adapter_id} differs from payload adapterId {}",
            state.adapter_id
        );
    }
    Ok(())
}

fn validate_result_topic_payload(
    topic_thing_name: &str,
    topic_adapter_id: &str,
    result: &CapabilityCommandResult,
) -> Result<()> {
    if result.thing_name != topic_thing_name {
        bail!(
            "capability command result topic thingName {topic_thing_name} differs from payload thingName {}",
            result.thing_name
        );
    }
    if result.adapter_id != topic_adapter_id {
        bail!(
            "capability command result topic adapterId {topic_adapter_id} differs from payload adapterId {}",
            result.adapter_id
        );
    }
    Ok(())
}

fn validate_heartbeat_topic_payload(
    topic_adapter_id: &str,
    heartbeat: &CapabilityHeartbeat,
) -> Result<()> {
    if heartbeat.adapter_id != topic_adapter_id {
        bail!(
            "capability heartbeat topic adapterId {topic_adapter_id} differs from payload adapterId {}",
            heartbeat.adapter_id
        );
    }
    Ok(())
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
fn validate_greengrass_ipc_environment() -> Result<()> {
    const IPC_SOCKET_ENV: &str = "AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT";
    const IPC_AUTH_TOKEN_ENV: &str = "SVCUID";
    let missing = [IPC_SOCKET_ENV, IPC_AUTH_TOKEN_ENV]
        .into_iter()
        .filter(|name| {
            std::env::var_os(name)
                .filter(|value| !value.is_empty())
                .is_none()
        })
        .collect::<Vec<_>>();
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

    #[test]
    fn parses_device_command_topics_for_this_node_only() {
        assert_eq!(
            parse_dcmd_topic("spBv1.0/town-1/DCMD/rig-1/time-1", "town-1", "rig-1"),
            Some("time-1")
        );
        assert_eq!(
            parse_dcmd_topic("spBv1.0/town-2/DCMD/rig-1/time-1", "town-1", "rig-1"),
            None
        );
        assert_eq!(
            parse_dcmd_topic("spBv1.0/town-1/DCMD/rig-1/time-1/extra", "town-1", "rig-1"),
            None
        );
    }

    #[test]
    fn parses_retained_board_capability_state_topics() {
        assert_eq!(
            parse_retained_capability_state_topic("txings/unit-1/capability/v2/state"),
            Some("unit-1")
        );
        assert_eq!(
            parse_retained_capability_state_topic("txings/unit-1/capability/v2/command"),
            None
        );
        assert_eq!(
            parse_retained_capability_state_topic("txings/unit-1/capability/v2/state/extra"),
            None
        );
    }

    #[test]
    fn retained_state_filter_only_accepts_board_owned_capabilities() {
        let board_state = CapabilityState {
            schema_version: txing_capability_protocol::SCHEMA_VERSION.to_string(),
            adapter_id: "dev.txing.board.Capability".to_string(),
            thing_name: "unit-1".to_string(),
            capabilities: BTreeMap::from([("video".to_string(), true)]),
            metrics: BTreeMap::new(),
            observed_at_ms: 1000,
            seq: 1,
        };
        let time_state = CapabilityState {
            schema_version: txing_capability_protocol::SCHEMA_VERSION.to_string(),
            adapter_id: "dev.txing.rig.AwsConnectivity".to_string(),
            thing_name: "time-1".to_string(),
            capabilities: BTreeMap::from([("time".to_string(), true)]),
            metrics: BTreeMap::new(),
            observed_at_ms: 1000,
            seq: 1,
        };

        assert!(state_has_board_owned_capability(&board_state));
        assert!(!state_has_board_owned_capability(&time_state));
        assert!(validate_retained_state_topic_payload("unit-1", &board_state).is_ok());
        assert!(validate_retained_state_topic_payload("other", &board_state).is_err());
    }

    #[test]
    fn retained_non_board_capability_state_payload_allows_omitted_bookkeeping_fields() {
        let payload = br#"{
            "schemaVersion": "2.0",
            "adapterId": "dev.txing.rig.AwsConnectivity",
            "thingName": "time-b98n8s",
            "capabilities": {"time": true}
        }"#;

        let state = decode_retained_capability_state_payload(
            "txings/time-b98n8s/capability/v2/state",
            payload,
        )
        .expect("retained state");

        assert_eq!(state.observed_at_ms, 0);
        assert_eq!(state.seq, 0);
        assert!(!state_has_board_owned_capability(&state));
    }

    #[test]
    fn retained_board_capability_state_payload_allows_omitted_bookkeeping_fields() {
        let payload = br#"{
            "schemaVersion": "2.0",
            "adapterId": "dev.txing.board.Capability",
            "thingName": "unit-1",
            "capabilities": {"video": true}
        }"#;

        let state =
            decode_retained_capability_state_payload("txings/unit-1/capability/v2/state", payload)
                .expect("retained state");

        assert_eq!(state.observed_at_ms, 0);
        assert_eq!(state.seq, 0);
        assert!(state_has_board_owned_capability(&state));
        assert!(validate_retained_state_topic_payload("unit-1", &state).is_ok());
    }

    #[test]
    fn invalid_retained_capability_state_payload_is_ignored() {
        let payload = br#"{
            "schemaVersion": "2.0",
            "adapterId": "dev.txing.board.Capability",
            "capabilities": {"video": true}
        }"#;

        assert!(
            decode_retained_capability_state_payload("txings/unit-1/capability/v2/state", payload)
                .is_none()
        );
    }

    #[test]
    fn managed_device_registration_excludes_rig_thing_itself() {
        let rig = ThingRegistration {
            thing_name: "cloud-1".to_string(),
            thing_type: "cloud".to_string(),
            rig_id: Some("cloud-1".to_string()),
            town_id: Some("town-1".to_string()),
            capabilities: Some(vec!["sparkplug".to_string()]),
        };
        let device = ThingRegistration {
            thing_name: "time-1".to_string(),
            thing_type: "time".to_string(),
            rig_id: Some("cloud-1".to_string()),
            town_id: Some("town-1".to_string()),
            capabilities: Some(vec![
                "sparkplug".to_string(),
                "mcp".to_string(),
                "time".to_string(),
            ]),
        };

        assert!(!is_managed_device_registration(&rig, "cloud-1"));
        assert!(is_managed_device_registration(&device, "cloud-1"));
    }

    #[test]
    fn validates_thing_capabilities_against_type_catalog() {
        let type_record = TypeCatalogDevice {
            thing_type: "power".to_string(),
            capabilities: vec![
                "sparkplug".to_string(),
                "ble".to_string(),
                "power".to_string(),
            ],
            redcon_command_levels: vec![4, 3],
            redcon_rules: BTreeMap::from([
                (4, vec!["sparkplug".to_string(), "ble".to_string()]),
                (
                    3,
                    vec![
                        "sparkplug".to_string(),
                        "ble".to_string(),
                        "power".to_string(),
                    ],
                ),
            ]),
        };
        let registration = ThingRegistration {
            thing_name: "power-1".to_string(),
            thing_type: "power".to_string(),
            rig_id: Some("raspi-1".to_string()),
            town_id: Some("town-1".to_string()),
            capabilities: Some(vec![
                "sparkplug".to_string(),
                "ble".to_string(),
                "power".to_string(),
            ]),
        };

        assert_eq!(
            validate_registration_capabilities(&registration, &type_record).unwrap(),
            vec![
                "sparkplug".to_string(),
                "ble".to_string(),
                "power".to_string(),
            ]
        );

        let missing = ThingRegistration {
            capabilities: None,
            ..registration.clone()
        };
        assert!(validate_registration_capabilities(&missing, &type_record).is_err());

        let mismatched = ThingRegistration {
            capabilities: Some(vec!["sparkplug".to_string(), "ble".to_string()]),
            ..registration
        };
        assert!(validate_registration_capabilities(&mismatched, &type_record).is_err());
    }

    #[test]
    fn startup_retry_delay_uses_bounded_exponential_backoff() {
        assert_eq!(startup_retry_delay_ms(1), 1_000);
        assert_eq!(startup_retry_delay_ms(2), 2_000);
        assert_eq!(startup_retry_delay_ms(3), 4_000);
        assert_eq!(startup_retry_delay_ms(100), STARTUP_RETRY_MAX_DELAY_MS);
    }

    #[test]
    fn rejects_local_topic_payload_mismatch() {
        let state = CapabilityState {
            schema_version: txing_capability_protocol::SCHEMA_VERSION.to_string(),
            adapter_id: "dev.txing.rig.BleConnectivity".to_string(),
            thing_name: "power-1".to_string(),
            capabilities: BTreeMap::from([("sparkplug".to_string(), true)]),
            metrics: BTreeMap::new(),
            observed_at_ms: 1000,
            seq: 1,
        };

        assert!(
            validate_state_topic_payload("power-1", "dev.txing.rig.BleConnectivity", &state)
                .is_ok()
        );
        assert!(
            validate_state_topic_payload("weather-1", "dev.txing.rig.BleConnectivity", &state)
                .is_err()
        );
        assert!(validate_state_topic_payload("power-1", "other-adapter", &state).is_err());

        let heartbeat = CapabilityHeartbeat {
            schema_version: txing_capability_protocol::SCHEMA_VERSION.to_string(),
            adapter_id: "time-aws".to_string(),
            status: "running".to_string(),
            active_thing_name: None,
            observed_at_ms: 1000,
            seq: 1,
        };
        assert!(validate_heartbeat_topic_payload("time-aws", &heartbeat).is_ok());
        assert!(
            validate_heartbeat_topic_payload("dev.txing.rig.BleConnectivity", &heartbeat).is_err()
        );
    }
}
