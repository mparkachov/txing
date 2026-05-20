use std::collections::{BTreeSet, HashMap};
use std::fmt::{Debug, Display};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, anyhow, bail};
use async_trait::async_trait;
use aws_sdk_ecs::types::{
    AssignPublicIp, AwsVpcConfiguration, LaunchType, NetworkConfiguration, Tag,
};
use aws_sdk_iotdataplane::primitives::Blob;
use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use serde::{Deserialize, Serialize};
use serde_json::{Number, Value, json};

pub const CLOUD_MCU_THING_TYPE: &str = "cloud-mcu";
pub const CLOUD_RIG_THING_TYPE: &str = "cloud";
pub const THING_INDEX_NAME: &str = "AWS_Things";
pub const CLOUD_MCU_SEARCH_QUERY: &str = "thingTypeName:cloud-mcu";
pub const CLOUD_MCU_SEARCH_PAGE_SIZE: i32 = 100;
pub const SPARKPLUG_NAMESPACE: &str = "spBv1.0";
pub const CAPABILITY_SPARKPLUG: &str = "sparkplug";
pub const CAPABILITY_SQS: &str = "sqs";
pub const CAPABILITY_POWER: &str = "power";
pub const CAPABILITY_ECS: &str = "ecs";
pub const REDCON_READY: u8 = 1;
pub const REDCON_WAKEUP: u8 = 3;
pub const REDCON_SLEEP: u8 = 4;
pub const NODE_BDSEQ: u64 = 1;
pub const TICK_OFFSETS_SECONDS: [i32; 10] = [0, 6, 12, 18, 24, 30, 36, 42, 48, 54];
pub const COMMAND_STATUS_SUCCEEDED: &str = "succeeded";
pub const COMMAND_STATUS_FAILED: &str = "failed";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CloudMcuDevice {
    pub thing_name: String,
    pub town_id: String,
    pub rig_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SearchPage {
    pub devices: Vec<CloudMcuDevice>,
    pub next_token: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ThingDescription {
    pub thing_type_name: Option<String>,
    pub attributes: HashMap<String, String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CloudMcuTick {
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "thingName")]
    pub thing_name: String,
    #[serde(rename = "townId")]
    pub town_id: String,
    #[serde(rename = "rigId")]
    pub rig_id: String,
    #[serde(rename = "tickOffsetSeconds")]
    pub tick_offset_seconds: i32,
    #[serde(rename = "scheduledAtMs")]
    pub scheduled_at_ms: i64,
}

impl CloudMcuTick {
    pub fn new(device: &CloudMcuDevice, tick_offset_seconds: i32, scheduled_at_ms: i64) -> Self {
        Self {
            schema_version: "1.0".to_string(),
            thing_name: device.thing_name.clone(),
            town_id: device.town_id.clone(),
            rig_id: device.rig_id.clone(),
            tick_offset_seconds,
            scheduled_at_ms,
        }
    }

    pub fn validate(&self) -> Result<()> {
        if self.schema_version != "1.0" {
            bail!("cloud MCU tick schemaVersion must be 1.0");
        }
        segment(&self.thing_name, "thingName")?;
        segment(&self.town_id, "townId")?;
        segment(&self.rig_id, "rigId")?;
        if !TICK_OFFSETS_SECONDS.contains(&self.tick_offset_seconds) {
            bail!("tickOffsetSeconds must be one of 0,6,...,54");
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EcsTaskState {
    pub task_arn: String,
    pub last_status: Option<String>,
}

impl EcsTaskState {
    pub fn is_active(&self) -> bool {
        !matches!(
            self.last_status.as_deref(),
            Some("STOPPED") | Some("DEPROVISIONING")
        )
    }
}

#[async_trait]
pub trait CloudAws: Send + Sync {
    async fn search_cloud_mcu_devices(&self, next_token: Option<&str>) -> Result<SearchPage>;
    async fn describe_thing(&self, thing_name: &str) -> Result<ThingDescription>;
    async fn publish(&self, topic: &str, payload: Vec<u8>) -> Result<()>;
    async fn send_tick(&self, tick: &CloudMcuTick, delay_seconds: i32) -> Result<()>;
    async fn get_thing_shadow(
        &self,
        thing_name: &str,
        shadow_name: &str,
    ) -> Result<Option<Vec<u8>>>;
    async fn update_thing_shadow(
        &self,
        thing_name: &str,
        shadow_name: &str,
        payload: Vec<u8>,
    ) -> Result<()>;
    async fn describe_task(&self, task_arn: &str) -> Result<Option<EcsTaskState>>;
    async fn run_task(&self, thing_name: &str, rig_id: &str) -> Result<EcsTaskState>;
    async fn stop_task(&self, task_arn: &str) -> Result<()>;
}

#[derive(Clone)]
pub struct AwsCloudClient {
    iot: aws_sdk_iot::Client,
    iot_data: aws_sdk_iotdataplane::Client,
    sqs: aws_sdk_sqs::Client,
    ecs: aws_sdk_ecs::Client,
    tick_queue_url: Option<String>,
    ecs_cluster: Option<String>,
    ecs_task_definition: Option<String>,
    ecs_subnets: Vec<String>,
    ecs_security_groups: Vec<String>,
}

impl AwsCloudClient {
    pub async fn from_env() -> Result<Self> {
        let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
        let iot = aws_sdk_iot::Client::new(&config);
        let endpoint = iot
            .describe_endpoint()
            .endpoint_type("iot:Data-ATS")
            .send()
            .await
            .context("describe AWS IoT data endpoint")?
            .endpoint_address()
            .ok_or_else(|| anyhow!("AWS IoT describe_endpoint returned no endpointAddress"))?
            .to_string();
        let data_config = aws_sdk_iotdataplane::config::Builder::from(&config)
            .endpoint_url(format!("https://{endpoint}"))
            .build();
        Ok(Self {
            iot,
            iot_data: aws_sdk_iotdataplane::Client::from_conf(data_config),
            sqs: aws_sdk_sqs::Client::new(&config),
            ecs: aws_sdk_ecs::Client::new(&config),
            tick_queue_url: env_nonempty("CLOUD_MCU_TICK_QUEUE_URL"),
            ecs_cluster: env_nonempty("CLOUD_MCU_ECS_CLUSTER"),
            ecs_task_definition: env_nonempty("CLOUD_MCU_ECS_TASK_DEFINITION"),
            ecs_subnets: env_csv("CLOUD_MCU_ECS_SUBNETS"),
            ecs_security_groups: env_csv("CLOUD_MCU_ECS_SECURITY_GROUPS"),
        })
    }

    fn required_tick_queue_url(&self) -> Result<&str> {
        self.tick_queue_url
            .as_deref()
            .ok_or_else(|| anyhow!("CLOUD_MCU_TICK_QUEUE_URL is required"))
    }

    fn required_ecs_cluster(&self) -> Result<&str> {
        self.ecs_cluster
            .as_deref()
            .ok_or_else(|| anyhow!("CLOUD_MCU_ECS_CLUSTER is required"))
    }

    fn required_ecs_task_definition(&self) -> Result<&str> {
        self.ecs_task_definition
            .as_deref()
            .ok_or_else(|| anyhow!("CLOUD_MCU_ECS_TASK_DEFINITION is required"))
    }

    fn required_ecs_subnets(&self) -> Result<Vec<String>> {
        if self.ecs_subnets.is_empty() {
            bail!("CLOUD_MCU_ECS_SUBNETS is required");
        }
        Ok(self.ecs_subnets.clone())
    }

    fn required_ecs_security_groups(&self) -> Result<Vec<String>> {
        if self.ecs_security_groups.is_empty() {
            bail!("CLOUD_MCU_ECS_SECURITY_GROUPS is required");
        }
        Ok(self.ecs_security_groups.clone())
    }
}

#[async_trait]
impl CloudAws for AwsCloudClient {
    async fn search_cloud_mcu_devices(&self, next_token: Option<&str>) -> Result<SearchPage> {
        let mut request = self
            .iot
            .search_index()
            .index_name(THING_INDEX_NAME)
            .query_string(CLOUD_MCU_SEARCH_QUERY)
            .max_results(CLOUD_MCU_SEARCH_PAGE_SIZE);
        if let Some(token) = next_token {
            request = request.next_token(token);
        }
        let response = request
            .send()
            .await
            .context("search cloud MCU things in AWS IoT index")?;
        let devices = response
            .things()
            .iter()
            .filter_map(|thing| {
                let thing_name = thing.thing_name()?.trim();
                if thing_name.is_empty() {
                    return None;
                }
                let attributes = thing.attributes()?;
                let town_id = attributes.get("townId")?.trim();
                let rig_id = attributes.get("rigId")?.trim();
                if town_id.is_empty() || rig_id.is_empty() {
                    return None;
                }
                Some(CloudMcuDevice {
                    thing_name: thing_name.to_string(),
                    town_id: town_id.to_string(),
                    rig_id: rig_id.to_string(),
                })
            })
            .collect();
        Ok(SearchPage {
            devices,
            next_token: response
                .next_token()
                .map(str::trim)
                .filter(|token| !token.is_empty())
                .map(ToOwned::to_owned),
        })
    }

    async fn describe_thing(&self, thing_name: &str) -> Result<ThingDescription> {
        let response = self
            .iot
            .describe_thing()
            .thing_name(thing_name)
            .send()
            .await
            .context("describe AWS IoT thing")?;
        Ok(ThingDescription {
            thing_type_name: response.thing_type_name().map(ToOwned::to_owned),
            attributes: response.attributes().cloned().unwrap_or_default(),
        })
    }

    async fn publish(&self, topic: &str, payload: Vec<u8>) -> Result<()> {
        self.iot_data
            .publish()
            .topic(topic)
            .qos(1)
            .payload(Blob::new(payload))
            .send()
            .await
            .context("publish AWS IoT message")?;
        Ok(())
    }

    async fn send_tick(&self, tick: &CloudMcuTick, delay_seconds: i32) -> Result<()> {
        self.sqs
            .send_message()
            .queue_url(self.required_tick_queue_url()?)
            .delay_seconds(delay_seconds)
            .message_body(serde_json::to_string(tick)?)
            .send()
            .await
            .context("send cloud MCU SQS tick")?;
        Ok(())
    }

    async fn get_thing_shadow(
        &self,
        thing_name: &str,
        shadow_name: &str,
    ) -> Result<Option<Vec<u8>>> {
        match self
            .iot_data
            .get_thing_shadow()
            .thing_name(thing_name)
            .shadow_name(shadow_name)
            .send()
            .await
        {
            Ok(output) => Ok(output.payload().map(|payload| payload.as_ref().to_vec())),
            Err(err) if error_is_not_found(&err) => Ok(None),
            Err(err) => Err(anyhow!(err)).context("get AWS IoT thing shadow"),
        }
    }

    async fn update_thing_shadow(
        &self,
        thing_name: &str,
        shadow_name: &str,
        payload: Vec<u8>,
    ) -> Result<()> {
        self.iot_data
            .update_thing_shadow()
            .thing_name(thing_name)
            .shadow_name(shadow_name)
            .payload(Blob::new(payload))
            .send()
            .await
            .context("update AWS IoT thing shadow")?;
        Ok(())
    }

    async fn describe_task(&self, task_arn: &str) -> Result<Option<EcsTaskState>> {
        let response = self
            .ecs
            .describe_tasks()
            .cluster(self.required_ecs_cluster()?)
            .tasks(task_arn)
            .send()
            .await
            .context("describe cloud MCU ECS task")?;
        Ok(response.tasks().first().and_then(task_state_from_aws_task))
    }

    async fn run_task(&self, thing_name: &str, rig_id: &str) -> Result<EcsTaskState> {
        let network = NetworkConfiguration::builder()
            .awsvpc_configuration(
                AwsVpcConfiguration::builder()
                    .set_subnets(Some(self.required_ecs_subnets()?))
                    .set_security_groups(Some(self.required_ecs_security_groups()?))
                    .assign_public_ip(AssignPublicIp::Enabled)
                    .build()?,
            )
            .build();
        let response = self
            .ecs
            .run_task()
            .cluster(self.required_ecs_cluster()?)
            .task_definition(self.required_ecs_task_definition()?)
            .launch_type(LaunchType::Fargate)
            .network_configuration(network)
            .tags(
                Tag::builder()
                    .key("txing:thingName")
                    .value(thing_name)
                    .build(),
            )
            .tags(Tag::builder().key("txing:rigId").value(rig_id).build())
            .send()
            .await
            .context("run cloud MCU ECS task")?;
        response
            .tasks()
            .first()
            .and_then(task_state_from_aws_task)
            .ok_or_else(|| anyhow!("ECS RunTask returned no task ARN"))
    }

    async fn stop_task(&self, task_arn: &str) -> Result<()> {
        self.ecs
            .stop_task()
            .cluster(self.required_ecs_cluster()?)
            .task(task_arn)
            .reason("txing cloud MCU REDCON 4")
            .send()
            .await
            .context("stop cloud MCU ECS task")?;
        Ok(())
    }
}

fn task_state_from_aws_task(task: &aws_sdk_ecs::types::Task) -> Option<EcsTaskState> {
    Some(EcsTaskState {
        task_arn: task.task_arn()?.to_string(),
        last_status: task.last_status().map(ToOwned::to_owned),
    })
}

fn error_is_not_found(error: &(impl Debug + Display)) -> bool {
    let text = format!("{error:?}");
    text.contains("ResourceNotFoundException") || text.contains("NotFoundException")
}

fn env_nonempty(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn env_csv(name: &str) -> Vec<String> {
    std::env::var(name)
        .ok()
        .map(|value| {
            value
                .split(',')
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToOwned::to_owned)
                .collect()
        })
        .unwrap_or_default()
}

pub fn utc_now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time before Unix epoch")
        .as_millis() as i64
}

pub fn segment(value: &str, field_name: &str) -> Result<String> {
    let text = value.trim();
    if text.is_empty() {
        bail!("{field_name} must not be empty");
    }
    if text.contains('/') || text.contains('+') || text.contains('#') {
        bail!("{field_name} must be a literal MQTT segment");
    }
    Ok(text.to_string())
}

pub fn build_node_topic(town_id: &str, message_type: &str, rig_id: &str) -> Result<String> {
    Ok(format!(
        "{}/{}/{}/{}",
        SPARKPLUG_NAMESPACE,
        segment(town_id, "townId")?,
        segment(message_type, "messageType")?,
        segment(rig_id, "rigId")?
    ))
}

pub fn build_device_topic(
    town_id: &str,
    message_type: &str,
    rig_id: &str,
    thing_name: &str,
) -> Result<String> {
    Ok(format!(
        "{}/{}/{}/{}/{}",
        SPARKPLUG_NAMESPACE,
        segment(town_id, "townId")?,
        segment(message_type, "messageType")?,
        segment(rig_id, "rigId")?,
        segment(thing_name, "thingName")?
    ))
}

#[derive(Debug, Clone, PartialEq)]
enum MetricValue {
    Int32(i32),
    UInt64(u64),
    Boolean(bool),
    String(String),
}

#[derive(Debug, Clone, PartialEq)]
struct Metric {
    name: String,
    value: MetricValue,
}

impl Metric {
    fn int32(name: impl Into<String>, value: i32) -> Self {
        Self {
            name: name.into(),
            value: MetricValue::Int32(value),
        }
    }

    fn uint64(name: impl Into<String>, value: u64) -> Self {
        Self {
            name: name.into(),
            value: MetricValue::UInt64(value),
        }
    }

    fn boolean(name: impl Into<String>, value: bool) -> Self {
        Self {
            name: name.into(),
            value: MetricValue::Boolean(value),
        }
    }

    fn string(name: impl Into<String>, value: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            value: MetricValue::String(value.into()),
        }
    }
}

pub fn build_node_birth_payload(seq: u64, timestamp: i64) -> Result<Vec<u8>> {
    encode_payload(
        timestamp as u64,
        Some(seq),
        &[
            Metric::uint64("bdSeq", NODE_BDSEQ),
            Metric::int32("redcon", REDCON_READY as i32),
        ],
    )
}

fn build_device_report_payload(
    redcon: u8,
    seq: u64,
    timestamp: i64,
    mut metrics: Vec<Metric>,
) -> Result<Vec<u8>> {
    let mut all_metrics = vec![Metric::int32("redcon", i32::from(redcon))];
    all_metrics.append(&mut metrics);
    encode_payload(timestamp as u64, Some(seq), &all_metrics)
}

fn build_capability_metrics(power: bool) -> Vec<Metric> {
    vec![
        Metric::boolean(format!("capability.{CAPABILITY_SPARKPLUG}"), true),
        Metric::boolean(format!("capability.{CAPABILITY_SQS}"), true),
        Metric::boolean(format!("capability.{CAPABILITY_POWER}"), power),
        Metric::boolean(format!("capability.{CAPABILITY_ECS}"), false),
    ]
}

fn build_command_result_metrics(
    seq: u64,
    target_redcon: u8,
    status: &str,
    message: Option<&str>,
) -> Vec<Metric> {
    let mut metrics = vec![
        Metric::string("redconCommandStatus", status),
        Metric::int32("redconCommandSeq", seq as i32),
        Metric::string("redconCommandId", format!("dcmd-{seq}")),
        Metric::int32("redconCommandTarget", i32::from(target_redcon)),
    ];
    if let Some(message) = message.filter(|value| !value.is_empty()) {
        metrics.push(Metric::string("redconCommandMessage", message));
    }
    metrics
}

fn encode_payload(timestamp: u64, seq: Option<u64>, metrics: &[Metric]) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    append_varint_field(&mut bytes, 1, timestamp)?;
    for metric in metrics {
        let metric_bytes = encode_metric(metric)?;
        append_bytes_field(&mut bytes, 2, &metric_bytes)?;
    }
    if let Some(seq) = seq {
        append_varint_field(&mut bytes, 3, seq)?;
    }
    Ok(bytes)
}

fn encode_metric(metric: &Metric) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    append_string_field(&mut bytes, 1, &metric.name)?;
    match &metric.value {
        MetricValue::Int32(value) => {
            append_varint_field(&mut bytes, 4, 3)?;
            append_varint_field(&mut bytes, 10, *value as u64)?;
        }
        MetricValue::UInt64(value) => {
            append_varint_field(&mut bytes, 4, 8)?;
            append_varint_field(&mut bytes, 11, *value)?;
        }
        MetricValue::Boolean(value) => {
            append_varint_field(&mut bytes, 4, 11)?;
            append_varint_field(&mut bytes, 14, u64::from(*value))?;
        }
        MetricValue::String(value) => {
            append_varint_field(&mut bytes, 4, 12)?;
            append_string_field(&mut bytes, 15, value)?;
        }
    }
    Ok(bytes)
}

