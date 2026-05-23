use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::io::{BufRead, BufReader, ErrorKind, Read};
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr, UdpSocket};
use std::path::{Path, PathBuf};
use std::process::{self, Stdio};
use std::sync::Arc;
use std::sync::Once;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, anyhow, bail};
use async_trait::async_trait;
use aws_config::BehaviorVersion;
use aws_credential_types::Credentials;
use aws_credential_types::provider::{
    self, ProvideCredentials, SharedCredentialsProvider, error::CredentialsError, future,
};
use aws_sdk_cloudwatchlogs::error::ProvideErrorMetadata;
use aws_sdk_cloudwatchlogs::types::InputLogEvent;
use aws_smithy_types::{DateTime, date_time::Format};
use clap::Parser;
use gneiss_mqtt::client::config::{ConnectOptions, TlsOptions};
use gneiss_mqtt::client::{
    AsyncClient, AsyncClientHandle, ClientEvent, ClientEventListenerCallback, PublishResponse,
    TokioClientBuilder,
};
use gneiss_mqtt::mqtt::{PublishPacket, QualityOfService, SubscribePacket};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::io::{
    AsyncBufReadExt, AsyncWriteExt, BufReader as TokioBufReader, split as split_async_io,
};
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::{mpsc, oneshot};
use tokio::task::JoinHandle;
use tokio::time::{Instant, MissedTickBehavior, interval_at, sleep, timeout};
use tokio_stream::wrappers::UnixListenerStream;
use tonic::transport::Server as TonicServer;
use tonic::{Request as TonicRequest, Response as TonicResponse, Status as TonicStatus};
use tracing::field::{Field, Visit};
use tracing::{Event, Level, Metadata, Subscriber};
use tracing::{debug, info, warn};
use tracing_subscriber::EnvFilter;
use tracing_subscriber::Layer;
use tracing_subscriber::layer::Context as LayerContext;
use tracing_subscriber::prelude::*;

pub mod board_video_bridge {
    tonic::include_proto!("txing.unit.board_video.v1");
}

pub mod unit_hardware {
    tonic::include_proto!("txing.unit.hardware.v1");
}

pub const SCHEMA_VERSION: &str = "2.0";
pub const DAEMON_VERSION: &str = env!("TXING_DAEMON_BUILD_VERSION");
pub const ADAPTER_ID: &str = "dev.txing.unit.Daemon";
pub const BOARD_CAPABILITY: &str = "board";
pub const MCP_CAPABILITY: &str = "mcp";
pub const VIDEO_CAPABILITY: &str = "video";
pub const BOARD_SHADOW_NAME: &str = "board";
pub const MCP_SHADOW_NAME: &str = "mcp";
pub const VIDEO_SHADOW_NAME: &str = "video";
pub const SPARKPLUG_SHADOW_NAME: &str = "sparkplug";
pub const MCP_PROTOCOL_VERSION: &str = "2026-05-19";
pub const DEFAULT_CONFIG_SUBDIR: &str = "txing/unit-daemon";
pub const DEFAULT_ENV_FILE_NAME: &str = "daemon.env";
pub const DEFAULT_DAEMON_ENV_TEMPLATE: &str = include_str!("../daemon.env.template");
pub const DEFAULT_IOT_CERT_FILE_NAME: &str = "certificate.pem.crt";
pub const DEFAULT_IOT_PRIVATE_KEY_FILE_NAME: &str = "private.pem.key";
pub const DEFAULT_IOT_ROOT_CA_FILE_NAME: &str = "AmazonRootCA1.pem";
pub const DEFAULT_CAPABILITY_TTL_SECONDS: u64 = 150;
pub const DEFAULT_HEARTBEAT_SECONDS: u64 = 60;
pub const DEFAULT_MCP_ACTIVE_TTL_MS: u64 = 5_000;
pub const DEFAULT_CLOUDWATCH_LOG_RETENTION_DAYS: i32 = 14;
pub const DEFAULT_KVS_MASTER_COMMAND: &str = "txing-board-kvs-master";
pub const DEFAULT_MCP_WEBRTC_SOCKET_PATH: &str = "/run/txing-unit-daemon/mcp-webrtc.sock";
pub const DEFAULT_BOARD_VIDEO_BRIDGE_SOCKET_PATH: &str =
    "/run/txing-unit-daemon/board-video-bridge.sock";
pub const DEFAULT_HARDWARE_WORKER_SOCKET_PATH: &str =
    "/run/txing-unit-hardware-worker/unit-hardware.sock";
pub const DEFAULT_HARDWARE_WORKER_TIMEOUT_MS: u64 = 700;
pub const MCP_WEBRTC_DATA_CHANNEL_LABEL: &str = "txing.mcp.v1";
pub const DEFAULT_MCP_RESPONSE_TIMEOUT_MS: u32 = 7_000;
pub const DEFAULT_VIDEO_CODEC: &str = "h264";
pub const DEFAULT_VIDEO_TRANSPORT: &str = "aws-webrtc";
pub const VIDEO_STATUS_STARTING: &str = "starting";
pub const VIDEO_STATUS_READY: &str = "ready";
pub const VIDEO_STATUS_ERROR: &str = "error";
pub const VIDEO_STATUS_UNAVAILABLE: &str = "unavailable";
pub const MQTT_PORT: u16 = 8883;
const MQTT_KEEP_ALIVE_SECONDS: u16 = 60;
const MQTT_CONNECT_WAIT_SECONDS: u64 = 15;
const MQTT_PUBLISH_OPERATION_TIMEOUT_SECONDS: u64 = 20;
const CLOUDWATCH_LOG_QUEUE_CAPACITY: usize = 4096;
const CLOUDWATCH_LOG_BATCH_MAX_EVENTS: usize = 100;
const CLOUDWATCH_LOG_BATCH_MAX_BYTES: usize = 256 * 1024;
const CLOUDWATCH_LOG_FLUSH_INTERVAL_SECONDS: u64 = 2;
const CLOUDWATCH_LOG_SHUTDOWN_TIMEOUT_SECONDS: u64 = 5;
const VIDEO_STATUS_HEARTBEAT_SECONDS: u64 = 5;
#[allow(dead_code)]
const VIDEO_RESTART_BACKOFF_INITIAL_SECONDS: u64 = 1;
#[allow(dead_code)]
const VIDEO_RESTART_BACKOFF_MAX_SECONDS: u64 = 30;
#[allow(dead_code)]
const VIDEO_CREDENTIAL_RESTART_MARGIN_SECONDS: u64 = 300;
#[allow(dead_code)]
const VIDEO_CREDENTIAL_RESTART_MIN_SECONDS: u64 = 30;
static RUSTLS_CRYPTO_PROVIDER: Once = Once::new();

pub fn install_default_crypto_provider() {
    RUSTLS_CRYPTO_PROVIDER.call_once(|| {
        let _ = rustls::crypto::aws_lc_rs::default_provider().install_default();
    });
}

pub fn init_logging(
    config: &RuntimeConfig,
    cloudwatch: Option<PreparedCloudWatchLogging>,
) -> Result<Option<CloudWatchLogHandle>> {
    let filter = match env::var("TXING_LOG") {
        Ok(value) => daemon_log_filter(&value),
        Err(_) => EnvFilter::try_from_default_env()
            .unwrap_or_else(|_| EnvFilter::new("error,txing_unit_daemon=info")),
    };
    let stderr_layer = StderrTextLayer.with_filter(filter);

    let registry = tracing_subscriber::registry().with(stderr_layer);
    if let Some(cloudwatch) = cloudwatch {
        let (layer, handle) = cloudwatch.start(CloudWatchLogBaseFields::from(config));
        registry
            .with(layer)
            .try_init()
            .map_err(|err| anyhow!("initialize logging: {err}"))?;
        Ok(Some(handle))
    } else {
        registry
            .try_init()
            .map_err(|err| anyhow!("initialize logging: {err}"))?;
        Ok(None)
    }
}

pub async fn shutdown_logging(handle: Option<CloudWatchLogHandle>) -> Result<()> {
    if let Some(handle) = handle {
        handle.shutdown().await
    } else {
        Ok(())
    }
}

pub async fn prepare_cloudwatch_logging(
    config: &RuntimeConfig,
) -> Result<Option<PreparedCloudWatchLogging>> {
    let Some(cloudwatch_config) = config.cloudwatch_logging.clone() else {
        return Ok(None);
    };
    let sdk_config = aws_sdk_config_from_iot_credentials(config)
        .await
        .context("prepare CloudWatch Logs credentials from IoT certificate")?;
    let logs_config = aws_sdk_cloudwatchlogs::config::Builder::from(&sdk_config).build();
    let client = Arc::new(RealCloudWatchLogsClient {
        client: aws_sdk_cloudwatchlogs::Client::from_conf(logs_config),
    });
    let writer = CloudWatchLogWriter::new(cloudwatch_config.clone(), client);
    writer
        .ensure_ready()
        .await
        .context("initialize CloudWatch Logs")?;
    Ok(Some(PreparedCloudWatchLogging {
        config: cloudwatch_config,
        client: writer.client,
    }))
}

fn daemon_log_filter(value: &str) -> EnvFilter {
    let value = value.trim();
    if matches!(value, "trace" | "debug" | "info" | "warn" | "error" | "off") {
        EnvFilter::new(format!("error,txing_unit_daemon={value}"))
    } else {
        EnvFilter::new(value)
    }
}

struct StderrTextLayer;

impl<S> Layer<S> for StderrTextLayer
where
    S: Subscriber,
{
    fn on_event(&self, event: &Event<'_>, _ctx: LayerContext<'_, S>) {
        let metadata = event.metadata();
        let mut visitor = TextFieldVisitor::default();
        event.record(&mut visitor);
        eprintln!(
            "{}",
            format_stderr_log_line(
                metadata.level(),
                visitor
                    .message
                    .as_deref()
                    .unwrap_or_else(|| metadata.name()),
                &visitor.fields,
            )
        );
    }
}

#[derive(Default)]
struct TextFieldVisitor {
    fields: Vec<(String, String)>,
    message: Option<String>,
}

impl Visit for TextFieldVisitor {
    fn record_debug(&mut self, field: &Field, value: &dyn fmt::Debug) {
        self.record_value(field, format!("{value:?}"));
    }

    fn record_str(&mut self, field: &Field, value: &str) {
        self.record_value(field, value.to_string());
    }

    fn record_bool(&mut self, field: &Field, value: bool) {
        self.record_value(field, value.to_string());
    }

    fn record_i64(&mut self, field: &Field, value: i64) {
        self.record_value(field, value.to_string());
    }

    fn record_u64(&mut self, field: &Field, value: u64) {
        self.record_value(field, value.to_string());
    }
}

impl TextFieldVisitor {
    fn record_value(&mut self, field: &Field, value: String) {
        if field.name() == "message" {
            self.message = Some(value);
        } else {
            self.fields.push((field.name().to_string(), value));
        }
    }
}

fn format_stderr_log_line(level: &Level, message: &str, fields: &[(String, String)]) -> String {
    let mut line = format!("{}: {message}", stderr_level_name(level));
    for (key, value) in fields {
        line.push(' ');
        line.push_str(key);
        line.push('=');
        line.push_str(value);
    }
    line
}

