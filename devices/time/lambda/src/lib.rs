use std::fmt::{Debug, Display};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, anyhow, bail};
use async_trait::async_trait;
use aws_sdk_iotdataplane::primitives::Blob;
use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use chrono::{DateTime, Utc};
use serde_json::{Map, Number, Value, json};

pub const SCHEMA_VERSION: &str = "2.0";
pub const TIME_TOPIC_NAMESPACE: &str = "txings";
pub const CAPABILITY_TOPIC_SEGMENT: &str = "capability";
pub const CAPABILITY_TOPIC_VERSION: &str = "v2";
pub const AWS_CONNECTIVITY_ADAPTER_ID: &str = "dev.txing.rig.AwsConnectivity";
pub const TIME_SERVICE_NAME: &str = "time";
pub const MCP_SERVICE_NAME: &str = "mcp";
pub const MCP_PROTOCOL_VERSION: &str = "2025-11-25";
pub const TIME_MODE_SLEEP: &str = "sleep";
pub const TIME_MODE_ACTIVE: &str = "active";
pub const COMMAND_STATUS_SUCCEEDED: &str = "succeeded";
pub const DEFAULT_ACTIVE_TTL_MS: i64 = 300_000;
pub const DEFAULT_LEASE_TTL_MS: i64 = 5_000;
pub const DEFAULT_SERVER_VERSION: &str = "0.9.114";
pub const TIME_DEVICE_SEARCH_QUERY: &str = "thingTypeName:time AND attributes.kind:deviceType";
pub const TIME_DEVICE_SEARCH_PAGE_SIZE: i32 = 100;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SearchPage {
    pub thing_names: Vec<String>,
    pub next_token: Option<String>,
}

#[async_trait]
pub trait TimeAws: Send + Sync {
    async fn search_time_things(&self, next_token: Option<&str>) -> Result<SearchPage>;
    async fn get_retained_message(&self, topic: &str) -> Result<Option<Vec<u8>>>;
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
    async fn publish(&self, topic: &str, retain: bool, payload: Vec<u8>) -> Result<()>;
}

#[derive(Clone)]
pub struct AwsTimeClient {
    iot: aws_sdk_iot::Client,
    iot_data: aws_sdk_iotdataplane::Client,
}

impl AwsTimeClient {
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
impl TimeAws for AwsTimeClient {
    async fn search_time_things(&self, next_token: Option<&str>) -> Result<SearchPage> {
        let mut request = self
            .iot
            .search_index()
            .index_name("AWS_Things")
            .query_string(TIME_DEVICE_SEARCH_QUERY)
            .max_results(TIME_DEVICE_SEARCH_PAGE_SIZE);
        if let Some(token) = next_token {
            request = request.next_token(token);
        }
        let response = request.send().await.context("search AWS IoT thing index")?;
        let thing_names = response
            .things()
            .iter()
            .filter_map(|thing| thing.thing_name().map(str::trim))
            .filter(|thing_name| !thing_name.is_empty())
            .map(ToOwned::to_owned)
            .collect();
        Ok(SearchPage {
            thing_names,
            next_token: response
                .next_token()
                .map(str::trim)
                .filter(|token| !token.is_empty())
                .map(ToOwned::to_owned),
        })
    }

