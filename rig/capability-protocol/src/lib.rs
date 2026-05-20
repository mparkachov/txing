use std::collections::BTreeMap;

use anyhow::{Result, anyhow, bail};
use serde::{Deserialize, Serialize};
use serde_json::{Number, Value};

pub const SCHEMA_VERSION: &str = "2.0";
pub const LOCAL_TOPIC_ROOT: &str = "dev/txing/rig/v2";
pub const INVENTORY_TOPIC: &str = "dev/txing/rig/v2/inventory";
pub const CAPABILITY_STATE_TOPIC_PREFIX: &str = "dev/txing/rig/v2/capability/state";
pub const CAPABILITY_COMMAND_TOPIC_PREFIX: &str = "dev/txing/rig/v2/capability/command";
pub const CAPABILITY_COMMAND_TOPIC_FILTER: &str = "dev/txing/rig/v2/capability/command/+";
pub const CAPABILITY_COMMAND_RESULT_TOPIC_PREFIX: &str =
    "dev/txing/rig/v2/capability/command-result";
pub const CAPABILITY_HEARTBEAT_TOPIC_PREFIX: &str = "dev/txing/rig/v2/capability/heartbeat";
pub const BLE_REDCON_METRIC: &str = "bleRedcon";

pub const COMMAND_PENDING: &str = "pending";
pub const COMMAND_ACCEPTED: &str = "accepted";
pub const COMMAND_SUCCEEDED: &str = "succeeded";
pub const COMMAND_FAILED: &str = "failed";
pub const COMMAND_REJECTED: &str = "rejected";
pub const HEARTBEAT_RUNNING: &str = "running";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Inventory {
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "managerId")]
    pub manager_id: String,
    pub devices: Vec<InventoryDevice>,
    pub seq: u64,
    #[serde(rename = "issuedAtMs")]
    pub issued_at_ms: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InventoryDevice {
    #[serde(rename = "thingName")]
    pub thing_name: String,
    #[serde(rename = "thingType")]
    pub thing_type: String,
    pub capabilities: Vec<String>,
    #[serde(rename = "redconCommandLevels")]
    pub redcon_command_levels: Vec<u8>,
    #[serde(rename = "redconRules")]
    pub redcon_rules: BTreeMap<u8, Vec<String>>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MetricValue {
    pub datatype: String,
    pub value: Value,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CapabilityState {
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "adapterId")]
    pub adapter_id: String,
    #[serde(rename = "thingName")]
    pub thing_name: String,
    pub capabilities: BTreeMap<String, bool>,
    #[serde(default)]
    pub metrics: BTreeMap<String, MetricValue>,
    #[serde(rename = "observedAtMs")]
    pub observed_at_ms: u64,
    #[serde(default)]
    pub seq: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapabilityCommand {
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "commandId")]
    pub command_id: String,
    #[serde(rename = "thingName")]
    pub thing_name: String,
    pub target: CapabilityCommandTarget,
    pub reason: String,
    #[serde(rename = "issuedAtMs")]
    pub issued_at_ms: u64,
    #[serde(rename = "deadlineMs", skip_serializing_if = "Option::is_none")]
    pub deadline_ms: Option<u64>,
    #[serde(default)]
    pub seq: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapabilityCommandTarget {
    pub redcon: u8,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapabilityCommandResult {
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "adapterId")]
    pub adapter_id: String,
    #[serde(rename = "commandId")]
    pub command_id: String,
    #[serde(rename = "thingName")]
    pub thing_name: String,
    pub status: String,
    pub target: CapabilityCommandResultTarget,
    pub message: Option<String>,
    #[serde(rename = "observedAtMs")]
    pub observed_at_ms: u64,
    #[serde(default)]
    pub seq: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapabilityCommandResultTarget {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub redcon: Option<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapabilityHeartbeat {
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

impl Inventory {
    pub fn new(
        manager_id: impl Into<String>,
        devices: Vec<InventoryDevice>,
        seq: u64,
        now_ms: u64,
    ) -> Self {
        Self {
            schema_version: SCHEMA_VERSION.to_string(),
            manager_id: manager_id.into(),
            devices,
            seq,
            issued_at_ms: now_ms,
        }
    }

    pub fn from_slice(payload: &[u8]) -> Result<Self> {
        let value: Self = serde_json::from_slice(payload)?;
        value.validate()?;
        Ok(value)
    }

    pub fn to_vec(&self) -> Result<Vec<u8>> {
        self.validate()?;
        Ok(serde_json::to_vec(self)?)
    }

    pub fn validate(&self) -> Result<()> {
        validate_schema(&self.schema_version)?;
        validate_segment(&self.manager_id, "managerId")?;
        for device in &self.devices {
            device.validate()?;
        }
        Ok(())
    }
}

impl InventoryDevice {
    pub fn validate(&self) -> Result<()> {
        validate_segment(&self.thing_name, "thingName")?;
        validate_segment(&self.thing_type, "thingType")?;
        if self.capabilities.is_empty() {
            bail!("capabilities must not be empty");
        }
        if self.redcon_command_levels.is_empty() {
            bail!("redconCommandLevels must not be empty");
        }
        for level in &self.redcon_command_levels {
            validate_redcon(*level, "redconCommandLevels")?;
        }
        for (level, capabilities) in &self.redcon_rules {
            validate_redcon(*level, "redconRules")?;
            if capabilities.is_empty() {
                bail!("redconRules.{level} must not be empty");
            }
            for capability in capabilities {
                validate_nonempty(capability, "redconRules capability")?;
            }
        }
        Ok(())
    }

    pub fn has_capability(&self, capability: &str) -> bool {
        self.capabilities
            .iter()
            .any(|candidate| candidate == capability)
    }
}

impl CapabilityState {
    pub fn new(
        adapter_id: impl Into<String>,
        thing_name: impl Into<String>,
        observed_at_ms: u64,
        seq: u64,
    ) -> Self {
        Self {
            schema_version: SCHEMA_VERSION.to_string(),
            adapter_id: adapter_id.into(),
            thing_name: thing_name.into(),
            capabilities: BTreeMap::new(),
            metrics: BTreeMap::new(),
            observed_at_ms,
            seq,
        }
    }

    pub fn from_slice(payload: &[u8]) -> Result<Self> {
        let value: Self = serde_json::from_slice(payload)?;
        value.validate()?;
        Ok(value)
    }

    pub fn to_vec(&self) -> Result<Vec<u8>> {
        self.validate()?;
        Ok(serde_json::to_vec(self)?)
    }

    pub fn validate(&self) -> Result<()> {
        validate_schema(&self.schema_version)?;
        validate_segment(&self.adapter_id, "adapterId")?;
        validate_segment(&self.thing_name, "thingName")?;
        if self.capabilities.is_empty() {
            bail!("capabilities must not be empty");
        }
        for capability in self.capabilities.keys() {
            validate_nonempty(capability, "capability")?;
        }
        for (name, metric) in &self.metrics {
            validate_nonempty(name, "metric name")?;
            metric.validate()?;
        }
        Ok(())
    }
}

impl MetricValue {
    pub fn boolean(value: bool) -> Self {
        Self {
            datatype: "Boolean".to_string(),
            value: Value::Bool(value),
        }
    }

    pub fn int32(value: i32) -> Self {
        Self {
            datatype: "Int32".to_string(),
            value: Value::Number(Number::from(value)),
        }
    }

    pub fn int64(value: i64) -> Self {
        Self {
            datatype: "Int64".to_string(),
            value: Value::Number(Number::from(value)),
        }
    }

    pub fn uint64(value: u64) -> Self {
        Self {
            datatype: "UInt64".to_string(),
            value: Value::Number(Number::from(value)),
        }
    }

    pub fn double(value: f64) -> Self {
        Self {
            datatype: "Double".to_string(),
            value: Number::from_f64(value)
                .map(Value::Number)
                .unwrap_or(Value::Null),
        }
    }

    pub fn string(value: impl Into<String>) -> Self {
        Self {
            datatype: "String".to_string(),
            value: Value::String(value.into()),
        }
    }

    pub fn validate(&self) -> Result<()> {
        match self.datatype.as_str() {
            "Boolean" if self.value.is_boolean() => Ok(()),
            "Int32" | "Int64" | "UInt32" | "UInt64"
                if self.value.as_i64().is_some() || self.value.as_u64().is_some() =>
            {
                Ok(())
            }
            "Float" | "Double" if self.value.as_f64().is_some() => Ok(()),
            "String" if self.value.is_string() => Ok(()),
            datatype => bail!("unsupported or mismatched metric datatype {datatype}"),
        }
    }
}

impl CapabilityCommand {
    pub fn new(
        command_id: impl Into<String>,
        thing_name: impl Into<String>,
        redcon: u8,
        reason: impl Into<String>,
        issued_at_ms: u64,
        seq: u64,
        deadline_ms: Option<u64>,
    ) -> Result<Self> {
        validate_redcon(redcon, "target.redcon")?;
        if let Some(deadline_ms) = deadline_ms {
            if deadline_ms <= issued_at_ms {
                bail!("deadlineMs must be after issuedAtMs");
            }
        }
        Ok(Self {
            schema_version: SCHEMA_VERSION.to_string(),
            command_id: command_id.into(),
            thing_name: thing_name.into(),
            target: CapabilityCommandTarget { redcon },
            reason: reason.into(),
            issued_at_ms,
            deadline_ms,
            seq,
        })
    }

    pub fn from_slice(payload: &[u8]) -> Result<Self> {
        let value: Self = serde_json::from_slice(payload)?;
        value.validate()?;
        Ok(value)
    }

    pub fn to_vec(&self) -> Result<Vec<u8>> {
        self.validate()?;
        Ok(serde_json::to_vec(self)?)
    }

    pub fn validate(&self) -> Result<()> {
        validate_schema(&self.schema_version)?;
        validate_nonempty(&self.command_id, "commandId")?;
        validate_segment(&self.thing_name, "thingName")?;
        validate_redcon(self.target.redcon, "target.redcon")?;
        validate_nonempty(&self.reason, "reason")?;
        Ok(())
    }
}

impl CapabilityCommandResult {
    pub fn new(
        adapter_id: impl Into<String>,
        command_id: impl Into<String>,
        thing_name: impl Into<String>,
        status: impl Into<String>,
        observed_at_ms: u64,
        seq: u64,
    ) -> Self {
        Self {
            schema_version: SCHEMA_VERSION.to_string(),
            adapter_id: adapter_id.into(),
            command_id: command_id.into(),
            thing_name: thing_name.into(),
            status: status.into(),
            target: CapabilityCommandResultTarget { redcon: None },
            message: None,
            observed_at_ms,
            seq,
        }
    }

    pub fn from_slice(payload: &[u8]) -> Result<Self> {
        let value: Self = serde_json::from_slice(payload)?;
        value.validate()?;
        Ok(value)
    }

    pub fn to_vec(&self) -> Result<Vec<u8>> {
        self.validate()?;
        Ok(serde_json::to_vec(self)?)
    }

    pub fn validate(&self) -> Result<()> {
        validate_schema(&self.schema_version)?;
        validate_segment(&self.adapter_id, "adapterId")?;
        validate_nonempty(&self.command_id, "commandId")?;
        validate_segment(&self.thing_name, "thingName")?;
        match self.status.as_str() {
            COMMAND_PENDING | COMMAND_ACCEPTED | COMMAND_SUCCEEDED | COMMAND_FAILED
            | COMMAND_REJECTED => {}
            _ => bail!("unsupported command result status {}", self.status),
        }
        if let Some(redcon) = self.target.redcon {
            validate_redcon(redcon, "target.redcon")?;
        }
        Ok(())
    }
}

impl CapabilityHeartbeat {
    pub fn new(
        adapter_id: impl Into<String>,
        status: impl Into<String>,
        active_thing_name: Option<String>,
        observed_at_ms: u64,
        seq: u64,
    ) -> Self {
        Self {
            schema_version: SCHEMA_VERSION.to_string(),
            adapter_id: adapter_id.into(),
            status: status.into(),
            active_thing_name,
            observed_at_ms,
            seq,
        }
    }

    pub fn from_slice(payload: &[u8]) -> Result<Self> {
        let value: Self = serde_json::from_slice(payload)?;
        value.validate()?;
        Ok(value)
    }

    pub fn to_vec(&self) -> Result<Vec<u8>> {
        self.validate()?;
        Ok(serde_json::to_vec(self)?)
    }

    pub fn validate(&self) -> Result<()> {
        validate_schema(&self.schema_version)?;
        validate_segment(&self.adapter_id, "adapterId")?;
        validate_nonempty(&self.status, "status")?;
        if let Some(thing_name) = &self.active_thing_name {
            validate_segment(thing_name, "activeThingName")?;
        }
        Ok(())
    }
}

pub fn build_capability_state_topic(thing_name: &str, adapter_id: &str) -> Result<String> {
    Ok(format!(
        "{}/{}/{}",
        CAPABILITY_STATE_TOPIC_PREFIX,
        validate_segment(thing_name, "thingName")?,
        validate_segment(adapter_id, "adapterId")?
    ))
}

pub fn build_capability_command_topic(thing_name: &str) -> Result<String> {
    Ok(format!(
        "{}/{}",
        CAPABILITY_COMMAND_TOPIC_PREFIX,
        validate_segment(thing_name, "thingName")?
    ))
}

pub fn build_capability_command_result_topic(thing_name: &str, adapter_id: &str) -> Result<String> {
    Ok(format!(
        "{}/{}/{}",
        CAPABILITY_COMMAND_RESULT_TOPIC_PREFIX,
        validate_segment(thing_name, "thingName")?,
        validate_segment(adapter_id, "adapterId")?
    ))
}

pub fn build_capability_heartbeat_topic(adapter_id: &str) -> Result<String> {
    Ok(format!(
        "{}/{}",
        CAPABILITY_HEARTBEAT_TOPIC_PREFIX,
        validate_segment(adapter_id, "adapterId")?
    ))
}

pub fn parse_capability_state_topic(topic: &str) -> Option<(&str, &str)> {
    parse_two_segment_suffix(topic, CAPABILITY_STATE_TOPIC_PREFIX)
}

pub fn parse_capability_command_topic(topic: &str) -> Option<&str> {
    let prefix = format!("{CAPABILITY_COMMAND_TOPIC_PREFIX}/");
    let suffix = topic.strip_prefix(&prefix)?;
    (!suffix.is_empty() && !suffix.contains('/')).then_some(suffix)
}

pub fn parse_capability_command_result_topic(topic: &str) -> Option<(&str, &str)> {
    parse_two_segment_suffix(topic, CAPABILITY_COMMAND_RESULT_TOPIC_PREFIX)
}

pub fn parse_capability_heartbeat_topic(topic: &str) -> Option<&str> {
    let prefix = format!("{CAPABILITY_HEARTBEAT_TOPIC_PREFIX}/");
    let suffix = topic.strip_prefix(&prefix)?;
    (!suffix.is_empty() && !suffix.contains('/')).then_some(suffix)
}

fn parse_two_segment_suffix<'a>(topic: &'a str, prefix: &str) -> Option<(&'a str, &'a str)> {
    let prefix = format!("{prefix}/");
    let suffix = topic.strip_prefix(&prefix)?;
    let mut parts = suffix.split('/');
    let first = parts.next()?;
    let second = parts.next()?;
    if first.is_empty() || second.is_empty() || parts.next().is_some() {
        return None;
    }
    Some((first, second))
}

pub fn command_deadline_expired(command: &CapabilityCommand, now_ms: u64) -> bool {
    command
        .deadline_ms
        .is_some_and(|deadline| now_ms > deadline)
}

pub fn normalize_ble_target_redcon(redcon: u8) -> Result<u8> {
    match redcon {
        1 | 2 | 3 => Ok(3),
        4 => Ok(4),
        _ => bail!("unsupported BLE target REDCON {redcon}"),
    }
}

pub fn topic_payload_thing_mismatch(topic_thing: &str, payload_thing: &str) -> anyhow::Error {
    anyhow!("topic thingName {topic_thing} does not match payload thingName {payload_thing}")
}

pub fn validate_schema(schema_version: &str) -> Result<()> {
    if schema_version != SCHEMA_VERSION {
        bail!("schemaVersion must be {SCHEMA_VERSION:?}, got {schema_version:?}");
    }
    Ok(())
}

pub fn validate_segment<'a>(value: &'a str, field_name: &str) -> Result<&'a str> {
    validate_nonempty(value, field_name)?;
    if value.contains('/') || value.contains('+') || value.contains('#') {
        return Err(anyhow!("{field_name} must be a literal MQTT segment"));
    }
    Ok(value)
}

