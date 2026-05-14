use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fmt;
use std::fs;
use std::io::ErrorKind;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr, UdpSocket};
use std::path::Path;
use std::process;
use std::sync::Arc;
use std::sync::Once;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, anyhow, bail};
use async_trait::async_trait;
use aws_config::BehaviorVersion;
use aws_credential_types::Credentials;
use clap::Parser;
use gneiss_mqtt::client::config::{ConnectOptions, TlsOptions};
use gneiss_mqtt::client::{AsyncClient, AsyncClientHandle, PublishResponse, TokioClientBuilder};
use gneiss_mqtt::mqtt::{PublishPacket, QualityOfService};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::time::{Instant, MissedTickBehavior, interval_at};

pub const SCHEMA_VERSION: &str = "2.0";
pub const ADAPTER_ID: &str = "dev.txing.unit.Daemon";
pub const BOARD_CAPABILITY: &str = "board";
pub const BOARD_SHADOW_NAME: &str = "board";
pub const SPARKPLUG_SHADOW_NAME: &str = "sparkplug";
pub const DEFAULT_ENV_FILE: &str = "/etc/txing/daemon/daemon.env";
pub const DEFAULT_CAPABILITY_TTL_SECONDS: u64 = 150;
pub const DEFAULT_HEARTBEAT_SECONDS: u64 = 60;
pub const MQTT_PORT: u16 = 8883;
const MQTT_KEEP_ALIVE_SECONDS: u16 = 60;
static RUSTLS_CRYPTO_PROVIDER: Once = Once::new();

pub fn install_default_crypto_provider() {
    RUSTLS_CRYPTO_PROVIDER.call_once(|| {
        let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();
    });
}

#[derive(Debug, Parser)]
#[command(name = "daemon")]
#[command(about = "Unit board daemon")]
pub struct Cli {
    #[arg(long = "env-file")]
    pub env_file: Option<String>,

    #[arg(long = "thing-id")]
    pub thing_id: Option<String>,

    #[arg(long = "aws-region")]
    pub aws_region: Option<String>,

    #[arg(long = "iot-endpoint")]
    pub iot_endpoint: Option<String>,

    #[arg(long = "iot-credential-endpoint")]
    pub iot_credential_endpoint: Option<String>,

    #[arg(long = "iot-role-alias")]
    pub iot_role_alias: Option<String>,

    #[arg(long = "iot-cert-file")]
    pub iot_cert_file: Option<String>,

    #[arg(long = "iot-private-key-file")]
    pub iot_private_key_file: Option<String>,

    #[arg(long = "iot-root-ca-file")]
    pub iot_root_ca_file: Option<String>,

    #[arg(long)]
    pub client_id: Option<String>,

    #[arg(long = "capability", value_name = "NAME")]
    pub capabilities: Vec<String>,

    #[arg(long)]
    pub capability_ttl_seconds: Option<u64>,

    #[arg(long)]
    pub heartbeat_seconds: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeConfig {
    pub thing_id: String,
    pub aws_region: String,
    pub iot_endpoint: String,
    pub iot_credential_endpoint: String,
    pub iot_role_alias: String,
    pub iot_cert_file: String,
    pub iot_private_key_file: String,
    pub iot_root_ca_file: String,
    pub client_id: String,
    pub capabilities: Vec<String>,
    pub capability_ttl: Duration,
    pub heartbeat: Duration,
}

impl RuntimeConfig {
    pub fn from_cli(cli: Cli) -> Result<Self> {
        let process_env = env::vars().collect::<BTreeMap<_, _>>();
        let file_env = load_env_file_for_cli(&cli, &process_env)?;
        Self::from_sources(cli, &process_env, &file_env)
    }