    async fn get_retained_message(&self, topic: &str) -> Result<Option<Vec<u8>>> {
        match self
            .iot_data
            .get_retained_message()
            .topic(topic)
            .send()
            .await
        {
            Ok(output) => Ok(output.payload().map(|payload| payload.as_ref().to_vec())),
            Err(err) if error_is_not_found(&err) => Ok(None),
            Err(err) => Err(anyhow!(err)).context("get retained AWS IoT message"),
        }
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

    async fn publish(&self, topic: &str, retain: bool, payload: Vec<u8>) -> Result<()> {
        self.iot_data
            .publish()
            .topic(topic)
            .qos(1)
            .retain(retain)
            .payload(Blob::new(payload))
            .send()
            .await
            .context("publish AWS IoT message")?;
        Ok(())
    }
}

fn error_is_not_found(error: &(impl Debug + Display)) -> bool {
    let text = format!("{error:?}");
    text.contains("ResourceNotFoundException") || text.contains("NotFoundException")
}

pub fn utc_now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time before Unix epoch")
        .as_millis() as i64
}

pub fn utc_iso(now_ms: i64) -> String {
    let dt = DateTime::<Utc>::from_timestamp_millis(now_ms)
        .unwrap_or_else(|| DateTime::<Utc>::from_timestamp_millis(0).expect("valid epoch"));
    if dt.timestamp_subsec_micros() == 0 {
        dt.format("%Y-%m-%dT%H:%M:%SZ").to_string()
    } else {
        dt.format("%Y-%m-%dT%H:%M:%S%.6fZ").to_string()
    }
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

pub fn build_capability_topic_root(thing_name: &str) -> Result<String> {
    Ok(format!(
        "{}/{}/{}/{}",
        TIME_TOPIC_NAMESPACE,
        segment(thing_name, "thing_name")?,
        CAPABILITY_TOPIC_SEGMENT,
        CAPABILITY_TOPIC_VERSION
    ))
}

pub fn build_capability_command_topic(thing_name: &str) -> Result<String> {
    Ok(format!(
        "{}/command",
        build_capability_topic_root(thing_name)?
    ))
}

pub fn build_capability_state_topic(thing_name: &str) -> Result<String> {
    Ok(format!(
        "{}/state",
        build_capability_topic_root(thing_name)?
    ))
}

pub fn build_capability_command_result_topic(thing_name: &str) -> Result<String> {
    Ok(format!(
        "{}/command-result",
        build_capability_topic_root(thing_name)?
    ))
}

pub fn build_mcp_topic_root(thing_name: &str) -> Result<String> {
    Ok(format!(
        "{}/{}/{}",
        TIME_TOPIC_NAMESPACE,
        segment(thing_name, "thing_name")?,
        MCP_SERVICE_NAME
    ))
}

pub fn build_mcp_descriptor_topic(thing_name: &str) -> Result<String> {
    Ok(format!("{}/descriptor", build_mcp_topic_root(thing_name)?))
}

pub fn build_mcp_status_topic(thing_name: &str) -> Result<String> {
    Ok(format!("{}/status", build_mcp_topic_root(thing_name)?))
}

pub fn build_mcp_session_s2c_topic(thing_name: &str, session_id: &str) -> Result<String> {
    Ok(format!(
        "{}/session/{}/s2c",
        build_mcp_topic_root(thing_name)?,
        segment(session_id, "session_id")?
    ))
}

pub fn parse_mcp_session_c2s_topic(topic: &str) -> Option<(String, String)> {
    let parts: Vec<&str> = topic.split('/').collect();
    if parts.len() != 6 {
        return None;
    }
    if parts[0] != TIME_TOPIC_NAMESPACE || parts[2] != MCP_SERVICE_NAME {
        return None;
    }
    if parts[3] != "session" || parts[5] != "c2s" {
        return None;
    }
    if parts[1].is_empty() || parts[4].is_empty() {
        return None;
    }
    Some((parts[1].to_string(), parts[4].to_string()))
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConnectivityCommand {
    pub command_id: String,
    pub thing_name: String,
    pub redcon: i64,
    pub reason: String,
    pub issued_at_ms: i64,
    pub deadline_ms: Option<i64>,
    pub seq: i64,
}

impl ConnectivityCommand {
    pub fn from_payload(payload: &[u8]) -> Result<Self> {
        let decoded: Value =
            serde_json::from_slice(payload).context("decode connectivity command")?;
        let object = decoded
            .as_object()
            .ok_or_else(|| anyhow!("payload must be a JSON object"))?;
        if object.get("schemaVersion").and_then(Value::as_str) != Some(SCHEMA_VERSION) {
            bail!("schemaVersion must be '2.0'");
        }
        let target = object
            .get("target")
            .and_then(Value::as_object)
            .ok_or_else(|| anyhow!("target must be an object"))?;
        let redcon = target
            .get("redcon")
            .and_then(Value::as_i64)
            .ok_or_else(|| anyhow!("target.redcon must be a REDCON level 1 through 4"))?;
        if !matches!(redcon, 1..=4) {
            bail!("target.redcon must be a REDCON level 1 through 4");
        }
        let command_id = required_string(object, "commandId")?;
        let thing_name = required_string(object, "thingName")?;
        let reason = required_string(object, "reason")?;
        let issued_at_ms = required_i64(object, "issuedAtMs")?;
        let deadline_ms = match object.get("deadlineMs") {
            None | Some(Value::Null) => None,
            Some(value) => Some(
                value
                    .as_i64()
                    .ok_or_else(|| anyhow!("deadlineMs must be an integer or null"))?,
            ),
        };
        let seq = match object.get("seq") {
            None | Some(Value::Null) => 0,
            Some(value) => value
                .as_i64()
                .ok_or_else(|| anyhow!("seq must be an integer"))?,
        };
        Ok(Self {
            command_id,
            thing_name,
            redcon,
            reason,
            issued_at_ms,
            deadline_ms,
            seq,
        })
    }

    pub fn activates_time(&self) -> bool {
        matches!(self.redcon, 1..=3)
    }
}

fn required_string(object: &Map<String, Value>, key: &str) -> Result<String> {
    let value = object
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| anyhow!("{key} must be a non-empty string"))?;
    Ok(value.to_string())
}

fn required_i64(object: &Map<String, Value>, key: &str) -> Result<i64> {
    object
        .get(key)
        .and_then(Value::as_i64)
        .ok_or_else(|| anyhow!("{key} must be an integer"))
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StoredTimeState {
    pub thing_name: String,
    pub mode: String,
    pub active_until_ms: Option<i64>,
    pub last_command_id: Option<String>,
}

impl StoredTimeState {
    pub fn new(thing_name: String) -> Self {
        Self {
            thing_name,
            mode: TIME_MODE_SLEEP.to_string(),
            active_until_ms: None,
            last_command_id: None,
        }
    }

    pub fn from_reported_shadow(thing_name: String, reported: Option<&Map<String, Value>>) -> Self {
        let Some(reported) = reported else {
            return Self::new(thing_name);
        };
        let mode = if reported.get("mode").and_then(Value::as_str) == Some(TIME_MODE_ACTIVE) {
            TIME_MODE_ACTIVE
        } else {
            TIME_MODE_SLEEP
        };
        let active_until_ms = reported.get("activeUntilMs").and_then(value_to_i64_lossy);
        let last_command_id = reported
            .get("lastCommandId")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned);
        Self {
            thing_name,
            mode: mode.to_string(),
            active_until_ms,
            last_command_id,
        }
    }
}

fn value_to_i64_lossy(value: &Value) -> Option<i64> {
    match value {
        Value::Number(number) => number.as_i64(),
        Value::String(text) => text.parse::<i64>().ok(),
        _ => None,
    }
}

pub struct TimeDeviceRuntime<'a, A: TimeAws + ?Sized> {
    thing_name: String,
    aws: &'a A,
    active_ttl_ms: i64,
    server_version: String,
}

impl<'a, A: TimeAws + ?Sized> TimeDeviceRuntime<'a, A> {
    pub fn new(
        thing_name: &str,
        aws: &'a A,
        active_ttl_ms: i64,
        server_version: impl Into<String>,
    ) -> Result<Self> {
        Ok(Self {
            thing_name: segment(thing_name, "thing_name")?,
            aws,
            active_ttl_ms,
            server_version: server_version.into(),
        })
    }