fn append_key(bytes: &mut Vec<u8>, field_number: u64, wire_type: u64) -> Result<()> {
    append_varint(bytes, (field_number << 3) | wire_type)
}

fn append_varint_field(bytes: &mut Vec<u8>, field_number: u64, value: u64) -> Result<()> {
    append_key(bytes, field_number, 0)?;
    append_varint(bytes, value)
}

fn append_string_field(bytes: &mut Vec<u8>, field_number: u64, value: &str) -> Result<()> {
    append_bytes_field(bytes, field_number, value.as_bytes())
}

fn append_bytes_field(bytes: &mut Vec<u8>, field_number: u64, value: &[u8]) -> Result<()> {
    append_key(bytes, field_number, 2)?;
    append_varint(bytes, value.len() as u64)?;
    bytes.extend_from_slice(value);
    Ok(())
}

fn append_varint(bytes: &mut Vec<u8>, mut value: u64) -> Result<()> {
    loop {
        let next = (value & 0x7f) as u8;
        value >>= 7;
        if value == 0 {
            bytes.push(next);
            return Ok(());
        }
        bytes.push(next | 0x80);
    }
}

fn read_varint(data: &[u8], start_offset: usize) -> Result<(u64, usize)> {
    let mut value = 0_u64;
    let mut shift = 0_u32;
    let mut offset = start_offset;
    while offset < data.len() {
        let byte = data[offset];
        offset += 1;
        value |= u64::from(byte & 0x7f) << shift;
        if (byte & 0x80) == 0 {
            return Ok((value, offset));
        }
        shift += 7;
        if shift > 63 {
            bail!("Sparkplug varint is too large");
        }
    }
    bail!("Unexpected end of Sparkplug payload");
}

