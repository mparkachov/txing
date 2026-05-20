use std::collections::HashMap;
use std::fmt::{Debug, Display};

use anyhow::{Context, Result, anyhow, bail};
use async_trait::async_trait;
use aws_sdk_iotdataplane::primitives::Blob;
use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use serde_json::{Map, Number, Value, json};

pub const SPARKPLUG_NAMESPACE: &str = "spBv1.0";
pub const RIG_KIND_ATTRIBUTE: &str = "rigType";
const DEVICE_MESSAGE_TYPES: &[&str] = &["DBIRTH", "DDATA", "DDEATH"];
const NODE_MESSAGE_TYPES: &[&str] = &["NBIRTH", "NDATA", "NDEATH"];
const REPLACE_METRICS_MESSAGE_TYPES: &[&str] = &["DBIRTH", "NBIRTH"];
const MERGE_METRICS_MESSAGE_TYPES: &[&str] = &["DDATA", "NDATA"];
const CLEAR_METRICS_MESSAGE_TYPES: &[&str] = &["DDEATH", "NDEATH"];
const COMMAND_RESULT_METRIC_KEYS: &[&str] = &[
    "redconCommandId",
    "redconCommandObservedAt",
    "redconCommandSeq",
    "redconCommandStatus",
    "redconCommandTarget",
    "redconCommandMessage",
];

#[derive(Debug, Clone, PartialEq)]
pub struct SparkplugMessage {
    pub group_id: String,
    pub message_type: String,
    pub edge_node_id: String,
    pub device_id: Option<String>,
    pub seq: Option<i64>,
    pub sparkplug_timestamp: Option<i64>,
    pub metrics: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ThingDescription {
    pub thing_type_name: Option<String>,
    pub attributes: HashMap<String, String>,
}

#[async_trait]
pub trait WitnessAws: Send + Sync {
    async fn describe_thing(&self, thing_name: &str) -> Result<ThingDescription>;
    async fn get_sparkplug_shadow(&self, thing_name: &str) -> Result<Option<Value>>;
    async fn update_sparkplug_shadow(&self, thing_name: &str, payload: Value) -> Result<()>;
}

#[derive(Clone)]
pub struct AwsWitnessClient {
    iot: aws_sdk_iot::Client,
    iot_data: aws_sdk_iotdataplane::Client,
}

impl AwsWitnessClient {
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
        })
    }
}

#[async_trait]
impl WitnessAws for AwsWitnessClient {
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

    async fn get_sparkplug_shadow(&self, thing_name: &str) -> Result<Option<Value>> {
        match self
            .iot_data
            .get_thing_shadow()
            .thing_name(thing_name)
            .shadow_name("sparkplug")
            .send()
            .await
        {
            Ok(output) => {
                let Some(payload) = output.payload() else {
                    return Ok(None);
                };
                let decoded = serde_json::from_slice(payload.as_ref())
                    .context("decode sparkplug shadow payload")?;
                Ok(Some(decoded))
            }
            Err(err) if error_is_not_found(&err) => Ok(None),
            Err(err) => {
                tracing::warn!(thing = thing_name, error = %err, "Unable to read sparkplug shadow");
                Ok(None)
            }
        }
    }

    async fn update_sparkplug_shadow(&self, thing_name: &str, payload: Value) -> Result<()> {
        self.iot_data
            .update_thing_shadow()
            .thing_name(thing_name)
            .shadow_name("sparkplug")
            .payload(Blob::new(
                serde_json::to_vec(&payload).context("encode sparkplug shadow update")?,
            ))
            .send()
            .await
            .context("update sparkplug shadow")?;
        Ok(())
    }
}