    pub async fn handle_scheduled_wake_with_now(
        &self,
        _event: &Value,
        now_ms: i64,
    ) -> Result<Value> {
        let current_time_iso = utc_iso(now_ms);
        let mut state = self.load_state().await?;
        let mut command = self.load_retained_command().await?;
        let mut command_result = None;

        if let Some(candidate) = command.as_ref() {
            if candidate.thing_name != self.thing_name {
                command = None;
            }
        }
        if let Some(candidate) = command.as_ref() {
            if Some(candidate.command_id.as_str()) == state.last_command_id.as_deref() {
                command = None;
            } else if candidate
                .deadline_ms
                .is_some_and(|deadline_ms| deadline_ms < now_ms)
            {
                command = None;
            }
        }
        if let Some(command) = command.as_ref() {
            state.last_command_id = Some(command.command_id.clone());
            if command.activates_time() {
                state.mode = TIME_MODE_ACTIVE.to_string();
                state.active_until_ms = Some(now_ms + self.active_ttl_ms);
            } else {
                state.mode = TIME_MODE_SLEEP.to_string();
                state.active_until_ms = None;
            }
            command_result = Some(self.build_command_result(
                command,
                COMMAND_STATUS_SUCCEEDED,
                Value::Null,
                command.seq,
            ));
        }

        if state.mode == TIME_MODE_ACTIVE
            && state
                .active_until_ms
                .is_some_and(|active_until_ms| active_until_ms <= now_ms)
        {
            state.mode = TIME_MODE_SLEEP.to_string();
            state.active_until_ms = None;
        }

        let mcp_available = state.mode == TIME_MODE_ACTIVE;
        self.publish_time_state(&state, &current_time_iso).await?;
        self.publish_mcp_discovery(mcp_available, now_ms).await?;
        self.update_time_shadow(&state, &current_time_iso).await?;
        self.update_mcp_shadow(mcp_available, now_ms).await?;
        if let Some(command_result) = command_result {
            self.publish_command_result(command_result).await?;
        }

        Ok(json!({
            "thingName": self.thing_name,
            "currentTimeIso": current_time_iso,
            "mode": state.mode,
            "activeUntilMs": state.active_until_ms,
            "lastCommandId": state.last_command_id,
            "mcpAvailable": mcp_available,
        }))
    }

    pub async fn handle_mcp_message_with_now(&self, event: &Value, now_ms: i64) -> Result<Value> {
        let topic = event
            .get("mqttTopic")
            .and_then(Value::as_str)
            .ok_or_else(|| anyhow!("MCP event is missing mqttTopic"))?;
        let (thing_name, session_id) = parse_mcp_session_c2s_topic(topic)
            .ok_or_else(|| anyhow!("unsupported MCP topic: {topic}"))?;
        if thing_name != self.thing_name {
            bail!(
                "MCP topic thing={thing_name} does not match {}",
                self.thing_name
            );
        }

        let message = self.decode_mcp_event_message(event)?;
        let mut state = self.load_state().await?;
        let mut active = state.mode == TIME_MODE_ACTIVE
            && state
                .active_until_ms
                .is_none_or(|active_until_ms| active_until_ms > now_ms);

        if state.mode == TIME_MODE_ACTIVE
            && state
                .active_until_ms
                .is_some_and(|active_until_ms| active_until_ms <= now_ms)
        {
            state.mode = TIME_MODE_SLEEP.to_string();
            state.active_until_ms = None;
            let current_time_iso = utc_iso(now_ms);
            self.publish_time_state(&state, &current_time_iso).await?;
            self.publish_mcp_discovery(false, now_ms).await?;
            self.update_time_shadow(&state, &current_time_iso).await?;
            self.update_mcp_shadow(false, now_ms).await?;
            active = false;
        }

        let response = self.build_mcp_response(&message, active, now_ms);
        if let Some(response) = response.as_ref() {
            self.publish_mcp_response(&session_id, response.clone())
                .await?;
        }
        Ok(json!({
            "thingName": self.thing_name,
            "sessionId": session_id,
            "active": active,
            "responded": response.is_some(),
        }))
    }

    async fn load_state(&self) -> Result<StoredTimeState> {
        let Some(payload) = self.aws.get_thing_shadow(&self.thing_name, "time").await? else {
            return Ok(StoredTimeState::new(self.thing_name.clone()));
        };
        let decoded: Value = serde_json::from_slice(&payload).context("decode time shadow")?;
        let reported = decoded
            .get("state")
            .and_then(Value::as_object)
            .and_then(|state| state.get("reported"))
            .and_then(Value::as_object);
        Ok(StoredTimeState::from_reported_shadow(
            self.thing_name.clone(),
            reported,
        ))
    }