fn read_length_delimited(data: &[u8], start_offset: usize) -> Result<(&[u8], usize)> {
    let (length, next_offset) = read_varint(data, start_offset)?;
    let end_offset = next_offset + length as usize;
    if end_offset > data.len() {
        bail!("Unexpected end of Sparkplug payload");
    }
    Ok((&data[next_offset..end_offset], end_offset))
}

fn skip_field(data: &[u8], start_offset: usize, wire_type: u64) -> Result<usize> {
    match wire_type {
        0 => Ok(read_varint(data, start_offset)?.1),
        1 => Ok(start_offset + 8),
        2 => Ok(read_length_delimited(data, start_offset)?.1),
        5 => Ok(start_offset + 4),
        _ => bail!("Unsupported Sparkplug wire type {wire_type}"),
    }
}

fn read_key(data: &[u8], start_offset: usize) -> Result<(u64, u64, usize)> {
    let (key, next_offset) = read_varint(data, start_offset)?;
    Ok((key >> 3, key & 0x07, next_offset))
}

fn decode_redcon_command(payload: &[u8]) -> Result<Option<(u8, u64)>> {
    let mut offset = 0;
    let mut seq = 0_u64;
    let mut redcon = None;
    while offset < payload.len() {
        let (field_number, wire_type, next_offset) = read_key(payload, offset)?;
        offset = next_offset;
        match (field_number, wire_type) {
            (2, 2) => {
                let (metric, next) = read_length_delimited(payload, offset)?;
                offset = next;
                if redcon.is_none() {
                    redcon = decode_redcon_metric(metric)?;
                }
            }
            (3, 0) => {
                let (value, next) = read_varint(payload, offset)?;
                seq = value;
                offset = next;
            }
            _ => offset = skip_field(payload, offset, wire_type)?,
        }
    }
    Ok(redcon.map(|redcon| (redcon, seq)))
}

