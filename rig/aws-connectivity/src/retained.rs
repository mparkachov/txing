use std::collections::BTreeMap;

use anyhow::{Result, bail};
use serde::{Deserialize, Serialize};
use txing_capability_protocol::{CapabilityState, MetricValue, SCHEMA_VERSION, validate_segment};

pub const ADAPTER_ID: &str = "dev.txing.rig.AwsConnectivity";
pub const RETAINED_TOPIC_ROOT: &str = "txings";
pub const RETAINED_COMMAND_FILTER: &str = "txings/+/capability/v2/command";
pub const RETAINED_STATE_FILTER: &str = "txings/+/capability/v2/state";
pub const RETAINED_COMMAND_RESULT_FILTER: &str = "txings/+/capability/v2/command-result";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RetainedTopicKind {
    Command,
    State,
    CommandResult,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RetainedCapabilityState {
    #[serde(rename = "schemaVersion")]
    pub schema_version: String,
    #[serde(rename = "adapterId")]
    pub adapter_id: String,
    #[serde(rename = "thingName")]
    pub thing_name: String,
    #[serde(default)]
    pub capabilities: BTreeMap<String, bool>,
    #[serde(default)]
    pub metrics: BTreeMap<String, MetricValue>,
    #[serde(rename = "observedAtMs")]
    pub observed_at_ms: u64,
    #[serde(default)]
    pub seq: u64,
    #[serde(
        rename = "expiresAtMs",
        default,
        skip_serializing_if = "Option::is_none"
    )]
    pub expires_at_ms: Option<u64>,
    #[serde(
        rename = "expiredCapabilities",
        default,
        skip_serializing_if = "Option::is_none"
    )]
    pub expired_capabilities: Option<BTreeMap<String, bool>>,
    #[serde(
        rename = "expiredMetrics",
        default,
        skip_serializing_if = "Option::is_none"
    )]
    pub expired_metrics: Option<BTreeMap<String, MetricValue>>,
}

impl RetainedCapabilityState {
    pub fn from_slice(payload: &[u8]) -> Result<Self> {
        let value: Self = serde_json::from_slice(payload)?;
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<()> {
        if self.schema_version != SCHEMA_VERSION {
            bail!(
                "schemaVersion must be {SCHEMA_VERSION:?}, got {:?}",
                self.schema_version
            );
        }
        validate_segment(&self.thing_name, "thingName")?;
        if self.capabilities.is_empty() {
            bail!("capabilities must not be empty");
        }
        for metric in self.metrics.values() {
            metric.validate()?;
        }
        if let Some(metrics) = &self.expired_metrics {
            for metric in metrics.values() {
                metric.validate()?;
            }
        }
        Ok(())
    }

    pub fn to_local_state(
        &self,
        adapter_id: &str,
        now_ms: u64,
        seq: u64,
    ) -> Option<CapabilityState> {
        let expired = self
            .expires_at_ms
            .is_some_and(|expires_at_ms| now_ms >= expires_at_ms);
        if expired && self.expired_capabilities.is_none() && self.expired_metrics.is_none() {
            return None;
        }
        let capabilities = if expired {
            self.expired_capabilities
                .clone()
                .unwrap_or_else(|| self.capabilities.clone())
        } else {
            self.capabilities.clone()
        };
        let metrics = if expired {
            self.expired_metrics
                .clone()
                .unwrap_or_else(|| self.metrics.clone())
        } else {
            self.metrics.clone()
        };
        Some(CapabilityState {
            schema_version: SCHEMA_VERSION.to_string(),
            adapter_id: adapter_id.to_string(),
            thing_name: self.thing_name.clone(),
            capabilities,
            metrics,
            observed_at_ms: now_ms,
            seq,
        })
    }
}

pub fn build_retained_command_topic(thing_name: &str) -> Result<String> {
    Ok(format!(
        "{}/{}/capability/v2/command",
        RETAINED_TOPIC_ROOT,
        validate_segment(thing_name, "thingName")?
    ))
}

pub fn build_retained_state_topic(thing_name: &str) -> Result<String> {
    Ok(format!(
        "{}/{}/capability/v2/state",
        RETAINED_TOPIC_ROOT,
        validate_segment(thing_name, "thingName")?
    ))
}

pub fn build_retained_command_result_topic(thing_name: &str) -> Result<String> {
    Ok(format!(
        "{}/{}/capability/v2/command-result",
        RETAINED_TOPIC_ROOT,
        validate_segment(thing_name, "thingName")?
    ))
}

pub fn parse_retained_topic(topic: &str) -> Option<(&str, RetainedTopicKind)> {
    let mut parts = topic.split('/');
    if parts.next()? != RETAINED_TOPIC_ROOT {
        return None;
    }
    let thing_name = parts.next()?;
    if thing_name.is_empty() || parts.next()? != "capability" || parts.next()? != "v2" {
        return None;
    }
    let kind = match parts.next()? {
        "command" => RetainedTopicKind::Command,
        "state" => RetainedTopicKind::State,
        "command-result" => RetainedTopicKind::CommandResult,
        _ => return None,
    };
    if parts.next().is_some() {
        return None;
    }
    Some((thing_name, kind))
}

#[cfg(test)]
mod tests {
    use super::*;
    use txing_capability_protocol::MetricValue;

