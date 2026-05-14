use std::collections::{BTreeMap, BTreeSet};
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr, UdpSocket};
use std::process;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, anyhow, bail};
use async_trait::async_trait;
use aws_config::BehaviorVersion;
use clap::Parser;
use gneiss_mqtt::client::{AsyncClient, AsyncClientHandle, PublishResponse};
use gneiss_mqtt::mqtt::{PublishPacket, QualityOfService};
use gneiss_mqtt_aws::{AwsClientBuilder, WebsocketSigv4OptionsBuilder};
use serde::{Deserialize, Serialize};
use tokio::time::{Instant, MissedTickBehavior, interval_at};

pub const SCHEMA_VERSION: &str = "2.0";
pub const ADAPTER_ID: &str = "dev.txing.unit.Daemon";
pub const BOARD_CAPABILITY: &str = "board";
pub const BOARD_SHADOW_NAME: &str = "board";
pub const DEFAULT_CAPABILITY_TTL_SECONDS: u64 = 150;
pub const DEFAULT_HEARTBEAT_SECONDS: u64 = 60;
const MQTT_KEEP_ALIVE_SECONDS: u16 = 60;

#[derive(Debug, Parser)]
#[command(name = "daemon")]
#[command(about = "Unit board daemon")]
pub struct Cli {
    #[arg(long = "thing-id", env = "TXING_THING_ID")]
    pub thing_id: String,

    #[arg(long = "aws-region", env = "AWS_REGION")]
    pub aws_region: Option<String>,

    #[arg(long = "iot-endpoint", env = "AWS_IOT_ENDPOINT")]
    pub iot_endpoint: Option<String>,

    #[arg(long)]
    pub client_id: Option<String>,

    #[arg(long = "capability", value_name = "NAME")]
    pub capabilities: Vec<String>,

    #[arg(long, default_value_t = DEFAULT_CAPABILITY_TTL_SECONDS)]
    pub capability_ttl_seconds: u64,

    #[arg(long, default_value_t = DEFAULT_HEARTBEAT_SECONDS)]
    pub heartbeat_seconds: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeConfig {
    pub thing_id: String,
    pub aws_region: Option<String>,
    pub iot_endpoint: Option<String>,
    pub client_id: String,
    pub capabilities: Vec<String>,
    pub capability_ttl: Duration,
    pub heartbeat: Duration,
}

impl TryFrom<Cli> for RuntimeConfig {
    type Error = anyhow::Error;