fn decode_redcon_metric(metric: &[u8]) -> Result<Option<u8>> {
    let mut offset = 0;
    let mut name = String::new();
    let mut int_value: Option<i32> = None;
    while offset < metric.len() {
        let (field_number, wire_type, next_offset) = read_key(metric, offset)?;
        offset = next_offset;
        match (field_number, wire_type) {
            (1, 2) => {
                let (value, next) = read_length_delimited(metric, offset)?;
                name = std::str::from_utf8(value)?.to_string();
                offset = next;
            }
            (10, 0) => {
                let (value, next) = read_varint(metric, offset)?;
                int_value = Some(value as i32);
                offset = next;
            }
            _ => offset = skip_field(metric, offset, wire_type)?,
        }
    }
    if name != "redcon" {
        return Ok(None);
    }
    let Some(value) = int_value else {
        return Ok(None);
    };
    if !(1..=4).contains(&value) {
        return Ok(None);
    }
    Ok(Some(value as u8))
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct PendingCommand {
    seq: u64,
    target_redcon: u8,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct PowerState {
    desired_redcon: u8,
    powered: bool,
    ecs_task_arn: Option<String>,
    ecs_task_status: Option<String>,
    pending_command: Option<PendingCommand>,
    sparkplug_born: bool,
}

impl Default for PowerState {
    fn default() -> Self {
        Self {
            desired_redcon: REDCON_SLEEP,
            powered: false,
            ecs_task_arn: None,
            ecs_task_status: None,
            pending_command: None,
            sparkplug_born: false,
        }
    }
}

impl PowerState {
    fn from_shadow(payload: Option<&[u8]>) -> Result<Self> {
        let Some(payload) = payload else {
            return Ok(Self::default());
        };
        let decoded: Value = serde_json::from_slice(payload).context("decode power shadow")?;
        let reported = decoded
            .get("state")
            .and_then(Value::as_object)
            .and_then(|state| state.get("reported"))
            .and_then(Value::as_object);
        let Some(reported) = reported else {
            return Ok(Self::default());
        };
        let desired_redcon = match reported.get("desiredRedcon").and_then(Value::as_u64) {
            Some(3) => REDCON_WAKEUP,
            _ => REDCON_SLEEP,
        };
        let pending_command = reported
            .get("pendingCommand")
            .and_then(Value::as_object)
            .and_then(|pending| {
                let seq = pending.get("seq")?.as_u64()?;
                let target_redcon = match pending.get("targetRedcon")?.as_u64()? {
                    3 => REDCON_WAKEUP,
                    4 => REDCON_SLEEP,
                    _ => return None,
                };
                Some(PendingCommand { seq, target_redcon })
            });
        Ok(Self {
            desired_redcon,
            powered: reported
                .get("powered")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            ecs_task_arn: reported
                .get("ecsTaskArn")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToOwned::to_owned),
            ecs_task_status: reported
                .get("ecsTaskStatus")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToOwned::to_owned),
            pending_command,
            sparkplug_born: reported
                .get("sparkplugBorn")
                .and_then(Value::as_bool)
                .unwrap_or(false),
        })
    }

    fn to_shadow_update(&self) -> Value {
        json!({
            "state": {
                "reported": {
                    "desiredRedcon": self.desired_redcon,
                    "powered": self.powered,
                    "ecsTaskArn": self.ecs_task_arn,
                    "ecsTaskStatus": self.ecs_task_status,
                    "pendingCommand": self.pending_command.as_ref().map(|pending| json!({
                        "seq": pending.seq,
                        "targetRedcon": pending.target_redcon,
                    })),
                    "sparkplugBorn": self.sparkplug_born,
                }
            }
        })
    }
}