    #[test]
    fn builds_and_parses_retained_topics() {
        assert_eq!(
            build_retained_command_topic("time-1").unwrap(),
            "txings/time-1/capability/v2/command"
        );
        assert_eq!(
            parse_retained_topic("txings/time-1/capability/v2/state"),
            Some(("time-1", RetainedTopicKind::State))
        );
        assert_eq!(
            parse_retained_topic("txings/time-1/capability/v2/command-result"),
            Some(("time-1", RetainedTopicKind::CommandResult))
        );
    }

    #[test]
    fn expired_projection_replaces_capabilities_and_metrics() {
        let state = RetainedCapabilityState {
            schema_version: SCHEMA_VERSION.to_string(),
            adapter_id: "time-lambda".to_string(),
            thing_name: "time-1".to_string(),
            capabilities: BTreeMap::from([("sparkplug".to_string(), true)]),
            metrics: BTreeMap::from([("mode".to_string(), MetricValue::string("active"))]),
            observed_at_ms: 10,
            seq: 1,
            expires_at_ms: Some(20),
            expired_capabilities: Some(BTreeMap::from([("sparkplug".to_string(), false)])),
            expired_metrics: Some(BTreeMap::from([(
                "mode".to_string(),
                MetricValue::string("sleep"),
            )])),
        };

        let projected = state
            .to_local_state(ADAPTER_ID, 21, 2)
            .expect("expired projection");

        assert_eq!(projected.adapter_id, ADAPTER_ID);
        assert_eq!(projected.capabilities.get("sparkplug"), Some(&false));
        assert_eq!(
            projected.metrics.get("mode").map(|metric| &metric.value),
            Some(&serde_json::json!("sleep"))
        );
        assert_eq!(projected.observed_at_ms, 21);
        assert_eq!(projected.seq, 2);
    }

    #[test]
    fn expired_state_without_projection_stops_refreshing() {
        let state = RetainedCapabilityState {
            schema_version: SCHEMA_VERSION.to_string(),
            adapter_id: "time-lambda".to_string(),
            thing_name: "time-1".to_string(),
            capabilities: BTreeMap::from([("sparkplug".to_string(), true)]),
            metrics: BTreeMap::new(),
            observed_at_ms: 10,
            seq: 1,
            expires_at_ms: Some(20),
            expired_capabilities: None,
            expired_metrics: None,
        };

        assert!(state.to_local_state(ADAPTER_ID, 21, 2).is_none());
    }
}