    fn try_from(cli: Cli) -> Result<Self> {
        let thing_id = normalize_required(cli.thing_id, "thing-id")?;
        validate_topic_segment(&thing_id, "thing-id")?;

        if cli.capability_ttl_seconds == 0 {
            bail!("capability-ttl-seconds must be greater than 0");
        }
        if cli.heartbeat_seconds == 0 {
            bail!("heartbeat-seconds must be greater than 0");
        }
        if cli.heartbeat_seconds >= cli.capability_ttl_seconds {
            bail!("heartbeat-seconds must be less than capability-ttl-seconds");
        }

        let capabilities = normalize_capabilities(cli.capabilities)?;
        let client_id = match normalize_optional(cli.client_id) {
            Some(value) => value,
            None => default_client_id(&thing_id, process::id()),
        };

        Ok(Self {
            thing_id,
            aws_region: normalize_optional(cli.aws_region),
            iot_endpoint: normalize_optional(cli.iot_endpoint),
            client_id,
            capabilities,
            capability_ttl: Duration::from_secs(cli.capability_ttl_seconds),
            heartbeat: Duration::from_secs(cli.heartbeat_seconds),
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DefaultRouteAddresses {
    pub ipv4: Option<Ipv4Addr>,
    pub ipv6: Option<Ipv6Addr>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublishedMessage {
    pub topic: String,
    pub payload: Vec<u8>,
    pub retain: bool,
}

#[async_trait]
pub trait Publisher: Send + Sync {
    async fn publish(&self, message: PublishedMessage) -> Result<()>;
}

struct MqttPublisher {
    client: AsyncClientHandle,
}

impl MqttPublisher {
    async fn connect(endpoint: &str, region: &str, client_id: &str) -> Result<Self> {
        eprintln!("connecting unit daemon MQTT clientId={client_id}");
        let sigv4_options = WebsocketSigv4OptionsBuilder::new(region).await.build();
        let mut connect_options = gneiss_mqtt::client::config::ConnectOptions::builder();
        connect_options
            .with_client_id(client_id)
            .with_keep_alive_interval_seconds(Some(MQTT_KEEP_ALIVE_SECONDS));
        let client = AwsClientBuilder::new_websockets_with_sigv4(endpoint, sigv4_options, None)?
            .with_connect_options(connect_options.build())
            .build_tokio()?;
        client.start(None)?;
        eprintln!("started unit daemon MQTT clientId={client_id}");
        Ok(Self { client })
    }

    fn stop(&self) -> Result<()> {
        self.client.stop(None)?;
        self.client.close()?;
        Ok(())
    }
}

#[async_trait]
impl Publisher for MqttPublisher {
    async fn publish(&self, message: PublishedMessage) -> Result<()> {
        let packet = PublishPacket::builder(message.topic.clone(), QualityOfService::AtLeastOnce)
            .with_payload(message.payload)
            .with_retain(message.retain)
            .build();
        let response = self.client.publish(packet, None).await?;
        if let PublishResponse::Qos1(puback) = response
            && !puback.reason_code().is_success()
        {
            bail!(
                "MQTT publish failed for {}: {}",
                message.topic,
                puback.reason_code()
            );
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapabilitySnapshot {
    pub name: String,
    pub available: bool,
}

#[async_trait]
pub trait Capability: Send + Sync {
    fn name(&self) -> &str;
    async fn snapshot(&self, available: bool) -> Result<CapabilitySnapshot>;
}

#[derive(Debug)]
pub struct BoardCapability;

#[async_trait]
impl Capability for BoardCapability {
    fn name(&self) -> &str {
        BOARD_CAPABILITY
    }

    async fn snapshot(&self, available: bool) -> Result<CapabilitySnapshot> {
        Ok(CapabilitySnapshot {
            name: BOARD_CAPABILITY.to_string(),
            available,
        })
    }
}

pub struct CapabilityManager {
    capabilities: Vec<Arc<dyn Capability>>,
    seq: u64,
}

impl CapabilityManager {
    pub fn new(capability_names: &[String]) -> Result<Self> {
        let mut names = BTreeSet::new();
        for name in capability_names {
            validate_capability_name(name)?;
            names.insert(name.as_str());
        }
        let mut capabilities: Vec<Arc<dyn Capability>> = Vec::new();
        for name in names {
            match name {
                BOARD_CAPABILITY => capabilities.push(Arc::new(BoardCapability)),
                _ => {
                    bail!("unsupported capability {name:?}; v1 supports only {BOARD_CAPABILITY:?}")
                }
            }
        }
        if capabilities.is_empty() {
            bail!("at least one capability is required");
        }
        Ok(Self {
            capabilities,
            seq: 0,
        })
    }

    pub async fn publish_state<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        thing_name: &str,
        available: bool,
        ttl: Duration,
        observed_at_ms: u64,
    ) -> Result<()> {
        self.seq += 1;
        let mut capabilities = BTreeMap::new();
        let mut expired_capabilities = BTreeMap::new();
        for capability in &self.capabilities {
            let snapshot = capability.snapshot(available).await?;
            capabilities.insert(snapshot.name.clone(), snapshot.available);
            expired_capabilities.insert(snapshot.name, false);
        }
        let payload = CapabilityStatePayload {
            schema_version: SCHEMA_VERSION.to_string(),
            adapter_id: ADAPTER_ID.to_string(),
            thing_name: thing_name.to_string(),
            capabilities,
            metrics: BTreeMap::new(),
            observed_at_ms,
            seq: self.seq,
            expires_at_ms: observed_at_ms.saturating_add(duration_millis(ttl)),
            expired_capabilities,
        };
        publisher
            .publish(PublishedMessage {
                topic: build_capability_state_topic(thing_name)?,
                payload: serde_json::to_vec(&payload)?,
                retain: true,
            })
            .await
    }

    pub fn seq(&self) -> u64 {
        self.seq
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CapabilityStatePayload {
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "adapterId")]
    pub adapter_id: String,
    #[serde(rename = "thingName")]
    pub thing_name: String,
    pub capabilities: BTreeMap<String, bool>,
    pub metrics: BTreeMap<String, serde_json::Value>,
    #[serde(rename = "observedAtMs")]
    pub observed_at_ms: u64,
    pub seq: u64,
    #[serde(rename = "expiresAtMs")]
    pub expires_at_ms: u64,
    #[serde(rename = "expiredCapabilities")]
    pub expired_capabilities: BTreeMap<String, bool>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BoardShadowUpdate {
    pub state: BoardShadowState,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BoardShadowState {
    pub reported: BoardReport,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BoardReport {
    pub power: bool,
    pub wifi: WifiReport,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WifiReport {
    pub online: bool,
    pub ipv4: Option<Ipv4Addr>,
    pub ipv6: Option<Ipv6Addr>,
}

pub struct RuntimeState {
    config: RuntimeConfig,
    capability_manager: CapabilityManager,
}

impl RuntimeState {
    pub fn new(config: RuntimeConfig) -> Result<Self> {
        let capability_manager = CapabilityManager::new(&config.capabilities)?;
        Ok(Self {
            config,
            capability_manager,
        })
    }

    pub async fn publish_online<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        addresses: DefaultRouteAddresses,
        observed_at_ms: u64,
    ) -> Result<()> {
        self.publish_board_shadow(publisher, build_online_board_report(addresses))
            .await?;
        self.publish_capabilities(publisher, true, observed_at_ms)
            .await
    }

    pub async fn refresh_capabilities<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        observed_at_ms: u64,
    ) -> Result<()> {
        self.publish_capabilities(publisher, true, observed_at_ms)
            .await
    }

    pub async fn publish_offline<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        observed_at_ms: u64,
    ) -> Result<()> {
        self.publish_board_shadow(publisher, build_offline_board_report())
            .await?;
        self.publish_capabilities(publisher, false, observed_at_ms)
            .await
    }

    pub fn capability_seq(&self) -> u64 {
        self.capability_manager.seq()
    }

    async fn publish_capabilities<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        available: bool,
        observed_at_ms: u64,
    ) -> Result<()> {
        self.capability_manager
            .publish_state(
                publisher,
                &self.config.thing_id,
                available,
                self.config.capability_ttl,
                observed_at_ms,
            )
            .await
    }

    async fn publish_board_shadow<P: Publisher + ?Sized>(
        &self,
        publisher: &P,
        report: BoardReport,
    ) -> Result<()> {
        publisher
            .publish(PublishedMessage {
                topic: build_board_shadow_update_topic(&self.config.thing_id)?,
                payload: serde_json::to_vec(&build_board_shadow_update(report))?,
                retain: false,
            })
            .await
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct LiveRuntimeConfig {
    endpoint: String,
    region: String,
}

pub async fn run_runtime(config: RuntimeConfig) -> Result<()> {
    let live_config = resolve_live_runtime_config(&config).await?;
    let publisher = MqttPublisher::connect(
        &live_config.endpoint,
        &live_config.region,
        &config.client_id,
    )
    .await?;
    let run_result = run_connected_runtime(config, &publisher).await;
    let stop_result = publisher.stop();
    run_result.and(stop_result)
}

async fn run_connected_runtime(config: RuntimeConfig, publisher: &MqttPublisher) -> Result<()> {
    let mut state = RuntimeState::new(config.clone())?;
    state
        .publish_online(publisher, discover_default_route_addresses(), now_ms())
        .await?;

    let mut heartbeat = interval_at(Instant::now() + config.heartbeat, config.heartbeat);
    heartbeat.set_missed_tick_behavior(MissedTickBehavior::Skip);

    loop {
        tokio::select! {
            shutdown = wait_for_shutdown_signal() => {
                shutdown?;
                break;
            }
            _ = heartbeat.tick() => {
                if let Err(err) = state.refresh_capabilities(publisher, now_ms()).await {
                    eprintln!("warning: failed to refresh unit daemon capability state: {err:#}");
                }
            }
        }
    }

    if let Err(err) = state.publish_offline(publisher, now_ms()).await {
        eprintln!("warning: failed to publish unit daemon offline state: {err:#}");
    }
    Ok(())
}

async fn resolve_live_runtime_config(config: &RuntimeConfig) -> Result<LiveRuntimeConfig> {
    let mut loader = aws_config::defaults(BehaviorVersion::latest());
    if let Some(region) = &config.aws_region {
        loader = loader.region(aws_sdk_iot::config::Region::new(region.clone()));
    }
    let sdk_config = loader.load().await;
    let region = config
        .aws_region
        .clone()
        .or_else(|| sdk_config.region().map(ToString::to_string))
        .ok_or_else(|| anyhow!("AWS region is required; pass --aws-region or set AWS_REGION"))?;
    let endpoint = match &config.iot_endpoint {
        Some(endpoint) => endpoint.clone(),
        None => {
            let iot = aws_sdk_iot::Client::new(&sdk_config);
            let response = iot
                .describe_endpoint()
                .endpoint_type("iot:Data-ATS")
                .send()
                .await
                .context("describe AWS IoT Data-ATS endpoint")?;
            response
                .endpoint_address()
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToString::to_string)
                .ok_or_else(|| anyhow!("AWS IoT DescribeEndpoint returned no endpointAddress"))?
        }
    };
    Ok(LiveRuntimeConfig { endpoint, region })
}

#[cfg(unix)]
async fn wait_for_shutdown_signal() -> Result<()> {
    let mut sigterm = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        .context("install SIGTERM handler")?;
    tokio::select! {
        result = tokio::signal::ctrl_c() => {
            result.context("wait for SIGINT")?;
        }
        _ = sigterm.recv() => {}
    }
    Ok(())
}

#[cfg(not(unix))]
async fn wait_for_shutdown_signal() -> Result<()> {
    tokio::signal::ctrl_c().await.context("wait for Ctrl+C")
}

pub fn build_capability_state_topic(thing_name: &str) -> Result<String> {
    Ok(format!(
        "txings/{}/capability/v2/state",
        validate_topic_segment(thing_name, "thing-id")?
    ))
}

pub fn build_board_shadow_update_topic(thing_name: &str) -> Result<String> {
    Ok(format!(
        "$aws/things/{}/shadow/name/{BOARD_SHADOW_NAME}/update",
        validate_topic_segment(thing_name, "thing-id")?
    ))
}

pub fn build_board_shadow_update(report: BoardReport) -> BoardShadowUpdate {
    BoardShadowUpdate {
        state: BoardShadowState { reported: report },
    }
}

pub fn build_online_board_report(addresses: DefaultRouteAddresses) -> BoardReport {
    BoardReport {
        power: true,
        wifi: WifiReport {
            online: true,
            ipv4: addresses.ipv4,
            ipv6: addresses.ipv6,
        },
    }
}

pub fn build_offline_board_report() -> BoardReport {
    BoardReport {
        power: false,
        wifi: WifiReport {
            online: false,
            ipv4: None,
            ipv6: None,
        },
    }
}

pub fn discover_default_route_addresses() -> DefaultRouteAddresses {
    DefaultRouteAddresses {
        ipv4: probe_default_route_ip(SocketAddr::new(IpAddr::V4(Ipv4Addr::new(8, 8, 8, 8)), 80))
            .and_then(|ip| match ip {
                IpAddr::V4(ipv4) => Some(ipv4),
                IpAddr::V6(_) => None,
            }),
        ipv6: probe_default_route_ip(SocketAddr::new(
            IpAddr::V6(Ipv6Addr::new(0x2001, 0x4860, 0x4860, 0, 0, 0, 0, 0x8888)),
            80,
        ))
        .and_then(|ip| match ip {
            IpAddr::V4(_) => None,
            IpAddr::V6(ipv6) => Some(ipv6),
        }),
    }
}

fn probe_default_route_ip(remote: SocketAddr) -> Option<IpAddr> {
    let bind_addr = match remote {
        SocketAddr::V4(_) => SocketAddr::new(IpAddr::V4(Ipv4Addr::UNSPECIFIED), 0),
        SocketAddr::V6(_) => SocketAddr::new(IpAddr::V6(Ipv6Addr::UNSPECIFIED), 0),
    };
    let socket = UdpSocket::bind(bind_addr).ok()?;
    socket.connect(remote).ok()?;
    Some(socket.local_addr().ok()?.ip())
}

fn normalize_required(value: String, label: &str) -> Result<String> {
    let normalized = value.trim().to_string();
    if normalized.is_empty() {
        bail!("{label} must not be empty");
    }
    Ok(normalized)
}

fn normalize_optional(value: Option<String>) -> Option<String> {
    value
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn normalize_capabilities(values: Vec<String>) -> Result<Vec<String>> {
    let mut capabilities = BTreeSet::new();
    if values.is_empty() {
        capabilities.insert(BOARD_CAPABILITY.to_string());
    } else {
        for value in values {
            let value = normalize_required(value, "capability")?;
            validate_capability_name(&value)?;
            capabilities.insert(value);
        }
    }
    Ok(capabilities.into_iter().collect())
}

fn validate_capability_name(value: &str) -> Result<&str> {
    validate_topic_segment(value, "capability")?;
    if value != BOARD_CAPABILITY {
        bail!("unsupported capability {value:?}; v1 supports only {BOARD_CAPABILITY:?}");
    }
    Ok(value)
}

fn validate_topic_segment<'a>(value: &'a str, label: &str) -> Result<&'a str> {
    if value.trim().is_empty() {
        bail!("{label} must not be empty");
    }
    if value.contains('/') || value.contains('#') || value.contains('+') {
        bail!("{label} must not contain MQTT topic separators or wildcards");
    }
    Ok(value)
}

fn default_client_id(thing_name: &str, pid: u32) -> String {
    let mut sanitized = thing_name
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' {
                ch
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches('-')
        .to_string();
    if sanitized.is_empty() {
        sanitized = "unit".to_string();
    }
    const SUFFIX_RESERVE: usize = 24;
    if sanitized.len() > 128 - SUFFIX_RESERVE {
        sanitized.truncate(128 - SUFFIX_RESERVE);
    }
    format!("{sanitized}-daemon-{pid}")
}

fn duration_millis(duration: Duration) -> u64 {
    duration.as_millis().try_into().unwrap_or(u64::MAX)
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
    use std::sync::Mutex;

    use super::*;

    #[derive(Default)]
    struct FakePublisher {
        messages: Mutex<Vec<PublishedMessage>>,
    }

    impl FakePublisher {
        fn messages(&self) -> Vec<PublishedMessage> {
            self.messages.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl Publisher for FakePublisher {
        async fn publish(&self, message: PublishedMessage) -> Result<()> {
            self.messages.lock().unwrap().push(message);
            Ok(())
        }
    }

    fn config() -> RuntimeConfig {
        RuntimeConfig {
            thing_id: "unit-local".to_string(),
            aws_region: Some("eu-central-1".to_string()),
            iot_endpoint: Some("example.iot.eu-central-1.amazonaws.com".to_string()),
            client_id: "unit-local-daemon-test".to_string(),
            capabilities: vec![BOARD_CAPABILITY.to_string()],
            capability_ttl: Duration::from_secs(150),
            heartbeat: Duration::from_secs(60),
        }
    }

    #[test]
    fn builds_retained_capability_state_topic() {
        assert_eq!(
            build_capability_state_topic("unit-local").unwrap(),
            "txings/unit-local/capability/v2/state"
        );
        assert!(build_capability_state_topic("unit/local").is_err());
    }

    #[test]
    fn builds_board_shadow_update_payloads() {
        let online = build_board_shadow_update(build_online_board_report(DefaultRouteAddresses {
            ipv4: Some(Ipv4Addr::new(192, 168, 1, 25)),
            ipv6: None,
        }));
        assert!(online.state.reported.power);
        assert!(online.state.reported.wifi.online);
        assert_eq!(
            online.state.reported.wifi.ipv4,
            Some(Ipv4Addr::new(192, 168, 1, 25))
        );

        let offline = build_board_shadow_update(build_offline_board_report());
        assert!(!offline.state.reported.power);
        assert!(!offline.state.reported.wifi.online);
        assert_eq!(offline.state.reported.wifi.ipv4, None);
        assert_eq!(offline.state.reported.wifi.ipv6, None);
    }

    #[tokio::test]
    async fn publishes_capability_payload_with_ttl_and_expired_state() {
        let publisher = FakePublisher::default();
        let mut manager = CapabilityManager::new(&[BOARD_CAPABILITY.to_string()]).unwrap();

        manager
            .publish_state(
                &publisher,
                "unit-local",
                true,
                Duration::from_secs(150),
                1_000,
            )
            .await
            .unwrap();

        let messages = publisher.messages();
        assert_eq!(messages.len(), 1);
        assert_eq!(messages[0].topic, "txings/unit-local/capability/v2/state");
        assert!(messages[0].retain);
        let payload: CapabilityStatePayload = serde_json::from_slice(&messages[0].payload).unwrap();
        assert_eq!(payload.schema_version, SCHEMA_VERSION);
        assert_eq!(payload.adapter_id, ADAPTER_ID);
        assert_eq!(payload.thing_name, "unit-local");
        assert_eq!(payload.capabilities.get(BOARD_CAPABILITY), Some(&true));
        assert_eq!(
            payload.expired_capabilities.get(BOARD_CAPABILITY),
            Some(&false)
        );
        assert_eq!(payload.observed_at_ms, 1_000);
        assert_eq!(payload.expires_at_ms, 151_000);
        assert_eq!(payload.seq, 1);
    }

    #[tokio::test]
    async fn runtime_publishes_board_shadow_then_capability_and_sequences_refreshes() {
        let publisher = FakePublisher::default();
        let mut runtime = RuntimeState::new(config()).unwrap();

        runtime
            .publish_online(
                &publisher,
                DefaultRouteAddresses {
                    ipv4: Some(Ipv4Addr::new(10, 0, 0, 5)),
                    ipv6: None,
                },
                10,
            )
            .await
            .unwrap();
        runtime.refresh_capabilities(&publisher, 20).await.unwrap();
        runtime.publish_offline(&publisher, 30).await.unwrap();

        let messages = publisher.messages();
        assert_eq!(messages.len(), 5);
        assert_eq!(
            messages[0].topic,
            "$aws/things/unit-local/shadow/name/board/update"
        );
        assert!(!messages[0].retain);
        assert_eq!(messages[1].topic, "txings/unit-local/capability/v2/state");
        assert_eq!(messages[2].topic, "txings/unit-local/capability/v2/state");
        assert_eq!(
            messages[3].topic,
            "$aws/things/unit-local/shadow/name/board/update"
        );
        assert_eq!(messages[4].topic, "txings/unit-local/capability/v2/state");

        let first: CapabilityStatePayload = serde_json::from_slice(&messages[1].payload).unwrap();
        let second: CapabilityStatePayload = serde_json::from_slice(&messages[2].payload).unwrap();
        let third: CapabilityStatePayload = serde_json::from_slice(&messages[4].payload).unwrap();
        assert_eq!(first.seq, 1);
        assert_eq!(second.seq, 2);
        assert_eq!(third.seq, 3);
        assert_eq!(third.capabilities.get(BOARD_CAPABILITY), Some(&false));
        assert_eq!(runtime.capability_seq(), 3);
    }

    #[test]
    fn cli_defaults_to_board_capability() {
        let cli = Cli::try_parse_from(["daemon", "--thing-id", "unit-local"]).unwrap();
        let config = RuntimeConfig::try_from(cli).unwrap();

        assert_eq!(config.thing_id, "unit-local");
        assert_eq!(config.capabilities, vec![BOARD_CAPABILITY.to_string()]);
        assert_eq!(config.capability_ttl, Duration::from_secs(150));
        assert_eq!(config.heartbeat, Duration::from_secs(60));
        assert!(config.client_id.starts_with("unit-local-daemon-"));
    }

    #[test]
    fn cli_requires_thing_name() {
        assert!(Cli::try_parse_from(["daemon"]).is_err());
    }

    #[test]
    fn config_rejects_heartbeat_at_or_after_ttl() {
        let cli = Cli::try_parse_from([
            "daemon",
            "--thing-id",
            "unit-local",
            "--capability-ttl-seconds",
            "60",
            "--heartbeat-seconds",
            "60",
        ])
        .unwrap();

        assert!(RuntimeConfig::try_from(cli).is_err());
    }

    #[test]
    fn config_rejects_unsupported_capability() {
        let cli = Cli::try_parse_from([
            "daemon",
            "--thing-id",
            "unit-local",
            "--capability",
            "video",
        ])
        .unwrap();

        assert!(RuntimeConfig::try_from(cli).is_err());
    }

    #[test]
    fn default_client_id_sanitizes_thing_name() {
        assert_eq!(default_client_id("Unit Local!", 42), "Unit-Local-daemon-42");
    }
}