    async fn load_retained_command(&self) -> Result<Option<ConnectivityCommand>> {
        let topic = build_capability_command_topic(&self.thing_name)?;
        let Some(payload) = self.aws.get_retained_message(&topic).await? else {
            return Ok(None);
        };
        if payload.is_empty() {
            return Ok(None);
        }
        Ok(Some(ConnectivityCommand::from_payload(&payload)?))
    }

    async fn publish_time_state(
        &self,
        state: &StoredTimeState,
        current_time_iso: &str,
    ) -> Result<()> {
        let mut payload = json!({
            "schemaVersion": SCHEMA_VERSION,
            "adapterId": AWS_CONNECTIVITY_ADAPTER_ID,
            "thingName": self.thing_name,
            "capabilities": self.build_capabilities(state.mode == TIME_MODE_ACTIVE),
            "metrics": self.build_time_metrics(state, current_time_iso),
        });
        if state.mode == TIME_MODE_ACTIVE {
            if let Some(active_until_ms) = state.active_until_ms {
                payload["expiresAtMs"] = json!(active_until_ms);
                payload["expiredCapabilities"] = self.build_capabilities(false);
                payload["expiredMetrics"] = self.build_expired_metrics();
            }
        }
        self.publish_json(
            &build_capability_state_topic(&self.thing_name)?,
            true,
            payload,
        )
        .await
    }

    async fn publish_mcp_discovery(&self, mcp_available: bool, now_ms: i64) -> Result<()> {
        self.publish_json(
            &build_mcp_descriptor_topic(&self.thing_name)?,
            true,
            self.build_mcp_descriptor()?,
        )
        .await?;
        self.publish_json(
            &build_mcp_status_topic(&self.thing_name)?,
            true,
            self.build_mcp_status(mcp_available, now_ms),
        )
        .await
    }

    async fn publish_command_result(&self, payload: Value) -> Result<()> {
        self.publish_json(
            &build_capability_command_result_topic(&self.thing_name)?,
            true,
            payload,
        )
        .await
    }

    async fn publish_mcp_response(&self, session_id: &str, response: Value) -> Result<()> {
        self.publish_json(
            &build_mcp_session_s2c_topic(&self.thing_name, session_id)?,
            false,
            response,
        )
        .await
    }

    async fn publish_json(&self, topic: &str, retain: bool, payload: Value) -> Result<()> {
        let bytes = serde_json::to_vec(&payload).context("encode publish payload")?;
        self.aws.publish(topic, retain, bytes).await
    }

    async fn update_time_shadow(
        &self,
        state: &StoredTimeState,
        current_time_iso: &str,
    ) -> Result<()> {
        self.update_named_shadow(
            "time",
            json!({
                "state": {
                    "reported": {
                        "currentTimeIso": current_time_iso,
                        "mode": state.mode,
                        "activeUntilMs": state.active_until_ms,
                        "lastCommandId": state.last_command_id,
                        "observedAtMs": Value::Null,
                        "seq": Value::Null,
                    }
                }
            }),
        )
        .await
    }

    async fn update_mcp_shadow(&self, mcp_available: bool, now_ms: i64) -> Result<()> {
        self.update_named_shadow(
            "mcp",
            json!({
                "state": {
                    "reported": {
                        "descriptor": self.build_mcp_descriptor()?,
                        "status": self.build_mcp_status(mcp_available, now_ms),
                    }
                }
            }),
        )
        .await
    }

    async fn update_named_shadow(&self, shadow_name: &str, payload: Value) -> Result<()> {
        self.aws
            .update_thing_shadow(
                &self.thing_name,
                shadow_name,
                serde_json::to_vec(&payload).context("encode shadow update")?,
            )
            .await
    }

    pub fn build_mcp_descriptor(&self) -> Result<Value> {
        let topic_root = build_mcp_topic_root(&self.thing_name)?;
        let session_topic_pattern = json!({
            "clientToServer": format!("{topic_root}/session/{{sessionId}}/c2s"),
            "serverToClient": format!("{topic_root}/session/{{sessionId}}/s2c"),
        });
        Ok(json!({
            "serviceId": MCP_SERVICE_NAME,
            "serverInfo": {
                "name": "time",
                "version": self.server_version,
            },
            "transport": "mqtt-jsonrpc",
            "mcpProtocolVersion": MCP_PROTOCOL_VERSION,
            "topicRoot": topic_root,
            "descriptorTopic": build_mcp_descriptor_topic(&self.thing_name)?,
            "sessionTopicPattern": session_topic_pattern,
            "transports": [{
                "type": "mqtt-jsonrpc",
                "priority": 100,
                "topicRoot": topic_root,
                "sessionTopicPattern": session_topic_pattern,
            }],
            "leaseRequired": false,
            "leaseTtlMs": DEFAULT_LEASE_TTL_MS,
            "serverVersion": self.server_version,
        }))
    }

    pub fn build_mcp_status(&self, mcp_available: bool, now_ms: i64) -> Value {
        json!({
            "serviceId": MCP_SERVICE_NAME,
            "available": mcp_available,
            "updatedAtMs": now_ms,
        })
    }

    pub fn build_capabilities(&self, active: bool) -> Value {
        json!({
            "sparkplug": true,
            TIME_SERVICE_NAME: active,
            MCP_SERVICE_NAME: active,
        })
    }