fn error_is_not_found(error: &(impl Debug + Display)) -> bool {
    let text = format!("{error:?}");
    text.contains("ResourceNotFoundException") || text.contains("NotFoundException")
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

fn read_fixed32(data: &[u8], start_offset: usize) -> Result<(f32, usize)> {
    let end_offset = start_offset + 4;
    if end_offset > data.len() {
        bail!("Unexpected end of Sparkplug payload");
    }
    let mut bytes = [0_u8; 4];
    bytes.copy_from_slice(&data[start_offset..end_offset]);
    Ok((f32::from_le_bytes(bytes), end_offset))
}

fn read_fixed64(data: &[u8], start_offset: usize) -> Result<(f64, usize)> {
    let end_offset = start_offset + 8;
    if end_offset > data.len() {
        bail!("Unexpected end of Sparkplug payload");
    }
    let mut bytes = [0_u8; 8];
    bytes.copy_from_slice(&data[start_offset..end_offset]);
    Ok((f64::from_le_bytes(bytes), end_offset))
}

fn read_key(data: &[u8], start_offset: usize) -> Result<(u64, u64, usize)> {
    let (key, next_offset) = read_varint(data, start_offset)?;
    Ok((key >> 3, key & 0x07, next_offset))
}

fn skip_field(data: &[u8], start_offset: usize, wire_type: u64) -> Result<usize> {
    match wire_type {
        0 => Ok(read_varint(data, start_offset)?.1),
        1 => {
            let end_offset = start_offset + 8;
            if end_offset > data.len() {
                bail!("Unexpected end of Sparkplug payload");
            }
            Ok(end_offset)
        }
        2 => Ok(read_length_delimited(data, start_offset)?.1),
        5 => {
            let end_offset = start_offset + 4;
            if end_offset > data.len() {
                bail!("Unexpected end of Sparkplug payload");
            }
            Ok(end_offset)
        }
        _ => bail!("Unsupported Sparkplug wire type {wire_type}"),
    }
}

fn decode_metric(metric_bytes: &[u8]) -> Result<Option<(String, Value)>> {
    let mut offset = 0;
    let mut name = String::new();
    let mut int_value: Option<i64> = None;
    let mut long_value: Option<i64> = None;
    let mut float_value: Option<f64> = None;
    let mut double_value: Option<f64> = None;
    let mut bool_value: Option<bool> = None;
    let mut string_value: Option<String> = None;

    while offset < metric_bytes.len() {
        let (field_number, wire_type, next_offset) = read_key(metric_bytes, offset)?;
        offset = next_offset;
        match (field_number, wire_type) {
            (1, 2) => {
                let (raw_name, next) = read_length_delimited(metric_bytes, offset)?;
                name = std::str::from_utf8(raw_name)
                    .context("decode Sparkplug metric name")?
                    .to_string();
                offset = next;
            }
            (10, 0) => {
                let (value, next) = read_varint(metric_bytes, offset)?;
                int_value = Some(value as i64);
                offset = next;
            }
            (11, 0) => {
                let (value, next) = read_varint(metric_bytes, offset)?;
                long_value = Some(value as i64);
                offset = next;
            }
            (12, 5) => {
                let (value, next) = read_fixed32(metric_bytes, offset)?;
                float_value = Some(f64::from(value));
                offset = next;
            }
            (13, 1) => {
                let (value, next) = read_fixed64(metric_bytes, offset)?;
                double_value = Some(value);
                offset = next;
            }
            (12, 0) => {
                let (value, next) = read_varint(metric_bytes, offset)?;
                bool_value = Some(value != 0);
                offset = next;
            }
            (13, 2) => {
                let (raw_string, next) = read_length_delimited(metric_bytes, offset)?;
                string_value = Some(
                    std::str::from_utf8(raw_string)
                        .context("decode legacy Sparkplug string metric")?
                        .to_string(),
                );
                offset = next;
            }
            (14, 0) => {
                let (value, next) = read_varint(metric_bytes, offset)?;
                bool_value = Some(value != 0);
                offset = next;
            }
            (15, 2) => {
                let (raw_string, next) = read_length_delimited(metric_bytes, offset)?;
                string_value = Some(
                    std::str::from_utf8(raw_string)
                        .context("decode Sparkplug string metric")?
                        .to_string(),
                );
                offset = next;
            }
            _ => {
                offset = skip_field(metric_bytes, offset, wire_type)?;
            }
        }
    }

    if name.is_empty() {
        return Ok(None);
    }
    let value = if let Some(value) = bool_value {
        Value::Bool(value)
    } else if let Some(value) = int_value {
        json!(value)
    } else if let Some(value) = long_value {
        json!(value)
    } else if let Some(value) = float_value {
        Value::Number(Number::from_f64(value).ok_or_else(|| anyhow!("invalid float metric"))?)
    } else if let Some(value) = double_value {
        Value::Number(Number::from_f64(value).ok_or_else(|| anyhow!("invalid double metric"))?)
    } else if let Some(value) = string_value {
        Value::String(value)
    } else {
        return Ok(None);
    };
    Ok(Some((name, value)))
}

fn assign_metric_path(root: &mut Map<String, Value>, metric_name: &str, value: Value) {
    let normalized = metric_name.replace('.', "/");
    let parts: Vec<&str> = normalized
        .split('/')
        .filter(|part| !part.is_empty())
        .collect();
    if parts.is_empty() {
        return;
    }
    let mut current = root;
    for part in &parts[..parts.len() - 1] {
        let entry = current
            .entry((*part).to_string())
            .or_insert_with(|| Value::Object(Map::new()));
        if !entry.is_object() {
            *entry = Value::Object(Map::new());
        }
        current = entry.as_object_mut().expect("object just inserted");
    }
    current.insert(parts[parts.len() - 1].to_string(), value);
}

fn parse_topic(mqtt_topic: &str) -> Option<(String, String, String, Option<String>)> {
    let parts: Vec<&str> = mqtt_topic.split('/').collect();
    if !matches!(parts.len(), 4 | 5) {
        return None;
    }
    if parts[0] != SPARKPLUG_NAMESPACE || parts.iter().any(|part| part.is_empty()) {
        return None;
    }
    let group_id = parts[1].to_string();
    let message_type = parts[2].to_string();
    let edge_node_id = parts[3].to_string();
    let device_id = parts.get(4).map(|value| (*value).to_string());
    if device_id.is_none() {
        if !NODE_MESSAGE_TYPES.contains(&message_type.as_str()) {
            return None;
        }
    } else if !DEVICE_MESSAGE_TYPES.contains(&message_type.as_str()) {
        return None;
    }
    Some((group_id, message_type, edge_node_id, device_id))
}

pub fn decode_sparkplug_payload(
    payload_base64: &str,
    mqtt_topic: &str,
) -> Option<SparkplugMessage> {
    let (group_id, message_type, edge_node_id, device_id) = parse_topic(mqtt_topic)?;
    let payload = STANDARD.decode(payload_base64).ok()?;
    let mut offset = 0;
    let mut sparkplug_timestamp = None;
    let mut seq = None;
    let mut metrics = Map::new();

    while offset < payload.len() {
        let (field_number, wire_type, next_offset) = read_key(&payload, offset).ok()?;
        offset = next_offset;
        match (field_number, wire_type) {
            (1, 0) => {
                let (value, next) = read_varint(&payload, offset).ok()?;
                sparkplug_timestamp = Some(value as i64);
                offset = next;
            }
            (2, 2) => {
                let (metric_bytes, next) = read_length_delimited(&payload, offset).ok()?;
                if let Some((metric_name, metric_value)) = decode_metric(metric_bytes).ok()? {
                    assign_metric_path(&mut metrics, &metric_name, metric_value);
                }
                offset = next;
            }
            (3, 0) => {
                let (value, next) = read_varint(&payload, offset).ok()?;
                seq = Some(value as i64);
                offset = next;
            }
            _ => {
                offset = skip_field(&payload, offset, wire_type).ok()?;
            }
        }
    }

    Some(SparkplugMessage {
        group_id,
        message_type,
        edge_node_id,
        device_id,
        seq,
        sparkplug_timestamp,
        metrics,
    })
}

fn build_reported_payload(message: &SparkplugMessage, observed_at: i64) -> Value {
    let mut topic = Map::new();
    topic.insert("namespace".to_string(), json!(SPARKPLUG_NAMESPACE));
    topic.insert("groupId".to_string(), json!(message.group_id));
    topic.insert("messageType".to_string(), json!(message.message_type));
    topic.insert("edgeNodeId".to_string(), json!(message.edge_node_id));
    if let Some(device_id) = message.device_id.as_ref() {
        topic.insert("deviceId".to_string(), json!(device_id));
    }

    json!({
        "topic": topic,
        "payload": {
            "timestamp": message.sparkplug_timestamp,
            "seq": message.seq,
            "metrics": message.metrics,
        },
        "projection": {
            "observedAt": observed_at,
        },
    })
}

pub async fn resolve_thing_name<A: WitnessAws + ?Sized>(
    message: &SparkplugMessage,
    aws: &A,
) -> Result<String> {
    if let Some(device_id) = message.device_id.as_ref() {
        return Ok(device_id.clone());
    }

    let town = aws.describe_thing(&message.group_id).await?;
    if town.thing_type_name.as_deref() != Some("town") {
        bail!(
            "Sparkplug group id {:?} does not identify a town thing",
            message.group_id
        );
    }

    let rig = aws.describe_thing(&message.edge_node_id).await?;
    if rig.attributes.get("kind").map(String::as_str) != Some(RIG_KIND_ATTRIBUTE) {
        bail!(
            "Sparkplug edge node id {:?} does not identify a rig thing",
            message.edge_node_id
        );
    }
    if rig.attributes.get("townId").map(String::as_str) != Some(message.group_id.as_str()) {
        bail!(
            "Rig thing {:?} is not assigned to town {:?}",
            message.edge_node_id,
            message.group_id
        );
    }
    Ok(message.edge_node_id.clone())
}

fn reported_metrics_from_shadow(shadow: Option<&Value>) -> Option<&Map<String, Value>> {
    shadow?
        .get("state")?
        .as_object()?
        .get("reported")?
        .as_object()?
        .get("payload")?
        .as_object()?
        .get("metrics")?
        .as_object()
}

fn metric_patch_is_noop(current: &Map<String, Value>, patch: &Map<String, Value>) -> bool {
    for (key, value) in patch {
        let Some(current_value) = current.get(key) else {
            return false;
        };
        if let Value::Object(patch_object) = value {
            let Some(current_object) = current_value.as_object() else {
                return false;
            };
            if !metric_patch_is_noop(current_object, patch_object) {
                return false;
            }
            continue;
        }
        if current_value != value {
            return false;
        }
    }
    true
}

fn patch_contains_command_result(metrics: &Map<String, Value>) -> bool {
    COMMAND_RESULT_METRIC_KEYS
        .iter()
        .any(|key| metrics.contains_key(*key))
}

fn prepare_metric_patch_for_merge(metrics: &Map<String, Value>) -> Map<String, Value> {
    if !patch_contains_command_result(metrics) {
        return metrics.clone();
    }
    let mut prepared = metrics.clone();
    prepared.insert("commands".to_string(), Value::Null);
    prepared
        .entry("redconCommandMessage".to_string())
        .or_insert(Value::Null);
    prepared
        .entry("redconCommandTarget".to_string())
        .or_insert(Value::Null);
    prepared
}

async fn replace_metrics<A: WitnessAws + ?Sized>(
    thing_name: &str,
    reported_payload: Value,
    aws: &A,
) -> Result<()> {
    aws.update_sparkplug_shadow(
        thing_name,
        json!({
            "state": {
                "reported": {
                    "payload": {
                        "metrics": Value::Null,
                    }
                }
            }
        }),
    )
    .await?;
    aws.update_sparkplug_shadow(
        thing_name,
        json!({
            "state": {
                "reported": reported_payload,
            }
        }),
    )
    .await
}

async fn merge_metrics<A: WitnessAws + ?Sized>(
    thing_name: &str,
    mut reported_payload: Value,
    aws: &A,
) -> Result<()> {
    let patch_metrics = reported_payload
        .get("payload")
        .and_then(Value::as_object)
        .and_then(|payload| payload.get("metrics"))
        .and_then(Value::as_object)
        .cloned();
    let prepared_patch = patch_metrics.as_ref().map(prepare_metric_patch_for_merge);
    if let Some(prepared_patch) = prepared_patch.as_ref() {
        reported_payload["payload"]["metrics"] = Value::Object(prepared_patch.clone());
    }

    let current_shadow = aws.get_sparkplug_shadow(thing_name).await?;
    if let (Some(patch), Some(current)) = (
        prepared_patch.as_ref(),
        reported_metrics_from_shadow(current_shadow.as_ref()),
    ) {
        if metric_patch_is_noop(current, patch) {
            tracing::debug!(
                thing = thing_name,
                "Skipping unchanged Sparkplug metric shadow merge"
            );
            return Ok(());
        }
    }

    aws.update_sparkplug_shadow(
        thing_name,
        json!({
            "state": {
                "reported": reported_payload,
            }
        }),
    )
    .await
}

pub async fn project_sparkplug_message<A: WitnessAws + ?Sized>(
    message: &SparkplugMessage,
    observed_at: i64,
    aws: &A,
) -> Result<String> {
    let thing_name = resolve_thing_name(message, aws).await?;
    let reported_payload = build_reported_payload(message, observed_at);
    if REPLACE_METRICS_MESSAGE_TYPES.contains(&message.message_type.as_str())
        || CLEAR_METRICS_MESSAGE_TYPES.contains(&message.message_type.as_str())
    {
        replace_metrics(&thing_name, reported_payload, aws).await?;
    } else if MERGE_METRICS_MESSAGE_TYPES.contains(&message.message_type.as_str()) {
        merge_metrics(&thing_name, reported_payload, aws).await?;
    } else {
        return Ok("ignored".to_string());
    }
    Ok(thing_name)
}

pub async fn handle_lambda_event<A: WitnessAws + ?Sized>(event: Value, aws: &A) -> Result<Value> {
    let mqtt_topic = event.get("mqttTopic").and_then(Value::as_str);
    let payload_base64 = event.get("payloadBase64").and_then(Value::as_str);
    let (Some(mqtt_topic), Some(payload_base64)) = (mqtt_topic, payload_base64) else {
        tracing::warn!(event = ?event, "Ignoring malformed witness event");
        return Ok(json!({"status": "ignored", "reason": "malformed-event"}));
    };
    let observed_at = event.get("observedAt").and_then(Value::as_i64).unwrap_or(0);
    let Some(message) = decode_sparkplug_payload(payload_base64, mqtt_topic) else {
        return Ok(json!({"status": "ignored", "reason": "unsupported-topic"}));
    };
    let thing_name = project_sparkplug_message(&message, observed_at, aws).await?;
    Ok(json!({"status": "ok", "thingName": thing_name}))
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use super::*;

    fn encode_varint(value: u64) -> Vec<u8> {
        let mut parts = Vec::new();
        let mut current = value;
        loop {
            let next_value = (current & 0x7f) as u8;
            current >>= 7;
            if current != 0 {
                parts.push(next_value | 0x80);
            } else {
                parts.push(next_value);
                return parts;
            }
        }
    }

    fn encode_key(field_number: u64, wire_type: u64) -> Vec<u8> {
        encode_varint((field_number << 3) | wire_type)
    }

    fn encode_length_delimited(field_number: u64, payload: &[u8]) -> Vec<u8> {
        let mut encoded = encode_key(field_number, 2);
        encoded.extend(encode_varint(payload.len() as u64));
        encoded.extend(payload);
        encoded
    }

    fn encode_metric(
        name: &str,
        int_value: Option<i64>,
        long_value: Option<i64>,
        double_value: Option<f64>,
        bool_value: Option<bool>,
        string_value: Option<&str>,
        canonical_fields: bool,
    ) -> Vec<u8> {
        let mut payload = Vec::new();
        payload.extend(encode_length_delimited(1, name.as_bytes()));
        if let Some(value) = int_value {
            payload.extend(encode_key(10, 0));
            payload.extend(encode_varint(value as u64));
        }
        if let Some(value) = long_value {
            payload.extend(encode_key(11, 0));
            payload.extend(encode_varint(value as u64));
        }
        if let Some(value) = double_value {
            payload.extend(encode_key(13, 1));
            payload.extend(value.to_le_bytes());
        }
        if let Some(value) = bool_value {
            payload.extend(encode_key(if canonical_fields { 14 } else { 12 }, 0));
            payload.extend(encode_varint(u64::from(value)));
        }
        if let Some(value) = string_value {
            payload.extend(encode_length_delimited(
                if canonical_fields { 15 } else { 13 },
                value.as_bytes(),
            ));
        }
        payload
    }

    fn encode_payload(timestamp: Option<i64>, seq: Option<i64>, metrics: Vec<Vec<u8>>) -> String {
        let mut payload = Vec::new();
        if let Some(timestamp) = timestamp {
            payload.extend(encode_key(1, 0));
            payload.extend(encode_varint(timestamp as u64));
        }
        for metric in metrics {
            payload.extend(encode_length_delimited(2, &metric));
        }
        if let Some(seq) = seq {
            payload.extend(encode_key(3, 0));
            payload.extend(encode_varint(seq as u64));
        }
        STANDARD.encode(payload)
    }

    #[derive(Default)]
    struct FakeAws {
        things: Mutex<HashMap<String, ThingDescription>>,
        shadow: Mutex<Option<Value>>,
        updates: Mutex<Vec<(String, Value)>>,
    }

    #[async_trait]
    impl WitnessAws for FakeAws {
        async fn describe_thing(&self, thing_name: &str) -> Result<ThingDescription> {
            self.things
                .lock()
                .unwrap()
                .get(thing_name)
                .cloned()
                .ok_or_else(|| anyhow!("unexpected thing: {thing_name}"))
        }

        async fn get_sparkplug_shadow(&self, _thing_name: &str) -> Result<Option<Value>> {
            Ok(self.shadow.lock().unwrap().clone())
        }

        async fn update_sparkplug_shadow(&self, thing_name: &str, payload: Value) -> Result<()> {
            self.updates
                .lock()
                .unwrap()
                .push((thing_name.to_string(), payload));
            Ok(())
        }
    }

    #[tokio::test]
    async fn resolve_node_message_accepts_current_rig_type_model() {
        let aws = FakeAws::default();
        aws.things.lock().unwrap().insert(
            "town-1".to_string(),
            ThingDescription {
                thing_type_name: Some("town".to_string()),
                attributes: HashMap::from([("kind".to_string(), "townType".to_string())]),
            },
        );
        aws.things.lock().unwrap().insert(
            "cloud-1".to_string(),
            ThingDescription {
                thing_type_name: Some("cloud".to_string()),
                attributes: HashMap::from([
                    ("kind".to_string(), "rigType".to_string()),
                    ("townId".to_string(), "town-1".to_string()),
                ]),
            },
        );
        let encoded_payload = encode_payload(
            Some(1710000000000),
            Some(7),
            vec![encode_metric(
                "redcon",
                Some(1),
                None,
                None,
                None,
                None,
                false,
            )],
        );
        let message = decode_sparkplug_payload(&encoded_payload, "spBv1.0/town-1/NBIRTH/cloud-1")
            .expect("message");

        assert_eq!(resolve_thing_name(&message, &aws).await.unwrap(), "cloud-1");
    }

    #[tokio::test]
    async fn resolve_node_message_rejects_non_rig_kind() {
        let aws = FakeAws::default();
        aws.things.lock().unwrap().insert(
            "town-1".to_string(),
            ThingDescription {
                thing_type_name: Some("town".to_string()),
                attributes: HashMap::new(),
            },
        );
        aws.things.lock().unwrap().insert(
            "unit-1".to_string(),
            ThingDescription {
                thing_type_name: Some("unit".to_string()),
                attributes: HashMap::from([
                    ("kind".to_string(), "deviceType".to_string()),
                    ("townId".to_string(), "town-1".to_string()),
                ]),
            },
        );
        let encoded_payload = encode_payload(
            Some(1710000000000),
            Some(7),
            vec![encode_metric(
                "redcon",
                Some(1),
                None,
                None,
                None,
                None,
                false,
            )],
        );
        let message = decode_sparkplug_payload(&encoded_payload, "spBv1.0/town-1/NBIRTH/unit-1")
            .expect("message");

        let err = resolve_thing_name(&message, &aws).await.unwrap_err();
        assert!(err.to_string().contains("does not identify a rig thing"));
    }

    #[test]
    fn decode_device_birth_projects_nested_metrics() {
        let encoded_payload = encode_payload(
            Some(1710000000000),
            Some(7),
            vec![
                encode_metric("redcon", Some(1), None, None, None, None, false),
                encode_metric("batteryMv", Some(3795), None, None, None, None, false),
                encode_metric(
                    "services/demo/available",
                    None,
                    None,
                    None,
                    Some(true),
                    None,
                    false,
                ),
            ],
        );

        let message = decode_sparkplug_payload(&encoded_payload, "spBv1.0/town/DBIRTH/rig/unit-1")
            .expect("message");

        assert_eq!(message.device_id.as_deref(), Some("unit-1"));
        assert_eq!(message.message_type, "DBIRTH");
        assert_eq!(
            Value::Object(message.metrics),
            json!({
                "redcon": 1,
                "batteryMv": 3795,
                "services": {
                    "demo": {
                        "available": true,
                    }
                },
            })
        );
    }

    #[test]
    fn decode_weather_double_and_canonical_bool_metrics() {
        let encoded_payload = encode_payload(
            Some(1710000000000),
            Some(7),
            vec![
                encode_metric("redcon", Some(4), None, None, None, None, false),
                encode_metric(
                    "measuredTemperature",
                    None,
                    None,
                    Some(21.625),
                    None,
                    None,
                    false,
                ),
                encode_metric(
                    "services/demo/available",
                    None,
                    None,
                    None,
                    Some(true),
                    None,
                    true,
                ),
            ],
        );

        let message =
            decode_sparkplug_payload(&encoded_payload, "spBv1.0/town/DBIRTH/rig/weather-1")
                .expect("message");

        assert_eq!(message.metrics["redcon"], 4);
        assert_eq!(message.metrics["measuredTemperature"], 21.625);
        assert_eq!(message.metrics["services"]["demo"]["available"], true);
    }

    #[tokio::test]
    async fn project_device_birth_replaces_metrics() {
        let aws = FakeAws::default();
        let encoded_payload = encode_payload(
            Some(1710000000000),
            Some(7),
            vec![
                encode_metric("redcon", Some(1), None, None, None, None, false),
                encode_metric("batteryMv", Some(3795), None, None, None, None, false),
            ],
        );
        let message = decode_sparkplug_payload(&encoded_payload, "spBv1.0/town/DBIRTH/rig/unit-1")
            .expect("message");

        let projected = project_sparkplug_message(&message, 1710000000999, &aws)
            .await
            .unwrap();

        assert_eq!(projected, "unit-1");
        let updates = aws.updates.lock().unwrap();
        assert_eq!(updates.len(), 2);
        assert_eq!(updates[0].0, "unit-1");
        assert!(updates[0].1["state"]["reported"]["payload"]["metrics"].is_null());
        assert_eq!(
            updates[1].1,
            json!({
                "state": {
                    "reported": {
                        "topic": {
                            "namespace": "spBv1.0",
                            "groupId": "town",
                            "messageType": "DBIRTH",
                            "edgeNodeId": "rig",
                            "deviceId": "unit-1",
                        },
                        "payload": {
                            "timestamp": 1710000000000_i64,
                            "seq": 7,
                            "metrics": {
                                "redcon": 1,
                                "batteryMv": 3795,
                            },
                        },
                        "projection": {
                            "observedAt": 1710000000999_i64,
                        },
                    }
                }
            })
        );
    }

    #[tokio::test]
    async fn project_device_data_skips_shadow_update_when_metrics_are_unchanged() {
        let aws = FakeAws::default();
        *aws.shadow.lock().unwrap() = Some(json!({
            "state": {
                "reported": {
                    "payload": {
                        "metrics": {
                            "redcon": 4,
                        }
                    }
                }
            }
        }));
        let encoded_payload = encode_payload(
            Some(1710000030000),
            Some(8),
            vec![encode_metric(
                "redcon",
                Some(4),
                None,
                None,
                None,
                None,
                false,
            )],
        );
        let message =
            decode_sparkplug_payload(&encoded_payload, "spBv1.0/town/DDATA/rig/weather-1")
                .expect("message");

        let projected = project_sparkplug_message(&message, 1710000030999, &aws)
            .await
            .unwrap();

        assert_eq!(projected, "weather-1");
        assert!(aws.updates.lock().unwrap().is_empty());
    }

    #[tokio::test]
    async fn project_device_data_updates_shadow_when_metric_changes() {
        let aws = FakeAws::default();
        *aws.shadow.lock().unwrap() = Some(json!({
            "state": {
                "reported": {
                    "payload": {
                        "metrics": {
                            "redcon": 4,
                        }
                    }
                }
            }
        }));
        let encoded_payload = encode_payload(
            Some(1710000030000),
            Some(8),
            vec![encode_metric(
                "redcon",
                Some(3),
                None,
                None,
                None,
                None,
                false,
            )],
        );
        let message =
            decode_sparkplug_payload(&encoded_payload, "spBv1.0/town/DDATA/rig/weather-1")
                .expect("message");

        project_sparkplug_message(&message, 1710000030999, &aws)
            .await
            .unwrap();

        let updates = aws.updates.lock().unwrap();
        assert_eq!(updates.len(), 1);
        assert_eq!(updates[0].0, "weather-1");
        assert_eq!(
            updates[0].1["state"]["reported"]["payload"]["metrics"]["redcon"],
            3
        );
    }

    #[tokio::test]
    async fn project_command_result_data_clears_legacy_commands_map() {
        let aws = FakeAws::default();
        *aws.shadow.lock().unwrap() = Some(json!({
            "state": {
                "reported": {
                    "payload": {
                        "metrics": {
                            "commands": {
                                "dcmd-cloud-mcu-1": {
                                    "status": "succeeded",
                                    "targetRedcon": 1,
                                }
                            },
                            "redconCommandMessage": "old failure",
                        }
                    }
                }
            }
        }));
        let encoded_payload = encode_payload(
            Some(1710000040000),
            Some(9),
            vec![
                encode_metric(
                    "redconCommandStatus",
                    None,
                    None,
                    None,
                    None,
                    Some("succeeded"),
                    false,
                ),
                encode_metric("redconCommandSeq", Some(2), None, None, None, None, false),
                encode_metric(
                    "redconCommandObservedAt",
                    None,
                    Some(1710000040123),
                    None,
                    None,
                    None,
                    false,
                ),
                encode_metric(
                    "redconCommandId",
                    None,
                    None,
                    None,
                    None,
                    Some("dcmd-cloud-mcu-2"),
                    false,
                ),
                encode_metric(
                    "redconCommandTarget",
                    Some(4),
                    None,
                    None,
                    None,
                    None,
                    false,
                ),
            ],
        );
        let message =
            decode_sparkplug_payload(&encoded_payload, "spBv1.0/town/DDATA/rig/cloud-mcu-1")
                .expect("message");

        project_sparkplug_message(&message, 1710000040999, &aws)
            .await
            .unwrap();

        let updates = aws.updates.lock().unwrap();
        assert_eq!(updates.len(), 1);
        let metrics = &updates[0].1["state"]["reported"]["payload"]["metrics"];
        assert_eq!(metrics["redconCommandStatus"], "succeeded");
        assert_eq!(metrics["redconCommandId"], "dcmd-cloud-mcu-2");
        assert!(metrics["commands"].is_null());
        assert!(metrics["redconCommandMessage"].is_null());
    }

    #[tokio::test]
    async fn project_node_death_replaces_metrics_with_death_payload() {
        let aws = FakeAws::default();
        aws.things.lock().unwrap().insert(
            "town".to_string(),
            ThingDescription {
                thing_type_name: Some("town".to_string()),
                attributes: HashMap::new(),
            },
        );
        aws.things.lock().unwrap().insert(
            "rig".to_string(),
            ThingDescription {
                thing_type_name: Some("cloud".to_string()),
                attributes: HashMap::from([
                    ("kind".to_string(), "rigType".to_string()),
                    ("townId".to_string(), "town".to_string()),
                ]),
            },
        );
        let encoded_payload = encode_payload(
            None,
            None,
            vec![
                encode_metric("bdSeq", None, Some(42), None, None, None, false),
                encode_metric("redcon", Some(4), None, None, None, None, false),
            ],
        );
        let message =
            decode_sparkplug_payload(&encoded_payload, "spBv1.0/town/NDEATH/rig").expect("message");

        project_sparkplug_message(&message, 1710000003999, &aws)
            .await
            .unwrap();

        let updates = aws.updates.lock().unwrap();
        assert_eq!(updates.len(), 2);
        assert_eq!(
            updates[1].1["state"]["reported"],
            json!({
                "topic": {
                    "namespace": "spBv1.0",
                    "groupId": "town",
                    "messageType": "NDEATH",
                    "edgeNodeId": "rig",
                },
                "payload": {
                    "timestamp": Value::Null,
                    "seq": Value::Null,
                    "metrics": {
                        "bdSeq": 42,
                        "redcon": 4,
                    },
                },
                "projection": {
                    "observedAt": 1710000003999_i64,
                },
            })
        );
    }

    #[test]
    fn rejects_invalid_topic_arity_and_message_pairings() {
        let encoded_payload = encode_payload(None, None, vec![]);
        assert!(decode_sparkplug_payload(&encoded_payload, "spBv1.0/town/DBIRTH/rig").is_none());
        assert!(
            decode_sparkplug_payload(&encoded_payload, "spBv1.0/town/NBIRTH/rig/unit-1").is_none()
        );
        assert!(decode_sparkplug_payload(&encoded_payload, "spBv1.0/town//rig").is_none());
    }

    #[tokio::test]
    async fn lambda_handler_ignores_unsupported_topics() {
        let aws = FakeAws::default();
        let result = handle_lambda_event(
            json!({
                "mqttTopic": "txings/unit-1/video/status",
                "payloadBase64": "",
                "observedAt": 123,
            }),
            &aws,
        )
        .await
        .unwrap();

        assert_eq!(
            result,
            json!({"status": "ignored", "reason": "unsupported-topic"})
        );
    }
}