pub fn validate_nonempty(value: &str, field_name: &str) -> Result<()> {
    if value.trim().is_empty() {
        bail!("{field_name} must not be empty");
    }
    Ok(())
}

pub fn validate_redcon(level: u8, field_name: &str) -> Result<()> {
    if !(1..=4).contains(&level) {
        bail!("{field_name} must be a REDCON level 1 through 4");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn command_requires_redcon_target() {
        let payload = br#"{"schemaVersion":"2.0","commandId":"cmd-1","thingName":"power-1","target":{"redcon":3},"reason":"operator","issuedAtMs":1}"#;

        let command = CapabilityCommand::from_slice(payload).unwrap();

        assert_eq!(command.target.redcon, 3);
        assert_eq!(
            command.to_vec().unwrap(),
            serde_json::to_vec(&command).unwrap()
        );
    }

    #[test]
    fn topic_parsing_uses_v2_root() {
        assert_eq!(
            build_capability_state_topic("weather-1", "dev.txing.rig.BleConnectivity").unwrap(),
            "dev/txing/rig/v2/capability/state/weather-1/dev.txing.rig.BleConnectivity"
        );
        assert_eq!(
            parse_capability_command_topic("dev/txing/rig/v2/capability/command/weather-1"),
            Some("weather-1")
        );
        assert_eq!(
            parse_capability_state_topic(
                "dev/txing/rig/v2/capability/state/weather-1/dev.txing.rig.BleConnectivity"
            ),
            Some(("weather-1", "dev.txing.rig.BleConnectivity"))
        );
        assert_eq!(
            parse_capability_heartbeat_topic(
                "dev/txing/rig/v2/capability/heartbeat/dev.txing.rig.BleConnectivity"
            ),
            Some("dev.txing.rig.BleConnectivity")
        );
    }

    #[test]
    fn heartbeat_round_trips() {
        let heartbeat = CapabilityHeartbeat {
            schema_version: SCHEMA_VERSION.to_string(),
            adapter_id: "dev.txing.rig.AwsConnectivity".to_string(),
            status: HEARTBEAT_RUNNING.to_string(),
            active_thing_name: Some("clock".to_string()),
            observed_at_ms: 1714380000000,
            seq: 1,
        };

        let decoded = CapabilityHeartbeat::from_slice(&heartbeat.to_vec().unwrap()).unwrap();

        assert_eq!(decoded, heartbeat);
    }

    #[test]
    fn inventory_device_capability_lookup_uses_capability_list() {
        let device = InventoryDevice {
            thing_name: "power-1".to_string(),
            thing_type: "power".to_string(),
            capabilities: vec!["sparkplug".to_string(), "ble".to_string()],
            redcon_command_levels: vec![4, 3],
            redcon_rules: BTreeMap::from([(4, vec!["sparkplug".to_string()])]),
        };

        assert!(device.has_capability("ble"));
        assert!(!device.has_capability("unknown"));
    }
}
