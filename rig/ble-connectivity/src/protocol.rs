use std::collections::BTreeMap;

use anyhow::{Result, anyhow, bail};
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const SCHEMA_VERSION: &str = "2.0";
pub const INVENTORY_TOPIC: &str = "dev/txing/rig/v2/inventory";
pub const CAPABILITY_STATE_TOPIC_PREFIX: &str = "dev/txing/rig/v2/capability/state";
pub const CAPABILITY_COMMAND_TOPIC_PREFIX: &str = "dev/txing/rig/v2/capability/command";
pub const CAPABILITY_COMMAND_RESULT_TOPIC_PREFIX: &str =
    "dev/txing/rig/v2/capability/command-result";
pub const CAPABILITY_HEARTBEAT_TOPIC_PREFIX: &str = "dev/txing/rig/v2/capability/heartbeat";

pub const COMMAND_ACCEPTED: &str = "accepted";
pub const COMMAND_SUCCEEDED: &str = "succeeded";
pub const COMMAND_FAILED: &str = "failed";
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

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
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

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
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
    pub fn from_slice(payload: &[u8]) -> Result<Self> {
        let value: Self = serde_json::from_slice(payload)?;
        value.validate()?;
        Ok(value)
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
        for capability in &self.capabilities {
            validate_nonempty(capability, "capability")?;
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

    pub fn has_capability(&self, name: &str) -> bool {
        self.capabilities
            .iter()
            .any(|capability| capability == name)
    }
}

impl CapabilityState {
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

    pub fn int32(value: impl Into<i64>) -> Self {
        Self {
            datatype: "Int32".to_string(),
            value: Value::Number(value.into().into()),
        }
    }

    pub fn double(value: f64) -> Self {
        Self {
            datatype: "Double".to_string(),
            value: serde_json::Number::from_f64(value)
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
    pub fn from_slice(payload: &[u8]) -> Result<Self> {
        let value: Self = serde_json::from_slice(payload)?;
        value.validate()?;
        Ok(value)
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
        adapter_id: &str,
        command: &CapabilityCommand,
        status: &str,
        target_redcon: Option<u8>,
        message: Option<String>,
        observed_at_ms: u64,
    ) -> Self {
        Self {
            schema_version: SCHEMA_VERSION.to_string(),
            adapter_id: adapter_id.to_string(),
            command_id: command.command_id.clone(),
            thing_name: command.thing_name.clone(),
            status: status.to_string(),
            target: CapabilityCommandResultTarget {
                redcon: target_redcon,
            },
            message,
            observed_at_ms,
            seq: command.seq,
        }
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
            COMMAND_ACCEPTED | COMMAND_SUCCEEDED | COMMAND_FAILED => {}
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
        adapter_id: &str,
        active_thing_name: Option<String>,
        observed_at_ms: u64,
        seq: u64,
    ) -> Self {
        Self {
            schema_version: SCHEMA_VERSION.to_string(),
            adapter_id: adapter_id.to_string(),
            status: HEARTBEAT_RUNNING.to_string(),
            active_thing_name,
            observed_at_ms,
            seq,
        }
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

pub fn parse_capability_command_topic(topic: &str) -> Option<&str> {
    let prefix = format!("{CAPABILITY_COMMAND_TOPIC_PREFIX}/");
    let suffix = topic.strip_prefix(&prefix)?;
    (!suffix.is_empty() && !suffix.contains('/')).then_some(suffix)
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

pub fn normalize_ble_target_redcon(level: u8) -> Result<u8> {
    validate_redcon(level, "target.redcon")?;
    Ok(match level {
        1 | 2 => 3,
        3 | 4 => level,
        _ => unreachable!("validated above"),
    })
}

pub fn command_deadline_expired(command: &CapabilityCommand, now_ms: u64) -> bool {
    command
        .deadline_ms
        .is_some_and(|deadline| now_ms >= deadline)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn topics_use_ble_connectivity_adapter_id() {
        assert_eq!(
            build_capability_state_topic("power-1", "dev.txing.rig.BleConnectivity").unwrap(),
            "dev/txing/rig/v2/capability/state/power-1/dev.txing.rig.BleConnectivity"
        );
        assert_eq!(
            build_capability_command_result_topic("power-1", "dev.txing.rig.BleConnectivity")
                .unwrap(),
            "dev/txing/rig/v2/capability/command-result/power-1/dev.txing.rig.BleConnectivity"
        );
        assert_eq!(
            parse_capability_command_topic("dev/txing/rig/v2/capability/command/weather-1"),
            Some("weather-1")
        );
    }

    #[test]
    fn command_requires_redcon_target() {
        let payload = br#"{"schemaVersion":"2.0","commandId":"cmd-1","thingName":"power-1","target":{"redcon":3},"reason":"operator","issuedAtMs":1}"#;

        let command = CapabilityCommand::from_slice(payload).unwrap();

        assert_eq!(command.target.redcon, 3);
        assert_eq!(normalize_ble_target_redcon(1).unwrap(), 3);
        assert_eq!(normalize_ble_target_redcon(2).unwrap(), 3);
        assert_eq!(normalize_ble_target_redcon(4).unwrap(), 4);
    }
}