pub struct CloudRigScheduler<'a, A: CloudAws + ?Sized> {
    aws: &'a A,
}

impl<'a, A: CloudAws + ?Sized> CloudRigScheduler<'a, A> {
    pub fn new(aws: &'a A) -> Self {
        Self { aws }
    }

    pub async fn handle_schedule_with_now(&self, now_ms: i64) -> Result<Value> {
        let devices = discover_cloud_mcu_devices(self.aws).await?;
        let rigs = devices
            .iter()
            .map(|device| (device.town_id.clone(), device.rig_id.clone()))
            .collect::<BTreeSet<_>>();

        let mut published_rigs = Vec::new();
        for (town_id, rig_id) in &rigs {
            let topic = build_node_topic(town_id, "NBIRTH", rig_id)?;
            let seq = (now_ms / 60_000).max(0) as u64;
            self.aws
                .publish(&topic, build_node_birth_payload(seq, now_ms)?)
                .await?;
            published_rigs.push(json!({"townId": town_id, "rigId": rig_id}));
        }

        let mut sent_ticks = 0_usize;
        for device in &devices {
            for offset in TICK_OFFSETS_SECONDS {
                self.aws
                    .send_tick(&CloudMcuTick::new(device, offset, now_ms), offset)
                    .await?;
                sent_ticks += 1;
            }
        }

        Ok(json!({
            "eventType": "schedule",
            "deviceCount": devices.len(),
            "rigCount": rigs.len(),
            "tickCount": sent_ticks,
            "publishedRigs": published_rigs,
        }))
    }
}

async fn discover_cloud_mcu_devices<A: CloudAws + ?Sized>(aws: &A) -> Result<Vec<CloudMcuDevice>> {
    let mut devices = Vec::new();
    let mut next_token: Option<String> = None;
    loop {
        let page = aws.search_cloud_mcu_devices(next_token.as_deref()).await?;
        devices.extend(page.devices);
        next_token = page.next_token;
        if next_token.is_none() {
            devices.sort_by(|left, right| left.thing_name.cmp(&right.thing_name));
            return Ok(devices);
        }
    }
}

pub struct CloudMcuRuntime<'a, A: CloudAws + ?Sized> {
    aws: &'a A,
}

impl<'a, A: CloudAws + ?Sized> CloudMcuRuntime<'a, A> {
    pub fn new(aws: &'a A) -> Self {
        Self { aws }
    }

    pub async fn handle_tick_with_now(&self, tick: CloudMcuTick, now_ms: i64) -> Result<Value> {
        tick.validate()?;
        self.validate_device_identity(&tick.thing_name, &tick.town_id, &tick.rig_id)
            .await?;
        let shadow = self
            .aws
            .get_thing_shadow(&tick.thing_name, CAPABILITY_POWER)
            .await?;
        let mut power = PowerState::from_shadow(shadow.as_deref())?;

        let actual_redcon = if power.desired_redcon == REDCON_WAKEUP {
            self.ensure_task_running(&tick, &mut power).await?;
            if power.powered {
                REDCON_WAKEUP
            } else {
                REDCON_SLEEP
            }
        } else {
            self.ensure_task_stopped(&mut power).await?;
            REDCON_SLEEP
        };

        self.update_sqs_shadow(&tick).await?;

        let mut extra_metrics = build_capability_metrics(actual_redcon == REDCON_WAKEUP);
        let mut command_result = None;
        if power
            .pending_command
            .as_ref()
            .is_some_and(|pending| pending.target_redcon == actual_redcon)
        {
            let pending = power.pending_command.take().expect("checked above");
            extra_metrics.extend(build_command_result_metrics(
                pending.seq,
                pending.target_redcon,
                COMMAND_STATUS_SUCCEEDED,
                None,
            ));
            command_result = Some(json!({
                "seq": pending.seq,
                "targetRedcon": pending.target_redcon,
                "status": COMMAND_STATUS_SUCCEEDED,
            }));
        }

        let message_type = if power.sparkplug_born {
            "DDATA"
        } else {
            "DBIRTH"
        };
        let topic =
            build_device_topic(&tick.town_id, message_type, &tick.rig_id, &tick.thing_name)?;
        self.aws
            .publish(
                &topic,
                build_device_report_payload(
                    actual_redcon,
                    tick.tick_offset_seconds as u64,
                    now_ms,
                    extra_metrics,
                )?,
            )
            .await?;
        power.sparkplug_born = true;
        self.update_power_shadow(&tick.thing_name, &power).await?;

        Ok(json!({
            "eventType": "sqsTick",
            "thingName": tick.thing_name,
            "redcon": actual_redcon,
            "messageType": message_type,
            "powered": power.powered,
            "ecsTaskArn": power.ecs_task_arn,
            "commandResult": command_result,
        }))
    }

