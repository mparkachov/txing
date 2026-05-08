use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};
use tokio::sync::mpsc;

use crate::error::{Result, RigError};

pub const SCHEMA_VERSION: &str = "1.0";
pub const LOCAL_TOPIC_ROOT: &str = "dev/txing/rig/v1/connectivity";
pub const COMMAND_TOPIC_PREFIX: &str = "dev/txing/rig/v1/connectivity/command";
pub const STATE_TOPIC_PREFIX: &str = "dev/txing/rig/v1/connectivity/state";
pub const COMMAND_RESULT_TOPIC_PREFIX: &str = "dev/txing/rig/v1/connectivity/command-result";
pub const HEARTBEAT_TOPIC_PREFIX: &str = "dev/txing/rig/v1/connectivity/heartbeat";

pub const TRANSPORT_BLE_GATT: &str = "ble-gatt";
pub const SLEEP_MODEL_BLE_CONNECTED_IDLE: &str = "ble-connected-idle";
pub const PRESENCE_ONLINE: &str = "online";
pub const CONTROL_IMMEDIATE: &str = "immediate";
pub const COMMAND_ACCEPTED: &str = "accepted";
pub const COMMAND_SUCCEEDED: &str = "succeeded";
pub const COMMAND_FAILED: &str = "failed";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PubSubMessage {
    pub topic: String,
    pub payload: Vec<u8>,
}

#[derive(Clone, Default)]
pub struct InMemoryPubSub {
    inner: Arc<Mutex<HashMap<String, Vec<mpsc::UnboundedSender<PubSubMessage>>>>>,
}

impl InMemoryPubSub {
    pub async fn publish(
        &self,
        topic: impl Into<String>,
        payload: impl Into<Vec<u8>>,
    ) -> Result<()> {
        let topic = topic.into();
        let payload = payload.into();
        let subscribers = {
            let inner = self.inner.lock().expect("pubsub lock");
            inner
                .iter()
                .filter(|(subscription, _)| topic_matches(subscription, &topic))
                .flat_map(|(_, senders)| senders.clone())
                .collect::<Vec<_>>()
        };
        for sender in subscribers {
            let _ = sender.send(PubSubMessage {
                topic: topic.clone(),
                payload: payload.clone(),
            });
        }
        Ok(())
    }

    pub async fn subscribe(&self, topic: impl Into<String>) -> Subscription {
        let topic = topic.into();
        let (sender, receiver) = mpsc::unbounded_channel();
        self.inner
            .lock()
            .expect("pubsub lock")
            .entry(topic.clone())
            .or_default()
            .push(sender);
        Subscription {
            topic,
            receiver,
            bus: self.clone(),
        }
    }

    fn unsubscribe(&self, topic: &str) {
        self.inner.lock().expect("pubsub lock").remove(topic);
    }
}

pub struct Subscription {
    topic: String,
    receiver: mpsc::UnboundedReceiver<PubSubMessage>,
    bus: InMemoryPubSub,
}

impl Subscription {
    pub async fn recv(&mut self) -> Option<PubSubMessage> {
        self.receiver.recv().await
    }

    pub fn close(&mut self) {
        self.bus.unsubscribe(&self.topic);
    }
}

impl Drop for Subscription {
    fn drop(&mut self) {
        self.close();
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ConnectivityCommand {
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "commandId")]
    pub command_id: String,
    #[serde(rename = "thingName")]
    pub thing_name: String,
    pub target: ConnectivityCommandTarget,
    pub reason: String,
    #[serde(rename = "issuedAtMs")]
    pub issued_at_ms: u64,
    #[serde(rename = "deadlineMs", skip_serializing_if = "Option::is_none")]
    pub deadline_ms: Option<u64>,
    #[serde(default)]
    pub seq: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ConnectivityCommandTarget {
    pub power: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ConnectivityCommandResult {
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "adapterId")]
    pub adapter_id: String,
    #[serde(rename = "commandId")]
    pub command_id: String,
    #[serde(rename = "thingName")]
    pub thing_name: String,
    pub status: String,
    pub message: Option<String>,
    #[serde(rename = "observedAtMs")]
    pub observed_at_ms: u64,
    #[serde(default)]
    pub seq: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ConnectivityState {
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "adapterId")]
    pub adapter_id: String,
    #[serde(rename = "thingName")]
    pub thing_name: String,
    pub transport: String,
    #[serde(rename = "nativeIdentity")]
    pub native_identity: HashMap<String, String>,
    pub presence: String,
    #[serde(rename = "controlAvailability")]
    pub control_availability: String,
    pub power: Option<bool>,
    #[serde(rename = "sleepModel")]
    pub sleep_model: String,
    #[serde(rename = "batteryMv")]
    pub battery_mv: Option<u16>,
    #[serde(rename = "observedAtMs")]
    pub observed_at_ms: u64,
    #[serde(default)]
    pub seq: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ConnectivityHeartbeat {
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "adapterId")]
    pub adapter_id: String,
    pub status: String,
    #[serde(rename = "activeThingName")]
    pub active_thing_name: Option<String>,
    #[serde(rename = "observedAtMs")]
    pub observed_at_ms: u64,
    #[serde(default)]
    pub seq: u64,
}