    pub fn build_time_metrics(&self, state: &StoredTimeState, current_time_iso: &str) -> Value {
        let mut metrics = Map::new();
        metrics.insert(
            "currentTimeIso".to_string(),
            metric_string(current_time_iso.to_string()),
        );
        metrics.insert(
            "activeUntilMs".to_string(),
            metric_int64(state.active_until_ms.unwrap_or(0)),
        );
        if let Some(last_command_id) = state.last_command_id.as_ref() {
            metrics.insert(
                "lastCommandId".to_string(),
                metric_string(last_command_id.clone()),
            );
        }
        Value::Object(metrics)
    }

    pub fn build_expired_metrics(&self) -> Value {
        json!({
            "activeUntilMs": metric_int64(0),
        })
    }

    pub fn build_command_result(
        &self,
        command: &ConnectivityCommand,
        status: &str,
        message: Value,
        seq: i64,
    ) -> Value {
        json!({
            "schemaVersion": SCHEMA_VERSION,
            "adapterId": AWS_CONNECTIVITY_ADAPTER_ID,
            "commandId": command.command_id,
            "thingName": self.thing_name,
            "status": status,
            "target": {
                "redcon": command.redcon,
            },
            "message": message,
            "seq": seq,
        })
    }

    pub fn decode_mcp_event_message(&self, event: &Value) -> Result<Value> {
        if let Some(payload) = event.get("payload").and_then(Value::as_object) {
            return Ok(Value::Object(payload.clone()));
        }
        if let Some(payload_base64) = event
            .get("payloadBase64")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
        {
            let bytes = STANDARD
                .decode(payload_base64)
                .context("decode MCP payloadBase64")?;
            return serde_json::from_slice(&bytes).context("decode MCP JSON payload");
        }
        if let Some(raw_payload) = event
            .get("rawPayload")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
        {
            return serde_json::from_str(raw_payload).context("decode MCP rawPayload");
        }
        let mut message = Map::new();
        if let Some(event) = event.as_object() {
            for (key, value) in event {
                if !matches!(key.as_str(), "mqttTopic" | "payloadBase64" | "rawPayload") {
                    message.insert(key.clone(), value.clone());
                }
            }
        }
        Ok(Value::Object(message))
    }

    pub fn build_mcp_response(&self, message: &Value, active: bool, now_ms: i64) -> Option<Value> {
        let request_id = message.get("id").cloned().unwrap_or(Value::Null);
        let method = message.get("method").and_then(Value::as_str);
        let Some(method) = method else {
            return Some(build_json_rpc_error(
                request_id,
                -32600,
                "Invalid JSON-RPC request",
            ));
        };
        if request_id.is_null() && method.starts_with("notifications/") {
            return None;
        }
        if !active {
            return Some(build_json_rpc_error(
                request_id,
                -32000,
                "MCP service unavailable",
            ));
        }
        match method {
            "initialize" => Some(json!({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {
                            "listChanged": false,
                        }
                    },
                    "serverInfo": {
                        "name": "time",
                        "version": self.server_version,
                    },
                },
            })),
            "tools/list" => Some(json!({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": [{
                        "name": "time.now",
                        "title": "Current time",
                        "description": "Return the current UTC time observed by the virtual time device.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": false,
                        },
                    }]
                },
            })),
            "tools/call" => {
                let params = message.get("params").and_then(Value::as_object);
                let Some(params) = params else {
                    return Some(build_json_rpc_error(request_id, -32602, "Missing params"));
                };
                if params.get("name").and_then(Value::as_str) != Some("time.now") {
                    return Some(build_json_rpc_error(request_id, -32601, "Unknown tool"));
                }
                let current_time_iso = utc_iso(now_ms);
                Some(json!({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{
                            "type": "text",
                            "text": current_time_iso,
                        }],
                        "structuredContent": {
                            "currentTimeIso": current_time_iso,
                            "epochMs": now_ms,
                        },
                        "isError": false,
                    },
                }))
            }
            _ => Some(build_json_rpc_error(request_id, -32601, "Unknown method")),
        }
    }
}

pub fn metric_string(value: String) -> Value {
    json!({ "datatype": "String", "value": value })
}

pub fn metric_int64(value: i64) -> Value {
    json!({ "datatype": "Int64", "value": value })
}

pub fn build_json_rpc_error(request_id: Value, code: i64, message: &str) -> Value {
    json!({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    })
}

pub fn env_int(name: &str, default: i64) -> i64 {
    std::env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .and_then(|value| value.parse::<i64>().ok())
        .unwrap_or(default)
}

pub fn server_version_from_env() -> String {
    std::env::var("SERVER_VERSION")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .or_else(|| {
            std::env::var("TXING_VERSION")
                .ok()
                .map(|value| value.trim().to_string())
                .filter(|value| !value.is_empty())
        })
        .unwrap_or_else(|| DEFAULT_SERVER_VERSION.to_string())
}

pub async fn discover_time_thing_names<A: TimeAws + ?Sized>(aws: &A) -> Result<Vec<String>> {
    let mut thing_names = Vec::new();
    let mut next_token: Option<String> = None;
    loop {
        let page = aws.search_time_things(next_token.as_deref()).await?;
        thing_names.extend(page.thing_names);
        next_token = page.next_token;
        if next_token.is_none() {
            return Ok(thing_names);
        }
    }
}