fn stderr_level_name(level: &Level) -> &'static str {
    match *level {
        Level::ERROR => "error",
        Level::WARN => "warning",
        Level::INFO => "info",
        Level::DEBUG => "debug",
        Level::TRACE => "trace",
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CloudWatchLogLevel {
    Error,
    Warn,
    Info,
    Debug,
    Trace,
}

impl CloudWatchLogLevel {
    fn parse(value: &str) -> Result<Self> {
        match value.trim().to_ascii_lowercase().as_str() {
            "error" => Ok(Self::Error),
            "warn" | "warning" => Ok(Self::Warn),
            "info" => Ok(Self::Info),
            "debug" => Ok(Self::Debug),
            "trace" => Ok(Self::Trace),
            _ => bail!("cloudwatch-log-level must be one of error, warn, info, debug, trace"),
        }
    }

    fn allows(self, level: &Level) -> bool {
        level_severity(level) <= self.severity()
    }

    fn severity(self) -> u8 {
        match self {
            Self::Error => 1,
            Self::Warn => 2,
            Self::Info => 3,
            Self::Debug => 4,
            Self::Trace => 5,
        }
    }
}

fn level_severity(level: &Level) -> u8 {
    match *level {
        Level::ERROR => 1,
        Level::WARN => 2,
        Level::INFO => 3,
        Level::DEBUG => 4,
        Level::TRACE => 5,
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CloudWatchLogConfig {
    pub log_group: String,
    pub log_stream: String,
    pub level: CloudWatchLogLevel,
    pub retention_days: i32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CloudWatchLogBaseFields {
    pub thing_id: String,
    pub client_id: String,
    pub iot_role_alias: String,
    pub aws_region: String,
}

impl From<&RuntimeConfig> for CloudWatchLogBaseFields {
    fn from(config: &RuntimeConfig) -> Self {
        Self {
            thing_id: config.thing_id.clone(),
            client_id: config.client_id.clone(),
            iot_role_alias: config.iot_role_alias.clone(),
            aws_region: config.aws_region.clone(),
        }
    }
}

pub struct PreparedCloudWatchLogging {
    config: CloudWatchLogConfig,
    client: Arc<dyn CloudWatchLogsClient>,
}

impl PreparedCloudWatchLogging {
    fn start(
        self,
        base_fields: CloudWatchLogBaseFields,
    ) -> (CloudWatchTracingLayer, CloudWatchLogHandle) {
        let (sender, receiver) = mpsc::channel(CLOUDWATCH_LOG_QUEUE_CAPACITY);
        let (shutdown_sender, shutdown_receiver) = oneshot::channel();
        let writer = CloudWatchLogWriter::new(self.config.clone(), self.client);
        let join = tokio::spawn(async move {
            writer.run(receiver, shutdown_receiver).await;
        });
        (
            CloudWatchTracingLayer {
                sender,
                level: self.config.level,
                base_fields,
                dropped_events: Arc::new(AtomicU64::new(0)),
            },
            CloudWatchLogHandle {
                shutdown_sender: Some(shutdown_sender),
                join,
            },
        )
    }
}

pub struct CloudWatchLogHandle {
    shutdown_sender: Option<oneshot::Sender<()>>,
    join: JoinHandle<()>,
}

impl CloudWatchLogHandle {
    pub async fn shutdown(mut self) -> Result<()> {
        if let Some(sender) = self.shutdown_sender.take() {
            let _ = sender.send(());
        }
        timeout(
            Duration::from_secs(CLOUDWATCH_LOG_SHUTDOWN_TIMEOUT_SECONDS),
            self.join,
        )
        .await
        .context("timed out flushing CloudWatch Logs during shutdown")?
        .context("CloudWatch Logs worker failed")?;
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CloudWatchLogRecord {
    pub timestamp_ms: i64,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CloudWatchPutLogEventsResult {
    pub next_sequence_token: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CloudWatchLogClientErrorKind {
    AlreadyExists,
    NotFound,
    InvalidSequenceToken { expected: Option<String> },
    DataAlreadyAccepted,
    Other,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CloudWatchLogClientError {
    pub kind: CloudWatchLogClientErrorKind,
    pub message: String,
}

impl CloudWatchLogClientError {
    fn new(kind: CloudWatchLogClientErrorKind, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
        }
    }
}

impl fmt::Display for CloudWatchLogClientError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl StdError for CloudWatchLogClientError {}

#[async_trait]
pub trait CloudWatchLogsClient: Send + Sync + 'static {
    async fn create_log_group(
        &self,
        log_group: &str,
    ) -> std::result::Result<(), CloudWatchLogClientError>;
    async fn put_retention_policy(
        &self,
        log_group: &str,
        retention_days: i32,
    ) -> std::result::Result<(), CloudWatchLogClientError>;
    async fn create_log_stream(
        &self,
        log_group: &str,
        log_stream: &str,
    ) -> std::result::Result<(), CloudWatchLogClientError>;
    async fn put_log_events(
        &self,
        log_group: &str,
        log_stream: &str,
        events: Vec<CloudWatchLogRecord>,
        sequence_token: Option<String>,
    ) -> std::result::Result<CloudWatchPutLogEventsResult, CloudWatchLogClientError>;
}

struct RealCloudWatchLogsClient {
    client: aws_sdk_cloudwatchlogs::Client,
}

#[async_trait]
impl CloudWatchLogsClient for RealCloudWatchLogsClient {
    async fn create_log_group(
        &self,
        log_group: &str,
    ) -> std::result::Result<(), CloudWatchLogClientError> {
        self.client
            .create_log_group()
            .log_group_name(log_group)
            .send()
            .await
            .map(|_| ())
            .map_err(map_cloudwatch_sdk_error)
    }

    async fn put_retention_policy(
        &self,
        log_group: &str,
        retention_days: i32,
    ) -> std::result::Result<(), CloudWatchLogClientError> {
        self.client
            .put_retention_policy()
            .log_group_name(log_group)
            .retention_in_days(retention_days)
            .send()
            .await
            .map(|_| ())
            .map_err(map_cloudwatch_sdk_error)
    }

    async fn create_log_stream(
        &self,
        log_group: &str,
        log_stream: &str,
    ) -> std::result::Result<(), CloudWatchLogClientError> {
        self.client
            .create_log_stream()
            .log_group_name(log_group)
            .log_stream_name(log_stream)
            .send()
            .await
            .map(|_| ())
            .map_err(map_cloudwatch_sdk_error)
    }

    async fn put_log_events(
        &self,
        log_group: &str,
        log_stream: &str,
        events: Vec<CloudWatchLogRecord>,
        sequence_token: Option<String>,
    ) -> std::result::Result<CloudWatchPutLogEventsResult, CloudWatchLogClientError> {
        let mut request = self
            .client
            .put_log_events()
            .log_group_name(log_group)
            .log_stream_name(log_stream);
        for event in events {
            let event = InputLogEvent::builder()
                .timestamp(event.timestamp_ms)
                .message(event.message)
                .build()
                .map_err(|err| {
                    CloudWatchLogClientError::new(
                        CloudWatchLogClientErrorKind::Other,
                        format!("build CloudWatch log event: {err}"),
                    )
                })?;
            request = request.log_events(event);
        }
        if let Some(sequence_token) = sequence_token {
            request = request.sequence_token(sequence_token);
        }
        request
            .send()
            .await
            .map(|output| CloudWatchPutLogEventsResult {
                next_sequence_token: output.next_sequence_token().map(str::to_string),
            })
            .map_err(map_cloudwatch_sdk_error)
    }
}

fn map_cloudwatch_sdk_error(
    error: impl ProvideErrorMetadata + fmt::Display,
) -> CloudWatchLogClientError {
    let kind = match error.code() {
        Some("ResourceAlreadyExistsException") => CloudWatchLogClientErrorKind::AlreadyExists,
        Some("ResourceNotFoundException") => CloudWatchLogClientErrorKind::NotFound,
        Some("InvalidSequenceTokenException") => {
            CloudWatchLogClientErrorKind::InvalidSequenceToken { expected: None }
        }
        Some("DataAlreadyAcceptedException") => CloudWatchLogClientErrorKind::DataAlreadyAccepted,
        _ => CloudWatchLogClientErrorKind::Other,
    };
    CloudWatchLogClientError::new(kind, error.to_string())
}

#[derive(Clone)]
struct CloudWatchLogWriter {
    config: CloudWatchLogConfig,
    client: Arc<dyn CloudWatchLogsClient>,
}

impl CloudWatchLogWriter {
    fn new(config: CloudWatchLogConfig, client: Arc<dyn CloudWatchLogsClient>) -> Self {
        Self { config, client }
    }

    async fn ensure_ready(&self) -> Result<()> {
        match self.client.create_log_group(&self.config.log_group).await {
            Ok(()) => {}
            Err(err) if err.kind == CloudWatchLogClientErrorKind::AlreadyExists => {}
            Err(err) => return Err(err).context("create CloudWatch log group"),
        }
        self.client
            .put_retention_policy(&self.config.log_group, self.config.retention_days)
            .await
            .context("set CloudWatch log group retention")?;
        match self
            .client
            .create_log_stream(&self.config.log_group, &self.config.log_stream)
            .await
        {
            Ok(()) => {}
            Err(err) if err.kind == CloudWatchLogClientErrorKind::AlreadyExists => {}
            Err(err) => return Err(err).context("create CloudWatch log stream"),
        }
        Ok(())
    }

    async fn run(
        self,
        mut receiver: mpsc::Receiver<CloudWatchLogRecord>,
        mut shutdown: oneshot::Receiver<()>,
    ) {
        let mut batch = Vec::new();
        let mut sequence_token = None;
        let mut flush_interval =
            tokio::time::interval(Duration::from_secs(CLOUDWATCH_LOG_FLUSH_INTERVAL_SECONDS));
        flush_interval.set_missed_tick_behavior(MissedTickBehavior::Skip);
        loop {
            tokio::select! {
                Some(record) = receiver.recv() => {
                    push_cloudwatch_log_batch_record(&mut batch, record);
                    if cloudwatch_log_batch_should_flush(&batch) {
                        self.flush_batch(&mut batch, &mut sequence_token).await;
                    }
                }
                _ = flush_interval.tick() => {
                    self.flush_batch(&mut batch, &mut sequence_token).await;
                }
                _ = &mut shutdown => {
                    while let Ok(record) = receiver.try_recv() {
                        push_cloudwatch_log_batch_record(&mut batch, record);
                        if cloudwatch_log_batch_should_flush(&batch) {
                            self.flush_batch(&mut batch, &mut sequence_token).await;
                        }
                    }
                    self.flush_batch(&mut batch, &mut sequence_token).await;
                    break;
                }
                else => {
                    self.flush_batch(&mut batch, &mut sequence_token).await;
                    break;
                }
            }
        }
    }

    async fn flush_batch(
        &self,
        batch: &mut Vec<CloudWatchLogRecord>,
        sequence_token: &mut Option<String>,
    ) {
        if batch.is_empty() {
            return;
        }
        batch.sort_by_key(|event| event.timestamp_ms);
        let events = std::mem::take(batch);
        match self
            .put_log_events_with_retry(events.clone(), sequence_token.clone())
            .await
        {
            Ok(result) => {
                *sequence_token = result.next_sequence_token;
            }
            Err(err) => {
                eprintln!("WARN failed to publish CloudWatch Logs batch: {err:#}");
            }
        }
    }

    async fn put_log_events_with_retry(
        &self,
        events: Vec<CloudWatchLogRecord>,
        sequence_token: Option<String>,
    ) -> Result<CloudWatchPutLogEventsResult> {
        match self
            .client
            .put_log_events(
                &self.config.log_group,
                &self.config.log_stream,
                events.clone(),
                sequence_token.clone(),
            )
            .await
        {
            Ok(result) => Ok(result),
            Err(err) if err.kind == CloudWatchLogClientErrorKind::NotFound => {
                self.ensure_ready().await?;
                self.client
                    .put_log_events(
                        &self.config.log_group,
                        &self.config.log_stream,
                        events,
                        sequence_token,
                    )
                    .await
                    .context("retry CloudWatch Logs batch after stream setup")
            }
            Err(err) => match err.kind {
                CloudWatchLogClientErrorKind::InvalidSequenceToken { expected } => self
                    .client
                    .put_log_events(
                        &self.config.log_group,
                        &self.config.log_stream,
                        events,
                        expected,
                    )
                    .await
                    .context("retry CloudWatch Logs batch with expected sequence token"),
                CloudWatchLogClientErrorKind::DataAlreadyAccepted => {
                    Ok(CloudWatchPutLogEventsResult {
                        next_sequence_token: None,
                    })
                }
                _ => Err(err).context("put CloudWatch Logs batch"),
            },
        }
    }
}

fn push_cloudwatch_log_batch_record(
    batch: &mut Vec<CloudWatchLogRecord>,
    record: CloudWatchLogRecord,
) {
    if record.message.len() + 26 > CLOUDWATCH_LOG_BATCH_MAX_BYTES {
        return;
    }
    batch.push(record);
}

fn cloudwatch_log_batch_should_flush(batch: &[CloudWatchLogRecord]) -> bool {
    if batch.len() >= CLOUDWATCH_LOG_BATCH_MAX_EVENTS {
        return true;
    }
    cloudwatch_log_batch_size(batch) >= CLOUDWATCH_LOG_BATCH_MAX_BYTES
}

fn cloudwatch_log_batch_size(batch: &[CloudWatchLogRecord]) -> usize {
    batch.iter().map(|event| event.message.len() + 26).sum()
}

pub struct CloudWatchTracingLayer {
    sender: mpsc::Sender<CloudWatchLogRecord>,
    level: CloudWatchLogLevel,
    base_fields: CloudWatchLogBaseFields,
    dropped_events: Arc<AtomicU64>,
}

impl<S> Layer<S> for CloudWatchTracingLayer
where
    S: Subscriber,
{
    fn on_event(&self, event: &Event<'_>, _ctx: LayerContext<'_, S>) {
        let metadata = event.metadata();
        if !metadata.target().starts_with("txing_unit_daemon") {
            return;
        }
        if !self.level.allows(metadata.level()) {
            return;
        }
        let record = cloudwatch_record_from_tracing_event(&self.base_fields, metadata, event);
        if self.sender.try_send(record).is_err() {
            self.dropped_events.fetch_add(1, Ordering::Relaxed);
        }
    }
}

fn cloudwatch_record_from_tracing_event(
    base_fields: &CloudWatchLogBaseFields,
    metadata: &Metadata<'_>,
    event: &Event<'_>,
) -> CloudWatchLogRecord {
    let timestamp_ms = now_ms();
    let mut visitor = JsonFieldVisitor::default();
    event.record(&mut visitor);
    let message = visitor
        .message
        .unwrap_or_else(|| metadata.name().to_string());
    let json = build_cloudwatch_log_message(
        base_fields,
        metadata.level().as_str(),
        metadata.target(),
        &message,
        visitor.fields,
        timestamp_ms,
    )
    .unwrap_or_else(|err| {
        format!(
            r#"{{"timestamp":{},"level":"ERROR","message":"failed to serialize daemon log event","error":"{}"}}"#,
            timestamp_ms,
            json_escape(&err.to_string())
        )
    });
    CloudWatchLogRecord {
        timestamp_ms: timestamp_ms.try_into().unwrap_or(i64::MAX),
        message: json,
    }
}

#[derive(Default)]
struct JsonFieldVisitor {
    fields: BTreeMap<String, Value>,
    message: Option<String>,
}

impl Visit for JsonFieldVisitor {
    fn record_debug(&mut self, field: &Field, value: &dyn fmt::Debug) {
        let value = format!("{value:?}");
        if field.name() == "message" {
            self.message = Some(value);
        } else {
            self.fields
                .insert(field.name().to_string(), debug_field_to_json_value(&value));
        }
    }

    fn record_str(&mut self, field: &Field, value: &str) {
        if field.name() == "message" {
            self.message = Some(value.to_string());
        } else {
            self.fields
                .insert(field.name().to_string(), Value::String(value.to_string()));
        }
    }

    fn record_bool(&mut self, field: &Field, value: bool) {
        self.fields
            .insert(field.name().to_string(), Value::Bool(value));
    }

    fn record_i64(&mut self, field: &Field, value: i64) {
        self.fields
            .insert(field.name().to_string(), Value::Number(value.into()));
    }

    fn record_u64(&mut self, field: &Field, value: u64) {
        self.fields
            .insert(field.name().to_string(), Value::Number(value.into()));
    }
}

fn debug_field_to_json_value(value: &str) -> Value {
    serde_json::from_str(value).unwrap_or_else(|_| Value::String(value.to_string()))
}

pub fn build_cloudwatch_log_message(
    base_fields: &CloudWatchLogBaseFields,
    level: &str,
    target: &str,
    message: &str,
    event_fields: BTreeMap<String, Value>,
    timestamp_ms: u64,
) -> Result<String> {
    let mut fields = BTreeMap::new();
    fields.insert("timestamp".to_string(), Value::Number(timestamp_ms.into()));
    fields.insert("level".to_string(), Value::String(level.to_string()));
    fields.insert("target".to_string(), Value::String(target.to_string()));
    fields.insert("message".to_string(), Value::String(message.to_string()));
    fields.insert(
        "thing_id".to_string(),
        Value::String(base_fields.thing_id.clone()),
    );
    fields.insert(
        "client_id".to_string(),
        Value::String(base_fields.client_id.clone()),
    );
    fields.insert(
        "iot_role_alias".to_string(),
        Value::String(base_fields.iot_role_alias.clone()),
    );
    fields.insert(
        "aws_region".to_string(),
        Value::String(base_fields.aws_region.clone()),
    );
    for (key, value) in event_fields {
        fields.insert(key, value);
    }
    serde_json::to_string(&fields).context("serialize CloudWatch log event")
}

fn json_escape(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

#[derive(Debug, Parser)]
#[command(name = "txing-unit-daemon")]
#[command(version = DAEMON_VERSION)]
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

    #[arg(long = "cloudwatch-log-group")]
    pub cloudwatch_log_group: Option<String>,

    #[arg(long = "cloudwatch-log-stream")]
    pub cloudwatch_log_stream: Option<String>,

    #[arg(long = "cloudwatch-log-level")]
    pub cloudwatch_log_level: Option<String>,

    #[arg(long = "cloudwatch-log-retention-days")]
    pub cloudwatch_log_retention_days: Option<i32>,

    #[arg(long = "kvs-master-command")]
    pub kvs_master_command: Option<String>,

    #[arg(long = "mcp-webrtc-socket-path")]
    pub mcp_webrtc_socket_path: Option<String>,

    #[arg(long = "board-video-bridge-socket-path")]
    pub board_video_bridge_socket_path: Option<String>,

    #[arg(long = "kvs-prefer-ipv6")]
    pub kvs_prefer_ipv6: Option<String>,

    #[arg(long = "kvs-disable-ipv4-turn")]
    pub kvs_disable_ipv4_turn: Option<String>,

    #[arg(long = "video-channel-name")]
    pub video_channel_name: Option<String>,

    #[arg(long = "hardware-worker-socket-path")]
    pub hardware_worker_socket_path: Option<String>,

    #[arg(long = "hardware-worker-timeout-ms")]
    pub hardware_worker_timeout_ms: Option<u64>,
}

#[derive(Debug, Clone, PartialEq)]
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
    pub kvs_master_command: String,
    pub mcp_webrtc_socket_path: String,
    pub board_video_bridge_socket_path: String,
    pub kvs_prefer_ipv6: bool,
    pub kvs_disable_ipv4_turn: bool,
    pub video_region: String,
    pub video_channel_name: String,
    pub hardware_worker_socket_path: String,
    pub hardware_worker_timeout: Duration,
    pub cloudwatch_logging: Option<CloudWatchLogConfig>,
}

impl RuntimeConfig {
    pub fn from_cli(cli: Cli) -> Result<Self> {
        let process_env = env::vars().collect::<BTreeMap<_, _>>();
        let file_env = load_env_file_for_cli(&cli, &process_env)?;
        Self::from_sources_with_env_file_dir(
            cli,
            &process_env,
            &file_env.values,
            file_env.parent_dir(),
        )
    }

    pub fn from_sources(
        cli: Cli,
        process_env: &BTreeMap<String, String>,
        file_env: &BTreeMap<String, String>,
    ) -> Result<Self> {
        Self::from_sources_with_env_file_dir(cli, process_env, file_env, None)
    }

    pub fn from_sources_with_env_file_dir(
        cli: Cli,
        process_env: &BTreeMap<String, String>,
        file_env: &BTreeMap<String, String>,
        env_file_dir: Option<&Path>,
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
            cli.client_id.clone(),
            process_env,
            file_env,
            "TXING_DAEMON_CLIENT_ID",
        ) {
            Some(value) => value,
            None => default_client_id(&thing_id, process::id()),
        };
        validate_client_id(&thing_id, &client_id)?;
        let kvs_master_command = optional_config_value(
            cli.kvs_master_command,
            process_env,
            file_env,
            "TXING_KVS_MASTER_COMMAND",
        )
        .unwrap_or_else(|| DEFAULT_KVS_MASTER_COMMAND.to_string());
        let mcp_webrtc_socket_path = optional_config_value(
            cli.mcp_webrtc_socket_path,
            process_env,
            file_env,
            "TXING_MCP_WEBRTC_SOCKET_PATH",
        )
        .unwrap_or_else(|| DEFAULT_MCP_WEBRTC_SOCKET_PATH.to_string());
        if mcp_webrtc_socket_path.trim().is_empty() {
            bail!("mcp-webrtc-socket-path must not be empty");
        }
        let board_video_bridge_socket_path = optional_config_value(
            cli.board_video_bridge_socket_path,
            process_env,
            file_env,
            "TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH",
        )
        .unwrap_or_else(|| DEFAULT_BOARD_VIDEO_BRIDGE_SOCKET_PATH.to_string());
        if board_video_bridge_socket_path.trim().is_empty() {
            bail!("board-video-bridge-socket-path must not be empty");
        }
        let hardware_worker_socket_path = optional_config_value(
            cli.hardware_worker_socket_path,
            process_env,
            file_env,
            "TXING_HARDWARE_WORKER_SOCKET_PATH",
        )
        .unwrap_or_else(|| DEFAULT_HARDWARE_WORKER_SOCKET_PATH.to_string());
        if hardware_worker_socket_path.trim().is_empty() {
            bail!("hardware-worker-socket-path must not be empty");
        }
        let hardware_worker_timeout_ms = cli
            .hardware_worker_timeout_ms
            .or(optional_u64_config(
                process_env,
                file_env,
                "TXING_HARDWARE_WORKER_TIMEOUT_MS",
            )?)
            .unwrap_or(DEFAULT_HARDWARE_WORKER_TIMEOUT_MS);
        if hardware_worker_timeout_ms == 0 {
            bail!("hardware-worker-timeout-ms must be positive");
        }
        let kvs_prefer_ipv6 = optional_bool_config(
            cli.kvs_prefer_ipv6,
            process_env,
            file_env,
            "TXING_KVS_PREFER_IPV6",
            "kvs-prefer-ipv6",
        )?
        .unwrap_or(true);
        let kvs_disable_ipv4_turn = optional_bool_config(
            cli.kvs_disable_ipv4_turn,
            process_env,
            file_env,
            "TXING_KVS_DISABLE_IPV4_TURN",
            "kvs-disable-ipv4-turn",
        )?
        .unwrap_or(false);
        let aws_region = required_config_value(
            cli.aws_region,
            process_env,
            file_env,
            "AWS_REGION",
            "aws-region",
        )?;
        let video_channel_name = optional_config_value(
            cli.video_channel_name,
            process_env,
            file_env,
            "TXING_BOARD_VIDEO_CHANNEL_NAME",
        )
        .unwrap_or_else(|| default_video_channel_name(&thing_id));
        validate_topic_segment(&video_channel_name, "video-channel-name")?;
        validate_topic_segment(&aws_region, "aws-region")?;
        let cloudwatch_logging = resolve_cloudwatch_log_config(
            cli.cloudwatch_log_group,
            cli.cloudwatch_log_stream,
            cli.cloudwatch_log_level,
            cli.cloudwatch_log_retention_days,
            process_env,
            file_env,
            &client_id,
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
        let iot_cert_file = config_value_or_colocated_file(
            cli.iot_cert_file,
            process_env,
            file_env,
            "TXING_IOT_CERT_FILE",
            "iot-cert-file",
            env_file_dir,
            DEFAULT_IOT_CERT_FILE_NAME,
        )?;
        let iot_private_key_file = config_value_or_colocated_file(
            cli.iot_private_key_file,
            process_env,
            file_env,
            "TXING_IOT_PRIVATE_KEY_FILE",
            "iot-private-key-file",
            env_file_dir,
            DEFAULT_IOT_PRIVATE_KEY_FILE_NAME,
        )?;
        let iot_root_ca_file = config_value_or_colocated_file(
            cli.iot_root_ca_file,
            process_env,
            file_env,
            "TXING_IOT_ROOT_CA_FILE",
            "iot-root-ca-file",
            env_file_dir,
            DEFAULT_IOT_ROOT_CA_FILE_NAME,
        )?;

        Ok(Self {
            thing_id,
            aws_region: aws_region.clone(),
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
            kvs_master_command,
            mcp_webrtc_socket_path,
            board_video_bridge_socket_path,
            kvs_prefer_ipv6,
            kvs_disable_ipv4_turn,
            video_region: aws_region,
            video_channel_name,
            hardware_worker_socket_path,
            hardware_worker_timeout: Duration::from_millis(hardware_worker_timeout_ms),
            cloudwatch_logging,
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RuntimeMqttEvent {
    Publish { topic: String, payload: Vec<u8> },
    Disconnected,
}

#[derive(Debug)]
pub enum RuntimeMcpIpcEvent {
    Open {
        session_id: String,
        transport: String,
        peer_id: Option<String>,
    },
    Request {
        session_id: String,
        payload: String,
        response_tx: oneshot::Sender<Option<String>>,
    },
    Close {
        session_id: String,
        reason: String,
    },
}

#[allow(dead_code)]
#[derive(Debug, Deserialize)]
struct McpIpcFrame {
    #[serde(rename = "type")]
    frame_type: String,
    #[serde(rename = "sessionId")]
    session_id: Option<String>,
    payload: Option<String>,
    reason: Option<String>,
}

#[async_trait]
pub trait Publisher: Send + Sync {
    async fn publish(&self, message: PublishedMessage) -> Result<()>;
}

struct MqttPublisher {
    client: AsyncClientHandle,
    stopping: Arc<AtomicBool>,
}

impl MqttPublisher {
    async fn connect(
        config: &RuntimeConfig,
    ) -> Result<(Self, mpsc::UnboundedReceiver<RuntimeMqttEvent>)> {
        info!(
            endpoint = %config.iot_endpoint,
            port = MQTT_PORT,
            client_id = %config.client_id,
            "connecting mqtt"
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
        let (connected_sender, connected_receiver) = oneshot::channel::<Result<(), String>>();
        let connected_sender = Arc::new(std::sync::Mutex::new(Some(connected_sender)));
        let event_client_id = config.client_id.clone();
        let stopping = Arc::new(AtomicBool::new(false));
        let (event_sender, event_receiver) = mpsc::unbounded_channel();
        let listener = {
            let connected_sender = Arc::clone(&connected_sender);
            let stopping = Arc::clone(&stopping);
            let event_sender = event_sender.clone();
            Arc::new(move |event: Arc<ClientEvent>| match event.as_ref() {
                ClientEvent::PublishReceived(received) => {
                    let payload = received
                        .publish
                        .payload()
                        .map(|payload| payload.to_vec())
                        .unwrap_or_default();
                    let _ = event_sender.send(RuntimeMqttEvent::Publish {
                        topic: received.publish.topic().to_string(),
                        payload,
                    });
                }
                ClientEvent::ConnectionSuccess(event) => {
                    info!(client_id = %event_client_id, "mqtt connected");
                    debug!(client_id = %event_client_id, event = %event, "mqtt connection detail");
                    if let Ok(mut sender) = connected_sender.lock()
                        && let Some(sender) = sender.take()
                    {
                        let _ = sender.send(Ok(()));
                    }
                }
                ClientEvent::ConnectionFailure(event) => {
                    warn!(client_id = %event_client_id, event = %event, "mqtt connection failed");
                    if let Ok(mut sender) = connected_sender.lock()
                        && let Some(sender) = sender.take()
                    {
                        let _ = sender.send(Err(event.to_string()));
                    }
                }
                ClientEvent::Disconnection(event) => {
                    if stopping.load(Ordering::Relaxed) {
                        debug!(client_id = %event_client_id, event = %event, "mqtt disconnected during shutdown");
                    } else {
                        warn!(client_id = %event_client_id, event = %event, "mqtt disconnected");
                        let _ = event_sender.send(RuntimeMqttEvent::Disconnected);
                    }
                    if let Ok(mut sender) = connected_sender.lock()
                        && let Some(sender) = sender.take()
                    {
                        let _ = sender.send(Err(event.to_string()));
                    }
                }
                _ => {}
            }) as Arc<ClientEventListenerCallback>
        };
        client.start(Some(listener))?;
        match timeout(
            Duration::from_secs(MQTT_CONNECT_WAIT_SECONDS),
            connected_receiver,
        )
        .await
        {
            Ok(Ok(Ok(()))) => {}
            Ok(Ok(Err(message))) => bail!("MQTT connection failed: {message}"),
            Ok(Err(_)) => bail!("MQTT connection listener dropped before connection result"),
            Err(_) => {
                bail!("MQTT connection did not complete within {MQTT_CONNECT_WAIT_SECONDS} seconds")
            }
        }
        info!(client_id = %config.client_id, "mqtt client started");
        Ok((Self { client, stopping }, event_receiver))
    }

    async fn subscribe(&self, topic_filter: String) -> Result<()> {
        let subscribe = SubscribePacket::builder()
            .with_subscription_simple(topic_filter.clone(), QualityOfService::AtLeastOnce)
            .build();
        let suback = self.client.subscribe(subscribe, None).await?;
        if let Some(reason_code) = suback.reason_codes().first()
            && !reason_code.is_success()
        {
            bail!("MQTT subscribe failed for {topic_filter}: {reason_code}");
        }
        Ok(())
    }

    fn stop(&self) -> Result<()> {
        self.stopping.store(true, Ordering::Relaxed);
        self.client.stop(None)?;
        self.client.close()?;
        Ok(())
    }
}

#[allow(dead_code)]
struct McpIpcServerHandle {
    stop: Arc<AtomicBool>,
    path: String,
    task: JoinHandle<()>,
}

#[allow(dead_code)]
impl McpIpcServerHandle {
    async fn shutdown(self) {
        self.stop.store(true, Ordering::SeqCst);
        let mut task = self.task;
        tokio::select! {
            join_result = &mut task => {
                if let Err(err) = join_result {
                    warn!(error = %err, "MCP IPC server task failed during shutdown");
                }
            }
            _ = tokio::time::sleep(Duration::from_secs(2)) => {
                task.abort();
                warn!("MCP IPC server did not stop within timeout; aborting task");
            }
        }
        if let Err(err) = fs::remove_file(&self.path)
            && err.kind() != ErrorKind::NotFound
        {
            warn!(path = %self.path, error = %err, "failed to remove MCP IPC socket");
        }
    }
}

#[allow(dead_code)]
fn start_mcp_ipc_server(
    socket_path: String,
    event_tx: mpsc::UnboundedSender<RuntimeMcpIpcEvent>,
) -> Result<McpIpcServerHandle> {
    let listener = bind_mcp_ipc_listener(&socket_path)?;
    let stop = Arc::new(AtomicBool::new(false));
    let task_stop = stop.clone();
    let task_path = socket_path.clone();
    let task = tokio::spawn(async move {
        if let Err(err) = run_mcp_ipc_server(listener, event_tx, task_stop).await {
            warn!(error = %format_args!("{err:#}"), "MCP IPC server stopped");
        }
    });
    Ok(McpIpcServerHandle {
        stop,
        path: task_path,
        task,
    })
}

#[allow(dead_code)]
fn bind_mcp_ipc_listener(socket_path: &str) -> Result<UnixListener> {
    let listener = bind_unix_listener(socket_path, "MCP IPC")?;
    info!(path = %socket_path, "MCP WebRTC IPC server started");
    Ok(listener)
}

fn bind_unix_listener(socket_path: &str, label: &str) -> Result<UnixListener> {
    let path = Path::new(socket_path);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("create {label} socket directory {}", parent.display()))?;
    }
    if let Err(err) = fs::remove_file(path)
        && err.kind() != ErrorKind::NotFound
    {
        return Err(err).with_context(|| format!("remove stale {label} socket {socket_path}"));
    }
    UnixListener::bind(path).with_context(|| format!("bind {label} socket {socket_path}"))
}

#[allow(dead_code)]
async fn run_mcp_ipc_server(
    listener: UnixListener,
    event_tx: mpsc::UnboundedSender<RuntimeMcpIpcEvent>,
    stop: Arc<AtomicBool>,
) -> Result<()> {
    while !stop.load(Ordering::SeqCst) {
        tokio::select! {
            accepted = listener.accept() => {
                match accepted {
                    Ok((stream, _)) => {
                        let connection_tx = event_tx.clone();
                        tokio::spawn(async move {
                            handle_mcp_ipc_connection(stream, connection_tx).await;
                        });
                    }
                    Err(err) => {
                        if stop.load(Ordering::SeqCst) {
                            break;
                        }
                        warn!(error = %err, "MCP IPC accept failed");
                    }
                }
            }
            _ = sleep(Duration::from_millis(200)) => {}
        }
    }
    Ok(())
}

#[allow(dead_code)]
async fn handle_mcp_ipc_connection(
    stream: UnixStream,
    event_tx: mpsc::UnboundedSender<RuntimeMcpIpcEvent>,
) {
    let (reader, mut writer) = split_async_io(stream);
    let mut reader = TokioBufReader::new(reader);
    let mut line = String::new();
    loop {
        line.clear();
        let read = match reader.read_line(&mut line).await {
            Ok(read) => read,
            Err(err) => {
                warn!(error = %err, "MCP IPC read failed");
                break;
            }
        };
        if read == 0 {
            break;
        }
        let frame: McpIpcFrame = match serde_json::from_str(line.trim_end()) {
            Ok(frame) => frame,
            Err(err) => {
                warn!(error = %err, "ignored invalid MCP IPC frame");
                continue;
            }
        };
        let Some(session_id) = frame
            .session_id
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(ToOwned::to_owned)
        else {
            warn!("ignored MCP IPC frame without sessionId");
            continue;
        };
        match frame.frame_type.as_str() {
            "request" => {
                let Some(payload) = frame.payload else {
                    warn!(session_id = %session_id, "ignored MCP IPC request without payload");
                    continue;
                };
                let (response_tx, response_rx) = oneshot::channel();
                if event_tx
                    .send(RuntimeMcpIpcEvent::Request {
                        session_id: session_id.clone(),
                        payload,
                        response_tx,
                    })
                    .is_err()
                {
                    break;
                }
                let response = response_rx.await.ok().flatten();
                if let Some(payload) = response {
                    let frame = serde_json::json!({
                        "type": "response",
                        "sessionId": session_id,
                        "payload": payload,
                    });
                    let mut encoded = match serde_json::to_vec(&frame) {
                        Ok(encoded) => encoded,
                        Err(err) => {
                            warn!(error = %err, "failed to encode MCP IPC response");
                            break;
                        }
                    };
                    encoded.push(b'\n');
                    if let Err(err) = writer.write_all(&encoded).await {
                        warn!(error = %err, "MCP IPC response write failed");
                        break;
                    }
                }
            }
            "close" => {
                let reason = frame
                    .reason
                    .unwrap_or_else(|| "MCP WebRTC data channel closed".to_string());
                let _ = event_tx.send(RuntimeMcpIpcEvent::Close { session_id, reason });
            }
            other => {
                warn!(frame_type = %other, "ignored unsupported MCP IPC frame");
            }
        }
    }
}

struct BoardVideoBridgeServerHandle {
    path: String,
    shutdown_tx: Option<oneshot::Sender<()>>,
    task: JoinHandle<()>,
}

impl BoardVideoBridgeServerHandle {
    async fn shutdown(mut self) {
        if let Some(shutdown_tx) = self.shutdown_tx.take() {
            let _ = shutdown_tx.send(());
        }
        let mut task = self.task;
        tokio::select! {
            join_result = &mut task => {
                if let Err(err) = join_result {
                    warn!(error = %err, "board video bridge server task failed during shutdown");
                }
            }
            _ = tokio::time::sleep(Duration::from_secs(2)) => {
                task.abort();
                warn!("board video bridge server did not stop within timeout; aborting task");
            }
        }
        if let Err(err) = fs::remove_file(&self.path)
            && err.kind() != ErrorKind::NotFound
        {
            warn!(path = %self.path, error = %err, "failed to remove board video bridge socket");
        }
    }
}

fn start_board_video_bridge_server(
    config: RuntimeConfig,
    video_event_tx: mpsc::UnboundedSender<VideoWorkerEvent>,
    mcp_event_tx: mpsc::UnboundedSender<RuntimeMcpIpcEvent>,
) -> Result<BoardVideoBridgeServerHandle> {
    let socket_path = config.board_video_bridge_socket_path.clone();
    let listener = bind_unix_listener(&socket_path, "board video bridge")?;
    let incoming = UnixListenerStream::new(listener);
    let (shutdown_tx, shutdown_rx) = oneshot::channel();
    let service = BoardVideoBridgeService {
        config: Arc::new(config),
        video_event_tx,
        mcp_event_tx,
    };
    let task_path = socket_path.clone();
    let task = tokio::spawn(async move {
        let server =
            board_video_bridge::board_video_bridge_server::BoardVideoBridgeServer::new(service);
        info!(path = %task_path, "board video bridge gRPC server started");
        if let Err(err) = TonicServer::builder()
            .add_service(server)
            .serve_with_incoming_shutdown(incoming, async {
                let _ = shutdown_rx.await;
            })
            .await
        {
            warn!(error = %err, "board video bridge gRPC server stopped");
        }
    });
    Ok(BoardVideoBridgeServerHandle {
        path: socket_path,
        shutdown_tx: Some(shutdown_tx),
        task,
    })
}

#[derive(Clone)]
struct BoardVideoBridgeService {
    config: Arc<RuntimeConfig>,
    video_event_tx: mpsc::UnboundedSender<VideoWorkerEvent>,
    mcp_event_tx: mpsc::UnboundedSender<RuntimeMcpIpcEvent>,
}

#[tonic::async_trait]
impl board_video_bridge::board_video_bridge_server::BoardVideoBridge for BoardVideoBridgeService {
    async fn get_worker_config(
        &self,
        request: TonicRequest<board_video_bridge::WorkerHello>,
    ) -> std::result::Result<TonicResponse<board_video_bridge::WorkerConfig>, TonicStatus> {
        let hello = request.into_inner();
        if hello.protocol_version.trim() != "1" {
            return Err(TonicStatus::invalid_argument(
                "unsupported board video bridge protocol_version",
            ));
        }
        let credentials = fetch_iot_temporary_credentials(&self.config)
            .await
            .map_err(|err| {
                TonicStatus::unavailable(format!("resolve KVS worker credentials: {err:#}"))
            })?;
        let response = build_worker_config_response(&self.config, credentials)
            .map_err(|err| TonicStatus::internal(format!("{err:#}")))?;
        info!(
            worker_name = %hello.worker_name,
            worker_version = %hello.worker_version,
            channel_name = %response.channel_name,
            "board video worker config served"
        );
        Ok(TonicResponse::new(response))
    }

    async fn refresh_credentials(
        &self,
        _request: TonicRequest<board_video_bridge::RefreshCredentialsRequest>,
    ) -> std::result::Result<TonicResponse<board_video_bridge::KvsCredentials>, TonicStatus> {
        let credentials = fetch_iot_temporary_credentials(&self.config)
            .await
            .map_err(|err| {
                TonicStatus::unavailable(format!("refresh KVS worker credentials: {err:#}"))
            })?;
        let response = bridge_credentials_from_iot(credentials)
            .map_err(|err| TonicStatus::internal(format!("{err:#}")))?;
        Ok(TonicResponse::new(response))
    }

    async fn report_video_state(
        &self,
        request: TonicRequest<board_video_bridge::VideoState>,
    ) -> std::result::Result<TonicResponse<board_video_bridge::Ack>, TonicStatus> {
        let report = request.into_inner();
        let state = board_video_bridge::video_state::State::try_from(report.state)
            .unwrap_or(board_video_bridge::video_state::State::Unspecified);
        match state {
            board_video_bridge::video_state::State::Starting => {
                self.send_video_event(VideoWorkerEvent::Starting)?;
                self.send_video_event(VideoWorkerEvent::ViewerConnected {
                    connected: report.viewer_count > 0,
                })?;
            }
            board_video_bridge::video_state::State::Ready => {
                self.send_video_event(VideoWorkerEvent::Ready {
                    worker_version: None,
                })?;
                self.send_video_event(VideoWorkerEvent::ViewerConnected {
                    connected: report.viewer_count > 0,
                })?;
            }
            board_video_bridge::video_state::State::Error => {
                self.send_video_event(VideoWorkerEvent::Error {
                    detail: if report.error.trim().is_empty() {
                        "board video worker reported an error".to_string()
                    } else {
                        report.error
                    },
                })?;
                self.send_video_event(VideoWorkerEvent::ViewerConnected {
                    connected: report.viewer_count > 0,
                })?;
            }
            board_video_bridge::video_state::State::Unspecified => {
                return Err(TonicStatus::invalid_argument(
                    "video state must be STARTING, READY, or ERROR",
                ));
            }
        }
        Ok(TonicResponse::new(board_video_bridge::Ack {}))
    }

    async fn open_mcp_session(
        &self,
        request: TonicRequest<board_video_bridge::OpenMcpSessionRequest>,
    ) -> std::result::Result<TonicResponse<board_video_bridge::Ack>, TonicStatus> {
        let request = request.into_inner();
        let session_id = normalize_bridge_session_id(request.mcp_session_id)?;
        let transport = if request.transport.trim().is_empty() {
            "webrtc-datachannel".to_string()
        } else {
            request.transport
        };
        let peer_id = if request.peer_id.trim().is_empty() {
            None
        } else {
            Some(request.peer_id)
        };
        self.send_mcp_event(RuntimeMcpIpcEvent::Open {
            session_id,
            transport,
            peer_id,
        })?;
        Ok(TonicResponse::new(board_video_bridge::Ack {}))
    }

    async fn handle_mcp(
        &self,
        request: TonicRequest<board_video_bridge::McpRequest>,
    ) -> std::result::Result<TonicResponse<board_video_bridge::McpResponse>, TonicStatus> {
        let request = request.into_inner();
        let session_id = normalize_bridge_session_id(request.mcp_session_id)?;
        let payload = String::from_utf8(request.payload)
            .map_err(|_| TonicStatus::invalid_argument("MCP payload must be UTF-8 JSON-RPC"))?;
        let (response_tx, response_rx) = oneshot::channel();
        self.send_mcp_event(RuntimeMcpIpcEvent::Request {
            session_id,
            payload,
            response_tx,
        })?;
        let response = timeout(
            Duration::from_millis(u64::from(DEFAULT_MCP_RESPONSE_TIMEOUT_MS)),
            response_rx,
        )
        .await
        .map_err(|_| TonicStatus::deadline_exceeded("MCP response timed out"))?
        .map_err(|_| TonicStatus::unavailable("daemon MCP runtime stopped"))?;
        let response = match response {
            Some(payload) => board_video_bridge::McpResponse {
                has_payload: true,
                payload: payload.into_bytes(),
            },
            None => board_video_bridge::McpResponse {
                has_payload: false,
                payload: Vec::new(),
            },
        };
        Ok(TonicResponse::new(response))
    }

    async fn close_mcp_session(
        &self,
        request: TonicRequest<board_video_bridge::CloseMcpSessionRequest>,
    ) -> std::result::Result<TonicResponse<board_video_bridge::Ack>, TonicStatus> {
        let request = request.into_inner();
        let session_id = normalize_bridge_session_id(request.mcp_session_id)?;
        let reason = if request.reason.trim().is_empty() {
            "MCP bridge session closed".to_string()
        } else {
            request.reason
        };
        self.send_mcp_event(RuntimeMcpIpcEvent::Close { session_id, reason })?;
        Ok(TonicResponse::new(board_video_bridge::Ack {}))
    }
}

impl BoardVideoBridgeService {
    fn send_video_event(&self, event: VideoWorkerEvent) -> std::result::Result<(), TonicStatus> {
        self.video_event_tx
            .send(event)
            .map_err(|_| TonicStatus::unavailable("daemon video runtime stopped"))
    }

    fn send_mcp_event(&self, event: RuntimeMcpIpcEvent) -> std::result::Result<(), TonicStatus> {
        self.mcp_event_tx
            .send(event)
            .map_err(|_| TonicStatus::unavailable("daemon MCP runtime stopped"))
    }
}

fn normalize_bridge_session_id(session_id: String) -> std::result::Result<String, TonicStatus> {
    let trimmed = session_id.trim();
    if trimmed.is_empty() {
        return Err(TonicStatus::invalid_argument("mcp_session_id is required"));
    }
    Ok(trimmed.to_string())
}

fn build_worker_config_response(
    config: &RuntimeConfig,
    credentials: IotTemporaryCredentials,
) -> Result<board_video_bridge::WorkerConfig> {
    Ok(board_video_bridge::WorkerConfig {
        region: config.video_region.clone(),
        channel_name: config.video_channel_name.clone(),
        client_id: board_video_worker_client_id(config),
        mcp_data_channel_label: MCP_WEBRTC_DATA_CHANNEL_LABEL.to_string(),
        mcp_response_timeout_ms: DEFAULT_MCP_RESPONSE_TIMEOUT_MS,
        prefer_ipv6: config.kvs_prefer_ipv6,
        disable_ipv4_turn: config.kvs_disable_ipv4_turn,
        credentials: Some(bridge_credentials_from_iot(credentials)?),
    })
}

fn bridge_credentials_from_iot(
    credentials: IotTemporaryCredentials,
) -> Result<board_video_bridge::KvsCredentials> {
    Ok(board_video_bridge::KvsCredentials {
        access_key_id: credentials.access_key_id,
        secret_access_key: credentials.secret_access_key,
        session_token: credentials.session_token,
        expires_at: Some(system_time_to_protobuf_timestamp(
            parse_iot_temporary_credentials_expiration(&credentials.expiration)?,
        )?),
    })
}

fn system_time_to_protobuf_timestamp(time: SystemTime) -> Result<prost_types::Timestamp> {
    let duration = time
        .duration_since(UNIX_EPOCH)
        .context("board video bridge credential expiration is before Unix epoch")?;
    Ok(prost_types::Timestamp {
        seconds: duration
            .as_secs()
            .try_into()
            .context("board video bridge credential expiration exceeds protobuf timestamp range")?,
        nanos: duration.subsec_nanos() as i32,
    })
}

fn board_video_worker_client_id(config: &RuntimeConfig) -> String {
    format!("{}-board-kvs-master", config.thing_id)
}

#[async_trait]
impl Publisher for MqttPublisher {
    async fn publish(&self, message: PublishedMessage) -> Result<()> {
        let topic = message.topic.clone();
        let retain = message.retain;
        let payload_len = message.payload.len();
        debug!(topic = %topic, retain, bytes = payload_len, "publishing mqtt message");
        let packet = PublishPacket::builder(message.topic.clone(), QualityOfService::AtLeastOnce)
            .with_payload(message.payload)
            .with_retain(message.retain)
            .build();
        let response = timeout(
            Duration::from_secs(MQTT_PUBLISH_OPERATION_TIMEOUT_SECONDS),
            self.client.publish(packet, None),
        )
        .await
        .with_context(|| {
            format!(
                "MQTT publish timed out for {topic} after {MQTT_PUBLISH_OPERATION_TIMEOUT_SECONDS} seconds"
            )
        })??;
        if let PublishResponse::Qos1(puback) = response
            && !puback.reason_code().is_success()
        {
            bail!(
                "MQTT publish failed for {}: {}",
                topic,
                puback.reason_code()
            );
        }
        debug!(topic = %topic, retain, bytes = payload_len, "published mqtt message");
        Ok(())
    }
}

pub struct CapabilityManager {
    capabilities: Vec<String>,
    seq: u64,
}

impl CapabilityManager {
    pub fn new(capability_names: &[String]) -> Result<Self> {
        let mut names = BTreeSet::new();
        for name in capability_names {
            validate_capability_name(name)?;
            names.insert(name.clone());
        }
        if names.is_empty() {
            bail!("at least one capability is required");
        }
        Ok(Self {
            capabilities: names.into_iter().collect(),
            seq: 0,
        })
    }

    pub async fn publish_state<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        thing_name: &str,
        availability: &BTreeMap<String, bool>,
        ttl: Duration,
        observed_at_ms: u64,
    ) -> Result<()> {
        self.seq += 1;
        let mut capabilities = BTreeMap::new();
        let mut expired_capabilities = BTreeMap::new();
        for capability in &self.capabilities {
            let available = availability.get(capability).copied().unwrap_or(false);
            capabilities.insert(capability.clone(), available);
            expired_capabilities.insert(capability.clone(), false);
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

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Vector3 {
    pub x: f64,
    pub y: f64,
    pub z: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Twist {
    pub linear: Vector3,
    pub angular: Vector3,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct DriveState {
    #[serde(rename = "leftSpeed")]
    pub left_speed: i32,
    #[serde(rename = "rightSpeed")]
    pub right_speed: i32,
    pub sequence: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HardwareStatusSnapshot {
    pub actuator_ready: bool,
    pub motion: DriveState,
}

#[async_trait]
pub trait HardwareClient: Send {
    async fn get_status(&mut self) -> Result<HardwareStatusSnapshot>;
    async fn apply_velocity(&mut self, twist: Twist, deadline_unix_ms: u64) -> Result<DriveState>;
    async fn stop(&mut self) -> Result<DriveState>;
}

struct GrpcHardwareClient {
    socket_path: String,
    timeout_duration: Duration,
    client:
        Option<unit_hardware::unit_hardware_client::UnitHardwareClient<tonic::transport::Channel>>,
}

impl GrpcHardwareClient {
    fn new(socket_path: String, timeout_duration: Duration) -> Self {
        Self {
            socket_path,
            timeout_duration,
            client: None,
        }
    }

    async fn ensure_client(&mut self) -> Result<()> {
        if self.client.is_some() {
            return Ok(());
        }
        let socket_path = PathBuf::from(self.socket_path.clone());
        let endpoint = tonic::transport::Endpoint::try_from("http://[::]:50051")
            .context("create hardware worker gRPC endpoint")?;
        let channel = timeout(
            self.timeout_duration,
            endpoint.connect_with_connector(tower::service_fn(move |_| {
                let path = socket_path.clone();
                async move {
                    UnixStream::connect(path)
                        .await
                        .map(hyper_util::rt::TokioIo::new)
                }
            })),
        )
        .await
        .context("connect to hardware worker timed out")?
        .context("connect to hardware worker")?;
        self.client = Some(unit_hardware::unit_hardware_client::UnitHardwareClient::new(channel));
        Ok(())
    }

    fn drop_client(&mut self) {
        self.client = None;
    }
}

#[async_trait]
impl HardwareClient for GrpcHardwareClient {
    async fn get_status(&mut self) -> Result<HardwareStatusSnapshot> {
        self.ensure_client().await?;
        let result = {
            let client = self.client.as_mut().expect("hardware client initialized");
            timeout(
                self.timeout_duration,
                client.get_status(unit_hardware::GetStatusRequest {}),
            )
            .await
        };
        match result {
            Ok(Ok(response)) => Ok(status_from_proto(response.into_inner())),
            Ok(Err(err)) => {
                self.drop_client();
                Err(anyhow!("hardware worker status failed: {}", err.message()))
            }
            Err(_) => {
                self.drop_client();
                Err(anyhow!("hardware worker status timed out"))
            }
        }
    }

    async fn apply_velocity(&mut self, twist: Twist, deadline_unix_ms: u64) -> Result<DriveState> {
        self.ensure_client().await?;
        let request = unit_hardware::ApplyVelocityRequest {
            twist: Some(twist_to_proto(twist)),
            deadline_unix_ms,
            command_id: format!("cmd_vel-{deadline_unix_ms}"),
        };
        let result = {
            let client = self.client.as_mut().expect("hardware client initialized");
            timeout(self.timeout_duration, client.apply_velocity(request)).await
        };
        match result {
            Ok(Ok(response)) => Ok(motion_from_proto(response.into_inner().motion)),
            Ok(Err(err)) => {
                self.drop_client();
                Err(anyhow!(
                    "hardware worker apply velocity failed: {}",
                    err.message()
                ))
            }
            Err(_) => {
                self.drop_client();
                Err(anyhow!("hardware worker apply velocity timed out"))
            }
        }
    }

    async fn stop(&mut self) -> Result<DriveState> {
        self.ensure_client().await?;
        let request = unit_hardware::StopRequest {
            reason: "daemon-policy".to_string(),
        };
        let result = {
            let client = self.client.as_mut().expect("hardware client initialized");
            timeout(self.timeout_duration, client.stop(request)).await
        };
        match result {
            Ok(Ok(response)) => Ok(motion_from_proto(response.into_inner().motion)),
            Ok(Err(err)) => {
                self.drop_client();
                Err(anyhow!("hardware worker stop failed: {}", err.message()))
            }
            Err(_) => {
                self.drop_client();
                Err(anyhow!("hardware worker stop timed out"))
            }
        }
    }
}

fn twist_to_proto(twist: Twist) -> unit_hardware::Twist {
    unit_hardware::Twist {
        linear: Some(unit_hardware::Vector3 {
            x: twist.linear.x,
            y: twist.linear.y,
            z: twist.linear.z,
        }),
        angular: Some(unit_hardware::Vector3 {
            x: twist.angular.x,
            y: twist.angular.y,
            z: twist.angular.z,
        }),
    }
}

fn motion_from_proto(motion: Option<unit_hardware::MotionState>) -> DriveState {
    let motion = motion.unwrap_or_default();
    DriveState {
        left_speed: motion.left_speed,
        right_speed: motion.right_speed,
        sequence: motion.sequence,
    }
}

fn status_from_proto(status: unit_hardware::HardwareStatus) -> HardwareStatusSnapshot {
    HardwareStatusSnapshot {
        actuator_ready: status.actuator_ready,
        motion: motion_from_proto(status.motion),
    }
}

pub struct CmdVelController {
    client: Box<dyn HardwareClient>,
    drive_state: DriveState,
}

impl CmdVelController {
    pub fn new(client: Box<dyn HardwareClient>) -> Self {
        Self {
            client,
            drive_state: DriveState {
                left_speed: 0,
                right_speed: 0,
                sequence: 0,
            },
        }
    }

    pub fn from_config(config: &RuntimeConfig) -> Self {
        Self::new(Box::new(GrpcHardwareClient::new(
            config.hardware_worker_socket_path.clone(),
            config.hardware_worker_timeout,
        )))
    }

    pub fn drive_state(&self) -> DriveState {
        self.drive_state.clone()
    }

    pub async fn publish_twist(
        &mut self,
        twist: Twist,
        deadline_unix_ms: u64,
    ) -> Result<DriveState> {
        let motion = self.client.apply_velocity(twist, deadline_unix_ms).await?;
        self.drive_state = motion;
        Ok(self.drive_state())
    }

    pub async fn stop(&mut self, _force: bool) -> Result<DriveState> {
        let motion = self.client.stop().await?;
        self.drive_state = motion;
        Ok(self.drive_state())
    }

    pub async fn refresh_status(&mut self) -> Result<bool> {
        let status = self.client.get_status().await?;
        let changed = self.drive_state != status.motion;
        self.drive_state = status.motion;
        if !status.actuator_ready {
            bail!("hardware worker actuator unavailable");
        }
        Ok(changed)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ActiveControlState {
    #[serde(rename = "sessionId")]
    pub session_id: String,
    pub actor: Option<String>,
    pub transport: String,
    #[serde(rename = "sinceMs")]
    pub since_ms: u64,
    #[serde(rename = "expiresAtMs")]
    pub expires_at_ms: u64,
    pub epoch: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RobotControlReport {
    #[serde(rename = "activeRequired")]
    pub active_required: bool,
    #[serde(rename = "activeTtlMs")]
    pub active_ttl_ms: u64,
    #[serde(rename = "activeHeldByCaller")]
    pub active_held_by_caller: bool,
    #[serde(rename = "activeOwnerSessionId")]
    pub active_owner_session_id: Option<String>,
    #[serde(rename = "activeExpiresAtMs")]
    pub active_expires_at_ms: Option<u64>,
    #[serde(rename = "activeEpoch")]
    pub active_epoch: Option<u64>,
    #[serde(rename = "activeControl")]
    pub active_control: Option<ActiveControlState>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RobotVideoReport {
    pub available: bool,
    pub ready: bool,
    pub status: String,
    #[serde(rename = "viewerConnected")]
    pub viewer_connected: bool,
    #[serde(rename = "lastError")]
    pub last_error: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RobotStateReport {
    pub control: RobotControlReport,
    pub motion: DriveState,
    pub video: RobotVideoReport,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VideoRuntimeState {
    pub available: bool,
    pub ready: bool,
    pub status: String,
    pub viewer_connected: bool,
    pub last_error: Option<String>,
    pub updated_at_ms: u64,
}

impl VideoRuntimeState {
    pub fn starting(observed_at_ms: u64) -> Self {
        Self {
            available: true,
            ready: false,
            status: VIDEO_STATUS_STARTING.to_string(),
            viewer_connected: false,
            last_error: None,
            updated_at_ms: observed_at_ms,
        }
    }

    pub fn unavailable(observed_at_ms: u64) -> Self {
        Self {
            available: false,
            ready: false,
            status: VIDEO_STATUS_UNAVAILABLE.to_string(),
            viewer_connected: false,
            last_error: None,
            updated_at_ms: observed_at_ms,
        }
    }

    pub fn robot_report(&self) -> RobotVideoReport {
        RobotVideoReport {
            available: self.available,
            ready: self.ready,
            status: self.status.clone(),
            viewer_connected: self.viewer_connected,
            last_error: self.last_error.clone(),
        }
    }

    fn apply_event(&mut self, event: VideoWorkerEvent, observed_at_ms: u64) {
        match event {
            VideoWorkerEvent::Starting => {
                *self = Self::starting(observed_at_ms);
            }
            VideoWorkerEvent::Ready { .. } => {
                self.available = true;
                self.ready = true;
                self.status = VIDEO_STATUS_READY.to_string();
                self.last_error = None;
                self.updated_at_ms = observed_at_ms;
            }
            VideoWorkerEvent::ViewerConnected { connected } => {
                self.viewer_connected = connected;
                self.updated_at_ms = observed_at_ms;
            }
            VideoWorkerEvent::Error { detail } => {
                self.available = true;
                self.ready = false;
                self.status = VIDEO_STATUS_ERROR.to_string();
                self.last_error = Some(detail);
                self.updated_at_ms = observed_at_ms;
            }
            VideoWorkerEvent::McpDataChannelOpen { .. }
            | VideoWorkerEvent::McpDataChannelClosed { .. }
            | VideoWorkerEvent::McpDataChannelError { .. } => {
                self.updated_at_ms = observed_at_ms;
            }
        }
    }
}

pub struct McpServer {
    active: Option<ActiveControlState>,
    next_epoch: u64,
    active_ttl: Duration,
}

impl McpServer {
    pub fn new(active_ttl: Duration) -> Self {
        Self {
            active: None,
            next_epoch: 0,
            active_ttl,
        }
    }

    pub fn descriptor(thing_name: &str) -> Value {
        serde_json::json!({
            "serviceId": "mcp",
            "mcpProtocolVersion": MCP_PROTOCOL_VERSION,
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "serverInfo": {
                "name": "txing-unit-daemon",
                "version": DAEMON_VERSION,
            },
            "serverVersion": DAEMON_VERSION,
            "control": {
                "mode": "active",
                "activeTtlMs": DEFAULT_MCP_ACTIVE_TTL_MS,
            },
            "transport": "mqtt-jsonrpc",
            "descriptorTopic": build_mcp_descriptor_topic(thing_name).unwrap_or_default(),
            "statusTopic": build_mcp_status_topic(thing_name).unwrap_or_default(),
            "transports": [{
                "type": "mqtt-jsonrpc",
                "priority": 100,
                "topicRoot": build_mcp_topic_root(thing_name).unwrap_or_default(),
                "sessionTopicPattern": {
                    "clientToServer": format!("txings/{thing_name}/mcp/session/{{sessionId}}/c2s"),
                    "serverToClient": format!("txings/{thing_name}/mcp/session/{{sessionId}}/s2c"),
                },
            }],
        })
    }

    pub fn status(&self, now_ms: u64) -> Value {
        serde_json::json!({
            "serviceId": MCP_CAPABILITY,
            "available": true,
            "status": "ready",
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "observedAtMs": now_ms,
            "activeControl": self.active,
        })
    }

    fn clear_expired(&mut self, now_ms: u64) -> bool {
        if self
            .active
            .as_ref()
            .is_some_and(|active| active.expires_at_ms <= now_ms)
        {
            self.active = None;
            return true;
        }
        false
    }

    fn activate(
        &mut self,
        session_id: &str,
        actor: Option<String>,
        transport: &str,
        takeover: bool,
        now_ms: u64,
    ) -> Result<(ActiveControlState, bool)> {
        let mut stop_required = self.clear_expired(now_ms);
        if let Some(active) = &self.active {
            if active.session_id != session_id {
                if !takeover {
                    bail!("active control busy");
                }
                stop_required = true;
            } else {
                return Ok((active.clone(), stop_required));
            }
        }
        self.next_epoch = self.next_epoch.saturating_add(1);
        let active = ActiveControlState {
            session_id: session_id.to_string(),
            actor,
            transport: transport.to_string(),
            since_ms: now_ms,
            expires_at_ms: now_ms.saturating_add(duration_millis(self.active_ttl)),
            epoch: self.next_epoch,
        };
        self.active = Some(active.clone());
        Ok((active, stop_required))
    }

    fn clear_active(&mut self) -> bool {
        if self.active.is_none() {
            return false;
        }
        self.active = None;
        true
    }

    fn close_session(&mut self, session_id: &str) -> bool {
        if self
            .active
            .as_ref()
            .is_some_and(|active| active.session_id == session_id)
        {
            return self.clear_active();
        }
        false
    }

    fn renew_active(
        &mut self,
        session_id: &str,
        epoch: u64,
        now_ms: u64,
    ) -> Result<ActiveControlState> {
        self.ensure_active(session_id, epoch, now_ms)?;
        let active = self.active.as_mut().expect("active checked");
        active.expires_at_ms = now_ms.saturating_add(duration_millis(self.active_ttl));
        Ok(active.clone())
    }

    fn release_active(&mut self, session_id: &str, epoch: u64, now_ms: u64) -> Result<bool> {
        self.ensure_active(session_id, epoch, now_ms)?;
        self.active = None;
        Ok(true)
    }

    fn ensure_active(
        &mut self,
        session_id: &str,
        epoch: u64,
        now_ms: u64,
    ) -> Result<ActiveControlState> {
        self.clear_expired(now_ms);
        let Some(active) = &self.active else {
            bail!("no active control");
        };
        if active.session_id != session_id {
            bail!("no active control");
        }
        if active.epoch != epoch {
            bail!("stale active control epoch");
        }
        Ok(active.clone())
    }

    pub fn robot_state(
        &self,
        caller_session_id: &str,
        motion: DriveState,
        video: RobotVideoReport,
    ) -> RobotStateReport {
        let active = self.active.clone();
        RobotStateReport {
            control: RobotControlReport {
                active_required: true,
                active_ttl_ms: duration_millis(self.active_ttl),
                active_held_by_caller: active
                    .as_ref()
                    .is_some_and(|state| state.session_id == caller_session_id),
                active_owner_session_id: active.as_ref().map(|state| state.session_id.clone()),
                active_expires_at_ms: active.as_ref().map(|state| state.expires_at_ms),
                active_epoch: active.as_ref().map(|state| state.epoch),
                active_control: active,
            },
            motion,
            video,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum McpTransportMode {
    Mqtt,
    WebRtcDataChannel,
}

impl McpTransportMode {
    fn name(self) -> &'static str {
        match self {
            Self::Mqtt => "mqtt-jsonrpc",
            Self::WebRtcDataChannel => "webrtc-datachannel",
        }
    }
}

struct McpJsonRpcHandleResult {
    response: Option<Value>,
    updates_status: bool,
}

pub struct RuntimeState {
    config: RuntimeConfig,
    capability_manager: CapabilityManager,
    mcp: McpServer,
    cmd_vel: CmdVelController,
    video: VideoRuntimeState,
}

impl RuntimeState {
    pub fn new(config: RuntimeConfig) -> Result<Self> {
        Self::new_with_hardware(config, None)
    }

    pub fn new_with_hardware(
        config: RuntimeConfig,
        hardware_client: Option<Box<dyn HardwareClient>>,
    ) -> Result<Self> {
        let capability_manager = CapabilityManager::new(&config.capabilities)?;
        let cmd_vel = match hardware_client {
            Some(client) => CmdVelController::new(client),
            None => CmdVelController::from_config(&config),
        };
        Ok(Self {
            config,
            capability_manager,
            mcp: McpServer::new(Duration::from_millis(DEFAULT_MCP_ACTIVE_TTL_MS)),
            cmd_vel,
            video: VideoRuntimeState::starting(0),
        })
    }

    pub async fn publish_online<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        addresses: DefaultRouteAddresses,
        observed_at_ms: u64,
    ) -> Result<()> {
        info!(
            thing_id = %self.config.thing_id,
            capabilities = ?self.config.capabilities,
            "publishing online state"
        );
        self.publish_board_shadow(publisher, build_online_board_report(addresses))
            .await?;
        self.publish_mcp_discovery(publisher, observed_at_ms)
            .await?;
        if self.video_enabled() {
            self.video = VideoRuntimeState::starting(observed_at_ms);
            self.publish_video_discovery(publisher).await?;
            self.publish_video_status_and_shadow(publisher).await?;
        }
        self.publish_capabilities(publisher, self.online_capabilities(), observed_at_ms)
            .await?;
        info!(thing_id = %self.config.thing_id, "online state published");
        Ok(())
    }

    pub async fn refresh_capabilities<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        observed_at_ms: u64,
    ) -> Result<()> {
        debug!(thing_id = %self.config.thing_id, "refreshing capability state");
        self.publish_mcp_status(publisher, observed_at_ms).await?;
        self.publish_capabilities(publisher, self.online_capabilities(), observed_at_ms)
            .await
    }

    pub async fn refresh_video_status<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        observed_at_ms: u64,
    ) -> Result<()> {
        if self.video_enabled() {
            self.video.updated_at_ms = observed_at_ms;
            self.publish_video_status_and_shadow(publisher).await?;
        }
        Ok(())
    }

    pub async fn publish_offline<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        observed_at_ms: u64,
    ) -> Result<()> {
        info!(thing_id = %self.config.thing_id, "publishing offline state");
        let _ = self.cmd_vel.stop(true).await;
        self.publish_board_shadow(publisher, build_offline_board_report())
            .await?;
        self.publish_mcp_unavailable(publisher, observed_at_ms)
            .await?;
        if self.video_enabled() {
            self.video = VideoRuntimeState::unavailable(observed_at_ms);
            self.publish_video_status_and_shadow(publisher).await?;
        }
        self.publish_capabilities(publisher, self.offline_capabilities(), observed_at_ms)
            .await?;
        info!(thing_id = %self.config.thing_id, "offline state published");
        Ok(())
    }

    pub fn capability_seq(&self) -> u64 {
        self.capability_manager.seq()
    }

    async fn publish_capabilities<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        availability: BTreeMap<String, bool>,
        observed_at_ms: u64,
    ) -> Result<()> {
        self.capability_manager
            .publish_state(
                publisher,
                &self.config.thing_id,
                &availability,
                self.config.capability_ttl,
                observed_at_ms,
            )
            .await
    }

    fn online_capabilities(&self) -> BTreeMap<String, bool> {
        BTreeMap::from([
            (BOARD_CAPABILITY.to_string(), true),
            (MCP_CAPABILITY.to_string(), true),
            (VIDEO_CAPABILITY.to_string(), self.video.ready),
        ])
    }

    fn offline_capabilities(&self) -> BTreeMap<String, bool> {
        BTreeMap::from([
            (BOARD_CAPABILITY.to_string(), false),
            (MCP_CAPABILITY.to_string(), false),
            (VIDEO_CAPABILITY.to_string(), false),
        ])
    }

    pub async fn tick_watchdogs<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        observed_at_ms: u64,
    ) -> Result<()> {
        let changed = self.mcp.clear_expired(observed_at_ms);
        if changed {
            let _ = self.cmd_vel.stop(true).await;
        }
        let motion_changed = self.cmd_vel.refresh_status().await.unwrap_or(false);
        if changed || motion_changed {
            self.publish_mcp_status(publisher, observed_at_ms).await?;
        }
        Ok(())
    }

    pub async fn handle_mqtt_event<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        event: RuntimeMqttEvent,
        observed_at_ms: u64,
    ) -> Result<()> {
        match event {
            RuntimeMqttEvent::Publish { topic, payload } => {
                self.handle_mcp_publish(publisher, &topic, &payload, observed_at_ms)
                    .await
            }
            RuntimeMqttEvent::Disconnected => {
                self.mcp.active = None;
                let _ = self.cmd_vel.stop(true).await;
                Ok(())
            }
        }
    }

    pub async fn handle_video_event<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        event: VideoWorkerEvent,
        observed_at_ms: u64,
    ) -> Result<()> {
        if !self.video_enabled() {
            return Ok(());
        }
        let previous_transport = self.mcp_transport_mode();
        self.video.apply_event(event.clone(), observed_at_ms);
        let mcp_status_changed = match event {
            VideoWorkerEvent::McpDataChannelClosed { session_id, reason } => {
                info!(session_id = %session_id, reason = %reason, "MCP WebRTC data channel closed");
                let stop_required = self.mcp.close_session(&session_id);
                self.stop_if_required(stop_required).await
            }
            VideoWorkerEvent::McpDataChannelError { session_id, detail } => {
                warn!(session_id = ?session_id, error = %detail, "MCP WebRTC data channel error");
                if let Some(session_id) = session_id {
                    let stop_required = self.mcp.close_session(&session_id);
                    self.stop_if_required(stop_required).await
                } else {
                    false
                }
            }
            VideoWorkerEvent::McpDataChannelOpen { session_id } => {
                info!(session_id = %session_id, "MCP WebRTC data channel open");
                false
            }
            VideoWorkerEvent::Ready { worker_version } => {
                info!(
                    worker_version = worker_version.as_deref().unwrap_or("unknown"),
                    "native KVS worker ready"
                );
                false
            }
            _ => false,
        };
        let next_transport = self.mcp_transport_mode();
        if previous_transport != next_transport {
            let stop_required = self.mcp.clear_active();
            let _ = self.stop_if_required(stop_required).await;
            self.publish_mcp_discovery(publisher, observed_at_ms)
                .await?;
        }
        if mcp_status_changed {
            self.publish_mcp_status(publisher, observed_at_ms).await?;
        }
        self.publish_video_status_and_shadow(publisher).await?;
        self.publish_capabilities(publisher, self.online_capabilities(), observed_at_ms)
            .await
    }

    pub async fn handle_mcp_ipc_event<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        event: RuntimeMcpIpcEvent,
        observed_at_ms: u64,
    ) -> Result<()> {
        match event {
            RuntimeMcpIpcEvent::Open {
                session_id,
                transport,
                peer_id,
            } => {
                info!(
                    session_id = %session_id,
                    transport = %transport,
                    peer_id = peer_id.as_deref().unwrap_or(""),
                    "MCP bridge session opened"
                );
            }
            RuntimeMcpIpcEvent::Request {
                session_id,
                payload,
                response_tx,
            } => {
                let mut updates_status = false;
                let response = match serde_json::from_str::<Value>(&payload) {
                    Ok(request) => {
                        let request_id = request.get("id").cloned();
                        match self
                            .handle_mcp_json_rpc_request(&session_id, request, observed_at_ms)
                            .await
                        {
                            Ok(result) => {
                                updates_status = result.updates_status;
                                result
                                    .response
                                    .map(|payload| serde_json::to_string(&payload))
                                    .transpose()?
                            }
                            Err(err) => Some(serde_json::to_string(&json_rpc_error_response(
                                request_id,
                                json_rpc_error(-32603, &format!("internal error: {err}")),
                            ))?),
                        }
                    }
                    Err(err) => Some(serde_json::to_string(&json_rpc_error_response(
                        None,
                        json_rpc_error(-32700, &format!("parse error: {err}")),
                    ))?),
                };
                let _ = response_tx.send(response);
                if updates_status
                    && let Err(err) = self.publish_mcp_status(publisher, observed_at_ms).await
                {
                    warn!(
                        session_id = %session_id,
                        error = %format_args!("{err:#}"),
                        "failed to publish MCP status after IPC response"
                    );
                }
            }
            RuntimeMcpIpcEvent::Close { session_id, reason } => {
                info!(session_id = %session_id, reason = %reason, "MCP WebRTC IPC session closed");
                let stop_required = self.mcp.close_session(&session_id);
                if self.stop_if_required(stop_required).await {
                    self.publish_mcp_status(publisher, observed_at_ms).await?;
                }
            }
        }
        Ok(())
    }

    fn video_enabled(&self) -> bool {
        self.config
            .capabilities
            .iter()
            .any(|capability| capability == VIDEO_CAPABILITY)
    }

    async fn stop_if_required(&mut self, required: bool) -> bool {
        if required {
            if let Err(err) = self.cmd_vel.stop(true).await {
                warn!(
                    error = %format_args!("{err:#}"),
                    "failed to stop hardware worker during control cleanup"
                );
            }
        }
        required
    }

    fn mcp_transport_mode(&self) -> McpTransportMode {
        if self.video_enabled() && self.video.ready {
            McpTransportMode::WebRtcDataChannel
        } else {
            McpTransportMode::Mqtt
        }
    }

    fn mcp_descriptor(&self) -> Value {
        let transport_mode = self.mcp_transport_mode();
        let topic_root = build_mcp_topic_root(&self.config.thing_id).unwrap_or_default();
        let session_topic_pattern = serde_json::json!({
            "clientToServer": format!("txings/{}/mcp/session/{{sessionId}}/c2s", self.config.thing_id),
            "serverToClient": format!("txings/{}/mcp/session/{{sessionId}}/s2c", self.config.thing_id),
        });
        let transports = match transport_mode {
            McpTransportMode::Mqtt => serde_json::json!([{
                "type": "mqtt-jsonrpc",
                "priority": 100,
                "topicRoot": topic_root,
                "sessionTopicPattern": session_topic_pattern,
            }]),
            McpTransportMode::WebRtcDataChannel => serde_json::json!([{
                "type": "webrtc-datachannel",
                "priority": 10,
                "sessionKind": "media",
                "signaling": "aws-kvs",
                "channelName": self.config.video_channel_name,
                "region": self.config.video_region,
                "label": "txing.mcp.v1",
            }]),
        };
        serde_json::json!({
            "serviceId": "mcp",
            "mcpProtocolVersion": MCP_PROTOCOL_VERSION,
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "serverInfo": {
                "name": "txing-unit-daemon",
                "version": DAEMON_VERSION,
            },
            "serverVersion": DAEMON_VERSION,
            "control": {
                "mode": "active",
                "activeTtlMs": DEFAULT_MCP_ACTIVE_TTL_MS,
            },
            "transport": transport_mode.name(),
            "descriptorTopic": build_mcp_descriptor_topic(&self.config.thing_id).unwrap_or_default(),
            "statusTopic": build_mcp_status_topic(&self.config.thing_id).unwrap_or_default(),
            "transports": transports,
        })
    }

    async fn publish_mcp_discovery<P: Publisher + ?Sized>(
        &self,
        publisher: &P,
        observed_at_ms: u64,
    ) -> Result<()> {
        let descriptor = self.mcp_descriptor();
        let status = self.mcp.status(observed_at_ms);
        publisher
            .publish(PublishedMessage {
                topic: build_mcp_descriptor_topic(&self.config.thing_id)?,
                payload: serde_json::to_vec(&descriptor)?,
                retain: true,
            })
            .await?;
        publisher
            .publish(PublishedMessage {
                topic: build_mcp_status_topic(&self.config.thing_id)?,
                payload: serde_json::to_vec(&status)?,
                retain: true,
            })
            .await?;
        self.publish_mcp_shadow(publisher, descriptor, status).await
    }

    async fn publish_mcp_status<P: Publisher + ?Sized>(
        &self,
        publisher: &P,
        observed_at_ms: u64,
    ) -> Result<()> {
        let status = self.mcp.status(observed_at_ms);
        publisher
            .publish(PublishedMessage {
                topic: build_mcp_status_topic(&self.config.thing_id)?,
                payload: serde_json::to_vec(&status)?,
                retain: true,
            })
            .await?;
        self.publish_mcp_shadow(publisher, self.mcp_descriptor(), status)
            .await
    }

    async fn publish_mcp_unavailable<P: Publisher + ?Sized>(
        &self,
        publisher: &P,
        observed_at_ms: u64,
    ) -> Result<()> {
        let descriptor = self.mcp_descriptor();
        let status = serde_json::json!({
            "serviceId": MCP_CAPABILITY,
            "available": false,
            "status": "offline",
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "observedAtMs": observed_at_ms,
            "activeControl": null,
        });
        publisher
            .publish(PublishedMessage {
                topic: build_mcp_status_topic(&self.config.thing_id)?,
                payload: serde_json::to_vec(&status)?,
                retain: true,
            })
            .await?;
        self.publish_mcp_shadow(publisher, descriptor, status).await
    }

    async fn publish_mcp_shadow<P: Publisher + ?Sized>(
        &self,
        publisher: &P,
        descriptor: Value,
        status: Value,
    ) -> Result<()> {
        let payload = serde_json::json!({
            "state": {
                "reported": {
                    "descriptor": descriptor,
                    "status": status,
                }
            }
        });
        publisher
            .publish(PublishedMessage {
                topic: build_mcp_shadow_update_topic(&self.config.thing_id)?,
                payload: serde_json::to_vec(&payload)?,
                retain: false,
            })
            .await
    }

    async fn publish_video_discovery<P: Publisher + ?Sized>(&self, publisher: &P) -> Result<()> {
        let descriptor = self.video_descriptor();
        publisher
            .publish(PublishedMessage {
                topic: build_video_descriptor_topic(&self.config.thing_id)?,
                payload: serde_json::to_vec(&descriptor)?,
                retain: true,
            })
            .await
    }

    async fn publish_video_status_and_shadow<P: Publisher + ?Sized>(
        &self,
        publisher: &P,
    ) -> Result<()> {
        let descriptor = self.video_descriptor();
        let status = self.video_status();
        publisher
            .publish(PublishedMessage {
                topic: build_video_status_topic(&self.config.thing_id)?,
                payload: serde_json::to_vec(&status)?,
                retain: true,
            })
            .await?;
        self.publish_video_shadow(publisher, descriptor, status)
            .await
    }

    async fn publish_video_shadow<P: Publisher + ?Sized>(
        &self,
        publisher: &P,
        descriptor: Value,
        status: Value,
    ) -> Result<()> {
        let payload = serde_json::json!({
            "state": {
                "reported": {
                    "descriptor": descriptor,
                    "status": status,
                }
            }
        });
        publisher
            .publish(PublishedMessage {
                topic: build_video_shadow_update_topic(&self.config.thing_id)?,
                payload: serde_json::to_vec(&payload)?,
                retain: false,
            })
            .await
    }

    fn video_descriptor(&self) -> Value {
        serde_json::json!({
            "serviceId": VIDEO_CAPABILITY,
            "serverInfo": {
                "name": VIDEO_CAPABILITY,
                "version": DAEMON_VERSION,
            },
            "topicRoot": build_video_topic_root(&self.config.thing_id).unwrap_or_default(),
            "descriptorTopic": build_video_descriptor_topic(&self.config.thing_id).unwrap_or_default(),
            "statusTopic": build_video_status_topic(&self.config.thing_id).unwrap_or_default(),
            "transport": DEFAULT_VIDEO_TRANSPORT,
            "channelName": self.config.video_channel_name,
            "region": self.config.video_region,
            "codec": {
                "video": DEFAULT_VIDEO_CODEC,
            },
            "serverVersion": DAEMON_VERSION,
        })
    }

    fn video_status(&self) -> Value {
        serde_json::json!({
            "serviceId": VIDEO_CAPABILITY,
            "available": self.video.available,
            "ready": self.video.ready,
            "status": self.video.status,
            "viewerConnected": self.video.viewer_connected,
            "lastError": self.video.last_error,
            "updatedAtMs": self.video.updated_at_ms,
        })
    }

    async fn handle_mcp_publish<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        topic: &str,
        payload: &[u8],
        observed_at_ms: u64,
    ) -> Result<()> {
        let Some(session_id) = parse_mcp_session_c2s_topic(&self.config.thing_id, topic) else {
            return Ok(());
        };
        let request: Value =
            serde_json::from_slice(payload).context("parse MCP JSON-RPC request")?;
        if self.mcp_transport_mode() == McpTransportMode::WebRtcDataChannel {
            let response = json_rpc_error_response(
                request.get("id").cloned(),
                json_rpc_error(
                    -32000,
                    "MCP is available only over WebRTC data channel while video is ready",
                ),
            );
            return self
                .publish_mcp_response(publisher, &session_id, response)
                .await;
        }
        let result = self
            .handle_mcp_json_rpc_request(&session_id, request, observed_at_ms)
            .await?;
        if let Some(payload) = result.response {
            self.publish_mcp_response(publisher, &session_id, payload)
                .await?;
        }
        if result.updates_status {
            self.publish_mcp_status(publisher, observed_at_ms).await?;
        }
        Ok(())
    }

    async fn handle_mcp_json_rpc_request(
        &mut self,
        session_id: &str,
        request: Value,
        observed_at_ms: u64,
    ) -> Result<McpJsonRpcHandleResult> {
        let Some(method) = request.get("method").and_then(Value::as_str) else {
            return Ok(McpJsonRpcHandleResult {
                response: Some(json_rpc_error_response(
                    request.get("id").cloned(),
                    json_rpc_error(-32600, "invalid request"),
                )),
                updates_status: false,
            });
        };
        let id = request.get("id").cloned();
        if id.is_none() {
            return Ok(McpJsonRpcHandleResult {
                response: None,
                updates_status: false,
            });
        }
        let response = match method {
            "initialize" => Ok(serde_json::json!({
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "serverInfo": {"name": "txing-unit-daemon", "version": DAEMON_VERSION},
                "capabilities": {"tools": {}},
            })),
            "tools/list" => Ok(serde_json::json!({
                "tools": [
                    {"name": "control.get_state"},
                    {"name": "control.activate"},
                    {"name": "control.renew_active"},
                    {"name": "control.release_active"},
                    {"name": "cmd_vel.publish"},
                    {"name": "cmd_vel.stop"},
                    {"name": "robot.get_state"},
                ]
            })),
            "tools/call" => {
                self.handle_mcp_tool_call(&session_id, request.get("params"), observed_at_ms)
                    .await
            }
            _ => Err(json_rpc_error(-32601, "method not found")),
        };
        let payload = match response {
            Ok(result) => json_rpc_success(id, result),
            Err(error) => json_rpc_error_response(id, error),
        };
        Ok(McpJsonRpcHandleResult {
            response: Some(payload),
            updates_status: mcp_request_updates_status(method, request.get("params")),
        })
    }

    async fn handle_mcp_tool_call(
        &mut self,
        session_id: &str,
        params: Option<&Value>,
        observed_at_ms: u64,
    ) -> std::result::Result<Value, Value> {
        let params = params.and_then(Value::as_object);
        let Some(name) = params
            .and_then(|params| params.get("name"))
            .and_then(Value::as_str)
        else {
            return Err(json_rpc_error(
                -32602,
                "MCP tools/call requires a tool name",
            ));
        };
        let arguments = params
            .and_then(|params| params.get("arguments"))
            .cloned()
            .unwrap_or_else(|| serde_json::json!({}));
        let structured = self
            .handle_mcp_tool(session_id, name, &arguments, observed_at_ms)
            .await
            .map_err(|err| tool_error_to_json_rpc_error(name, &err))?;
        Ok(serde_json::json!({
            "structuredContent": structured,
            "content": [{"type": "json", "json": structured}],
        }))
    }

    async fn handle_mcp_tool(
        &mut self,
        session_id: &str,
        name: &str,
        arguments: &Value,
        observed_at_ms: u64,
    ) -> Result<Value> {
        match name {
            "control.get_state" => {
                let state = self
                    .mcp
                    .robot_state(
                        session_id,
                        self.cmd_vel.drive_state(),
                        self.video.robot_report(),
                    )
                    .control;
                serde_json::to_value(state).context("serialize control state")
            }
            "control.activate" => {
                let actor = arguments
                    .get("actor")
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|value| !value.is_empty())
                    .map(ToOwned::to_owned);
                let takeover = arguments
                    .get("takeover")
                    .and_then(Value::as_bool)
                    .unwrap_or(false);
                let (active, stop_required) = self.mcp.activate(
                    session_id,
                    actor,
                    self.mcp_transport_mode().name(),
                    takeover,
                    observed_at_ms,
                )?;
                self.stop_if_required(stop_required).await;
                Ok(serde_json::json!({
                    "activeControl": active,
                    "activeTtlMs": DEFAULT_MCP_ACTIVE_TTL_MS,
                }))
            }
            "control.renew_active" => {
                let epoch = parse_epoch_argument(arguments)?;
                let active = self.mcp.renew_active(session_id, epoch, observed_at_ms)?;
                Ok(serde_json::json!({
                    "activeControl": active,
                    "activeTtlMs": DEFAULT_MCP_ACTIVE_TTL_MS,
                }))
            }
            "control.release_active" => {
                let epoch = parse_epoch_argument(arguments)?;
                let stop_required = self.mcp.release_active(session_id, epoch, observed_at_ms)?;
                self.stop_if_required(stop_required).await;
                let motion = self.cmd_vel.drive_state();
                Ok(serde_json::json!({ "motion": motion }))
            }
            "cmd_vel.publish" => {
                let epoch = parse_epoch_argument(arguments)?;
                let active = self.mcp.ensure_active(session_id, epoch, observed_at_ms)?;
                let twist_value = arguments
                    .get("twist")
                    .ok_or_else(|| anyhow!("cmd_vel.publish requires twist"))?;
                let twist: Twist =
                    serde_json::from_value(twist_value.clone()).context("parse cmd_vel twist")?;
                let motion = self
                    .cmd_vel
                    .publish_twist(twist, active.expires_at_ms)
                    .await?;
                let state =
                    self.mcp
                        .robot_state(session_id, motion.clone(), self.video.robot_report());
                Ok(serde_json::json!({
                    "motion": motion,
                    "activeControl": state.control.active_control,
                    "activeExpiresAtMs": state.control.active_expires_at_ms,
                }))
            }
            "cmd_vel.stop" => {
                let epoch = parse_epoch_argument(arguments)?;
                self.mcp.ensure_active(session_id, epoch, observed_at_ms)?;
                let motion = self.cmd_vel.stop(true).await?;
                let state =
                    self.mcp
                        .robot_state(session_id, motion.clone(), self.video.robot_report());
                Ok(serde_json::json!({
                    "motion": motion,
                    "activeControl": state.control.active_control,
                    "activeExpiresAtMs": state.control.active_expires_at_ms,
                }))
            }
            "robot.get_state" => {
                let _ = self.cmd_vel.refresh_status().await;
                let state = self.mcp.robot_state(
                    session_id,
                    self.cmd_vel.drive_state(),
                    self.video.robot_report(),
                );
                serde_json::to_value(state).context("serialize robot state")
            }
            _ => bail!("unknown MCP tool {name}"),
        }
    }

    async fn publish_mcp_response<P: Publisher + ?Sized>(
        &self,
        publisher: &P,
        session_id: &str,
        payload: Value,
    ) -> Result<()> {
        publisher
            .publish(PublishedMessage {
                topic: build_mcp_session_s2c_topic(&self.config.thing_id, session_id)?,
                payload: serde_json::to_vec(&payload)?,
                retain: false,
            })
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

fn mcp_request_updates_status(method: &str, params: Option<&Value>) -> bool {
    if method != "tools/call" {
        return false;
    }
    let Some(tool_name) = params
        .and_then(Value::as_object)
        .and_then(|params| params.get("name"))
        .and_then(Value::as_str)
    else {
        return false;
    };
    matches!(
        tool_name,
        "control.activate" | "control.renew_active" | "control.release_active"
    )
}

fn parse_epoch_argument(arguments: &Value) -> Result<u64> {
    arguments
        .get("epoch")
        .and_then(Value::as_u64)
        .ok_or_else(|| anyhow!("active control epoch is required"))
}

fn tool_error_to_json_rpc_error(_tool_name: &str, err: &anyhow::Error) -> Value {
    let message = err.to_string();
    let code = if message.contains("no active control") {
        -32011
    } else if message.contains("active control busy") {
        -32012
    } else if message.contains("stale active control epoch") {
        -32013
    } else {
        -32602
    };
    json_rpc_error(code, &message)
}

fn json_rpc_success(id: Option<Value>, result: Value) -> Value {
    serde_json::json!({
        "jsonrpc": "2.0",
        "id": id.unwrap_or(Value::Null),
        "result": result,
    })
}

fn json_rpc_error_response(id: Option<Value>, error: Value) -> Value {
    let mut response = serde_json::json!({
        "jsonrpc": "2.0",
        "id": id.unwrap_or(Value::Null),
    });
    response["error"] = error;
    response
}

fn json_rpc_error(code: i64, message: &str) -> Value {
    serde_json::json!({
        "code": code,
        "message": message,
    })
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VideoWorkerEvent {
    Starting,
    Ready {
        worker_version: Option<String>,
    },
    ViewerConnected {
        connected: bool,
    },
    McpDataChannelOpen {
        session_id: String,
    },
    McpDataChannelClosed {
        session_id: String,
        reason: String,
    },
    McpDataChannelError {
        session_id: Option<String>,
        detail: String,
    },
    Error {
        detail: String,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VideoWorkerMarker {
    Ready {
        worker_version: Option<String>,
    },
    ViewerConnected,
    ViewerDisconnected,
    McpDataChannelOpen {
        session_id: String,
    },
    McpDataChannelClosed {
        session_id: String,
        reason: String,
    },
    McpDataChannelError {
        session_id: Option<String>,
        detail: String,
    },
    Error {
        detail: String,
    },
}

pub fn parse_video_worker_marker(line: &str) -> Option<VideoWorkerMarker> {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return None;
    }
    let (marker, rest) = trimmed
        .split_once(char::is_whitespace)
        .map_or((trimmed, ""), |(marker, rest)| (marker, rest.trim()));
    match marker {
        "TXING_KVS_READY" => Some(VideoWorkerMarker::Ready {
            worker_version: parse_marker_field(rest, "version"),
        }),
        "TXING_VIEWER_CONNECTED" => Some(VideoWorkerMarker::ViewerConnected),
        "TXING_VIEWER_DISCONNECTED" => Some(VideoWorkerMarker::ViewerDisconnected),
        "TXING_MCP_DATACHANNEL_OPEN" => Some(VideoWorkerMarker::McpDataChannelOpen {
            session_id: parse_marker_field(rest, "sessionId").unwrap_or_default(),
        }),
        "TXING_MCP_DATACHANNEL_CLOSED" => Some(VideoWorkerMarker::McpDataChannelClosed {
            session_id: parse_marker_field(rest, "sessionId").unwrap_or_default(),
            reason: parse_marker_field(rest, "reason")
                .unwrap_or_else(|| "MCP WebRTC data channel closed".to_string()),
        }),
        "TXING_MCP_DATACHANNEL_ERROR" => Some(VideoWorkerMarker::McpDataChannelError {
            session_id: parse_marker_field(rest, "sessionId"),
            detail: parse_marker_field(rest, "detail")
                .unwrap_or_else(|| "MCP WebRTC data channel error".to_string()),
        }),
        "TXING_KVS_ERROR" => Some(VideoWorkerMarker::Error {
            detail: parse_marker_field(rest, "detail")
                .unwrap_or_else(|| "native KVS worker reported an error".to_string()),
        }),
        _ => None,
    }
}

fn parse_marker_field(fields: &str, key: &str) -> Option<String> {
    let prefix = format!("{key}=");
    if let Some(value) = fields.strip_prefix(&prefix) {
        if matches!(key, "detail" | "reason") {
            return Some(value.to_string());
        }
        return value.split_whitespace().next().map(str::to_string);
    }
    fields
        .split_whitespace()
        .find_map(|field| field.strip_prefix(&prefix))
        .map(str::to_string)
}

#[allow(dead_code)]
struct VideoSupervisorHandle {
    stop: Arc<AtomicBool>,
    task: JoinHandle<()>,
}

#[allow(dead_code)]
impl VideoSupervisorHandle {
    async fn shutdown(self) {
        self.stop.store(true, Ordering::SeqCst);
        let mut task = self.task;
        tokio::select! {
            join_result = &mut task => {
                if let Err(err) = join_result {
                    warn!(error = %err, "video supervisor task failed during shutdown");
                }
            }
            _ = tokio::time::sleep(Duration::from_secs(5)) => {
                task.abort();
                warn!("video supervisor did not stop within timeout; aborting task");
            }
        }
    }
}

#[allow(dead_code)]
fn start_video_supervisor(
    config: RuntimeConfig,
    event_tx: mpsc::UnboundedSender<VideoWorkerEvent>,
) -> VideoSupervisorHandle {
    let stop = Arc::new(AtomicBool::new(false));
    let task_stop = stop.clone();
    let task = tokio::spawn(async move {
        run_video_supervisor(config, event_tx, task_stop).await;
    });
    VideoSupervisorHandle { stop, task }
}

#[allow(dead_code)]
async fn run_video_supervisor(
    config: RuntimeConfig,
    event_tx: mpsc::UnboundedSender<VideoWorkerEvent>,
    stop: Arc<AtomicBool>,
) {
    let mut backoff = VideoRestartBackoff::default();
    while !stop.load(Ordering::SeqCst) {
        let _ = event_tx.send(VideoWorkerEvent::Starting);
        let credentials = match fetch_iot_temporary_credentials(&config).await {
            Ok(credentials) => credentials,
            Err(err) => {
                let detail = format!("resolve KVS worker credentials: {err:#}");
                warn!(error = %detail, "video worker credential resolution failed");
                let _ = event_tx.send(VideoWorkerEvent::Error { detail });
                sleep_until_stop(stop.clone(), backoff.next_delay()).await;
                continue;
            }
        };
        let expires_at = match parse_iot_temporary_credentials_expiration(&credentials.expiration) {
            Ok(expires_at) => expires_at,
            Err(err) => {
                let detail = format!("parse KVS worker credential expiration: {err:#}");
                warn!(error = %detail, "video worker credential expiration invalid");
                let _ = event_tx.send(VideoWorkerEvent::Error { detail });
                sleep_until_stop(stop.clone(), backoff.next_delay()).await;
                continue;
            }
        };
        let worker = VideoWorkerRunConfig {
            command: config.kvs_master_command.clone(),
            mcp_webrtc_socket_path: config.mcp_webrtc_socket_path.clone(),
            kvs_prefer_ipv6: config.kvs_prefer_ipv6,
            kvs_disable_ipv4_turn: config.kvs_disable_ipv4_turn,
            region: config.video_region.clone(),
            channel_name: config.video_channel_name.clone(),
            credentials,
            expires_at,
            stop: stop.clone(),
            event_tx: event_tx.clone(),
        };
        let result =
            match tokio::task::spawn_blocking(move || run_video_worker_blocking(worker)).await {
                Ok(result) => result,
                Err(err) => {
                    let detail = format!("join KVS worker supervisor: {err}");
                    let _ = event_tx.send(VideoWorkerEvent::Error {
                        detail: detail.clone(),
                    });
                    VideoWorkerRunResult::Failed(detail)
                }
            };
        if stop.load(Ordering::SeqCst) {
            break;
        }
        match result {
            VideoWorkerRunResult::CredentialRefresh => {
                backoff.reset();
            }
            VideoWorkerRunResult::Stopped => break,
            VideoWorkerRunResult::Failed(detail) => {
                warn!(error = %detail, "video worker stopped unexpectedly");
                let _ = event_tx.send(VideoWorkerEvent::Error { detail });
                sleep_until_stop(stop.clone(), backoff.next_delay()).await;
            }
        }
    }
}

#[derive(Debug, Default)]
#[allow(dead_code)]
struct VideoRestartBackoff {
    next_seconds: u64,
}

#[allow(dead_code)]
impl VideoRestartBackoff {
    fn next_delay(&mut self) -> Duration {
        let delay = if self.next_seconds == 0 {
            VIDEO_RESTART_BACKOFF_INITIAL_SECONDS
        } else {
            self.next_seconds
        };
        self.next_seconds = delay
            .saturating_mul(2)
            .min(VIDEO_RESTART_BACKOFF_MAX_SECONDS);
        Duration::from_secs(delay)
    }

    fn reset(&mut self) {
        self.next_seconds = 0;
    }
}

#[allow(dead_code)]
async fn sleep_until_stop(stop: Arc<AtomicBool>, duration: Duration) {
    let deadline = Instant::now() + duration;
    while !stop.load(Ordering::SeqCst) {
        let now = Instant::now();
        if now >= deadline {
            break;
        }
        let remaining = deadline.saturating_duration_since(now);
        tokio::time::sleep(remaining.min(Duration::from_millis(200))).await;
    }
}

#[allow(dead_code)]
struct VideoWorkerRunConfig {
    command: String,
    mcp_webrtc_socket_path: String,
    kvs_prefer_ipv6: bool,
    kvs_disable_ipv4_turn: bool,
    region: String,
    channel_name: String,
    credentials: IotTemporaryCredentials,
    expires_at: SystemTime,
    stop: Arc<AtomicBool>,
    event_tx: mpsc::UnboundedSender<VideoWorkerEvent>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
#[allow(dead_code)]
enum VideoWorkerRunResult {
    CredentialRefresh,
    Failed(String),
    Stopped,
}

#[allow(dead_code)]
fn run_video_worker_blocking(config: VideoWorkerRunConfig) -> VideoWorkerRunResult {
    let restart_at = video_credential_restart_at(config.expires_at, SystemTime::now());
    let mut command = std::process::Command::new(&config.command);
    configure_video_worker_command(&mut command, &config);

    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(err) => {
            return VideoWorkerRunResult::Failed(format!(
                "spawn KVS worker command {:?}: {err}",
                config.command
            ));
        }
    };
    info!(
        command = %config.command,
        channel_name = %config.channel_name,
        region = %config.region,
        pid = child.id(),
        "native KVS worker started"
    );

    let mut readers = Vec::new();
    if let Some(stdout) = child.stdout.take() {
        readers.push(spawn_video_marker_reader(
            "stdout",
            stdout,
            config.event_tx.clone(),
        ));
    }
    if let Some(stderr) = child.stderr.take() {
        readers.push(spawn_video_marker_reader(
            "stderr",
            stderr,
            config.event_tx.clone(),
        ));
    }

    loop {
        if config.stop.load(Ordering::SeqCst) {
            terminate_video_child(&mut child);
            join_video_marker_readers(readers);
            return VideoWorkerRunResult::Stopped;
        }
        match child.try_wait() {
            Ok(Some(status)) => {
                join_video_marker_readers(readers);
                return VideoWorkerRunResult::Failed(format!(
                    "KVS worker exited with status {status}"
                ));
            }
            Ok(None) => {}
            Err(err) => {
                terminate_video_child(&mut child);
                join_video_marker_readers(readers);
                return VideoWorkerRunResult::Failed(format!("poll KVS worker status: {err}"));
            }
        }
        if SystemTime::now() >= restart_at {
            info!("restarting native KVS worker before IoT credentials expire");
            terminate_video_child(&mut child);
            join_video_marker_readers(readers);
            return VideoWorkerRunResult::CredentialRefresh;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
}

#[allow(dead_code)]
fn configure_video_worker_command(
    command: &mut std::process::Command,
    config: &VideoWorkerRunConfig,
) {
    command
        .env("BOARD_VIDEO_REGION", &config.region)
        .env("BOARD_VIDEO_CHANNEL_NAME", &config.channel_name)
        .env(
            "BOARD_MCP_WEBRTC_SOCKET_PATH",
            &config.mcp_webrtc_socket_path,
        )
        .env("AWS_ACCESS_KEY_ID", &config.credentials.access_key_id)
        .env(
            "AWS_SECRET_ACCESS_KEY",
            &config.credentials.secret_access_key,
        )
        .env_remove("AWS_PROFILE")
        .env_remove("AWS_DEFAULT_PROFILE")
        .env_remove("AWS_DEVICE_PROFILE")
        .env_remove("AWS_TXING_PROFILE")
        .env_remove("AWS_SHARED_CREDENTIALS_FILE")
        .env_remove("AWS_CONFIG_FILE")
        .env_remove("TXING_BOARD_MCP_WEBRTC_SOCKET_PATH")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if config.kvs_prefer_ipv6 {
        command
            .env("KVS_DUALSTACK_ENDPOINTS", "ON")
            .env("AWS_USE_DUALSTACK_ENDPOINT", "true");
    } else {
        command
            .env_remove("KVS_DUALSTACK_ENDPOINTS")
            .env_remove("AWS_USE_DUALSTACK_ENDPOINT");
    }
    if config.kvs_disable_ipv4_turn {
        command.env("KVS_DISABLE_IPV4_TURN", "ON");
    } else {
        command.env_remove("KVS_DISABLE_IPV4_TURN");
    }
    if config.credentials.session_token.trim().is_empty() {
        command.env_remove("AWS_SESSION_TOKEN");
    } else {
        command.env("AWS_SESSION_TOKEN", &config.credentials.session_token);
    }
}

#[allow(dead_code)]
fn video_credential_restart_at(expires_at: SystemTime, now: SystemTime) -> SystemTime {
    let margin = Duration::from_secs(VIDEO_CREDENTIAL_RESTART_MARGIN_SECONDS);
    let min_delay = Duration::from_secs(VIDEO_CREDENTIAL_RESTART_MIN_SECONDS);
    if expires_at
        .duration_since(now)
        .is_ok_and(|remaining| remaining > margin + min_delay)
    {
        expires_at - margin
    } else {
        now + min_delay
    }
}

#[allow(dead_code)]
fn spawn_video_marker_reader<R>(
    stream_name: &'static str,
    reader: R,
    event_tx: mpsc::UnboundedSender<VideoWorkerEvent>,
) -> std::thread::JoinHandle<()>
where
    R: Read + Send + 'static,
{
    std::thread::Builder::new()
        .name(format!("kvs-worker-{stream_name}"))
        .spawn(move || {
            let reader = BufReader::new(reader);
            for line in reader.lines() {
                let Ok(line) = line else {
                    break;
                };
                if line.trim().is_empty() {
                    continue;
                }
                if let Some(marker) = parse_video_worker_marker(&line) {
                    let event = match marker {
                        VideoWorkerMarker::Ready { worker_version } => {
                            VideoWorkerEvent::Ready { worker_version }
                        }
                        VideoWorkerMarker::ViewerConnected => {
                            VideoWorkerEvent::ViewerConnected { connected: true }
                        }
                        VideoWorkerMarker::ViewerDisconnected => {
                            VideoWorkerEvent::ViewerConnected { connected: false }
                        }
                        VideoWorkerMarker::McpDataChannelOpen { session_id } => {
                            VideoWorkerEvent::McpDataChannelOpen { session_id }
                        }
                        VideoWorkerMarker::McpDataChannelClosed { session_id, reason } => {
                            VideoWorkerEvent::McpDataChannelClosed { session_id, reason }
                        }
                        VideoWorkerMarker::McpDataChannelError { session_id, detail } => {
                            VideoWorkerEvent::McpDataChannelError { session_id, detail }
                        }
                        VideoWorkerMarker::Error { detail } => VideoWorkerEvent::Error { detail },
                    };
                    let _ = event_tx.send(event);
                } else {
                    log_video_worker_output_line(stream_name, &line);
                }
            }
        })
        .expect("spawn KVS worker marker reader")
}

#[allow(dead_code)]
fn log_video_worker_output_line(stream_name: &'static str, line: &str) {
    if video_worker_output_level(stream_name) == Level::WARN {
        warn!(stream = stream_name, line = %line, "native KVS worker output");
    } else {
        info!(stream = stream_name, line = %line, "native KVS worker output");
    }
}

#[allow(dead_code)]
fn video_worker_output_level(stream_name: &str) -> Level {
    if stream_name == "stderr" {
        Level::WARN
    } else {
        Level::INFO
    }
}

#[allow(dead_code)]
fn join_video_marker_readers(readers: Vec<std::thread::JoinHandle<()>>) {
    for reader in readers {
        let _ = reader.join();
    }
}

#[allow(dead_code)]
fn terminate_video_child(child: &mut std::process::Child) {
    if child.try_wait().ok().flatten().is_some() {
        return;
    }
    let _ = child.kill();
    let _ = child.wait();
}

pub async fn run_runtime(config: RuntimeConfig) -> Result<()> {
    info!(
        version = DAEMON_VERSION,
        thing_id = %config.thing_id,
        aws_region = %config.aws_region,
        iot_endpoint = %config.iot_endpoint,
        iot_credential_endpoint = %config.iot_credential_endpoint,
        iot_role_alias = %config.iot_role_alias,
        client_id = %config.client_id,
        capabilities = ?config.capabilities,
        "starting unit daemon"
    );
    let redcon = read_current_sparkplug_redcon(&config).await?;
    let sparkplug_redcon = match redcon {
        SparkplugRedcon::Level(level) => level.to_string(),
        SparkplugRedcon::Unavailable => "unavailable".to_string(),
    };
    info!(
        thing_id = %config.thing_id,
        sparkplug_redcon = %sparkplug_redcon,
        "read sparkplug shadow"
    );
    let (publisher, incoming_events) = MqttPublisher::connect(&config).await?;
    let run_result = run_connected_runtime(config, &publisher, incoming_events).await;
    let stop_result = publisher.stop();
    if stop_result.is_ok() {
        info!("mqtt client stopped");
    }
    run_result.and(stop_result)
}

async fn run_connected_runtime(
    config: RuntimeConfig,
    publisher: &MqttPublisher,
    mut incoming_events: mpsc::UnboundedReceiver<RuntimeMqttEvent>,
) -> Result<()> {
    let mut state = RuntimeState::new(config.clone())?;
    let (video_event_tx, mut video_events) = mpsc::unbounded_channel();
    let video_enabled = config
        .capabilities
        .iter()
        .any(|capability| capability == VIDEO_CAPABILITY);
    let (mcp_ipc_event_tx, mut mcp_ipc_events) = mpsc::unbounded_channel();
    let board_video_bridge_server = if video_enabled {
        Some(start_board_video_bridge_server(
            config.clone(),
            video_event_tx,
            mcp_ipc_event_tx,
        )?)
    } else {
        None
    };
    publisher
        .subscribe(build_mcp_session_c2s_subscription(&config.thing_id)?)
        .await?;
    state
        .publish_online(publisher, discover_default_route_addresses(), now_ms())
        .await?;

    let mut heartbeat = interval_at(Instant::now() + config.heartbeat, config.heartbeat);
    heartbeat.set_missed_tick_behavior(MissedTickBehavior::Skip);
    let mut watchdog = interval_at(
        Instant::now() + Duration::from_millis(100),
        Duration::from_millis(100),
    );
    watchdog.set_missed_tick_behavior(MissedTickBehavior::Skip);
    let mut video_status = interval_at(
        Instant::now() + Duration::from_secs(VIDEO_STATUS_HEARTBEAT_SECONDS),
        Duration::from_secs(VIDEO_STATUS_HEARTBEAT_SECONDS),
    );
    video_status.set_missed_tick_behavior(MissedTickBehavior::Skip);

    loop {
        tokio::select! {
            Some(event) = incoming_events.recv() => {
                if let Err(err) = state.handle_mqtt_event(publisher, event, now_ms()).await {
                    warn!(error = %format_args!("{err:#}"), "failed to handle MQTT runtime event");
                }
            }
            Some(event) = video_events.recv() => {
                if let Err(err) = state.handle_video_event(publisher, event, now_ms()).await {
                    warn!(error = %format_args!("{err:#}"), "failed to handle video worker event");
                }
            }
            Some(event) = mcp_ipc_events.recv() => {
                if let Err(err) = state.handle_mcp_ipc_event(publisher, event, now_ms()).await {
                    warn!(error = %format_args!("{err:#}"), "failed to handle MCP WebRTC IPC event");
                }
            }
            shutdown = wait_for_shutdown_signal() => {
                shutdown?;
                info!("shutdown signal received");
                break;
            }
            _ = heartbeat.tick() => {
                if let Err(err) = state.refresh_capabilities(publisher, now_ms()).await {
                    warn!(error = %format_args!("{err:#}"), "failed to refresh capability state");
                }
            }
            _ = watchdog.tick() => {
                if let Err(err) = state.tick_watchdogs(publisher, now_ms()).await {
                    warn!(error = %format_args!("{err:#}"), "failed to tick watchdogs");
                }
            }
            _ = video_status.tick() => {
                if let Err(err) = state.refresh_video_status(publisher, now_ms()).await {
                    warn!(error = %format_args!("{err:#}"), "failed to refresh video status");
                }
            }
        }
    }

    if let Some(board_video_bridge_server) = board_video_bridge_server {
        board_video_bridge_server.shutdown().await;
    }
    if let Err(err) = state.publish_offline(publisher, now_ms()).await {
        warn!(error = %format_args!("{err:#}"), "failed to publish offline state");
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

#[derive(Debug, Clone)]
struct IotCertificateCredentialsProvider {
    config: RuntimeConfig,
}

impl IotCertificateCredentialsProvider {
    async fn load_credentials(&self) -> provider::Result {
        fetch_iot_temporary_credentials(&self.config)
            .await
            .and_then(iot_temporary_credentials_to_sdk)
            .map_err(|err| CredentialsError::provider_error(format!("{err:#}")))
    }
}

impl ProvideCredentials for IotCertificateCredentialsProvider {
    fn provide_credentials<'a>(&'a self) -> future::ProvideCredentials<'a>
    where
        Self: 'a,
    {
        future::ProvideCredentials::new(self.load_credentials())
    }
}

fn iot_temporary_credentials_to_sdk(credentials: IotTemporaryCredentials) -> Result<Credentials> {
    let expiry = parse_iot_temporary_credentials_expiration(&credentials.expiration)?;
    Ok(Credentials::builder()
        .access_key_id(credentials.access_key_id)
        .secret_access_key(credentials.secret_access_key)
        .session_token(credentials.session_token)
        .expiry(expiry)
        .provider_name("aws-iot-credential-provider")
        .build())
}

fn parse_iot_temporary_credentials_expiration(value: &str) -> Result<SystemTime> {
    let date_time = DateTime::from_str(value, Format::DateTime)
        .with_context(|| format!("parse IoT temporary credential expiration {value:?}"))?;
    SystemTime::try_from(date_time).context("convert IoT temporary credential expiration")
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

async fn aws_sdk_config_from_iot_credentials(
    config: &RuntimeConfig,
) -> Result<aws_config::SdkConfig> {
    let credentials_provider = SharedCredentialsProvider::new(IotCertificateCredentialsProvider {
        config: config.clone(),
    });
    Ok(aws_config::defaults(BehaviorVersion::latest())
        .region(aws_sdk_iotdataplane::config::Region::new(
            config.aws_region.clone(),
        ))
        .credentials_provider(credentials_provider)
        .load()
        .await)
}

pub fn build_iot_data_endpoint_url(endpoint: &str) -> Result<String> {
    validate_endpoint_host(endpoint, "iot-endpoint")?;
    Ok(format!("https://{endpoint}"))
}

pub async fn read_current_sparkplug_redcon(config: &RuntimeConfig) -> Result<SparkplugRedcon> {
    let sdk_config = aws_sdk_config_from_iot_credentials(config).await?;
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

pub fn build_mcp_topic_root(thing_name: &str) -> Result<String> {
    Ok(format!(
        "txings/{}/mcp",
        validate_topic_segment(thing_name, "thing-id")?
    ))
}

pub fn build_mcp_descriptor_topic(thing_name: &str) -> Result<String> {
    Ok(format!("{}/descriptor", build_mcp_topic_root(thing_name)?))
}

pub fn build_mcp_status_topic(thing_name: &str) -> Result<String> {
    Ok(format!("{}/status", build_mcp_topic_root(thing_name)?))
}

pub fn build_video_topic_root(thing_name: &str) -> Result<String> {
    Ok(format!(
        "txings/{}/video",
        validate_topic_segment(thing_name, "thing-id")?
    ))
}

pub fn build_video_descriptor_topic(thing_name: &str) -> Result<String> {
    Ok(format!(
        "{}/descriptor",
        build_video_topic_root(thing_name)?
    ))
}

pub fn build_video_status_topic(thing_name: &str) -> Result<String> {
    Ok(format!("{}/status", build_video_topic_root(thing_name)?))
}

pub fn build_mcp_session_c2s_subscription(thing_name: &str) -> Result<String> {
    Ok(format!(
        "{}/session/+/c2s",
        build_mcp_topic_root(thing_name)?
    ))
}

pub fn build_mcp_session_s2c_topic(thing_name: &str, session_id: &str) -> Result<String> {
    validate_topic_segment(session_id, "mcp-session-id")?;
    Ok(format!(
        "{}/session/{session_id}/s2c",
        build_mcp_topic_root(thing_name)?
    ))
}

fn parse_mcp_session_c2s_topic(thing_name: &str, topic: &str) -> Option<String> {
    let root = build_mcp_topic_root(thing_name).ok()?;
    let suffix = topic.strip_prefix(&(root + "/session/"))?;
    let session_id = suffix.strip_suffix("/c2s")?;
    validate_topic_segment(session_id, "mcp-session-id").ok()?;
    Some(session_id.to_string())
}

pub fn build_board_shadow_update_topic(thing_name: &str) -> Result<String> {
    Ok(format!(
        "$aws/things/{}/shadow/name/{BOARD_SHADOW_NAME}/update",
        validate_topic_segment(thing_name, "thing-id")?
    ))
}

pub fn build_mcp_shadow_update_topic(thing_name: &str) -> Result<String> {
    Ok(format!(
        "$aws/things/{}/shadow/name/{MCP_SHADOW_NAME}/update",
        validate_topic_segment(thing_name, "thing-id")?
    ))
}

pub fn build_video_shadow_update_topic(thing_name: &str) -> Result<String> {
    Ok(format!(
        "$aws/things/{}/shadow/name/{VIDEO_SHADOW_NAME}/update",
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LoadedEnvFile {
    pub values: BTreeMap<String, String>,
    pub path: Option<PathBuf>,
}

impl LoadedEnvFile {
    pub fn parent_dir(&self) -> Option<&Path> {
        self.path.as_deref().and_then(Path::parent)
    }
}

pub fn load_env_file_for_cli(
    cli: &Cli,
    process_env: &BTreeMap<String, String>,
) -> Result<LoadedEnvFile> {
    let cli_env_file = normalize_optional(cli.env_file.clone());
    if let Some(env_file) = cli_env_file {
        return read_env_file(PathBuf::from(env_file), true);
    }
    if let Some(env_file) = normalize_optional(process_env.get("TXING_DAEMON_ENV_FILE").cloned()) {
        return read_env_file(PathBuf::from(env_file), true);
    }
    if let Some(config_dir) =
        normalize_optional(process_env.get("TXING_DAEMON_CONFIG_DIR").cloned())
    {
        return read_env_file(Path::new(&config_dir).join(DEFAULT_ENV_FILE_NAME), true);
    }

    read_env_file_candidates(&default_env_file_candidates(process_env), false)
}

fn read_env_file_candidates(candidates: &[PathBuf], explicit: bool) -> Result<LoadedEnvFile> {
    for env_file in candidates {
        match read_env_file(env_file.clone(), false) {
            Ok(loaded) if loaded.path.is_some() => return Ok(loaded),
            Ok(_) => {}
            Err(err) => return Err(err),
        }
    }
    if explicit {
        if let Some(env_file) = candidates.first() {
            return read_env_file(env_file.clone(), true);
        }
    }
    Ok(LoadedEnvFile {
        values: BTreeMap::new(),
        path: None,
    })
}

fn read_env_file(path: PathBuf, explicit: bool) -> Result<LoadedEnvFile> {
    match fs::read_to_string(&path) {
        Ok(contents) => Ok(LoadedEnvFile {
            values: parse_env_file_contents(&contents)?,
            path: Some(path),
        }),
        Err(err) if err.kind() == ErrorKind::NotFound && !explicit => Ok(LoadedEnvFile {
            values: BTreeMap::new(),
            path: None,
        }),
        Err(err) => Err(err).with_context(|| format!("read daemon env file {}", path.display())),
    }
}

fn default_env_file_candidates(process_env: &BTreeMap<String, String>) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(xdg_config_home) = normalize_optional(process_env.get("XDG_CONFIG_HOME").cloned()) {
        let config_dir = Path::new(&xdg_config_home).join(DEFAULT_CONFIG_SUBDIR);
        candidates.push(config_dir.join(DEFAULT_ENV_FILE_NAME));
    }
    if let Some(home) = normalize_optional(process_env.get("HOME").cloned()) {
        let config_dir = Path::new(&home).join(".config").join(DEFAULT_CONFIG_SUBDIR);
        candidates.push(config_dir.join(DEFAULT_ENV_FILE_NAME));
    }
    candidates
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

fn config_value_or_colocated_file(
    cli_value: Option<String>,
    process_env: &BTreeMap<String, String>,
    file_env: &BTreeMap<String, String>,
    env_name: &str,
    label: &str,
    env_file_dir: Option<&Path>,
    file_name: &str,
) -> Result<String> {
    if let Some(value) = optional_config_value(cli_value, process_env, file_env, env_name) {
        return Ok(value);
    }
    if let Some(env_file_dir) = env_file_dir {
        return Ok(env_file_dir.join(file_name).display().to_string());
    }
    bail!(
        "{label} is required; pass --{label}, set {env_name}, or load an env file from the daemon config directory"
    )
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

fn default_video_channel_name(thing_id: &str) -> String {
    format!("{thing_id}-board-video")
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

fn optional_i32_config(
    process_env: &BTreeMap<String, String>,
    file_env: &BTreeMap<String, String>,
    env_name: &str,
) -> Result<Option<i32>> {
    let Some(value) = optional_config_value(None, process_env, file_env, env_name) else {
        return Ok(None);
    };
    value
        .parse::<i32>()
        .with_context(|| format!("{env_name} must be an integer"))
        .map(Some)
}

fn parse_bool_text(value: &str, label: &str) -> Result<bool> {
    match value.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" => Ok(false),
        _ => bail!("{label} expects one of true/false, 1/0, yes/no, on/off"),
    }
}

fn optional_bool_config(
    cli_value: Option<String>,
    process_env: &BTreeMap<String, String>,
    file_env: &BTreeMap<String, String>,
    env_name: &str,
    label: &str,
) -> Result<Option<bool>> {
    let Some(value) = optional_config_value(cli_value, process_env, file_env, env_name) else {
        return Ok(None);
    };
    parse_bool_text(&value, label).map(Some)
}

fn resolve_cloudwatch_log_config(
    cli_log_group: Option<String>,
    cli_log_stream: Option<String>,
    cli_log_level: Option<String>,
    cli_retention_days: Option<i32>,
    process_env: &BTreeMap<String, String>,
    file_env: &BTreeMap<String, String>,
    client_id: &str,
) -> Result<Option<CloudWatchLogConfig>> {
    let log_group = optional_config_value(
        cli_log_group,
        process_env,
        file_env,
        "TXING_CLOUDWATCH_LOG_GROUP",
    );
    let log_stream = optional_config_value(
        cli_log_stream,
        process_env,
        file_env,
        "TXING_CLOUDWATCH_LOG_STREAM",
    );
    let log_level = optional_config_value(
        cli_log_level,
        process_env,
        file_env,
        "TXING_CLOUDWATCH_LOG_LEVEL",
    );
    let retention_days = match cli_retention_days {
        Some(value) => Some(value),
        None => optional_i32_config(process_env, file_env, "TXING_CLOUDWATCH_LOG_RETENTION_DAYS")?,
    };

    let requested = log_group.is_some()
        || log_stream.is_some()
        || log_level.is_some()
        || retention_days.is_some();
    let Some(log_group) = log_group else {
        if requested {
            bail!("cloudwatch-log-group is required when CloudWatch logging options are set");
        }
        return Ok(None);
    };
    validate_cloudwatch_log_group(&log_group)?;

    let log_stream = log_stream.unwrap_or_else(|| default_cloudwatch_log_stream(client_id));
    validate_cloudwatch_log_stream(&log_stream)?;

    let level = match log_level {
        Some(value) => CloudWatchLogLevel::parse(&value)?,
        None => CloudWatchLogLevel::Info,
    };
    let retention_days = retention_days.unwrap_or(DEFAULT_CLOUDWATCH_LOG_RETENTION_DAYS);
    if retention_days <= 0 {
        bail!("cloudwatch-log-retention-days must be greater than 0");
    }

    Ok(Some(CloudWatchLogConfig {
        log_group,
        log_stream,
        level,
        retention_days,
    }))
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
        capabilities.insert(MCP_CAPABILITY.to_string());
        capabilities.insert(VIDEO_CAPABILITY.to_string());
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
    if !matches!(value, BOARD_CAPABILITY | MCP_CAPABILITY | VIDEO_CAPABILITY) {
        bail!(
            "unsupported capability {value:?}; supported capabilities are {BOARD_CAPABILITY:?}, {MCP_CAPABILITY:?}, {VIDEO_CAPABILITY:?}"
        );
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

fn validate_cloudwatch_log_group(value: &str) -> Result<()> {
    let value = normalize_required(value.to_string(), "cloudwatch-log-group")?;
    if value.len() > 512 {
        bail!("cloudwatch-log-group must be 512 characters or fewer");
    }
    if value.starts_with("aws/") || value.starts_with("/aws/") {
        bail!("cloudwatch-log-group must not use the reserved aws/ prefix");
    }
    if !value
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '-' | '/' | '#'))
    {
        bail!("cloudwatch-log-group contains an unsupported character");
    }
    Ok(())
}

fn validate_cloudwatch_log_stream(value: &str) -> Result<()> {
    let value = normalize_required(value.to_string(), "cloudwatch-log-stream")?;
    if value.len() > 512 {
        bail!("cloudwatch-log-stream must be 512 characters or fewer");
    }
    if value.contains(':') || value.contains('*') || value.chars().any(char::is_control) {
        bail!("cloudwatch-log-stream contains an unsupported character");
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

fn default_cloudwatch_log_stream(client_id: &str) -> String {
    format!(
        "daemon/{}",
        client_id
            .chars()
            .map(|ch| {
                if ch == ':' || ch == '*' || ch.is_control() {
                    '-'
                } else {
                    ch
                }
            })
            .collect::<String>()
            .trim_matches('/')
    )
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
    use std::sync::{Arc, Mutex};

    use super::*;

    fn test_temp_dir(label: &str) -> PathBuf {
        env::temp_dir().join(format!(
            "txing-unit-daemon-{label}-{}-{}",
            process::id(),
            now_ms()
        ))
    }

    #[derive(Default)]
    struct FakePublisher {
        messages: Mutex<Vec<PublishedMessage>>,
    }

    impl FakePublisher {
        fn messages(&self) -> Vec<PublishedMessage> {
            self.messages.lock().unwrap().clone()
        }

        fn clear(&self) {
            self.messages.lock().unwrap().clear();
        }
    }

    async fn call_mcp_ipc<P: Publisher + ?Sized>(
        runtime: &mut RuntimeState,
        publisher: &P,
        session_id: &str,
        request: Value,
        observed_at_ms: u64,
    ) -> Value {
        let (response_tx, response_rx) = oneshot::channel();
        runtime
            .handle_mcp_ipc_event(
                publisher,
                RuntimeMcpIpcEvent::Request {
                    session_id: session_id.to_string(),
                    payload: serde_json::to_string(&request).unwrap(),
                    response_tx,
                },
                observed_at_ms,
            )
            .await
            .unwrap();
        serde_json::from_str(&response_rx.await.unwrap().unwrap()).unwrap()
    }

    #[async_trait]
    impl Publisher for FakePublisher {
        async fn publish(&self, message: PublishedMessage) -> Result<()> {
            self.messages.lock().unwrap().push(message);
            Ok(())
        }
    }

    struct FailingPublisher;

    #[async_trait]
    impl Publisher for FailingPublisher {
        async fn publish(&self, _message: PublishedMessage) -> Result<()> {
            Err(anyhow!("publish failed"))
        }
    }

    #[derive(Clone, Default)]
    struct FakeHardwareClient {
        calls: Arc<Mutex<Vec<String>>>,
        motion: Arc<Mutex<DriveState>>,
        fail: Arc<AtomicBool>,
    }

    impl FakeHardwareClient {
        fn unavailable() -> Self {
            let client = Self::default();
            client.fail.store(true, Ordering::SeqCst);
            client
        }

        fn calls(&self) -> Vec<String> {
            self.calls.lock().unwrap().clone()
        }
    }

    #[async_trait]
    impl HardwareClient for FakeHardwareClient {
        async fn get_status(&mut self) -> Result<HardwareStatusSnapshot> {
            if self.fail.load(Ordering::SeqCst) {
                bail!("hardware worker unavailable");
            }
            Ok(HardwareStatusSnapshot {
                actuator_ready: true,
                motion: self.motion.lock().unwrap().clone(),
            })
        }

        async fn apply_velocity(
            &mut self,
            _twist: Twist,
            deadline_unix_ms: u64,
        ) -> Result<DriveState> {
            if self.fail.load(Ordering::SeqCst) {
                bail!("hardware worker unavailable");
            }
            self.calls
                .lock()
                .unwrap()
                .push(format!("apply:{deadline_unix_ms}"));
            let mut motion = self.motion.lock().unwrap();
            motion.left_speed = 50;
            motion.right_speed = 50;
            motion.sequence = motion.sequence.saturating_add(1);
            Ok(motion.clone())
        }

        async fn stop(&mut self) -> Result<DriveState> {
            if self.fail.load(Ordering::SeqCst) {
                bail!("hardware worker unavailable");
            }
            self.calls.lock().unwrap().push("stop".to_string());
            let mut motion = self.motion.lock().unwrap();
            motion.left_speed = 0;
            motion.right_speed = 0;
            motion.sequence = motion.sequence.saturating_add(1);
            Ok(motion.clone())
        }
    }

    #[derive(Debug, Clone, PartialEq, Eq)]
    struct FakeCloudWatchPut {
        log_group: String,
        log_stream: String,
        events: Vec<CloudWatchLogRecord>,
        sequence_token: Option<String>,
    }

    #[derive(Default)]
    struct FakeCloudWatchLogsClient {
        calls: Mutex<Vec<String>>,
        puts: Mutex<Vec<FakeCloudWatchPut>>,
        create_log_group_result: Mutex<Option<std::result::Result<(), CloudWatchLogClientError>>>,
        create_log_stream_result: Mutex<Option<std::result::Result<(), CloudWatchLogClientError>>>,
        put_results:
            Mutex<Vec<std::result::Result<CloudWatchPutLogEventsResult, CloudWatchLogClientError>>>,
    }

    impl FakeCloudWatchLogsClient {
        fn calls(&self) -> Vec<String> {
            self.calls.lock().unwrap().clone()
        }

        fn puts(&self) -> Vec<FakeCloudWatchPut> {
            self.puts.lock().unwrap().clone()
        }

        fn set_create_log_group_result(
            &self,
            result: std::result::Result<(), CloudWatchLogClientError>,
        ) {
            *self.create_log_group_result.lock().unwrap() = Some(result);
        }

        fn set_create_log_stream_result(
            &self,
            result: std::result::Result<(), CloudWatchLogClientError>,
        ) {
            *self.create_log_stream_result.lock().unwrap() = Some(result);
        }

        fn push_put_result(
            &self,
            result: std::result::Result<CloudWatchPutLogEventsResult, CloudWatchLogClientError>,
        ) {
            self.put_results.lock().unwrap().push(result);
        }
    }

    #[async_trait]
    impl CloudWatchLogsClient for FakeCloudWatchLogsClient {
        async fn create_log_group(
            &self,
            log_group: &str,
        ) -> std::result::Result<(), CloudWatchLogClientError> {
            self.calls
                .lock()
                .unwrap()
                .push(format!("create-log-group:{log_group}"));
            self.create_log_group_result
                .lock()
                .unwrap()
                .take()
                .unwrap_or(Ok(()))
        }

        async fn put_retention_policy(
            &self,
            log_group: &str,
            retention_days: i32,
        ) -> std::result::Result<(), CloudWatchLogClientError> {
            self.calls
                .lock()
                .unwrap()
                .push(format!("put-retention:{log_group}:{retention_days}"));
            Ok(())
        }

        async fn create_log_stream(
            &self,
            log_group: &str,
            log_stream: &str,
        ) -> std::result::Result<(), CloudWatchLogClientError> {
            self.calls
                .lock()
                .unwrap()
                .push(format!("create-log-stream:{log_group}:{log_stream}"));
            self.create_log_stream_result
                .lock()
                .unwrap()
                .take()
                .unwrap_or(Ok(()))
        }

        async fn put_log_events(
            &self,
            log_group: &str,
            log_stream: &str,
            events: Vec<CloudWatchLogRecord>,
            sequence_token: Option<String>,
        ) -> std::result::Result<CloudWatchPutLogEventsResult, CloudWatchLogClientError> {
            self.puts.lock().unwrap().push(FakeCloudWatchPut {
                log_group: log_group.to_string(),
                log_stream: log_stream.to_string(),
                events,
                sequence_token,
            });
            let mut results = self.put_results.lock().unwrap();
            if results.is_empty() {
                Ok(CloudWatchPutLogEventsResult {
                    next_sequence_token: Some("next-token".to_string()),
                })
            } else {
                results.remove(0)
            }
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
            iot_cert_file: "/home/txing/.config/txing/unit-daemon/certificate.pem.crt".to_string(),
            iot_private_key_file: "/home/txing/.config/txing/unit-daemon/private.pem.key"
                .to_string(),
            iot_root_ca_file: "/home/txing/.config/txing/unit-daemon/AmazonRootCA1.pem".to_string(),
            client_id: "unit-local-daemon-test".to_string(),
            capabilities: vec![
                BOARD_CAPABILITY.to_string(),
                MCP_CAPABILITY.to_string(),
                VIDEO_CAPABILITY.to_string(),
            ],
            capability_ttl: Duration::from_secs(150),
            heartbeat: Duration::from_secs(60),
            kvs_master_command: DEFAULT_KVS_MASTER_COMMAND.to_string(),
            mcp_webrtc_socket_path: DEFAULT_MCP_WEBRTC_SOCKET_PATH.to_string(),
            board_video_bridge_socket_path: DEFAULT_BOARD_VIDEO_BRIDGE_SOCKET_PATH.to_string(),
            kvs_prefer_ipv6: true,
            kvs_disable_ipv4_turn: false,
            video_region: "eu-central-1".to_string(),
            video_channel_name: "unit-local-board-video".to_string(),
            hardware_worker_socket_path: DEFAULT_HARDWARE_WORKER_SOCKET_PATH.to_string(),
            hardware_worker_timeout: Duration::from_millis(DEFAULT_HARDWARE_WORKER_TIMEOUT_MS),
            cloudwatch_logging: None,
        }
    }

    fn runtime_state() -> RuntimeState {
        RuntimeState::new_with_hardware(config(), Some(Box::new(FakeHardwareClient::default())))
            .unwrap()
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
                "/home/txing/.config/txing/unit-daemon/certificate.pem.crt".to_string(),
            ),
            (
                "TXING_IOT_PRIVATE_KEY_FILE".to_string(),
                "/home/txing/.config/txing/unit-daemon/private.pem.key".to_string(),
            ),
            (
                "TXING_IOT_ROOT_CA_FILE".to_string(),
                "/home/txing/.config/txing/unit-daemon/AmazonRootCA1.pem".to_string(),
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

    fn cloudwatch_log_config() -> CloudWatchLogConfig {
        CloudWatchLogConfig {
            log_group: "txing/town-local/rig-local/unit-local".to_string(),
            log_stream: "daemon/unit-local-daemon-test".to_string(),
            level: CloudWatchLogLevel::Info,
            retention_days: DEFAULT_CLOUDWATCH_LOG_RETENTION_DAYS,
        }
    }

    fn cloudwatch_log_record(message: &str, timestamp_ms: i64) -> CloudWatchLogRecord {
        CloudWatchLogRecord {
            timestamp_ms,
            message: message.to_string(),
        }
    }

    #[test]
    fn cli_reports_daemon_build_version() {
        use clap::CommandFactory;

        let command = Cli::command();
        assert_eq!(command.get_name(), "txing-unit-daemon");
        assert_eq!(command.get_version(), Some(DAEMON_VERSION));
    }

    #[test]
    fn formats_stderr_line_like_systemd_service_message() {
        assert_eq!(
            format_stderr_log_line(
                &Level::WARN,
                "BLE connect from advertisement failed",
                &[
                    ("thing".to_string(), "unit-bl95f2".to_string()),
                    ("retryDelayMs".to_string(), "2000".to_string()),
                    (
                        "error".to_string(),
                        "create BLE manager: limit reached".to_string()
                    ),
                ],
            ),
            "warning: BLE connect from advertisement failed thing=unit-bl95f2 retryDelayMs=2000 error=create BLE manager: limit reached"
        );

        assert_eq!(
            format_stderr_log_line(
                &Level::INFO,
                "starting unit daemon",
                &[
                    ("version".to_string(), "0.9.8".to_string()),
                    ("capabilities".to_string(), r#"["board"]"#.to_string()),
                ],
            ),
            r#"info: starting unit daemon version=0.9.8 capabilities=["board"]"#
        );
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
        let availability = BTreeMap::from([(BOARD_CAPABILITY.to_string(), true)]);

        manager
            .publish_state(
                &publisher,
                "unit-local",
                &availability,
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
        let mut runtime = runtime_state();

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
        assert_eq!(messages.len(), 17);
        assert_eq!(
            messages[0].topic,
            "$aws/things/unit-local/shadow/name/board/update"
        );
        assert!(!messages[0].retain);
        assert_eq!(messages[1].topic, "txings/unit-local/mcp/descriptor");
        assert!(messages[1].retain);
        assert_eq!(messages[2].topic, "txings/unit-local/mcp/status");
        assert!(messages[2].retain);
        assert_eq!(
            messages[3].topic,
            "$aws/things/unit-local/shadow/name/mcp/update"
        );
        assert_eq!(messages[4].topic, "txings/unit-local/video/descriptor");
        assert!(messages[4].retain);
        assert_eq!(messages[5].topic, "txings/unit-local/video/status");
        assert!(messages[5].retain);
        assert_eq!(
            messages[6].topic,
            "$aws/things/unit-local/shadow/name/video/update"
        );
        assert_eq!(messages[7].topic, "txings/unit-local/capability/v2/state");
        assert_eq!(messages[8].topic, "txings/unit-local/mcp/status");
        assert_eq!(
            messages[9].topic,
            "$aws/things/unit-local/shadow/name/mcp/update"
        );
        assert_eq!(messages[10].topic, "txings/unit-local/capability/v2/state");
        assert_eq!(
            messages[11].topic,
            "$aws/things/unit-local/shadow/name/board/update"
        );
        assert_eq!(messages[12].topic, "txings/unit-local/mcp/status");
        assert_eq!(
            messages[13].topic,
            "$aws/things/unit-local/shadow/name/mcp/update"
        );
        assert_eq!(messages[14].topic, "txings/unit-local/video/status");
        assert_eq!(
            messages[15].topic,
            "$aws/things/unit-local/shadow/name/video/update"
        );
        assert_eq!(messages[16].topic, "txings/unit-local/capability/v2/state");

        let descriptor: Value = serde_json::from_slice(&messages[1].payload).unwrap();
        assert_eq!(descriptor["protocolVersion"], MCP_PROTOCOL_VERSION);
        assert_eq!(descriptor["control"]["mode"], "active");
        assert_eq!(descriptor["control"]["activeTtlMs"], 5_000);
        let status: Value = serde_json::from_slice(&messages[2].payload).unwrap();
        assert_eq!(status["available"], true);
        assert_eq!(status["protocolVersion"], MCP_PROTOCOL_VERSION);
        assert_eq!(descriptor["transports"][0]["type"], "mqtt-jsonrpc");
        assert_eq!(descriptor["transports"].as_array().unwrap().len(), 1);

        let video_descriptor: Value = serde_json::from_slice(&messages[4].payload).unwrap();
        assert_eq!(video_descriptor["transport"], DEFAULT_VIDEO_TRANSPORT);
        assert_eq!(video_descriptor["channelName"], "unit-local-board-video");
        let video_status: Value = serde_json::from_slice(&messages[5].payload).unwrap();
        assert_eq!(video_status["available"], true);
        assert_eq!(video_status["ready"], false);
        assert_eq!(video_status["status"], VIDEO_STATUS_STARTING);

        let first: CapabilityStatePayload = serde_json::from_slice(&messages[7].payload).unwrap();
        let second: CapabilityStatePayload = serde_json::from_slice(&messages[10].payload).unwrap();
        let third: CapabilityStatePayload = serde_json::from_slice(&messages[16].payload).unwrap();
        assert_eq!(first.seq, 1);
        assert_eq!(second.seq, 2);
        assert_eq!(third.seq, 3);
        assert_eq!(third.capabilities.get(BOARD_CAPABILITY), Some(&false));
        assert_eq!(third.capabilities.get(MCP_CAPABILITY), Some(&false));
        assert_eq!(third.capabilities.get(VIDEO_CAPABILITY), Some(&false));
        assert_eq!(runtime.capability_seq(), 3);
    }

    #[tokio::test]
    async fn video_worker_events_publish_status_shadow_and_capability() {
        let publisher = FakePublisher::default();
        let mut runtime = runtime_state();

        runtime
            .handle_video_event(
                &publisher,
                VideoWorkerEvent::Ready {
                    worker_version: Some("1.2.3".to_string()),
                },
                42,
            )
            .await
            .unwrap();

        let messages = publisher.messages();
        assert_eq!(messages.len(), 6);
        assert_eq!(messages[0].topic, "txings/unit-local/mcp/descriptor");
        assert_eq!(messages[1].topic, "txings/unit-local/mcp/status");
        assert_eq!(
            messages[2].topic,
            "$aws/things/unit-local/shadow/name/mcp/update"
        );
        assert_eq!(messages[3].topic, "txings/unit-local/video/status");
        assert_eq!(
            messages[4].topic,
            "$aws/things/unit-local/shadow/name/video/update"
        );
        assert_eq!(messages[5].topic, "txings/unit-local/capability/v2/state");

        let mcp_descriptor: Value = serde_json::from_slice(&messages[0].payload).unwrap();
        assert_eq!(
            mcp_descriptor["transports"][0]["type"],
            "webrtc-datachannel"
        );
        assert_eq!(mcp_descriptor["transports"].as_array().unwrap().len(), 1);

        let status: Value = serde_json::from_slice(&messages[3].payload).unwrap();
        assert_eq!(status["available"], true);
        assert_eq!(status["ready"], true);
        assert_eq!(status["status"], VIDEO_STATUS_READY);
        assert_eq!(status["updatedAtMs"], 42);

        let capability: CapabilityStatePayload =
            serde_json::from_slice(&messages[5].payload).unwrap();
        assert_eq!(capability.capabilities.get(VIDEO_CAPABILITY), Some(&true));
    }

    #[tokio::test]
    async fn mqtt_mcp_requests_are_rejected_while_webrtc_only_is_advertised() {
        let publisher = FakePublisher::default();
        let mut runtime = runtime_state();
        runtime
            .handle_video_event(
                &publisher,
                VideoWorkerEvent::Ready {
                    worker_version: None,
                },
                42,
            )
            .await
            .unwrap();
        publisher.clear();

        runtime
            .handle_mqtt_event(
                &publisher,
                RuntimeMqttEvent::Publish {
                    topic: "txings/unit-local/mcp/session/session-a/c2s".to_string(),
                    payload: serde_json::to_vec(&serde_json::json!({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                    }))
                    .unwrap(),
                },
                43,
            )
            .await
            .unwrap();

        let messages = publisher.messages();
        assert_eq!(messages.len(), 1);
        assert_eq!(
            messages[0].topic,
            "txings/unit-local/mcp/session/session-a/s2c"
        );
        let response: Value = serde_json::from_slice(&messages[0].payload).unwrap();
        assert_eq!(response["id"], 1);
        assert_eq!(response["error"]["code"], -32000);
        assert!(
            response["error"]["message"]
                .as_str()
                .unwrap()
                .contains("WebRTC data channel")
        );
    }

    #[tokio::test]
    async fn mcp_ipc_requests_use_core_and_close_clears_active_control() {
        let publisher = FakePublisher::default();
        let mut runtime = runtime_state();
        runtime
            .handle_video_event(
                &publisher,
                VideoWorkerEvent::Ready {
                    worker_version: None,
                },
                42,
            )
            .await
            .unwrap();
        publisher.clear();

        let response = call_mcp_ipc(
            &mut runtime,
            &publisher,
            "rtc-session",
            serde_json::json!({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "control.activate",
                    "arguments": {"actor": "operator"},
                },
            }),
            43,
        )
        .await;
        assert_eq!(
            response["result"]["structuredContent"]["activeControl"]["transport"],
            "webrtc-datachannel"
        );
        assert_eq!(publisher.messages().len(), 2);

        let busy_response = call_mcp_ipc(
            &mut runtime,
            &publisher,
            "rtc-session-b",
            serde_json::json!({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "control.activate",
                    "arguments": {"actor": "operator-b"},
                },
            }),
            44,
        )
        .await;
        assert_eq!(busy_response["error"]["code"], -32012);
        assert!(
            busy_response["error"]["message"]
                .as_str()
                .unwrap()
                .contains("active control busy")
        );

        let takeover_response = call_mcp_ipc(
            &mut runtime,
            &publisher,
            "rtc-session-b",
            serde_json::json!({
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "control.activate",
                    "arguments": {"actor": "operator-b", "takeover": true},
                },
            }),
            45,
        )
        .await;
        let takeover_active = &takeover_response["result"]["structuredContent"]["activeControl"];
        assert_eq!(takeover_active["sessionId"], "rtc-session-b");
        assert_eq!(takeover_active["actor"], "operator-b");
        assert_eq!(takeover_active["epoch"], 2);

        let displaced_response = call_mcp_ipc(
            &mut runtime,
            &publisher,
            "rtc-session",
            serde_json::json!({
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "cmd_vel.stop",
                    "arguments": {"epoch": 1},
                },
            }),
            46,
        )
        .await;
        assert_eq!(displaced_response["error"]["code"], -32011);

        runtime
            .handle_mcp_ipc_event(
                &publisher,
                RuntimeMcpIpcEvent::Close {
                    session_id: "rtc-session".to_string(),
                    reason: "data channel closed".to_string(),
                },
                47,
            )
            .await
            .unwrap();
        let status_after_old_close: Value =
            serde_json::from_slice(&publisher.messages().last().unwrap().payload).unwrap();
        assert_eq!(
            status_after_old_close["state"]["reported"]["status"]["activeControl"]["sessionId"],
            "rtc-session-b"
        );

        runtime
            .handle_mcp_ipc_event(
                &publisher,
                RuntimeMcpIpcEvent::Close {
                    session_id: "rtc-session-b".to_string(),
                    reason: "data channel closed".to_string(),
                },
                48,
            )
            .await
            .unwrap();

        let messages = publisher.messages();
        let status: Value = serde_json::from_slice(&messages.last().unwrap().payload).unwrap();
        assert_eq!(
            status["state"]["reported"]["status"]["activeControl"],
            Value::Null
        );
    }

    #[tokio::test]
    async fn mcp_ipc_returns_response_even_when_status_publish_fails() {
        let publisher = FakePublisher::default();
        let failing_publisher = FailingPublisher;
        let mut runtime = runtime_state();
        runtime
            .handle_video_event(
                &publisher,
                VideoWorkerEvent::Ready {
                    worker_version: Some("0.9.test".to_string()),
                },
                42,
            )
            .await
            .unwrap();

        let response = call_mcp_ipc(
            &mut runtime,
            &failing_publisher,
            "rtc-session",
            serde_json::json!({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "control.activate",
                    "arguments": {"actor": "operator"},
                },
            }),
            43,
        )
        .await;

        assert_eq!(response["id"], 1);
        assert_eq!(
            response["result"]["structuredContent"]["activeControl"]["sessionId"],
            "rtc-session"
        );
    }

    #[tokio::test]
    async fn video_status_refresh_updates_freshness_timestamp() {
        let publisher = FakePublisher::default();
        let mut runtime = runtime_state();

        runtime
            .handle_video_event(
                &publisher,
                VideoWorkerEvent::Ready {
                    worker_version: None,
                },
                42,
            )
            .await
            .unwrap();
        runtime
            .refresh_video_status(&publisher, 5_042)
            .await
            .unwrap();

        let messages = publisher.messages();
        assert_eq!(messages.len(), 8);
        assert_eq!(messages[6].topic, "txings/unit-local/video/status");
        let status: Value = serde_json::from_slice(&messages[6].payload).unwrap();
        assert_eq!(status["ready"], true);
        assert_eq!(status["updatedAtMs"], 5_042);
    }

    #[test]
    fn parses_native_kvs_worker_markers() {
        assert_eq!(
            parse_video_worker_marker("TXING_KVS_READY version=0.9.121"),
            Some(VideoWorkerMarker::Ready {
                worker_version: Some("0.9.121".to_string())
            })
        );
        assert_eq!(
            parse_video_worker_marker("TXING_VIEWER_CONNECTED clientId=a viewers=1"),
            Some(VideoWorkerMarker::ViewerConnected)
        );
        assert_eq!(
            parse_video_worker_marker("TXING_VIEWER_DISCONNECTED clientId=a viewers=0"),
            Some(VideoWorkerMarker::ViewerDisconnected)
        );
        assert_eq!(
            parse_video_worker_marker("TXING_KVS_ERROR detail=bad line here"),
            Some(VideoWorkerMarker::Error {
                detail: "bad line here".to_string()
            })
        );
        assert_eq!(
            parse_video_worker_marker("TXING_MCP_DATACHANNEL_OPEN sessionId=peer-a"),
            Some(VideoWorkerMarker::McpDataChannelOpen {
                session_id: "peer-a".to_string()
            })
        );
        assert_eq!(
            parse_video_worker_marker(
                "TXING_MCP_DATACHANNEL_CLOSED sessionId=peer-a reason=closed"
            ),
            Some(VideoWorkerMarker::McpDataChannelClosed {
                session_id: "peer-a".to_string(),
                reason: "closed".to_string()
            })
        );
        assert_eq!(
            parse_video_worker_marker("TXING_MCP_DATACHANNEL_ERROR sessionId=peer-a detail=bad"),
            Some(VideoWorkerMarker::McpDataChannelError {
                session_id: Some("peer-a".to_string()),
                detail: "bad".to_string()
            })
        );
        assert_eq!(parse_video_worker_marker("INFO normal log"), None);
    }

    #[test]
    fn native_kvs_worker_output_is_visible_in_default_logs() {
        assert_eq!(video_worker_output_level("stdout"), Level::INFO);
        assert_eq!(video_worker_output_level("stderr"), Level::WARN);
    }

    #[tokio::test]
    async fn mcp_ipc_listener_binds_under_runtime_directory() {
        let socket_dir = PathBuf::from(format!("/tmp/tx-mcp-{}-{}", process::id(), now_ms()));
        let socket_path = socket_dir.join("nested").join("mcp.sock");

        let listener = bind_mcp_ipc_listener(socket_path.to_str().unwrap()).unwrap();
        assert!(socket_path.exists());

        drop(listener);
        fs::remove_file(&socket_path).unwrap();
        fs::remove_dir_all(socket_dir).unwrap();
    }

    #[test]
    fn computes_video_credential_restart_before_expiry_with_floor() {
        let now = UNIX_EPOCH + Duration::from_secs(1_000);
        let long_expiry = now + Duration::from_secs(3_600);
        assert_eq!(
            video_credential_restart_at(long_expiry, now),
            long_expiry - Duration::from_secs(VIDEO_CREDENTIAL_RESTART_MARGIN_SECONDS)
        );
        let short_expiry = now + Duration::from_secs(60);
        assert_eq!(
            video_credential_restart_at(short_expiry, now),
            now + Duration::from_secs(VIDEO_CREDENTIAL_RESTART_MIN_SECONDS)
        );
    }

    #[test]
    fn video_worker_command_includes_mcp_socket_and_ipv6_environment() {
        let (event_tx, _event_rx) = mpsc::unbounded_channel();
        let run_config = VideoWorkerRunConfig {
            command: "txing-board-kvs-master".to_string(),
            mcp_webrtc_socket_path: "/tmp/mcp.sock".to_string(),
            kvs_prefer_ipv6: true,
            kvs_disable_ipv4_turn: true,
            region: "eu-central-1".to_string(),
            channel_name: "unit-local-board-video".to_string(),
            credentials: IotTemporaryCredentials {
                access_key_id: "akid".to_string(),
                secret_access_key: "secret".to_string(),
                session_token: "token".to_string(),
                expiration: "2026-05-14T12:00:00Z".to_string(),
            },
            expires_at: UNIX_EPOCH + Duration::from_secs(3_600),
            stop: Arc::new(AtomicBool::new(false)),
            event_tx,
        };
        let mut command = std::process::Command::new(&run_config.command);
        configure_video_worker_command(&mut command, &run_config);
        let envs = command
            .get_envs()
            .map(|(key, value)| {
                (
                    key.to_string_lossy().to_string(),
                    value.map(|value| value.to_string_lossy().to_string()),
                )
            })
            .collect::<BTreeMap<_, _>>();

        assert_eq!(
            envs.get("BOARD_MCP_WEBRTC_SOCKET_PATH"),
            Some(&Some("/tmp/mcp.sock".to_string()))
        );
        assert_eq!(
            envs.get("KVS_DUALSTACK_ENDPOINTS"),
            Some(&Some("ON".to_string()))
        );
        assert_eq!(
            envs.get("AWS_USE_DUALSTACK_ENDPOINT"),
            Some(&Some("true".to_string()))
        );
        assert_eq!(
            envs.get("KVS_DISABLE_IPV4_TURN"),
            Some(&Some("ON".to_string()))
        );
    }

    #[test]
    fn board_video_bridge_worker_config_maps_runtime_config_and_credentials() {
        let mut config = config();
        config.kvs_prefer_ipv6 = false;
        config.kvs_disable_ipv4_turn = true;
        let response = build_worker_config_response(
            &config,
            IotTemporaryCredentials {
                access_key_id: "akid".to_string(),
                secret_access_key: "secret".to_string(),
                session_token: "token".to_string(),
                expiration: "2026-05-14T12:00:00Z".to_string(),
            },
        )
        .unwrap();

        assert_eq!(response.region, "eu-central-1");
        assert_eq!(response.channel_name, "unit-local-board-video");
        assert_eq!(response.client_id, "unit-local-board-kvs-master");
        assert_eq!(
            response.mcp_data_channel_label,
            MCP_WEBRTC_DATA_CHANNEL_LABEL
        );
        assert_eq!(
            response.mcp_response_timeout_ms,
            DEFAULT_MCP_RESPONSE_TIMEOUT_MS
        );
        assert!(!response.prefer_ipv6);
        assert!(response.disable_ipv4_turn);
        let credentials = response.credentials.unwrap();
        assert_eq!(credentials.access_key_id, "akid");
        assert_eq!(credentials.secret_access_key, "secret");
        assert_eq!(credentials.session_token, "token");
        assert_eq!(credentials.expires_at.unwrap().seconds, 1_778_760_000);
    }

    #[tokio::test]
    async fn mcp_bridge_open_session_does_not_grant_active_control() {
        let publisher = FakePublisher::default();
        let mut state = runtime_state();
        state
            .handle_mcp_ipc_event(
                &publisher,
                RuntimeMcpIpcEvent::Open {
                    session_id: "session-a".to_string(),
                    transport: "webrtc-datachannel".to_string(),
                    peer_id: Some("peer-a".to_string()),
                },
                now_ms(),
            )
            .await
            .unwrap();

        assert!(state.mcp.active.is_none());
        assert!(publisher.messages().is_empty());
    }

    #[tokio::test]
    async fn board_video_bridge_serves_video_state_and_mcp_over_unix_socket() {
        let temp_dir = PathBuf::from(format!("/tmp/txing-bvb-{}-{}", process::id(), now_ms()));
        let socket_path = temp_dir.join("bridge.sock");
        let mut config = config();
        config.board_video_bridge_socket_path = socket_path.to_string_lossy().to_string();
        let (video_event_tx, mut video_events) = mpsc::unbounded_channel();
        let (mcp_event_tx, mut mcp_events) = mpsc::unbounded_channel();
        let server = start_board_video_bridge_server(config, video_event_tx, mcp_event_tx).unwrap();

        let connector_path = socket_path.clone();
        let channel = tonic::transport::Endpoint::try_from("http://[::]:50051")
            .unwrap()
            .connect_with_connector(tower::service_fn(move |_| {
                let path = connector_path.clone();
                async move {
                    UnixStream::connect(path)
                        .await
                        .map(hyper_util::rt::TokioIo::new)
                }
            }))
            .await
            .unwrap();
        let mut client =
            board_video_bridge::board_video_bridge_client::BoardVideoBridgeClient::new(channel);

        client
            .report_video_state(board_video_bridge::VideoState {
                state: board_video_bridge::video_state::State::Ready as i32,
                viewer_count: 2,
                error: String::new(),
            })
            .await
            .unwrap();
        assert_eq!(
            video_events.recv().await.unwrap(),
            VideoWorkerEvent::Ready {
                worker_version: None
            }
        );
        assert_eq!(
            video_events.recv().await.unwrap(),
            VideoWorkerEvent::ViewerConnected { connected: true }
        );

        client
            .open_mcp_session(board_video_bridge::OpenMcpSessionRequest {
                mcp_session_id: "session-a".to_string(),
                transport: "webrtc-datachannel".to_string(),
                peer_id: "peer-a".to_string(),
            })
            .await
            .unwrap();
        match mcp_events.recv().await.unwrap() {
            RuntimeMcpIpcEvent::Open {
                session_id,
                transport,
                peer_id,
            } => {
                assert_eq!(session_id, "session-a");
                assert_eq!(transport, "webrtc-datachannel");
                assert_eq!(peer_id.as_deref(), Some("peer-a"));
            }
            other => panic!("unexpected MCP event: {other:?}"),
        }

        let mut request_client = client.clone();
        let response_task = tokio::spawn(async move {
            request_client
                .handle_mcp(board_video_bridge::McpRequest {
                    mcp_session_id: "session-a".to_string(),
                    payload: br#"{"jsonrpc":"2.0","id":1,"method":"ping"}"#.to_vec(),
                })
                .await
                .unwrap()
                .into_inner()
        });
        match mcp_events.recv().await.unwrap() {
            RuntimeMcpIpcEvent::Request {
                session_id,
                payload,
                response_tx,
            } => {
                assert_eq!(session_id, "session-a");
                assert!(payload.contains("\"method\":\"ping\""));
                response_tx
                    .send(Some(r#"{"jsonrpc":"2.0","id":1,"result":{}}"#.to_string()))
                    .unwrap();
            }
            other => panic!("unexpected MCP event: {other:?}"),
        }
        let response = response_task.await.unwrap();
        assert!(response.has_payload);
        assert_eq!(
            String::from_utf8(response.payload).unwrap(),
            r#"{"jsonrpc":"2.0","id":1,"result":{}}"#
        );

        client
            .close_mcp_session(board_video_bridge::CloseMcpSessionRequest {
                mcp_session_id: "session-a".to_string(),
                reason: "test done".to_string(),
            })
            .await
            .unwrap();
        match mcp_events.recv().await.unwrap() {
            RuntimeMcpIpcEvent::Close { session_id, reason } => {
                assert_eq!(session_id, "session-a");
                assert_eq!(reason, "test done");
            }
            other => panic!("unexpected MCP event: {other:?}"),
        }

        server.shutdown().await;
    }

    #[test]
    fn video_restart_backoff_is_bounded_and_resettable() {
        let mut backoff = VideoRestartBackoff::default();

        assert_eq!(
            backoff.next_delay(),
            Duration::from_secs(VIDEO_RESTART_BACKOFF_INITIAL_SECONDS)
        );
        assert_eq!(backoff.next_delay(), Duration::from_secs(2));
        assert_eq!(backoff.next_delay(), Duration::from_secs(4));
        for _ in 0..10 {
            backoff.next_delay();
        }
        assert_eq!(
            backoff.next_delay(),
            Duration::from_secs(VIDEO_RESTART_BACKOFF_MAX_SECONDS)
        );

        backoff.reset();
        assert_eq!(
            backoff.next_delay(),
            Duration::from_secs(VIDEO_RESTART_BACKOFF_INITIAL_SECONDS)
        );
    }

    #[test]
    fn mcp_active_control_enforces_single_session_epoch_and_expiry() {
        let mut mcp = McpServer::new(Duration::from_millis(DEFAULT_MCP_ACTIVE_TTL_MS));

        let (active, stop_required) = mcp
            .activate(
                "session-a",
                Some("operator".to_string()),
                "mqtt-jsonrpc",
                false,
                1_000,
            )
            .unwrap();
        assert!(!stop_required);
        assert_eq!(active.session_id, "session-a");
        assert_eq!(active.actor.as_deref(), Some("operator"));
        assert_eq!(active.epoch, 1);
        assert_eq!(active.expires_at_ms, 6_000);
        assert!(
            mcp.activate("session-b", None, "mqtt-jsonrpc", false, 1_500,)
                .unwrap_err()
                .to_string()
                .contains("active control busy")
        );
        let (takeover, stop_required) = mcp
            .activate(
                "session-b",
                Some("operator-b".to_string()),
                "webrtc-datachannel",
                true,
                1_600,
            )
            .unwrap();
        assert!(stop_required);
        assert_eq!(takeover.session_id, "session-b");
        assert_eq!(takeover.actor.as_deref(), Some("operator-b"));
        assert_eq!(takeover.transport, "webrtc-datachannel");
        assert_eq!(takeover.epoch, active.epoch + 1);
        assert_eq!(takeover.expires_at_ms, 6_600);
        assert!(
            mcp.renew_active("session-a", active.epoch, 1_700)
                .unwrap_err()
                .to_string()
                .contains("no active control")
        );
        let released_takeover = mcp
            .release_active("session-b", takeover.epoch, 1_800)
            .unwrap();
        assert!(released_takeover);

        let (active, stop_required) = mcp
            .activate(
                "session-a",
                Some("operator".to_string()),
                "mqtt-jsonrpc",
                false,
                1_900,
            )
            .unwrap();
        assert!(!stop_required);
        assert!(
            mcp.renew_active("session-a", active.epoch + 1, 2_000)
                .unwrap_err()
                .to_string()
                .contains("stale active control epoch")
        );

        let renewed = mcp.renew_active("session-a", active.epoch, 2_000).unwrap();
        assert_eq!(renewed.epoch, active.epoch);
        assert_eq!(renewed.expires_at_ms, 7_000);

        let released = mcp
            .release_active("session-a", active.epoch, 2_100)
            .unwrap();
        assert!(released);
        assert!(
            mcp.renew_active("session-a", active.epoch, 2_200)
                .unwrap_err()
                .to_string()
                .contains("no active control")
        );

        let (expired, stop_required) = mcp
            .activate("session-a", None, "mqtt-jsonrpc", false, 3_000)
            .unwrap();
        assert!(!stop_required);
        assert!(
            mcp.renew_active("session-a", expired.epoch, 8_000)
                .unwrap_err()
                .to_string()
                .contains("no active control")
        );
    }

    #[test]
    fn mcp_status_updates_are_kept_off_cmd_vel_hot_path() {
        let cmd_vel_publish = serde_json::json!({
            "name": "cmd_vel.publish",
            "arguments": {"epoch": 1, "twist": {}}
        });
        let robot_state = serde_json::json!({"name": "robot.get_state"});
        let activate = serde_json::json!({"name": "control.activate"});
        let renew = serde_json::json!({"name": "control.renew_active"});
        let release = serde_json::json!({"name": "control.release_active"});

        assert!(!mcp_request_updates_status("initialize", None));
        assert!(!mcp_request_updates_status(
            "tools/call",
            Some(&cmd_vel_publish)
        ));
        assert!(!mcp_request_updates_status(
            "tools/call",
            Some(&robot_state)
        ));
        assert!(mcp_request_updates_status("tools/call", Some(&activate)));
        assert!(mcp_request_updates_status("tools/call", Some(&renew)));
        assert!(mcp_request_updates_status("tools/call", Some(&release)));
    }

    #[tokio::test]
    async fn cmd_vel_publish_delegates_to_hardware_worker_with_active_deadline() {
        let hardware = FakeHardwareClient::default();
        let probe = hardware.clone();
        let mut runtime =
            RuntimeState::new_with_hardware(config(), Some(Box::new(hardware))).unwrap();
        let active = runtime
            .handle_mcp_tool(
                "session-a",
                "control.activate",
                &serde_json::json!({"actor": "operator"}),
                1_000,
            )
            .await
            .unwrap();
        let epoch = active["activeControl"]["epoch"].as_u64().unwrap();

        let response = runtime
            .handle_mcp_tool(
                "session-a",
                "cmd_vel.publish",
                &serde_json::json!({
                    "epoch": epoch,
                    "twist": {
                        "linear": {"x": 0.25, "y": 0.0, "z": 0.0},
                        "angular": {"x": 0.0, "y": 0.0, "z": 0.0}
                    }
                }),
                1_100,
            )
            .await
            .unwrap();

        assert_eq!(response["motion"]["leftSpeed"], 50);
        assert_eq!(response["activeExpiresAtMs"], 6_000);
        assert_eq!(probe.calls(), vec!["apply:6000".to_string()]);
    }

    #[tokio::test]
    async fn cmd_vel_publish_rejects_when_hardware_worker_is_unavailable() {
        let mut runtime = RuntimeState::new_with_hardware(
            config(),
            Some(Box::new(FakeHardwareClient::unavailable())),
        )
        .unwrap();
        let active = runtime
            .handle_mcp_tool(
                "session-a",
                "control.activate",
                &serde_json::json!({"actor": "operator"}),
                1_000,
            )
            .await
            .unwrap();
        let epoch = active["activeControl"]["epoch"].as_u64().unwrap();

        let err = runtime
            .handle_mcp_tool(
                "session-a",
                "cmd_vel.publish",
                &serde_json::json!({
                    "epoch": epoch,
                    "twist": {
                        "linear": {"x": 0.25, "y": 0.0, "z": 0.0},
                        "angular": {"x": 0.0, "y": 0.0, "z": 0.0}
                    }
                }),
                1_100,
            )
            .await
            .unwrap_err();
        assert!(err.to_string().contains("hardware worker unavailable"));
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
    fn daemon_env_template_contains_forward_runtime_defaults() {
        let template = DEFAULT_DAEMON_ENV_TEMPLATE;
        let parsed = parse_env_file_contents(template).unwrap();
        let get = |key: &str| {
            parsed
                .get(key)
                .unwrap_or_else(|| panic!("missing daemon env template key {key}"))
        };
        assert!(template.contains("export TXING_DAEMON_CAPABILITIES=board,mcp,video"));
        assert!(template.contains(&format!(
            "export TXING_CAPABILITY_TTL_SECONDS={DEFAULT_CAPABILITY_TTL_SECONDS}"
        )));
        assert!(template.contains(&format!(
            "export TXING_HEARTBEAT_SECONDS={DEFAULT_HEARTBEAT_SECONDS}"
        )));
        assert!(template.contains(&format!(
            "export TXING_BOARD_VIDEO_BRIDGE_SOCKET_PATH={DEFAULT_BOARD_VIDEO_BRIDGE_SOCKET_PATH}"
        )));
        assert!(template.contains(&format!(
            "export TXING_HARDWARE_WORKER_SOCKET_PATH={DEFAULT_HARDWARE_WORKER_SOCKET_PATH}"
        )));
        assert!(template.contains(&format!(
            "export TXING_HARDWARE_WORKER_TIMEOUT_MS={DEFAULT_HARDWARE_WORKER_TIMEOUT_MS}"
        )));
        assert!(!template.contains("TXING_KVS_MASTER_COMMAND"));
        assert!(!template.contains("TXING_MCP_WEBRTC_SOCKET_PATH"));
        assert_eq!(get("TXING_KVS_PREFER_IPV6"), "true");
        assert_eq!(get("TXING_KVS_DISABLE_IPV4_TURN"), "false");
        assert!(
            template.contains(
                "export TXING_BOARD_VIDEO_CHANNEL_NAME={{TXING_BOARD_VIDEO_CHANNEL_NAME}}"
            )
        );
        assert!(!template.contains("AWS_DEFAULT_REGION"));
        assert!(!template.contains("TXING_BOARD_VIDEO_REGION"));
        assert!(!template.contains("export BOARD_DRIVE_"));
        assert!(!template.contains("export BOARD_VIDEO_"));
        assert_eq!(get("TXING_MOTOR_ENABLED"), "true");
        assert_eq!(get("TXING_MOTOR_PWM_SYSFS_ROOT"), "/sys/class/pwm");
        assert_eq!(get("TXING_MOTOR_WATCHDOG_TIMEOUT_MS"), "5000");
    }

    #[test]
    fn loads_env_file_from_config_dir() {
        let config_dir = test_temp_dir("config-dir");
        let env_file = config_dir.join(DEFAULT_ENV_FILE_NAME);
        fs::create_dir_all(&config_dir).unwrap();
        fs::write(
            &env_file,
            "export TXING_THING_ID=unit-local\nexport AWS_REGION=eu-central-1\n",
        )
        .unwrap();

        let process_env = BTreeMap::from([(
            "TXING_DAEMON_CONFIG_DIR".to_string(),
            config_dir.display().to_string(),
        )]);
        let cli = Cli::try_parse_from(["daemon"]).unwrap();
        let loaded = load_env_file_for_cli(&cli, &process_env).unwrap();

        assert_eq!(loaded.path, Some(env_file));
        assert_eq!(
            loaded.values.get("TXING_THING_ID").map(String::as_str),
            Some("unit-local")
        );
        fs::remove_dir_all(config_dir).unwrap();
    }

    #[test]
    fn loads_env_file_from_xdg_then_home() {
        let root = test_temp_dir("xdg-home");
        let xdg_env_file = root
            .join("xdg")
            .join(DEFAULT_CONFIG_SUBDIR)
            .join(DEFAULT_ENV_FILE_NAME);
        let home_env_file = root
            .join("home")
            .join(".config")
            .join(DEFAULT_CONFIG_SUBDIR)
            .join(DEFAULT_ENV_FILE_NAME);
        fs::create_dir_all(xdg_env_file.parent().unwrap()).unwrap();
        fs::create_dir_all(home_env_file.parent().unwrap()).unwrap();
        fs::write(&xdg_env_file, "TXING_THING_ID=from-xdg\n").unwrap();
        fs::write(&home_env_file, "TXING_THING_ID=from-home\n").unwrap();

        let cli = Cli::try_parse_from(["daemon"]).unwrap();
        let process_env = BTreeMap::from([
            (
                "XDG_CONFIG_HOME".to_string(),
                root.join("xdg").display().to_string(),
            ),
            ("HOME".to_string(), root.join("home").display().to_string()),
        ]);
        let loaded = load_env_file_for_cli(&cli, &process_env).unwrap();
        assert_eq!(loaded.path, Some(xdg_env_file));
        assert_eq!(
            loaded.values.get("TXING_THING_ID").map(String::as_str),
            Some("from-xdg")
        );

        let process_env =
            BTreeMap::from([("HOME".to_string(), root.join("home").display().to_string())]);
        let loaded = load_env_file_for_cli(&cli, &process_env).unwrap();
        assert_eq!(loaded.path, Some(home_env_file));
        assert_eq!(
            loaded.values.get("TXING_THING_ID").map(String::as_str),
            Some("from-home")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn colocated_cert_paths_default_to_env_file_directory() {
        let mut file_env = file_env();
        file_env.remove("TXING_IOT_CERT_FILE");
        file_env.remove("TXING_IOT_PRIVATE_KEY_FILE");
        file_env.remove("TXING_IOT_ROOT_CA_FILE");
        let env_file_dir = Path::new("/home/txing/.config/txing/unit-daemon");
        let cli = Cli::try_parse_from(["daemon", "--client-id", "unit-local-daemon-test"]).unwrap();
        let config = RuntimeConfig::from_sources_with_env_file_dir(
            cli,
            &BTreeMap::new(),
            &file_env,
            Some(env_file_dir),
        )
        .unwrap();

        assert_eq!(
            config.iot_cert_file,
            "/home/txing/.config/txing/unit-daemon/certificate.pem.crt"
        );
        assert_eq!(
            config.iot_private_key_file,
            "/home/txing/.config/txing/unit-daemon/private.pem.key"
        );
        assert_eq!(
            config.iot_root_ca_file,
            "/home/txing/.config/txing/unit-daemon/AmazonRootCA1.pem"
        );
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
        assert_eq!(config.kvs_master_command, DEFAULT_KVS_MASTER_COMMAND);
        assert_eq!(
            config.board_video_bridge_socket_path,
            DEFAULT_BOARD_VIDEO_BRIDGE_SOCKET_PATH
        );
        assert_eq!(config.video_region, "from-file");
        assert_eq!(config.video_channel_name, "from-cli-board-video");
        assert_eq!(
            config.hardware_worker_socket_path,
            DEFAULT_HARDWARE_WORKER_SOCKET_PATH
        );
        assert_eq!(
            config.hardware_worker_timeout,
            Duration::from_millis(DEFAULT_HARDWARE_WORKER_TIMEOUT_MS)
        );
        assert_eq!(
            config.capabilities,
            vec![
                BOARD_CAPABILITY.to_string(),
                MCP_CAPABILITY.to_string(),
                VIDEO_CAPABILITY.to_string()
            ]
        );
        assert_eq!(config.cloudwatch_logging, None);
    }

    #[test]
    fn cloudwatch_config_uses_precedence_and_defaults() {
        let mut file_env = file_env();
        file_env.insert(
            "TXING_CLOUDWATCH_LOG_GROUP".to_string(),
            "txing/town-file/rig-file/unit-local".to_string(),
        );
        file_env.insert(
            "TXING_CLOUDWATCH_LOG_STREAM".to_string(),
            "daemon/file".to_string(),
        );
        file_env.insert(
            "TXING_CLOUDWATCH_LOG_LEVEL".to_string(),
            "debug".to_string(),
        );
        file_env.insert(
            "TXING_CLOUDWATCH_LOG_RETENTION_DAYS".to_string(),
            "7".to_string(),
        );
        let process_env = BTreeMap::from([(
            "TXING_CLOUDWATCH_LOG_STREAM".to_string(),
            "daemon/process".to_string(),
        )]);
        let cli = Cli::try_parse_from([
            "daemon",
            "--client-id",
            "unit-local-daemon-test",
            "--cloudwatch-log-group",
            "txing/town-cli/rig-cli/unit-local",
            "--cloudwatch-log-retention-days",
            "30",
        ])
        .unwrap();
        let config = RuntimeConfig::from_sources(cli, &process_env, &file_env).unwrap();

        assert_eq!(
            config.cloudwatch_logging,
            Some(CloudWatchLogConfig {
                log_group: "txing/town-cli/rig-cli/unit-local".to_string(),
                log_stream: "daemon/process".to_string(),
                level: CloudWatchLogLevel::Debug,
                retention_days: 30,
            })
        );
    }

    #[test]
    fn cloudwatch_config_defaults_stream_level_and_retention() {
        let config = runtime_config_from_args(&[
            "daemon",
            "--client-id",
            "unit-local-daemon-test",
            "--cloudwatch-log-group",
            "txing/town-local/rig-local/unit-local",
        ])
        .unwrap();

        assert_eq!(config.cloudwatch_logging, Some(cloudwatch_log_config()));
    }

    #[test]
    fn cloudwatch_config_requires_group_when_other_cloudwatch_options_are_set() {
        assert!(
            runtime_config_from_args(&["daemon", "--cloudwatch-log-stream", "daemon/test"])
                .is_err()
        );
        assert!(
            runtime_config_from_args(&["daemon", "--cloudwatch-log-group", "txing/invalid:*"])
                .is_err()
        );
    }

    #[test]
    fn cli_defaults_to_declared_unit_capabilities() {
        let config = runtime_config_from_args(&["daemon"]).unwrap();

        assert_eq!(config.thing_id, "unit-local");
        assert_eq!(
            config.capabilities,
            vec![
                BOARD_CAPABILITY.to_string(),
                MCP_CAPABILITY.to_string(),
                VIDEO_CAPABILITY.to_string()
            ]
        );
        assert_eq!(config.capability_ttl, Duration::from_secs(150));
        assert_eq!(config.heartbeat, Duration::from_secs(60));
        assert_eq!(config.kvs_master_command, DEFAULT_KVS_MASTER_COMMAND);
        assert_eq!(
            config.board_video_bridge_socket_path,
            DEFAULT_BOARD_VIDEO_BRIDGE_SOCKET_PATH
        );
        assert_eq!(config.video_region, "eu-central-1");
        assert_eq!(config.video_channel_name, "unit-local-board-video");
        assert_eq!(
            config.hardware_worker_socket_path,
            DEFAULT_HARDWARE_WORKER_SOCKET_PATH
        );
        assert_eq!(
            config.hardware_worker_timeout,
            Duration::from_millis(DEFAULT_HARDWARE_WORKER_TIMEOUT_MS)
        );
        assert!(config.client_id.starts_with("unit-local-daemon-"));
        assert_eq!(config.cloudwatch_logging, None);
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
        assert!(runtime_config_from_args(&["daemon", "--capability", "camera"]).is_err());
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
        let sdk_credentials = iot_temporary_credentials_to_sdk(credentials).unwrap();
        assert!(sdk_credentials.expiry().is_some());
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
    fn builds_structured_cloudwatch_log_message() {
        let base_fields = CloudWatchLogBaseFields {
            thing_id: "unit-local".to_string(),
            client_id: "unit-local-daemon-test".to_string(),
            iot_role_alias: "txing-daemon-unit-local".to_string(),
            aws_region: "eu-central-1".to_string(),
        };
        let message = build_cloudwatch_log_message(
            &base_fields,
            "INFO",
            "txing_unit_daemon",
            "read sparkplug shadow",
            BTreeMap::from([(
                "sparkplug_redcon".to_string(),
                Value::String("4".to_string()),
            )]),
            1234,
        )
        .unwrap();
        let parsed: Value = serde_json::from_str(&message).unwrap();

        assert_eq!(parsed["timestamp"], 1234);
        assert_eq!(parsed["level"], "INFO");
        assert_eq!(parsed["target"], "txing_unit_daemon");
        assert_eq!(parsed["message"], "read sparkplug shadow");
        assert_eq!(parsed["thing_id"], "unit-local");
        assert_eq!(parsed["client_id"], "unit-local-daemon-test");
        assert_eq!(parsed["iot_role_alias"], "txing-daemon-unit-local");
        assert_eq!(parsed["aws_region"], "eu-central-1");
        assert_eq!(parsed["sparkplug_redcon"], "4");
    }

    #[test]
    fn cloudwatch_debug_fields_preserve_json_shapes_when_possible() {
        assert_eq!(
            debug_field_to_json_value(r#"["board"]"#),
            Value::Array(vec![Value::String("board".to_string())])
        );
        assert_eq!(debug_field_to_json_value("4"), Value::Number(4.into()));
        assert_eq!(
            debug_field_to_json_value("ConnectionSuccessEvent { ok: true }"),
            Value::String("ConnectionSuccessEvent { ok: true }".to_string())
        );
    }

    #[test]
    fn cloudwatch_batch_flushes_by_event_count_and_size() {
        let records = (0..CLOUDWATCH_LOG_BATCH_MAX_EVENTS)
            .map(|index| cloudwatch_log_record(&format!("event-{index}"), index as i64))
            .collect::<Vec<_>>();
        assert!(cloudwatch_log_batch_should_flush(&records));

        let mut oversized = Vec::new();
        push_cloudwatch_log_batch_record(
            &mut oversized,
            cloudwatch_log_record(&"x".repeat(CLOUDWATCH_LOG_BATCH_MAX_BYTES), 1),
        );
        assert!(oversized.is_empty());
    }

    #[tokio::test]
    async fn cloudwatch_writer_sets_up_group_retention_and_stream() {
        let fake = Arc::new(FakeCloudWatchLogsClient::default());
        fake.set_create_log_group_result(Err(CloudWatchLogClientError::new(
            CloudWatchLogClientErrorKind::AlreadyExists,
            "group exists",
        )));
        fake.set_create_log_stream_result(Err(CloudWatchLogClientError::new(
            CloudWatchLogClientErrorKind::AlreadyExists,
            "stream exists",
        )));
        let writer = CloudWatchLogWriter::new(cloudwatch_log_config(), fake.clone());

        writer.ensure_ready().await.unwrap();

        assert_eq!(
            fake.calls(),
            vec![
                "create-log-group:txing/town-local/rig-local/unit-local",
                "put-retention:txing/town-local/rig-local/unit-local:14",
                "create-log-stream:txing/town-local/rig-local/unit-local:daemon/unit-local-daemon-test",
            ]
        );
    }

    #[tokio::test]
    async fn cloudwatch_writer_retries_missing_stream_after_setup() {
        let fake = Arc::new(FakeCloudWatchLogsClient::default());
        fake.push_put_result(Err(CloudWatchLogClientError::new(
            CloudWatchLogClientErrorKind::NotFound,
            "stream missing",
        )));
        fake.push_put_result(Ok(CloudWatchPutLogEventsResult {
            next_sequence_token: Some("next".to_string()),
        }));
        let writer = CloudWatchLogWriter::new(cloudwatch_log_config(), fake.clone());

        let result = writer
            .put_log_events_with_retry(vec![cloudwatch_log_record("first", 1)], None)
            .await
            .unwrap();

        assert_eq!(result.next_sequence_token.as_deref(), Some("next"));
        assert_eq!(fake.puts().len(), 2);
        assert_eq!(
            fake.calls(),
            vec![
                "create-log-group:txing/town-local/rig-local/unit-local",
                "put-retention:txing/town-local/rig-local/unit-local:14",
                "create-log-stream:txing/town-local/rig-local/unit-local:daemon/unit-local-daemon-test",
            ]
        );
    }

    #[tokio::test]
    async fn cloudwatch_writer_retries_invalid_sequence_token() {
        let fake = Arc::new(FakeCloudWatchLogsClient::default());
        fake.push_put_result(Err(CloudWatchLogClientError::new(
            CloudWatchLogClientErrorKind::InvalidSequenceToken {
                expected: Some("expected".to_string()),
            },
            "invalid token",
        )));
        fake.push_put_result(Ok(CloudWatchPutLogEventsResult {
            next_sequence_token: Some("next".to_string()),
        }));
        let writer = CloudWatchLogWriter::new(cloudwatch_log_config(), fake.clone());

        let result = writer
            .put_log_events_with_retry(
                vec![cloudwatch_log_record("first", 1)],
                Some("stale".to_string()),
            )
            .await
            .unwrap();
        let puts = fake.puts();

        assert_eq!(result.next_sequence_token.as_deref(), Some("next"));
        assert_eq!(puts.len(), 2);
        assert_eq!(puts[0].sequence_token.as_deref(), Some("stale"));
        assert_eq!(puts[1].sequence_token.as_deref(), Some("expected"));
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