    pub async fn handle_dcmd_with_now(&self, event: &Value, now_ms: i64) -> Result<Value> {
        let topic = event
            .get("mqttTopic")
            .and_then(Value::as_str)
            .ok_or_else(|| anyhow!("DCMD event is missing mqttTopic"))?;
        let (town_id, rig_id, thing_name) =
            parse_dcmd_topic(topic).ok_or_else(|| anyhow!("unsupported DCMD topic: {topic}"))?;
        self.validate_device_identity(&thing_name, &town_id, &rig_id)
            .await?;
        let payload = decode_event_payload(event).context("decode DCMD payload")?;
        let Some((redcon, seq)) = decode_redcon_command(&payload)? else {
            return Ok(json!({"eventType": "dcmd", "thingName": thing_name, "status": "ignored"}));
        };
        if !matches!(redcon, REDCON_WAKEUP | REDCON_SLEEP) {
            let topic = build_device_topic(&town_id, "DDATA", &rig_id, &thing_name)?;
            let mut metrics = build_capability_metrics(false);
            metrics.extend(build_command_result_metrics(
                seq,
                redcon,
                COMMAND_STATUS_FAILED,
                Some("cloud-mcu supports REDCON 3 and 4 only"),
            ));
            self.aws
                .publish(
                    &topic,
                    build_device_report_payload(REDCON_SLEEP, seq, now_ms, metrics)?,
                )
                .await?;
            return Ok(json!({
                "eventType": "dcmd",
                "thingName": thing_name,
                "status": COMMAND_STATUS_FAILED,
                "targetRedcon": redcon,
            }));
        }

        let shadow = self
            .aws
            .get_thing_shadow(&thing_name, CAPABILITY_POWER)
            .await?;
        let mut power = PowerState::from_shadow(shadow.as_deref())?;
        power.desired_redcon = redcon;
        power.pending_command = Some(PendingCommand {
            seq,
            target_redcon: redcon,
        });
        self.update_power_shadow(&thing_name, &power).await?;
        Ok(json!({
            "eventType": "dcmd",
            "thingName": thing_name,
            "status": "accepted",
            "targetRedcon": redcon,
            "seq": seq,
        }))
    }

    async fn validate_device_identity(
        &self,
        thing_name: &str,
        town_id: &str,
        rig_id: &str,
    ) -> Result<()> {
        let description = self.aws.describe_thing(thing_name).await?;
        if description.thing_type_name.as_deref() != Some(CLOUD_MCU_THING_TYPE) {
            bail!("{thing_name} is not a cloud-mcu thing");
        }
        if description.attributes.get("townId").map(String::as_str) != Some(town_id) {
            bail!("{thing_name} townId does not match event");
        }
        if description.attributes.get("rigId").map(String::as_str) != Some(rig_id) {
            bail!("{thing_name} rigId does not match event");
        }
        Ok(())
    }

    async fn ensure_task_running(&self, tick: &CloudMcuTick, power: &mut PowerState) -> Result<()> {
        if let Some(task_arn) = power.ecs_task_arn.as_deref() {
            if let Some(task) = self.aws.describe_task(task_arn).await? {
                if task.is_active() {
                    power.powered = true;
                    power.ecs_task_arn = Some(task.task_arn);
                    power.ecs_task_status = task.last_status;
                    return Ok(());
                }
            }
        }
        let task = self.aws.run_task(&tick.thing_name, &tick.rig_id).await?;
        power.powered = task.is_active();
        power.ecs_task_arn = Some(task.task_arn);
        power.ecs_task_status = task.last_status;
        Ok(())
    }

    async fn ensure_task_stopped(&self, power: &mut PowerState) -> Result<()> {
        if let Some(task_arn) = power.ecs_task_arn.as_deref() {
            self.aws.stop_task(task_arn).await?;
        }
        power.powered = false;
        power.ecs_task_arn = None;
        power.ecs_task_status = None;
        Ok(())
    }

    async fn update_sqs_shadow(&self, tick: &CloudMcuTick) -> Result<()> {
        self.aws
            .update_thing_shadow(
                &tick.thing_name,
                CAPABILITY_SQS,
                serde_json::to_vec(&json!({
                    "state": {
                        "reported": {
                            "lastTickOffsetSeconds": tick.tick_offset_seconds,
                            "lastTickScheduledAtMs": tick.scheduled_at_ms,
                        }
                    }
                }))?,
            )
            .await
    }

    async fn update_power_shadow(&self, thing_name: &str, power: &PowerState) -> Result<()> {
        self.aws
            .update_thing_shadow(
                thing_name,
                CAPABILITY_POWER,
                serde_json::to_vec(&power.to_shadow_update())?,
            )
            .await
    }
}

fn parse_dcmd_topic(topic: &str) -> Option<(String, String, String)> {
    let parts: Vec<&str> = topic.split('/').collect();
    if parts.len() != 5 || parts[0] != SPARKPLUG_NAMESPACE || parts[2] != "DCMD" {
        return None;
    }
    if parts.iter().any(|part| part.is_empty()) {
        return None;
    }
    Some((
        parts[1].to_string(),
        parts[3].to_string(),
        parts[4].to_string(),
    ))
}

fn decode_event_payload(event: &Value) -> Result<Vec<u8>> {
    if let Some(payload_base64) = event.get("payloadBase64").and_then(Value::as_str) {
        return STANDARD
            .decode(payload_base64)
            .context("decode payloadBase64");
    }
    if let Some(raw_payload) = event.get("rawPayload").and_then(Value::as_str) {
        return Ok(raw_payload.as_bytes().to_vec());
    }
    bail!("event does not contain payloadBase64 or rawPayload")
}