impl ConnectivityCommand {
    pub fn new(command_id: impl Into<String>, thing_name: impl Into<String>, power: bool) -> Self {
        Self {
            schema_version: SCHEMA_VERSION.to_string(),
            command_id: command_id.into(),
            thing_name: thing_name.into(),
            target: ConnectivityCommandTarget { power },
            reason: "rust-debug".to_string(),
            issued_at_ms: now_ms(),
            deadline_ms: None,
            seq: 0,
        }
    }

    pub fn to_json(&self) -> Result<Vec<u8>> {
        serde_json::to_vec(self).map_err(|err| RigError::new("pubsub", err.to_string()))
    }

    pub fn from_slice(payload: &[u8]) -> Result<Self> {
        let command: Self = serde_json::from_slice(payload)
            .map_err(|err| RigError::new("pubsub", format!("invalid command JSON: {err}")))?;
        if command.schema_version != SCHEMA_VERSION {
            return Err(RigError::new(
                "pubsub",
                format!("schemaVersion must be {SCHEMA_VERSION:?}"),
            ));
        }
        Ok(command)
    }
}

impl ConnectivityCommandResult {
    pub fn to_json(&self) -> Result<Vec<u8>> {
        serde_json::to_vec(self).map_err(|err| RigError::new("pubsub", err.to_string()))
    }
}

impl ConnectivityState {
    pub fn to_json(&self) -> Result<Vec<u8>> {
        serde_json::to_vec(self).map_err(|err| RigError::new("pubsub", err.to_string()))
    }

    pub fn from_slice(payload: &[u8]) -> Result<Self> {
        serde_json::from_slice(payload)
            .map_err(|err| RigError::new("pubsub", format!("invalid state JSON: {err}")))
    }
}

impl ConnectivityHeartbeat {
    pub fn to_json(&self) -> Result<Vec<u8>> {
        serde_json::to_vec(self).map_err(|err| RigError::new("pubsub", err.to_string()))
    }
}

pub fn build_command_topic(thing_name: &str) -> String {
    format!("{COMMAND_TOPIC_PREFIX}/{}", topic_segment(thing_name))
}

pub fn build_state_topic(thing_name: &str) -> String {
    format!("{STATE_TOPIC_PREFIX}/{}", topic_segment(thing_name))
}

pub fn build_command_result_topic(thing_name: &str) -> String {
    format!(
        "{COMMAND_RESULT_TOPIC_PREFIX}/{}",
        topic_segment(thing_name)
    )
}

pub fn build_heartbeat_topic(adapter_id: &str) -> String {
    format!("{HEARTBEAT_TOPIC_PREFIX}/{}", topic_segment(adapter_id))
}

fn topic_segment(value: &str) -> String {
    let value = value.trim();
    assert!(!value.is_empty(), "topic segment must not be empty");
    assert!(
        !value.contains('/') && !value.contains('+') && !value.contains('#'),
        "topic segment must be literal"
    );
    value.to_string()
}

fn topic_matches(subscription: &str, topic: &str) -> bool {
    if subscription == topic {
        return true;
    }
    let sub_parts: Vec<&str> = subscription.split('/').collect();
    let topic_parts: Vec<&str> = topic.split('/').collect();
    let mut index = 0usize;
    while index < sub_parts.len() {
        match sub_parts[index] {
            "#" => return true,
            "+" => {
                if index >= topic_parts.len() {
                    return false;
                }
            }
            literal => {
                if topic_parts.get(index).copied() != Some(literal) {
                    return false;
                }
            }
        }
        index += 1;
    }
    index == topic_parts.len()
}

pub fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}