pub async fn handle_scheduled_wake_for_time_devices_with_now<A: TimeAws + ?Sized>(
    event: &Value,
    aws: &A,
    active_ttl_ms: i64,
    server_version: &str,
    now_ms: i64,
) -> Result<Value> {
    let thing_names = discover_time_thing_names(aws).await?;
    let mut processed = Vec::new();
    let mut failed = Vec::new();
    for thing_name in thing_names.iter() {
        let runtime = TimeDeviceRuntime::new(thing_name, aws, active_ttl_ms, server_version)?;
        match runtime.handle_scheduled_wake_with_now(event, now_ms).await {
            Ok(result) => processed.push(result),
            Err(err) => {
                tracing::error!(thingName = %thing_name, error = %err, "time scheduled wake failed");
                failed.push(json!({
                    "thingName": thing_name,
                    "errorType": error_type_name(err.as_ref()),
                    "error": err.to_string(),
                }));
            }
        }
    }
    Ok(json!({
        "eventType": "schedule",
        "thingCount": thing_names.len(),
        "processedCount": processed.len(),
        "failedCount": failed.len(),
        "processed": processed,
        "failed": failed,
    }))
}

fn error_type_name(_error: &(dyn std::error::Error + Send + Sync + 'static)) -> &'static str {
    "Error"
}

pub async fn handle_lambda_event_from_env<A: TimeAws + ?Sized>(
    event: Value,
    aws: &A,
) -> Result<Value> {
    handle_lambda_event(
        event,
        aws,
        env_int("ACTIVE_TTL_MS", DEFAULT_ACTIVE_TTL_MS),
        &server_version_from_env(),
    )
    .await
}

pub async fn handle_lambda_event<A: TimeAws + ?Sized>(
    event: Value,
    aws: &A,
    active_ttl_ms: i64,
    server_version: &str,
) -> Result<Value> {
    let parsed_topic = event
        .get("mqttTopic")
        .and_then(Value::as_str)
        .and_then(parse_mcp_session_c2s_topic);
    if let Some((thing_name, _session_id)) = parsed_topic {
        let runtime = TimeDeviceRuntime::new(&thing_name, aws, active_ttl_ms, server_version)?;
        let result = runtime
            .handle_mcp_message_with_now(&event, utc_now_ms())
            .await?;
        tracing::info!(
            eventType = "mcp",
            thingName = result.get("thingName").and_then(|value| value.as_str()),
            active = result.get("active").and_then(|value| value.as_bool()),
            "time lambda invocation succeeded"
        );
        Ok(result)
    } else {
        let result = handle_scheduled_wake_for_time_devices_with_now(
            &event,
            aws,
            active_ttl_ms,
            server_version,
            utc_now_ms(),
        )
        .await?;
        tracing::info!(
            eventType = "schedule",
            thingCount = result.get("thingCount").and_then(|value| value.as_u64()),
            "time lambda invocation succeeded"
        );
        Ok(result)
    }
}

#[allow(dead_code)]
fn number_i64(value: i64) -> Value {
    Value::Number(Number::from(value))
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::{Arc, Mutex};

    use super::*;

    #[derive(Debug, Clone)]
    struct Published {
        topic: String,
        retain: bool,
        payload: Value,
    }

    #[derive(Debug, Default)]
    struct FakeAws {
        retained: Mutex<HashMap<String, Vec<u8>>>,
        published: Mutex<Vec<Published>>,
        shadow_updates: Mutex<Vec<(String, String, Value)>>,
        time_reported: Mutex<Map<String, Value>>,
        pages: Mutex<Vec<SearchPage>>,
        search_requests: Mutex<Vec<Option<String>>>,
        fail_thing: Mutex<Option<String>>,
    }

    #[async_trait]
    impl TimeAws for FakeAws {
        async fn search_time_things(&self, next_token: Option<&str>) -> Result<SearchPage> {
            self.search_requests
                .lock()
                .unwrap()
                .push(next_token.map(ToOwned::to_owned));
            let mut pages = self.pages.lock().unwrap();
            if pages.is_empty() {
                return Ok(SearchPage {
                    thing_names: vec![],
                    next_token: None,
                });
            }
            Ok(pages.remove(0))
        }

        async fn get_retained_message(&self, topic: &str) -> Result<Option<Vec<u8>>> {
            Ok(self.retained.lock().unwrap().get(topic).cloned())
        }

        async fn get_thing_shadow(
            &self,
            thing_name: &str,
            shadow_name: &str,
        ) -> Result<Option<Vec<u8>>> {
            if self
                .fail_thing
                .lock()
                .unwrap()
                .as_deref()
                .is_some_and(|failed| failed == thing_name)
            {
                bail!("boom");
            }
            if shadow_name != "time" {
                return Ok(Some(br#"{"state":{"reported":{}}}"#.to_vec()));
            }
            let reported = self.time_reported.lock().unwrap().clone();
            Ok(Some(
                serde_json::to_vec(&json!({"state": {"reported": reported}})).unwrap(),
            ))
        }

        async fn update_thing_shadow(
            &self,
            thing_name: &str,
            shadow_name: &str,
            payload: Vec<u8>,
        ) -> Result<()> {
            let decoded: Value = serde_json::from_slice(&payload)?;
            self.shadow_updates.lock().unwrap().push((
                thing_name.to_string(),
                shadow_name.to_string(),
                decoded.clone(),
            ));
            if shadow_name == "time" {
                if let Some(reported) = decoded
                    .get("state")
                    .and_then(Value::as_object)
                    .and_then(|state| state.get("reported"))
                    .and_then(Value::as_object)
                {
                    *self.time_reported.lock().unwrap() = reported.clone();
                }
            }
            Ok(())
        }

        async fn publish(&self, topic: &str, retain: bool, payload: Vec<u8>) -> Result<()> {
            self.published.lock().unwrap().push(Published {
                topic: topic.to_string(),
                retain,
                payload: serde_json::from_slice(&payload)?,
            });
            Ok(())
        }
    }

    fn command_payload(command_id: &str, redcon: i64, deadline_ms: i64) -> Vec<u8> {
        serde_json::to_vec(&json!({
            "schemaVersion": "2.0",
            "commandId": command_id,
            "thingName": "clock",
            "seq": 1,
            "target": {
                "redcon": redcon,
            },
            "reason": "redcon=1",
            "issuedAtMs": 1714380000000_i64,
            "deadlineMs": deadline_ms,
        }))
        .unwrap()
    }

    fn runtime<'a>(aws: &'a FakeAws) -> TimeDeviceRuntime<'a, FakeAws> {
        TimeDeviceRuntime::new("clock", aws, 300_000, "test").unwrap()
    }

    #[tokio::test]
    async fn minute_wake_publishes_current_time_and_sleep_state() {
        let aws = FakeAws::default();
        let result = runtime(&aws)
            .handle_scheduled_wake_with_now(&json!({}), 1714380000000)
            .await
            .unwrap();

        assert_eq!(result["mode"], TIME_MODE_SLEEP);
        assert_eq!(aws.time_reported.lock().unwrap()["mode"], TIME_MODE_SLEEP);
        let state_topic = build_capability_state_topic("clock").unwrap();
        let published = aws.published.lock().unwrap();
        let state_publish = published
            .iter()
            .find(|item| item.topic == state_topic)
            .expect("state publish");
        assert!(state_publish.retain);
        assert_eq!(state_publish.payload["schemaVersion"], "2.0");
        assert_eq!(
            state_publish.payload["adapterId"],
            AWS_CONNECTIVITY_ADAPTER_ID
        );
        assert_eq!(state_publish.payload["capabilities"]["sparkplug"], true);
        assert_eq!(state_publish.payload["capabilities"]["time"], false);
        assert_eq!(state_publish.payload["capabilities"]["mcp"], false);
        assert_eq!(
            state_publish.payload["metrics"]["currentTimeIso"]["value"],
            "2024-04-29T08:40:00Z"
        );
        assert!(state_publish.payload.get("observedAtMs").is_none());
        assert!(state_publish.payload.get("seq").is_none());
        assert!(state_publish.payload["metrics"].get("mode").is_none());
        let updates = aws.shadow_updates.lock().unwrap();
        let time_update = updates
            .iter()
            .find(|(_, shadow_name, _)| shadow_name == "time")
            .expect("time shadow update");
        assert!(time_update.2["state"]["reported"]["observedAtMs"].is_null());
        assert!(time_update.2["state"]["reported"]["seq"].is_null());
    }

    #[tokio::test]
    async fn redcon_one_command_enters_active_mode_and_publishes_mcp_status() {
        let aws = FakeAws::default();
        aws.retained.lock().unwrap().insert(
            build_capability_command_topic("clock").unwrap(),
            command_payload("cmd-active", 1, 1714380060000),
        );

        let result = runtime(&aws)
            .handle_scheduled_wake_with_now(&json!({}), 1714380000000)
            .await
            .unwrap();

        assert_eq!(result["mode"], TIME_MODE_ACTIVE);
        assert_eq!(result["activeUntilMs"], 1714380300000_i64);
        assert_eq!(
            aws.time_reported.lock().unwrap()["lastCommandId"],
            "cmd-active"
        );
        let published = aws.published.lock().unwrap();
        let state_publish = published
            .iter()
            .find(|item| item.topic == build_capability_state_topic("clock").unwrap())
            .expect("state publish");
        assert_eq!(state_publish.payload["expiresAtMs"], 1714380300000_i64);
        assert_eq!(state_publish.payload["expiredCapabilities"]["time"], false);
        assert_eq!(
            state_publish.payload["expiredMetrics"]["activeUntilMs"]["value"],
            0
        );
        let command_result = published
            .iter()
            .find(|item| item.topic == build_capability_command_result_topic("clock").unwrap())
            .expect("command result");
        assert_eq!(
            command_result.payload["adapterId"],
            AWS_CONNECTIVITY_ADAPTER_ID
        );
        assert_eq!(command_result.payload["status"], "succeeded");
        assert_eq!(command_result.payload["seq"], 1);
        assert_eq!(command_result.payload["target"], json!({"redcon": 1}));
        let status = published
            .iter()
            .find(|item| item.topic == "txings/clock/mcp/status")
            .expect("mcp status");
        assert_eq!(status.payload["available"], true);
    }

    #[tokio::test]
    async fn mcp_time_now_responds_over_session_topic_while_active() {
        let aws = FakeAws::default();
        aws.time_reported.lock().unwrap().extend([
            ("mode".to_string(), json!(TIME_MODE_ACTIVE)),
            ("activeUntilMs".to_string(), json!(1714380300000_i64)),
        ]);
        let message = json!({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "time.now",
                "arguments": {},
            },
        });
        let event = json!({
            "mqttTopic": "txings/clock/mcp/session/session-1/c2s",
            "payloadBase64": STANDARD.encode(serde_json::to_vec(&message).unwrap()),
        });

        let result = runtime(&aws)
            .handle_mcp_message_with_now(&event, 1714380005000)
            .await
            .unwrap();

        assert_eq!(result["active"], true);
        let published = aws.published.lock().unwrap();
        let response = published
            .iter()
            .find(|item| item.topic == build_mcp_session_s2c_topic("clock", "session-1").unwrap())
            .expect("mcp response");
        assert!(!response.retain);
        assert_eq!(response.payload["id"], 7);
        assert_eq!(
            response.payload["result"]["structuredContent"]["currentTimeIso"],
            "2024-04-29T08:40:05Z"
        );
    }

    #[tokio::test]
    async fn expired_retained_command_is_ignored() {
        let aws = FakeAws::default();
        aws.retained.lock().unwrap().insert(
            build_capability_command_topic("clock").unwrap(),
            command_payload("expired", 1, 1714379999000),
        );

        let result = runtime(&aws)
            .handle_scheduled_wake_with_now(&json!({}), 1714380000000)
            .await
            .unwrap();

        assert_eq!(result["mode"], TIME_MODE_SLEEP);
        assert!(result["lastCommandId"].is_null());
        assert!(
            !aws.published
                .lock()
                .unwrap()
                .iter()
                .any(|item| item.topic == build_capability_command_result_topic("clock").unwrap())
        );
        assert!(
            aws.time_reported
                .lock()
                .unwrap()
                .get("lastCommandId")
                .is_none_or(Value::is_null)
        );
    }

    #[tokio::test]
    async fn active_mode_times_out_to_redcon_four_state() {
        let aws = FakeAws::default();
        aws.time_reported.lock().unwrap().extend([
            ("mode".to_string(), json!(TIME_MODE_ACTIVE)),
            ("activeUntilMs".to_string(), json!(1714379999999_i64)),
            ("lastCommandId".to_string(), json!("cmd-active")),
        ]);

        let result = runtime(&aws)
            .handle_scheduled_wake_with_now(&json!({}), 1714380000000)
            .await
            .unwrap();

        assert_eq!(result["mode"], TIME_MODE_SLEEP);
        assert!(result["activeUntilMs"].is_null());
        let published = aws.published.lock().unwrap();
        let state_publish = published
            .iter()
            .find(|item| item.topic == build_capability_state_topic("clock").unwrap())
            .expect("state publish");
        assert_eq!(state_publish.payload["capabilities"]["mcp"], false);
    }

    #[tokio::test]
    async fn scheduled_wake_processes_paginated_time_things() {
        let aws = FakeAws::default();
        *aws.pages.lock().unwrap() = vec![
            SearchPage {
                thing_names: vec!["clock-a".to_string()],
                next_token: Some("page-2".to_string()),
            },
            SearchPage {
                thing_names: vec!["clock-b".to_string()],
                next_token: None,
            },
        ];

        let result = handle_scheduled_wake_for_time_devices_with_now(
            &json!({}),
            &aws,
            300_000,
            "test",
            1714380000000,
        )
        .await
        .unwrap();

        assert_eq!(result["thingCount"], 2);
        assert_eq!(result["processedCount"], 2);
        assert_eq!(result["failedCount"], 0);
        assert_eq!(
            *aws.search_requests.lock().unwrap(),
            vec![None, Some("page-2".to_string())]
        );
        let published = aws.published.lock().unwrap();
        assert!(
            published
                .iter()
                .any(|item| item.topic == build_capability_state_topic("clock-a").unwrap())
        );
        assert!(
            published
                .iter()
                .any(|item| item.topic == build_capability_state_topic("clock-b").unwrap())
        );
    }

    #[tokio::test]
    async fn scheduled_wake_reports_one_device_failure_and_continues() {
        let aws = Arc::new(FakeAws::default());
        *aws.pages.lock().unwrap() = vec![SearchPage {
            thing_names: vec!["clock-a".to_string(), "clock-b".to_string()],
            next_token: None,
        }];
        *aws.fail_thing.lock().unwrap() = Some("clock-a".to_string());

        let result = handle_scheduled_wake_for_time_devices_with_now(
            &json!({}),
            aws.as_ref(),
            300_000,
            "test",
            1714380000000,
        )
        .await
        .unwrap();

        assert_eq!(result["thingCount"], 2);
        assert_eq!(result["processedCount"], 1);
        assert_eq!(result["failedCount"], 1);
        assert_eq!(result["processed"][0]["thingName"], "clock-b");
        assert_eq!(result["failed"][0]["thingName"], "clock-a");
    }

    #[tokio::test]
    async fn lambda_handler_uses_mcp_topic_thing_without_env() {
        let aws = FakeAws::default();
        aws.time_reported.lock().unwrap().extend([
            ("mode".to_string(), json!(TIME_MODE_ACTIVE)),
            ("activeUntilMs".to_string(), json!(i64::MAX)),
        ]);
        let event = json!({
            "mqttTopic": "txings/clock/mcp/session/session-1/c2s",
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        });

        let result = handle_lambda_event(event, &aws, 300_000, "test")
            .await
            .unwrap();

        assert_eq!(result["thingName"], "clock");
        assert_eq!(result["sessionId"], "session-1");
    }
}
