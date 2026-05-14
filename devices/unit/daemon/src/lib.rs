use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::io::ErrorKind;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr, UdpSocket};
use std::path::{Path, PathBuf};
use std::process;
use std::sync::Arc;
use std::sync::Once;
use std::sync::atomic::{AtomicU64, Ordering};
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
use gneiss_mqtt::mqtt::{PublishPacket, QualityOfService};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::sync::{mpsc, oneshot};
use tokio::task::JoinHandle;
use tokio::time::{Instant, MissedTickBehavior, interval_at, timeout};
use tracing::field::{Field, Visit};
use tracing::{Event, Level, Metadata, Subscriber};
use tracing::{debug, info, warn};
use tracing_subscriber::EnvFilter;
use tracing_subscriber::Layer;
use tracing_subscriber::layer::Context as LayerContext;
use tracing_subscriber::prelude::*;

pub const SCHEMA_VERSION: &str = "2.0";
pub const ADAPTER_ID: &str = "dev.txing.unit.Daemon";
pub const BOARD_CAPABILITY: &str = "board";
pub const BOARD_SHADOW_NAME: &str = "board";
pub const SPARKPLUG_SHADOW_NAME: &str = "sparkplug";
pub const DEFAULT_CONFIG_SUBDIR: &str = "txing/unit-daemon";
pub const DEFAULT_ENV_FILE_NAME: &str = ".env";
pub const DEFAULT_IOT_CERT_FILE_NAME: &str = "certificate.pem.crt";
pub const DEFAULT_IOT_PRIVATE_KEY_FILE_NAME: &str = "private.pem.key";
pub const DEFAULT_IOT_ROOT_CA_FILE_NAME: &str = "AmazonRootCA1.pem";
pub const DEFAULT_CAPABILITY_TTL_SECONDS: u64 = 150;
pub const DEFAULT_HEARTBEAT_SECONDS: u64 = 60;
pub const DEFAULT_CLOUDWATCH_LOG_RETENTION_DAYS: i32 = 14;
pub const MQTT_PORT: u16 = 8883;
const MQTT_KEEP_ALIVE_SECONDS: u16 = 60;
const MQTT_CONNECT_WAIT_SECONDS: u64 = 15;
const MQTT_PUBLISH_OPERATION_TIMEOUT_SECONDS: u64 = 20;
const CLOUDWATCH_LOG_QUEUE_CAPACITY: usize = 4096;
const CLOUDWATCH_LOG_BATCH_MAX_EVENTS: usize = 100;
const CLOUDWATCH_LOG_BATCH_MAX_BYTES: usize = 256 * 1024;
const CLOUDWATCH_LOG_FLUSH_INTERVAL_SECONDS: u64 = 2;
const CLOUDWATCH_LOG_SHUTDOWN_TIMEOUT_SECONDS: u64 = 5;
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

    #[arg(long = "cloudwatch-log-group")]
    pub cloudwatch_log_group: Option<String>,

    #[arg(long = "cloudwatch-log-stream")]
    pub cloudwatch_log_stream: Option<String>,

    #[arg(long = "cloudwatch-log-level")]
    pub cloudwatch_log_level: Option<String>,

    #[arg(long = "cloudwatch-log-retention-days")]
    pub cloudwatch_log_retention_days: Option<i32>,
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
        let cloudwatch_logging = resolve_cloudwatch_log_config(
            cli.cloudwatch_log_group,
            cli.cloudwatch_log_stream,
            cli.cloudwatch_log_level,
            cli.cloudwatch_log_retention_days,
            process_env,
            file_env,
            &client_id,
        )?;

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

#[async_trait]
pub trait Publisher: Send + Sync {
    async fn publish(&self, message: PublishedMessage) -> Result<()>;
}

struct MqttPublisher {
    client: AsyncClientHandle,
}

impl MqttPublisher {
    async fn connect(config: &RuntimeConfig) -> Result<Self> {
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
        let listener = {
            let connected_sender = Arc::clone(&connected_sender);
            Arc::new(move |event: Arc<ClientEvent>| match event.as_ref() {
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
                    warn!(client_id = %event_client_id, event = %event, "mqtt disconnected");
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
        info!(
            thing_id = %self.config.thing_id,
            capabilities = ?self.config.capabilities,
            "publishing online state"
        );
        self.publish_board_shadow(publisher, build_online_board_report(addresses))
            .await?;
        self.publish_capabilities(publisher, true, observed_at_ms)
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
        self.publish_capabilities(publisher, true, observed_at_ms)
            .await
    }

    pub async fn publish_offline<P: Publisher + ?Sized>(
        &mut self,
        publisher: &P,
        observed_at_ms: u64,
    ) -> Result<()> {
        info!(thing_id = %self.config.thing_id, "publishing offline state");
        self.publish_board_shadow(publisher, build_offline_board_report())
            .await?;
        self.publish_capabilities(publisher, false, observed_at_ms)
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
    info!(
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
    let publisher = MqttPublisher::connect(&config).await?;
    let run_result = run_connected_runtime(config, &publisher).await;
    let stop_result = publisher.stop();
    if stop_result.is_ok() {
        info!("mqtt client stopped");
    }
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
                info!("shutdown signal received");
                break;
            }
            _ = heartbeat.tick() => {
                if let Err(err) = state.refresh_capabilities(publisher, now_ms()).await {
                    warn!(error = %format_args!("{err:#}"), "failed to refresh capability state");
                }
            }
        }
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

    for env_file in default_env_file_candidates(process_env) {
        match read_env_file(env_file, false) {
            Ok(loaded) if loaded.path.is_some() => return Ok(loaded),
            Ok(_) => {}
            Err(err) => return Err(err),
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
        candidates.push(
            Path::new(&xdg_config_home)
                .join(DEFAULT_CONFIG_SUBDIR)
                .join(DEFAULT_ENV_FILE_NAME),
        );
    }
    if let Some(home) = normalize_optional(process_env.get("HOME").cloned()) {
        candidates.push(
            Path::new(&home)
                .join(".config")
                .join(DEFAULT_CONFIG_SUBDIR)
                .join(DEFAULT_ENV_FILE_NAME),
        );
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
    use std::sync::Mutex;

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
    }

    #[async_trait]
    impl Publisher for FakePublisher {
        async fn publish(&self, message: PublishedMessage) -> Result<()> {
            self.messages.lock().unwrap().push(message);
            Ok(())
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
            capabilities: vec![BOARD_CAPABILITY.to_string()],
            capability_ttl: Duration::from_secs(150),
            heartbeat: Duration::from_secs(60),
            cloudwatch_logging: None,
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
                &[("capabilities".to_string(), r#"["board"]"#.to_string())],
            ),
            r#"info: starting unit daemon capabilities=["board"]"#
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
        assert_eq!(config.capabilities, vec![BOARD_CAPABILITY.to_string()]);
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
    fn cli_defaults_to_board_capability() {
        let config = runtime_config_from_args(&["daemon"]).unwrap();

        assert_eq!(config.thing_id, "unit-local");
        assert_eq!(config.capabilities, vec![BOARD_CAPABILITY.to_string()]);
        assert_eq!(config.capability_ttl, Duration::from_secs(150));
        assert_eq!(config.heartbeat, Duration::from_secs(60));
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