pub async fn handle_rig_lambda_event_from_env<A: CloudAws + ?Sized>(
    _event: Value,
    aws: &A,
) -> Result<Value> {
    CloudRigScheduler::new(aws)
        .handle_schedule_with_now(utc_now_ms())
        .await
}

pub async fn handle_mcu_lambda_event_from_env<A: CloudAws + ?Sized>(
    event: Value,
    aws: &A,
) -> Result<Value> {
    handle_mcu_lambda_event_with_now(event, aws, utc_now_ms()).await
}

pub async fn handle_mcu_lambda_event_with_now<A: CloudAws + ?Sized>(
    event: Value,
    aws: &A,
    now_ms: i64,
) -> Result<Value> {
    let runtime = CloudMcuRuntime::new(aws);
    if event.get("mqttTopic").and_then(Value::as_str).is_some() {
        return runtime.handle_dcmd_with_now(&event, now_ms).await;
    }
    if let Some(records) = event.get("Records").and_then(Value::as_array) {
        let mut processed = Vec::new();
        for record in records {
            let body = record
                .get("body")
                .and_then(Value::as_str)
                .ok_or_else(|| anyhow!("SQS record is missing body"))?;
            let tick: CloudMcuTick = serde_json::from_str(body).context("decode SQS tick body")?;
            processed.push(runtime.handle_tick_with_now(tick, now_ms).await?);
        }
        return Ok(json!({
            "eventType": "sqsBatch",
            "processedCount": processed.len(),
            "processed": processed,
        }));
    }
    bail!("unsupported cloud MCU Lambda event")
}

#[allow(dead_code)]
fn number_i64(value: i64) -> Value {
    Value::Number(Number::from(value))
}

#[cfg(test)]
mod tests {
    use std::sync::{Arc, Mutex};

    use super::*;

    #[derive(Debug, Clone)]
    struct Published {
        topic: String,
        payload: Vec<u8>,
    }

    #[derive(Debug, Clone)]
    struct SentTick {
        tick: CloudMcuTick,
        delay_seconds: i32,
    }

    #[derive(Debug, Default)]
    struct FakeAws {
        pages: Mutex<Vec<SearchPage>>,
        descriptions: Mutex<HashMap<String, ThingDescription>>,
        published: Mutex<Vec<Published>>,
        sent_ticks: Mutex<Vec<SentTick>>,
        shadows: Mutex<HashMap<(String, String), Vec<u8>>>,
        tasks: Mutex<HashMap<String, EcsTaskState>>,
        run_task_count: Mutex<usize>,
        stopped_tasks: Mutex<Vec<String>>,
    }

    #[async_trait]
    impl CloudAws for FakeAws {
        async fn search_cloud_mcu_devices(&self, _next_token: Option<&str>) -> Result<SearchPage> {
            let mut pages = self.pages.lock().unwrap();
            if pages.is_empty() {
                return Ok(SearchPage {
                    devices: Vec::new(),
                    next_token: None,
                });
            }
            Ok(pages.remove(0))
        }

        async fn describe_thing(&self, thing_name: &str) -> Result<ThingDescription> {
            self.descriptions
                .lock()
                .unwrap()
                .get(thing_name)
                .cloned()
                .ok_or_else(|| anyhow!("missing thing {thing_name}"))
        }

        async fn publish(&self, topic: &str, payload: Vec<u8>) -> Result<()> {
            self.published.lock().unwrap().push(Published {
                topic: topic.to_string(),
                payload,
            });
            Ok(())
        }

        async fn send_tick(&self, tick: &CloudMcuTick, delay_seconds: i32) -> Result<()> {
            self.sent_ticks.lock().unwrap().push(SentTick {
                tick: tick.clone(),
                delay_seconds,
            });
            Ok(())
        }

        async fn get_thing_shadow(
            &self,
            thing_name: &str,
            shadow_name: &str,
        ) -> Result<Option<Vec<u8>>> {
            Ok(self
                .shadows
                .lock()
                .unwrap()
                .get(&(thing_name.to_string(), shadow_name.to_string()))
                .cloned())
        }

        async fn update_thing_shadow(
            &self,
            thing_name: &str,
            shadow_name: &str,
            payload: Vec<u8>,
        ) -> Result<()> {
            self.shadows
                .lock()
                .unwrap()
                .insert((thing_name.to_string(), shadow_name.to_string()), payload);
            Ok(())
        }

        async fn describe_task(&self, task_arn: &str) -> Result<Option<EcsTaskState>> {
            Ok(self.tasks.lock().unwrap().get(task_arn).cloned())
        }

        async fn run_task(&self, thing_name: &str, _rig_id: &str) -> Result<EcsTaskState> {
            let mut count = self.run_task_count.lock().unwrap();
            *count += 1;
            let task = EcsTaskState {
                task_arn: format!("arn:aws:ecs:task/{thing_name}-{count}"),
                last_status: Some("PENDING".to_string()),
            };
            self.tasks
                .lock()
                .unwrap()
                .insert(task.task_arn.clone(), task.clone());
            Ok(task)
        }

        async fn stop_task(&self, task_arn: &str) -> Result<()> {
            self.stopped_tasks
                .lock()
                .unwrap()
                .push(task_arn.to_string());
            Ok(())
        }
    }

    fn fake() -> Arc<FakeAws> {
        let aws = Arc::new(FakeAws::default());
        aws.descriptions.lock().unwrap().insert(
            "cloud-1".to_string(),
            ThingDescription {
                thing_type_name: Some(CLOUD_MCU_THING_TYPE.to_string()),
                attributes: HashMap::from([
                    ("townId".to_string(), "town-1".to_string()),
                    ("rigId".to_string(), "rig-1".to_string()),
                ]),
            },
        );
        aws
    }

    fn tick() -> CloudMcuTick {
        CloudMcuTick {
            schema_version: "1.0".to_string(),
            thing_name: "cloud-1".to_string(),
            town_id: "town-1".to_string(),
            rig_id: "rig-1".to_string(),
            tick_offset_seconds: 6,
            scheduled_at_ms: 1714380000000,
        }
    }