    pub fn from_sources(
        cli: Cli,
        process_env: &BTreeMap<String, String>,
        file_env: &BTreeMap<String, String>,
    ) -> Result<Self> {
        let thing_id = required_config_value(
            cli.thing_id,
            process_env,
            file_env,
            "TXING_THING_ID",
            "thing-id",
        )?;
        validate_topic_segment(&thing_id, "thing-id")?;

        let capability_ttl_seconds = cli
            .capability_ttl_seconds
            .or(optional_u64_config(
                process_env,
                file_env,
                "TXING_CAPABILITY_TTL_SECONDS",
            )?)
            .unwrap_or(DEFAULT_CAPABILITY_TTL_SECONDS);
        let heartbeat_seconds = cli
            .heartbeat_seconds
            .or(optional_u64_config(
                process_env,
                file_env,
                "TXING_HEARTBEAT_SECONDS",
            )?)
            .unwrap_or(DEFAULT_HEARTBEAT_SECONDS);

        if capability_ttl_seconds == 0 {
            bail!("capability-ttl-seconds must be greater than 0");
        }
        if heartbeat_seconds == 0 {
            bail!("heartbeat-seconds must be greater than 0");
        }
        if heartbeat_seconds >= capability_ttl_seconds {
            bail!("heartbeat-seconds must be less than capability-ttl-seconds");
        }

        let capabilities = normalize_capabilities(resolve_capabilities(
            &cli.capabilities,
            process_env,
            file_env,
        )?)?;
        let client_id = match optional_config_value(
            cli.client_id,
            process_env,
            file_env,
            "TXING_DAEMON_CLIENT_ID",
        ) {
            Some(value) => value,
            None => default_client_id(&thing_id, process::id()),
        };
        validate_client_id(&thing_id, &client_id)?;

        let aws_region = required_config_value(
            cli.aws_region,
            process_env,
            file_env,
            "AWS_REGION",
            "aws-region",
        )?;
        let iot_endpoint = required_config_value(
            cli.iot_endpoint,
            process_env,
            file_env,
            "TXING_IOT_ENDPOINT",
            "iot-endpoint",
        )?;
        validate_endpoint_host(&iot_endpoint, "iot-endpoint")?;
        let iot_credential_endpoint = required_config_value(
            cli.iot_credential_endpoint,
            process_env,
            file_env,
            "TXING_IOT_CREDENTIAL_ENDPOINT",
            "iot-credential-endpoint",
        )?;
        validate_endpoint_host(&iot_credential_endpoint, "iot-credential-endpoint")?;
        let iot_role_alias = required_config_value(
            cli.iot_role_alias,
            process_env,
            file_env,
            "TXING_IOT_ROLE_ALIAS",
            "iot-role-alias",
        )?;
        validate_role_alias(&iot_role_alias)?;
        let iot_cert_file = required_config_value(
            cli.iot_cert_file,
            process_env,
            file_env,
            "TXING_IOT_CERT_FILE",
            "iot-cert-file",
        )?;
        let iot_private_key_file = required_config_value(
            cli.iot_private_key_file,
            process_env,
            file_env,
            "TXING_IOT_PRIVATE_KEY_FILE",
            "iot-private-key-file",
        )?;
        let iot_root_ca_file = required_config_value(
            cli.iot_root_ca_file,
            process_env,
            file_env,
            "TXING_IOT_ROOT_CA_FILE",
            "iot-root-ca-file",
        )?;

        Ok(Self {
            thing_id,
            aws_region,
            iot_endpoint,
            iot_credential_endpoint,
            iot_role_alias,
            iot_cert_file,
            iot_private_key_file,
            iot_root_ca_file,
            client_id,
            capabilities,
            capability_ttl: Duration::from_secs(capability_ttl_seconds),
            heartbeat: Duration::from_secs(heartbeat_seconds),
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
    async fn connect(config: &RuntimeConfig) -> Result<Self> {
        eprintln!(
            "connecting unit daemon MQTT endpoint={} port={} clientId={}",
            config.iot_endpoint, MQTT_PORT, config.client_id
        );
        let mut connect_options = ConnectOptions::builder();
        connect_options
            .with_client_id(&config.client_id)
            .with_keep_alive_interval_seconds(Some(MQTT_KEEP_ALIVE_SECONDS));
        let mut tls_options = TlsOptions::builder_with_mtls_from_path(
            &config.iot_cert_file,
            &config.iot_private_key_file,
        )?;
        tls_options.with_root_ca_from_path(&config.iot_root_ca_file)?;
        let mut builder = TokioClientBuilder::new(&config.iot_endpoint, MQTT_PORT);
        builder
            .with_connect_options(connect_options.build())
            .with_tls_options(tls_options.build_rustls()?);
        let client = builder.build()?;
        client.start(None)?;
        eprintln!("started unit daemon MQTT clientId={}", config.client_id);
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

pub async fn run_runtime(config: RuntimeConfig) -> Result<()> {
    let redcon = read_current_sparkplug_redcon(&config).await?;
    println!("{redcon}");
    let publisher = MqttPublisher::connect(&config).await?;
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SparkplugRedcon {
    Level(u8),
    Unavailable,
}

impl fmt::Display for SparkplugRedcon {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Level(level) => write!(formatter, "sparkplug.redcon={level}"),
            Self::Unavailable => formatter.write_str("sparkplug.redcon=unavailable"),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IotCredentialsRequest {
    pub url: String,
    pub thing_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
struct IotCredentialsEnvelope {
    credentials: IotTemporaryCredentials,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct IotTemporaryCredentials {
    #[serde(rename = "accessKeyId")]
    pub access_key_id: String,
    #[serde(rename = "secretAccessKey")]
    pub secret_access_key: String,
    #[serde(rename = "sessionToken")]
    pub session_token: String,
    pub expiration: String,
}

pub fn build_iot_credentials_request(config: &RuntimeConfig) -> Result<IotCredentialsRequest> {
    validate_endpoint_host(&config.iot_credential_endpoint, "iot-credential-endpoint")?;
    validate_role_alias(&config.iot_role_alias)?;
    Ok(IotCredentialsRequest {
        url: format!(
            "https://{}/role-aliases/{}/credentials",
            config.iot_credential_endpoint, config.iot_role_alias
        ),
        thing_name: config.thing_id.clone(),
    })
}

pub fn parse_iot_credentials_response(payload: &[u8]) -> Result<IotTemporaryCredentials> {
    let envelope: IotCredentialsEnvelope =
        serde_json::from_slice(payload).context("parse AWS IoT credential provider response")?;
    envelope.credentials.validate()?;
    Ok(envelope.credentials)
}

impl IotTemporaryCredentials {
    fn validate(&self) -> Result<()> {
        normalize_required(self.access_key_id.clone(), "accessKeyId")?;
        normalize_required(self.secret_access_key.clone(), "secretAccessKey")?;
        normalize_required(self.session_token.clone(), "sessionToken")?;
        normalize_required(self.expiration.clone(), "expiration")?;
        Ok(())
    }
}

async fn fetch_iot_temporary_credentials(
    config: &RuntimeConfig,
) -> Result<IotTemporaryCredentials> {
    let request = build_iot_credentials_request(config)?;
    let mut identity_pem = fs::read(&config.iot_cert_file)
        .with_context(|| format!("read IoT certificate {}", config.iot_cert_file))?;
    identity_pem.push(b'\n');
    identity_pem.extend(
        fs::read(&config.iot_private_key_file)
            .with_context(|| format!("read IoT private key {}", config.iot_private_key_file))?,
    );
    let identity =
        reqwest::Identity::from_pem(&identity_pem).context("load IoT client identity")?;
    let root_ca = reqwest::Certificate::from_pem(
        &fs::read(&config.iot_root_ca_file)
            .with_context(|| format!("read IoT root CA {}", config.iot_root_ca_file))?,
    )
    .context("load IoT root CA")?;
    let client = reqwest::Client::builder()
        .use_rustls_tls()
        .identity(identity)
        .add_root_certificate(root_ca)
        .build()
        .context("build IoT credential provider HTTP client")?;
    let bytes = client
        .get(&request.url)
        .header("x-amzn-iot-thingname", &request.thing_name)
        .send()
        .await
        .context("request AWS IoT temporary credentials")?
        .error_for_status()
        .context("AWS IoT temporary credential request failed")?
        .bytes()
        .await
        .context("read AWS IoT temporary credential response")?;
    parse_iot_credentials_response(&bytes)
}

pub fn build_iot_data_endpoint_url(endpoint: &str) -> Result<String> {
    validate_endpoint_host(endpoint, "iot-endpoint")?;
    Ok(format!("https://{endpoint}"))
}

pub async fn read_current_sparkplug_redcon(config: &RuntimeConfig) -> Result<SparkplugRedcon> {
    let temporary_credentials = fetch_iot_temporary_credentials(config).await?;
    let sdk_credentials = Credentials::new(
        temporary_credentials.access_key_id,
        temporary_credentials.secret_access_key,
        Some(temporary_credentials.session_token),
        None,
        "aws-iot-credential-provider",
    );
    let sdk_config = aws_config::defaults(BehaviorVersion::latest())
        .region(aws_sdk_iotdataplane::config::Region::new(
            config.aws_region.clone(),
        ))
        .credentials_provider(sdk_credentials)
        .load()
        .await;
    let data_config = aws_sdk_iotdataplane::config::Builder::from(&sdk_config)
        .endpoint_url(build_iot_data_endpoint_url(&config.iot_endpoint)?)
        .build();
    let iot_data = aws_sdk_iotdataplane::Client::from_conf(data_config);
    let response = iot_data
        .get_thing_shadow()
        .thing_name(&config.thing_id)
        .shadow_name(SPARKPLUG_SHADOW_NAME)
        .send()
        .await
        .with_context(|| {
            format!(
                "get sparkplug thing shadow thing={} shadow={} endpoint={} region={} roleAlias={}",
                config.thing_id,
                SPARKPLUG_SHADOW_NAME,
                config.iot_endpoint,
                config.aws_region,
                config.iot_role_alias
            )
        })?;
    let payload = response
        .payload()
        .map(|payload| payload.as_ref())
        .ok_or_else(|| anyhow!("sparkplug shadow response did not include payload"))?;
    parse_sparkplug_redcon(payload)
}

pub fn parse_sparkplug_redcon(payload: &[u8]) -> Result<SparkplugRedcon> {
    let shadow: Value = serde_json::from_slice(payload).context("parse sparkplug shadow")?;
    if shadow
        .pointer("/state/reported/topic/messageType")
        .and_then(Value::as_str)
        == Some("DDEATH")
    {
        return Ok(SparkplugRedcon::Unavailable);
    }
    match shadow
        .pointer("/state/reported/payload/metrics/redcon")
        .and_then(Value::as_u64)
    {
        Some(level @ 1..=4) => Ok(SparkplugRedcon::Level(level as u8)),
        Some(level) => bail!("sparkplug redcon value {level} is outside 1..=4"),
        None => Ok(SparkplugRedcon::Unavailable),
    }
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

pub fn load_env_file_for_cli(
    cli: &Cli,
    process_env: &BTreeMap<String, String>,
) -> Result<BTreeMap<String, String>> {
    let cli_env_file = normalize_optional(cli.env_file.clone());
    let process_env_file = normalize_optional(process_env.get("TXING_DAEMON_ENV_FILE").cloned());
    let explicit = cli_env_file.is_some() || process_env_file.is_some();
    let env_file = cli_env_file
        .or(process_env_file)
        .unwrap_or_else(|| DEFAULT_ENV_FILE.to_string());
    match fs::read_to_string(Path::new(&env_file)) {
        Ok(contents) => parse_env_file_contents(&contents),
        Err(err) if err.kind() == ErrorKind::NotFound && !explicit => Ok(BTreeMap::new()),
        Err(err) => Err(err).with_context(|| format!("read daemon env file {env_file}")),
    }
}

pub fn parse_env_file_contents(contents: &str) -> Result<BTreeMap<String, String>> {
    let mut values = BTreeMap::new();
    for (index, raw_line) in contents.lines().enumerate() {
        let line_number = index + 1;
        let mut line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some(without_export) = line.strip_prefix("export ") {
            line = without_export.trim_start();
        }
        let Some((key, value)) = line.split_once('=') else {
            bail!("invalid daemon env line {line_number}: expected KEY=VALUE");
        };
        let key = key.trim();
        validate_env_key(key).with_context(|| format!("invalid daemon env line {line_number}"))?;
        let value = parse_env_value(value.trim(), line_number)?;
        values.insert(key.to_string(), value);
    }
    Ok(values)
}

fn parse_env_value(value: &str, line_number: usize) -> Result<String> {
    if value.len() >= 2 {
        let first = value.as_bytes()[0];
        let last = value.as_bytes()[value.len() - 1];
        if (first == b'\'' && last == b'\'') || (first == b'"' && last == b'"') {
            return Ok(value[1..value.len() - 1].to_string());
        }
    }
    if value.starts_with('\'') || value.starts_with('"') {
        bail!("invalid daemon env line {line_number}: unterminated quoted value");
    }
    Ok(value.to_string())
}

fn validate_env_key(key: &str) -> Result<()> {
    let mut chars = key.chars();
    match chars.next() {
        Some(ch) if ch.is_ascii_alphabetic() || ch == '_' => {}
        _ => bail!("env key must start with an ASCII letter or underscore"),
    }
    if !chars.all(|ch| ch.is_ascii_alphanumeric() || ch == '_') {
        bail!("env key must contain only ASCII letters, digits, and underscore");
    }
    Ok(())
}

fn required_config_value(
    cli_value: Option<String>,
    process_env: &BTreeMap<String, String>,
    file_env: &BTreeMap<String, String>,
    env_name: &str,
    label: &str,
) -> Result<String> {
    optional_config_value(cli_value, process_env, file_env, env_name)
        .ok_or_else(|| anyhow!("{label} is required; pass --{label} or set {env_name}"))
}

fn optional_config_value(
    cli_value: Option<String>,
    process_env: &BTreeMap<String, String>,
    file_env: &BTreeMap<String, String>,
    env_name: &str,
) -> Option<String> {
    normalize_optional(cli_value)
        .or_else(|| normalize_optional(process_env.get(env_name).cloned()))
        .or_else(|| normalize_optional(file_env.get(env_name).cloned()))
}

fn optional_u64_config(
    process_env: &BTreeMap<String, String>,
    file_env: &BTreeMap<String, String>,
    env_name: &str,
) -> Result<Option<u64>> {
    let Some(value) = optional_config_value(None, process_env, file_env, env_name) else {
        return Ok(None);
    };
    value
        .parse::<u64>()
        .with_context(|| format!("{env_name} must be an unsigned integer"))
        .map(Some)
}

fn resolve_capabilities(
    cli_capabilities: &[String],
    process_env: &BTreeMap<String, String>,
    file_env: &BTreeMap<String, String>,
) -> Result<Vec<String>> {
    if !cli_capabilities.is_empty() {
        return Ok(cli_capabilities.to_vec());
    }
    let Some(value) =
        optional_config_value(None, process_env, file_env, "TXING_DAEMON_CAPABILITIES")
    else {
        return Ok(Vec::new());
    };
    Ok(value
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
        .collect())
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

fn validate_endpoint_host(value: &str, label: &str) -> Result<()> {
    validate_topic_segment(value, label)?;
    if value.contains("://") || value.contains('/') || value.contains(':') {
        bail!("{label} must be an endpoint hostname without scheme, path, or port");
    }
    if value.chars().any(char::is_whitespace) {
        bail!("{label} must not contain whitespace");
    }
    Ok(())
}

fn validate_role_alias(value: &str) -> Result<()> {
    let value = normalize_required(value.to_string(), "iot-role-alias")?;
    if value.len() > 128 {
        bail!("iot-role-alias must be 128 characters or fewer");
    }
    if !value
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '=' | ',' | '@' | '-'))
    {
        bail!("iot-role-alias contains an unsupported character");
    }
    Ok(())
}

fn validate_client_id(thing_name: &str, client_id: &str) -> Result<()> {
    let client_id = normalize_required(client_id.to_string(), "client-id")?;
    validate_topic_segment(&client_id, "client-id")?;
    if client_id.len() > 128 {
        bail!("client-id must be 128 characters or fewer");
    }
    let expected_prefix = default_client_id_prefix(thing_name);
    if !client_id.starts_with(&expected_prefix) {
        bail!("client-id must start with {expected_prefix:?}");
    }
    Ok(())
}

fn default_client_id_prefix(thing_name: &str) -> String {
    format!("{}-daemon-", sanitize_client_id_fragment(thing_name))
}

fn default_client_id(thing_name: &str, pid: u32) -> String {
    format!("{}{pid}", default_client_id_prefix(thing_name))
}

fn sanitize_client_id_fragment(thing_name: &str) -> String {
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
    sanitized
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
            aws_region: "eu-central-1".to_string(),
            iot_endpoint: "example.iot.eu-central-1.amazonaws.com".to_string(),
            iot_credential_endpoint: "example.credentials.iot.eu-central-1.amazonaws.com"
                .to_string(),
            iot_role_alias: "unit-daemon-role-alias".to_string(),
            iot_cert_file: "/etc/txing/daemon/certs/certificate.pem.crt".to_string(),
            iot_private_key_file: "/etc/txing/daemon/certs/private.pem.key".to_string(),
            iot_root_ca_file: "/etc/txing/daemon/certs/AmazonRootCA1.pem".to_string(),
            client_id: "unit-local-daemon-test".to_string(),
            capabilities: vec![BOARD_CAPABILITY.to_string()],
            capability_ttl: Duration::from_secs(150),
            heartbeat: Duration::from_secs(60),
        }
    }

    fn file_env() -> BTreeMap<String, String> {
        BTreeMap::from([
            ("TXING_THING_ID".to_string(), "unit-local".to_string()),
            ("AWS_REGION".to_string(), "eu-central-1".to_string()),
            (
                "TXING_IOT_ENDPOINT".to_string(),
                "example.iot.eu-central-1.amazonaws.com".to_string(),
            ),
            (
                "TXING_IOT_CREDENTIAL_ENDPOINT".to_string(),
                "example.credentials.iot.eu-central-1.amazonaws.com".to_string(),
            ),
            (
                "TXING_IOT_ROLE_ALIAS".to_string(),
                "unit-daemon-role-alias".to_string(),
            ),
            (
                "TXING_IOT_CERT_FILE".to_string(),
                "/etc/txing/daemon/certs/certificate.pem.crt".to_string(),
            ),
            (
                "TXING_IOT_PRIVATE_KEY_FILE".to_string(),
                "/etc/txing/daemon/certs/private.pem.key".to_string(),
            ),
            (
                "TXING_IOT_ROOT_CA_FILE".to_string(),
                "/etc/txing/daemon/certs/AmazonRootCA1.pem".to_string(),
            ),
        ])
    }

    fn runtime_config_from_args(args: &[&str]) -> Result<RuntimeConfig> {
        RuntimeConfig::from_sources(
            Cli::try_parse_from(args.iter().copied()).unwrap(),
            &BTreeMap::new(),
            &file_env(),
        )
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
    fn parses_env_file_without_shell_execution() {
        let parsed = parse_env_file_contents(
            r#"
            # comment
            export TXING_THING_ID=unit-local
            AWS_REGION="eu-central-1"
            TXING_IOT_ROLE_ALIAS='alias-name'
            EMPTY=
            "#,
        )
        .unwrap();

        assert_eq!(
            parsed.get("TXING_THING_ID").map(String::as_str),
            Some("unit-local")
        );
        assert_eq!(
            parsed.get("AWS_REGION").map(String::as_str),
            Some("eu-central-1")
        );
        assert_eq!(
            parsed.get("TXING_IOT_ROLE_ALIAS").map(String::as_str),
            Some("alias-name")
        );
        assert_eq!(parsed.get("EMPTY").map(String::as_str), Some(""));
        assert!(parse_env_file_contents("$(echo bad)").is_err());
    }

    #[test]
    fn config_precedence_is_cli_then_process_env_then_env_file_then_defaults() {
        let file_env = BTreeMap::from([
            ("TXING_THING_ID".to_string(), "from-file".to_string()),
            ("AWS_REGION".to_string(), "from-file".to_string()),
            (
                "TXING_IOT_ENDPOINT".to_string(),
                "file.iot.eu-central-1.amazonaws.com".to_string(),
            ),
            (
                "TXING_IOT_CREDENTIAL_ENDPOINT".to_string(),
                "file.credentials.iot.eu-central-1.amazonaws.com".to_string(),
            ),
            ("TXING_IOT_ROLE_ALIAS".to_string(), "file-alias".to_string()),
            (
                "TXING_IOT_CERT_FILE".to_string(),
                "/file/cert.pem".to_string(),
            ),
            (
                "TXING_IOT_PRIVATE_KEY_FILE".to_string(),
                "/file/private.key".to_string(),
            ),
            (
                "TXING_IOT_ROOT_CA_FILE".to_string(),
                "/file/ca.pem".to_string(),
            ),
            ("TXING_HEARTBEAT_SECONDS".to_string(), "30".to_string()),
        ]);
        let process_env = BTreeMap::from([
            ("TXING_THING_ID".to_string(), "from-process".to_string()),
            (
                "TXING_IOT_ENDPOINT".to_string(),
                "process.iot.eu-central-1.amazonaws.com".to_string(),
            ),
        ]);
        let cli = Cli::try_parse_from([
            "daemon",
            "--thing-id",
            "from-cli",
            "--client-id",
            "from-cli-daemon-test",
            "--capability-ttl-seconds",
            "120",
        ])
        .unwrap();
        let config = RuntimeConfig::from_sources(cli, &process_env, &file_env).unwrap();

        assert_eq!(config.thing_id, "from-cli");
        assert_eq!(
            config.iot_endpoint,
            "process.iot.eu-central-1.amazonaws.com"
        );
        assert_eq!(config.aws_region, "from-file");
        assert_eq!(config.capability_ttl, Duration::from_secs(120));
        assert_eq!(config.heartbeat, Duration::from_secs(30));
        assert_eq!(config.capabilities, vec![BOARD_CAPABILITY.to_string()]);
    }

    #[test]
    fn cli_defaults_to_board_capability() {
        let config = runtime_config_from_args(&["daemon"]).unwrap();

        assert_eq!(config.thing_id, "unit-local");
        assert_eq!(config.capabilities, vec![BOARD_CAPABILITY.to_string()]);
        assert_eq!(config.capability_ttl, Duration::from_secs(150));
        assert_eq!(config.heartbeat, Duration::from_secs(60));
        assert!(config.client_id.starts_with("unit-local-daemon-"));
    }

    #[test]
    fn config_requires_production_connection_values() {
        let cli = Cli::try_parse_from(["daemon"]).unwrap();
        assert!(RuntimeConfig::from_sources(cli, &BTreeMap::new(), &BTreeMap::new()).is_err());
    }

    #[test]
    fn config_rejects_heartbeat_at_or_after_ttl() {
        assert!(
            runtime_config_from_args(&[
                "daemon",
                "--capability-ttl-seconds",
                "60",
                "--heartbeat-seconds",
                "60",
            ])
            .is_err()
        );
    }

    #[test]
    fn config_rejects_unsupported_capability() {
        assert!(runtime_config_from_args(&["daemon", "--capability", "video"]).is_err());
    }

    #[test]
    fn config_rejects_client_id_outside_thing_daemon_prefix() {
        assert!(runtime_config_from_args(&["daemon", "--client-id", "other-client"]).is_err());
    }

    #[test]
    fn config_rejects_endpoint_with_scheme_or_port() {
        assert!(
            runtime_config_from_args(&[
                "daemon",
                "--iot-endpoint",
                "https://example.iot.eu-central-1.amazonaws.com:443",
            ])
            .is_err()
        );
    }

    #[test]
    fn default_client_id_sanitizes_thing_name() {
        assert_eq!(default_client_id("Unit Local!", 42), "Unit-Local-daemon-42");
    }

    #[test]
    fn mqtt_mtls_uses_direct_tls_port() {
        assert_eq!(MQTT_PORT, 8883);
    }

    #[test]
    fn builds_iot_credential_provider_request_and_parses_response() {
        let mut config = config();
        config.iot_role_alias = "unit_daemon,role-alias@Test=1".to_string();
        let request = build_iot_credentials_request(&config).unwrap();
        assert_eq!(
            request.url,
            "https://example.credentials.iot.eu-central-1.amazonaws.com/role-aliases/unit_daemon,role-alias@Test=1/credentials"
        );
        assert_eq!(request.thing_name, "unit-local");

        let credentials = parse_iot_credentials_response(
            br#"{"credentials":{"accessKeyId":"akid","secretAccessKey":"secret","sessionToken":"token","expiration":"2026-05-14T12:00:00Z"}}"#,
        )
        .unwrap();
        assert_eq!(credentials.access_key_id, "akid");
        assert_eq!(credentials.secret_access_key, "secret");
        assert_eq!(credentials.session_token, "token");
        assert!(parse_iot_credentials_response(br#"{"credentials":{"accessKeyId":""}}"#).is_err());
    }

    #[test]
    fn builds_iot_data_endpoint_url() {
        assert_eq!(
            build_iot_data_endpoint_url("example.iot.eu-central-1.amazonaws.com").unwrap(),
            "https://example.iot.eu-central-1.amazonaws.com"
        );
        assert!(
            build_iot_data_endpoint_url("https://example.iot.eu-central-1.amazonaws.com").is_err()
        );
    }

    #[test]
    fn parses_sparkplug_redcon_shadow_states() {
        assert_eq!(
            parse_sparkplug_redcon(
                br#"{"state":{"reported":{"topic":{"messageType":"DDATA"},"payload":{"metrics":{"redcon":2}}}}}"#,
            )
            .unwrap(),
            SparkplugRedcon::Level(2)
        );
        assert_eq!(
            parse_sparkplug_redcon(
                br#"{"state":{"reported":{"topic":{"messageType":"DDEATH"},"payload":{"metrics":{"redcon":2}}}}}"#,
            )
            .unwrap(),
            SparkplugRedcon::Unavailable
        );
        assert_eq!(
            parse_sparkplug_redcon(br#"{"state":{"reported":{"payload":{"metrics":{}}}}}"#)
                .unwrap(),
            SparkplugRedcon::Unavailable
        );
        assert!(
            parse_sparkplug_redcon(
                br#"{"state":{"reported":{"payload":{"metrics":{"redcon":8}}}}}"#
            )
            .is_err()
        );
        assert_eq!(SparkplugRedcon::Level(3).to_string(), "sparkplug.redcon=3");
        assert_eq!(
            SparkplugRedcon::Unavailable.to_string(),
            "sparkplug.redcon=unavailable"
        );
    }
}