    fn redcon_command(redcon: u8, seq: u64) -> Vec<u8> {
        encode_payload(
            1714380000000,
            Some(seq),
            &[Metric::int32("redcon", i32::from(redcon))],
        )
        .unwrap()
    }

    #[tokio::test]
    async fn scheduler_publishes_rig_birth_and_ten_ticks_per_device() {
        let aws = fake();
        aws.pages.lock().unwrap().push(SearchPage {
            devices: vec![CloudMcuDevice {
                thing_name: "cloud-1".to_string(),
                town_id: "town-1".to_string(),
                rig_id: "rig-1".to_string(),
            }],
            next_token: None,
        });

        let result = CloudRigScheduler::new(aws.as_ref())
            .handle_schedule_with_now(1714380000000)
            .await
            .unwrap();

        assert_eq!(result["deviceCount"], 1);
        assert_eq!(result["tickCount"], 10);
        assert_eq!(
            aws.published.lock().unwrap()[0].topic,
            "spBv1.0/town-1/NBIRTH/rig-1"
        );
        let sent = aws.sent_ticks.lock().unwrap();
        assert_eq!(
            sent.iter()
                .map(|tick| tick.delay_seconds)
                .collect::<Vec<_>>(),
            TICK_OFFSETS_SECONDS
        );
        assert_eq!(sent[0].tick.thing_name, "cloud-1");
    }

    #[tokio::test]
    async fn dcmd_stores_desired_redcon_and_pending_command() {
        let aws = fake();
        let event = json!({
            "mqttTopic": "spBv1.0/town-1/DCMD/rig-1/cloud-1",
            "payloadBase64": STANDARD.encode(redcon_command(REDCON_WAKEUP, 7)),
        });

        let result = CloudMcuRuntime::new(aws.as_ref())
            .handle_dcmd_with_now(&event, 1714380000000)
            .await
            .unwrap();

        assert_eq!(result["status"], "accepted");
        let shadow = aws
            .shadows
            .lock()
            .unwrap()
            .get(&("cloud-1".to_string(), "power".to_string()))
            .cloned()
            .unwrap();
        let decoded: Value = serde_json::from_slice(&shadow).unwrap();
        assert_eq!(decoded["state"]["reported"]["desiredRedcon"], 3);
        assert_eq!(decoded["state"]["reported"]["pendingCommand"]["seq"], 7);
    }

    #[tokio::test]
    async fn first_tick_defaults_to_redcon_four_birth() {
        let aws = fake();

        let result = CloudMcuRuntime::new(aws.as_ref())
            .handle_tick_with_now(tick(), 1714380006000)
            .await
            .unwrap();

        assert_eq!(result["redcon"], 4);
        assert_eq!(result["messageType"], "DBIRTH");
        let published = aws.published.lock().unwrap();
        assert_eq!(published[0].topic, "spBv1.0/town-1/DBIRTH/rig-1/cloud-1");
        assert!(!published[0].payload.is_empty());
        let power = aws
            .shadows
            .lock()
            .unwrap()
            .get(&("cloud-1".to_string(), "power".to_string()))
            .cloned()
            .unwrap();
        let decoded: Value = serde_json::from_slice(&power).unwrap();
        assert_eq!(decoded["state"]["reported"]["powered"], false);
        assert_eq!(decoded["state"]["reported"]["sparkplugBorn"], true);
    }

    #[tokio::test]
    async fn redcon_three_tick_starts_task_and_completes_command() {
        let aws = fake();
        aws.shadows.lock().unwrap().insert(
            ("cloud-1".to_string(), "power".to_string()),
            serde_json::to_vec(&json!({
                "state": {
                    "reported": {
                        "desiredRedcon": 3,
                        "pendingCommand": {
                            "seq": 8,
                            "targetRedcon": 3
                        },
                        "sparkplugBorn": true
                    }
                }
            }))
            .unwrap(),
        );

        let result = CloudMcuRuntime::new(aws.as_ref())
            .handle_tick_with_now(tick(), 1714380006000)
            .await
            .unwrap();

        assert_eq!(result["redcon"], 3);
        assert_eq!(*aws.run_task_count.lock().unwrap(), 1);
        let power = aws
            .shadows
            .lock()
            .unwrap()
            .get(&("cloud-1".to_string(), "power".to_string()))
            .cloned()
            .unwrap();
        let decoded: Value = serde_json::from_slice(&power).unwrap();
        assert_eq!(decoded["state"]["reported"]["powered"], true);
        assert!(decoded["state"]["reported"]["pendingCommand"].is_null());
    }

    #[tokio::test]
    async fn redcon_four_tick_stops_tracked_task() {
        let aws = fake();
        aws.shadows.lock().unwrap().insert(
            ("cloud-1".to_string(), "power".to_string()),
            serde_json::to_vec(&json!({
                "state": {
                    "reported": {
                        "desiredRedcon": 4,
                        "powered": true,
                        "ecsTaskArn": "arn:aws:ecs:task/cloud-1",
                        "ecsTaskStatus": "RUNNING",
                        "pendingCommand": {
                            "seq": 9,
                            "targetRedcon": 4
                        },
                        "sparkplugBorn": true
                    }
                }
            }))
            .unwrap(),
        );

        let result = CloudMcuRuntime::new(aws.as_ref())
            .handle_tick_with_now(tick(), 1714380006000)
            .await
            .unwrap();

        assert_eq!(result["redcon"], 4);
        assert_eq!(
            aws.stopped_tasks.lock().unwrap().as_slice(),
            ["arn:aws:ecs:task/cloud-1"]
        );
        let power = aws
            .shadows
            .lock()
            .unwrap()
            .get(&("cloud-1".to_string(), "power".to_string()))
            .cloned()
            .unwrap();
        let decoded: Value = serde_json::from_slice(&power).unwrap();
        assert_eq!(decoded["state"]["reported"]["powered"], false);
        assert!(decoded["state"]["reported"]["ecsTaskArn"].is_null());
        assert!(decoded["state"]["reported"]["pendingCommand"].is_null());
    }
}
