use std::collections::BTreeMap;

use anyhow::{Result, bail};
use serde_json::Value;

use crate::sparkplug::{self, Metric};
use txing_capability_protocol::{
    CapabilityCommand, CapabilityCommandResult, CapabilityState, InventoryDevice, MetricValue,
};

const STATE_TTL_MS: u64 = 45_000;

#[derive(Debug, Clone, PartialEq)]
pub struct DeviceSnapshot {
    pub thing_name: String,
    pub thing_type: String,
    pub capabilities: BTreeMap<String, bool>,
    pub metrics: BTreeMap<String, MetricValue>,
    pub redcon: Option<u8>,
    pub sparkplug_available: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub enum DevicePublication {
    Birth { redcon: u8, metrics: Vec<Metric> },
    Data { redcon: u8, metrics: Vec<Metric> },
    Death,
    None,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MqttWill {
    pub topic: String,
    pub payload: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MqttSessionSpec {
    pub client_id: String,
    pub will: MqttWill,
}

pub fn node_client_id(edge_node_id: &str) -> String {
    format!("{edge_node_id}-sparkplug-manager")
}

#[derive(Debug, Clone)]
pub struct DeviceRuntimeState {
    inventory: InventoryDevice,
    adapter_states: BTreeMap<String, CapabilityState>,
    last_published_redcon: Option<u8>,
    last_published_capabilities: BTreeMap<String, bool>,
    last_published_metrics: BTreeMap<String, MetricValue>,
    born: bool,
}

impl DeviceRuntimeState {
    pub fn new(inventory: InventoryDevice) -> Self {
        Self {
            inventory,
            adapter_states: BTreeMap::new(),
            last_published_redcon: None,
            last_published_capabilities: BTreeMap::new(),
            last_published_metrics: BTreeMap::new(),
            born: false,
        }
    }

    pub fn inventory(&self) -> &InventoryDevice {
        &self.inventory
    }

    pub fn replace_inventory(&mut self, inventory: InventoryDevice) {
        if self.inventory.capabilities != inventory.capabilities {
            self.born = false;
            self.last_published_redcon = None;
            self.last_published_capabilities.clear();
            self.last_published_metrics.clear();
        }
        self.inventory = inventory;
    }

    pub fn observe_state(&mut self, state: CapabilityState) -> Result<()> {
        state.validate()?;
        if state.thing_name != self.inventory.thing_name {
            bail!(
                "state thingName {} does not match inventory thingName {}",
                state.thing_name,
                self.inventory.thing_name
            );
        }
        self.adapter_states.insert(state.adapter_id.clone(), state);
        Ok(())
    }

    pub fn snapshot(&self, now_ms: u64) -> DeviceSnapshot {
        let mut capabilities: BTreeMap<String, bool> = BTreeMap::new();
        let mut metrics: BTreeMap<String, MetricValue> = BTreeMap::new();
        for capability in &self.inventory.capabilities {
            capabilities.insert(capability.clone(), false);
        }
        for state in self.adapter_states.values() {
            if state.observed_at_ms + STATE_TTL_MS < now_ms {
                continue;
            }
            for (capability, available) in &state.capabilities {
                if let Some(current) = capabilities.get_mut(capability) {
                    *current = *current || *available;
                }
            }
            for (name, metric) in &state.metrics {
                metrics.insert(name.clone(), metric.clone());
            }
        }
        let redcon = select_best_redcon(&self.inventory.redcon_rules, &capabilities);
        let sparkplug_available = capabilities.get("sparkplug").copied().unwrap_or(false);
        DeviceSnapshot {
            thing_name: self.inventory.thing_name.clone(),
            thing_type: self.inventory.thing_type.clone(),
            capabilities,
            metrics,
            redcon,
            sparkplug_available,
        }
    }

    pub fn decide_publication(&mut self, now_ms: u64) -> Result<DevicePublication> {
        let snapshot = self.snapshot(now_ms);
        if !snapshot.sparkplug_available {
            if self.born {
                self.born = false;
                self.last_published_redcon = None;
                self.last_published_capabilities.clear();
                self.last_published_metrics.clear();
                return Ok(DevicePublication::Death);
            }
            return Ok(DevicePublication::None);
        }
        let redcon = snapshot.redcon.unwrap_or(4);
        let capabilities_changed = self.last_published_capabilities != snapshot.capabilities;
        let metrics_changed = self.last_published_metrics != snapshot.metrics;
        let metrics = if !self.born
            || self.last_published_redcon != Some(redcon)
            || capabilities_changed
            || metrics_changed
        {
            sparkplug_metrics_from_snapshot(&snapshot.capabilities, &snapshot.metrics)?
        } else {
            Vec::new()
        };
        if !self.born {
            self.born = true;
            self.last_published_redcon = Some(redcon);
            self.last_published_capabilities = snapshot.capabilities;
            self.last_published_metrics = snapshot.metrics;
            return Ok(DevicePublication::Birth { redcon, metrics });
        }
        if self.last_published_redcon != Some(redcon) || capabilities_changed || metrics_changed {
            self.last_published_redcon = Some(redcon);
            self.last_published_capabilities = snapshot.capabilities;
            self.last_published_metrics = snapshot.metrics;
            return Ok(DevicePublication::Data { redcon, metrics });
        }
        Ok(DevicePublication::None)
    }
}

pub fn select_best_redcon(
    rules: &BTreeMap<u8, Vec<String>>,
    capabilities: &BTreeMap<String, bool>,
) -> Option<u8> {
    rules
        .iter()
        .filter(|(_, required)| {
            required
                .iter()
                .all(|capability| capabilities.get(capability).copied().unwrap_or(false))
        })
        .map(|(level, _)| *level)
        .min()
}

pub fn command_from_dcmd(
    thing_name: &str,
    payload: &[u8],
    command_id: String,
    now_ms: u64,
    deadline_ms: Option<u64>,
) -> Result<Option<CapabilityCommand>> {
    let Some(decoded) = sparkplug::decode_redcon_command(payload)? else {
        return Ok(None);
    };
    CapabilityCommand::new(
        command_id,
        thing_name,
        decoded.value,
        "sparkplug-dcmd",
        now_ms,
        decoded.seq.unwrap_or(0),
        deadline_ms,
    )
    .map(Some)
}

pub fn command_result_metrics(result: &CapabilityCommandResult) -> Result<Vec<Metric>> {
    result.validate()?;
    let mut metrics = vec![
        Metric::string("redconCommandStatus", result.status.clone()),
        Metric::int32("redconCommandSeq", i32::try_from(result.seq)?),
        Metric::uint64("redconCommandObservedAt", result.observed_at_ms),
        Metric::string("redconCommandId", result.command_id.clone()),
    ];
    if let Some(redcon) = result.target.redcon {
        metrics.push(Metric::int32("redconCommandTarget", i32::from(redcon)));
    }
    if let Some(message) = &result.message {
        if !message.is_empty() {
            metrics.push(Metric::string("redconCommandMessage", message.clone()));
        }
    }
    Ok(metrics)
}

pub fn node_session_spec(
    group_id: &str,
    edge_node_id: &str,
    client_id: &str,
    bdseq: u64,
    timestamp: u64,
) -> Result<MqttSessionSpec> {
    Ok(MqttSessionSpec {
        client_id: client_id.to_string(),
        will: MqttWill {
            topic: sparkplug::build_node_topic(group_id, "NDEATH", edge_node_id),
            payload: sparkplug::build_node_death_payload(4, bdseq, timestamp)?,
        },
    })
}

pub fn device_session_spec(
    group_id: &str,
    edge_node_id: &str,
    thing_name: &str,
    timestamp: u64,
) -> Result<MqttSessionSpec> {
    Ok(MqttSessionSpec {
        client_id: thing_name.to_string(),
        will: MqttWill {
            topic: sparkplug::build_device_topic(group_id, "DDEATH", edge_node_id, thing_name),
            payload: sparkplug::build_device_death_payload(0, timestamp)?,
        },
    })
}

pub fn graceful_device_death(
    group_id: &str,
    edge_node_id: &str,
    thing_name: &str,
    seq: u64,
    timestamp: u64,
) -> Result<(String, Vec<u8>)> {
    Ok((
        sparkplug::build_device_topic(group_id, "DDEATH", edge_node_id, thing_name),
        sparkplug::build_device_death_payload(seq, timestamp)?,
    ))
}

pub fn graceful_node_death(
    group_id: &str,
    edge_node_id: &str,
    bdseq: u64,
    timestamp: u64,
) -> Result<(String, Vec<u8>)> {
    Ok((
        sparkplug::build_node_topic(group_id, "NDEATH", edge_node_id),
        sparkplug::build_node_death_payload(4, bdseq, timestamp)?,
    ))
}

fn sparkplug_metrics_from_capability_metrics(
    metrics: &BTreeMap<String, MetricValue>,
) -> Result<Vec<Metric>> {
    let mut result = Vec::new();
    for (name, metric) in metrics {
        let value = match metric.datatype.as_str() {
            "Boolean" => Metric::boolean(name.clone(), bool_value(&metric.value)?),
            "Int32" => Metric::int32(name.clone(), i32_value(&metric.value)?),
            "Int64" | "UInt64" => Metric::uint64(name.clone(), u64_value(&metric.value)?),
            "Double" | "Float" => Metric::double(name.clone(), f64_value(&metric.value)?),
            "String" => Metric::string(name.clone(), string_value(&metric.value)?),
            datatype => bail!("unsupported capability metric datatype {datatype}"),
        };
        result.push(value);
    }
    Ok(result)
}

fn sparkplug_metrics_from_snapshot(
    capabilities: &BTreeMap<String, bool>,
    metrics: &BTreeMap<String, MetricValue>,
) -> Result<Vec<Metric>> {
    let mut result = capabilities
        .iter()
        .map(|(name, available)| Metric::boolean(format!("capability.{name}"), *available))
        .collect::<Vec<_>>();
    result.extend(sparkplug_metrics_from_capability_metrics(metrics)?);
    Ok(result)
}

fn bool_value(value: &Value) -> Result<bool> {
    value
        .as_bool()
        .ok_or_else(|| anyhow::anyhow!("metric value must be a boolean"))
}

fn i32_value(value: &Value) -> Result<i32> {
    let value = value
        .as_i64()
        .ok_or_else(|| anyhow::anyhow!("metric value must be an integer"))?;
    Ok(i32::try_from(value)?)
}

fn u64_value(value: &Value) -> Result<u64> {
    value
        .as_u64()
        .or_else(|| value.as_i64().and_then(|value| u64::try_from(value).ok()))
        .ok_or_else(|| anyhow::anyhow!("metric value must be a non-negative integer"))
}

fn f64_value(value: &Value) -> Result<f64> {
    value
        .as_f64()
        .ok_or_else(|| anyhow::anyhow!("metric value must be a number"))
}

fn string_value(value: &Value) -> Result<String> {
    value
        .as_str()
        .map(ToString::to_string)
        .ok_or_else(|| anyhow::anyhow!("metric value must be a string"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use txing_capability_protocol::{
        COMMAND_SUCCEEDED, CapabilityCommandResultTarget, SCHEMA_VERSION,
    };

    fn power_inventory() -> InventoryDevice {
        InventoryDevice {
            thing_name: "power-1".to_string(),
            thing_type: "power".to_string(),
            capabilities: vec![
                "sparkplug".to_string(),
                "ble".to_string(),
                "power".to_string(),
            ],
            redcon_command_levels: vec![4, 3],
            redcon_rules: BTreeMap::from([
                (4, vec!["sparkplug".to_string(), "ble".to_string()]),
                (
                    3,
                    vec![
                        "sparkplug".to_string(),
                        "ble".to_string(),
                        "power".to_string(),
                    ],
                ),
            ]),
        }
    }

    #[test]
    fn redcon_rule_selection_uses_best_ready_level() {
        let rules = power_inventory().redcon_rules;
        let mut capabilities = BTreeMap::from([
            ("sparkplug".to_string(), true),
            ("ble".to_string(), true),
            ("power".to_string(), false),
        ]);

        assert_eq!(select_best_redcon(&rules, &capabilities), Some(4));

        capabilities.insert("power".to_string(), true);
        assert_eq!(select_best_redcon(&rules, &capabilities), Some(3));
    }

    #[test]
    fn stale_state_removes_capability_availability() {
        let mut state = DeviceRuntimeState::new(power_inventory());
        state
            .observe_state(CapabilityState {
                schema_version: SCHEMA_VERSION.to_string(),
                adapter_id: "dev.txing.rig.BleConnectivity".to_string(),
                thing_name: "power-1".to_string(),
                capabilities: BTreeMap::from([
                    ("sparkplug".to_string(), true),
                    ("ble".to_string(), true),
                    ("power".to_string(), true),
                ]),
                metrics: BTreeMap::new(),
                observed_at_ms: 1000,
                seq: 1,
            })
            .unwrap();

        assert_eq!(state.snapshot(1000).redcon, Some(3));
        assert_eq!(state.snapshot(1000 + STATE_TTL_MS + 1).redcon, None);
    }

    #[test]
    fn snapshot_initializes_inventory_capabilities_to_false() {
        let state = DeviceRuntimeState::new(power_inventory());
        let snapshot = state.snapshot(1000);

        assert_eq!(
            snapshot.capabilities,
            BTreeMap::from([
                ("ble".to_string(), false),
                ("power".to_string(), false),
                ("sparkplug".to_string(), false),
            ])
        );
        assert_eq!(snapshot.redcon, None);
        assert!(!snapshot.sparkplug_available);
    }

    #[test]
    fn birth_metrics_include_all_capability_availability_values() {
        let mut state = DeviceRuntimeState::new(power_inventory());
        state
            .observe_state(CapabilityState {
                schema_version: SCHEMA_VERSION.to_string(),
                adapter_id: "dev.txing.rig.BleConnectivity".to_string(),
                thing_name: "power-1".to_string(),
                capabilities: BTreeMap::from([
                    ("sparkplug".to_string(), true),
                    ("ble".to_string(), true),
                    ("power".to_string(), false),
                ]),
                metrics: BTreeMap::from([("batteryMv".to_string(), MetricValue::int32(3970))]),
                observed_at_ms: 1000,
                seq: 1,
            })
            .unwrap();

        let publication = state.decide_publication(1000).unwrap();

        assert_eq!(
            publication,
            DevicePublication::Birth {
                redcon: 4,
                metrics: vec![
                    Metric::boolean("capability.ble", true),
                    Metric::boolean("capability.power", false),
                    Metric::boolean("capability.sparkplug", true),
                    Metric::int32("batteryMv", 3970),
                ],
            }
        );
    }

    #[test]
    fn capability_only_change_publishes_data_with_false_values() {
        let mut inventory = power_inventory();
        inventory.capabilities.push("diagnostics".to_string());
        let mut state = DeviceRuntimeState::new(inventory);
        state
            .observe_state(CapabilityState {
                schema_version: SCHEMA_VERSION.to_string(),
                adapter_id: "dev.txing.rig.BleConnectivity".to_string(),
                thing_name: "power-1".to_string(),
                capabilities: BTreeMap::from([
                    ("sparkplug".to_string(), true),
                    ("ble".to_string(), true),
                    ("power".to_string(), false),
                    ("diagnostics".to_string(), true),
                ]),
                metrics: BTreeMap::from([("batteryMv".to_string(), MetricValue::int32(3970))]),
                observed_at_ms: 1000,
                seq: 1,
            })
            .unwrap();
        assert!(matches!(
            state.decide_publication(1000).unwrap(),
            DevicePublication::Birth { redcon: 4, .. }
        ));

        state
            .observe_state(CapabilityState {
                schema_version: SCHEMA_VERSION.to_string(),
                adapter_id: "dev.txing.rig.BleConnectivity".to_string(),
                thing_name: "power-1".to_string(),
                capabilities: BTreeMap::from([
                    ("sparkplug".to_string(), true),
                    ("ble".to_string(), true),
                    ("power".to_string(), false),
                    ("diagnostics".to_string(), false),
                ]),
                metrics: BTreeMap::from([("batteryMv".to_string(), MetricValue::int32(3970))]),
                observed_at_ms: 2000,
                seq: 2,
            })
            .unwrap();

        assert_eq!(
            state.decide_publication(2000).unwrap(),
            DevicePublication::Data {
                redcon: 4,
                metrics: vec![
                    Metric::boolean("capability.ble", true),
                    Metric::boolean("capability.diagnostics", false),
                    Metric::boolean("capability.power", false),
                    Metric::boolean("capability.sparkplug", true),
                    Metric::int32("batteryMv", 3970),
                ],
            }
        );
    }

    #[test]
    fn adapter_capabilities_not_declared_by_inventory_are_ignored() {
        let mut state = DeviceRuntimeState::new(power_inventory());
        state
            .observe_state(CapabilityState {
                schema_version: SCHEMA_VERSION.to_string(),
                adapter_id: "dev.txing.rig.BleConnectivity".to_string(),
                thing_name: "power-1".to_string(),
                capabilities: BTreeMap::from([
                    ("sparkplug".to_string(), true),
                    ("ble".to_string(), true),
                    ("power".to_string(), false),
                    ("debugOnly".to_string(), true),
                ]),
                metrics: BTreeMap::new(),
                observed_at_ms: 1000,
                seq: 1,
            })
            .unwrap();

        let snapshot = state.snapshot(1000);

        assert_eq!(snapshot.capabilities.get("debugOnly"), None);
        assert_eq!(snapshot.capabilities.get("ble"), Some(&true));
    }

    #[test]
    fn publication_lifecycle_birth_data_and_death() {
        let mut state = DeviceRuntimeState::new(power_inventory());
        state
            .observe_state(CapabilityState {
                schema_version: SCHEMA_VERSION.to_string(),
                adapter_id: "dev.txing.rig.BleConnectivity".to_string(),
                thing_name: "power-1".to_string(),
                capabilities: BTreeMap::from([
                    ("sparkplug".to_string(), true),
                    ("ble".to_string(), true),
                    ("power".to_string(), false),
                ]),
                metrics: BTreeMap::from([(
                    "batteryMv".to_string(),
                    MetricValue {
                        datatype: "Int32".to_string(),
                        value: Value::from(3970),
                    },
                )]),
                observed_at_ms: 1000,
                seq: 1,
            })
            .unwrap();

        assert!(matches!(
            state.decide_publication(1000).unwrap(),
            DevicePublication::Birth { redcon: 4, .. }
        ));

        state
            .observe_state(CapabilityState {
                schema_version: SCHEMA_VERSION.to_string(),
                adapter_id: "dev.txing.rig.BleConnectivity".to_string(),
                thing_name: "power-1".to_string(),
                capabilities: BTreeMap::from([
                    ("sparkplug".to_string(), true),
                    ("ble".to_string(), true),
                    ("power".to_string(), true),
                ]),
                metrics: BTreeMap::new(),
                observed_at_ms: 2000,
                seq: 2,
            })
            .unwrap();
        assert!(matches!(
            state.decide_publication(2000).unwrap(),
            DevicePublication::Data { redcon: 3, .. }
        ));

        state
            .observe_state(CapabilityState {
                schema_version: SCHEMA_VERSION.to_string(),
                adapter_id: "dev.txing.rig.BleConnectivity".to_string(),
                thing_name: "power-1".to_string(),
                capabilities: BTreeMap::from([
                    ("sparkplug".to_string(), false),
                    ("ble".to_string(), false),
                    ("power".to_string(), false),
                ]),
                metrics: BTreeMap::new(),
                observed_at_ms: 3000,
                seq: 3,
            })
            .unwrap();
        assert_eq!(
            state.decide_publication(3000).unwrap(),
            DevicePublication::Death
        );
    }

    #[test]
    fn unchanged_metrics_do_not_publish_repeated_data() {
        let mut state = DeviceRuntimeState::new(power_inventory());
        state
            .observe_state(CapabilityState {
                schema_version: SCHEMA_VERSION.to_string(),
                adapter_id: "dev.txing.rig.BleConnectivity".to_string(),
                thing_name: "power-1".to_string(),
                capabilities: BTreeMap::from([
                    ("sparkplug".to_string(), true),
                    ("ble".to_string(), true),
                    ("power".to_string(), false),
                ]),
                metrics: BTreeMap::from([(
                    "batteryMv".to_string(),
                    MetricValue {
                        datatype: "Int32".to_string(),
                        value: Value::from(3970),
                    },
                )]),
                observed_at_ms: 1000,
                seq: 1,
            })
            .unwrap();

        assert!(matches!(
            state.decide_publication(1000).unwrap(),
            DevicePublication::Birth { redcon: 4, .. }
        ));
        assert_eq!(
            state.decide_publication(2000).unwrap(),
            DevicePublication::None
        );

        state
            .observe_state(CapabilityState {
                schema_version: SCHEMA_VERSION.to_string(),
                adapter_id: "dev.txing.rig.BleConnectivity".to_string(),
                thing_name: "power-1".to_string(),
                capabilities: BTreeMap::from([
                    ("sparkplug".to_string(), true),
                    ("ble".to_string(), true),
                    ("power".to_string(), false),
                ]),
                metrics: BTreeMap::from([(
                    "batteryMv".to_string(),
                    MetricValue {
                        datatype: "Int32".to_string(),
                        value: Value::from(3971),
                    },
                )]),
                observed_at_ms: 3000,
                seq: 2,
            })
            .unwrap();

        assert!(matches!(
            state.decide_publication(3000).unwrap(),
            DevicePublication::Data { redcon: 4, .. }
        ));
    }

    #[test]
    fn dcmd_payload_translates_to_v2_redcon_command() {
        let payload = sparkplug::build_redcon_payload(3, 77, 1714380000000).unwrap();

        let command = command_from_dcmd(
            "power-1",
            &payload,
            "cmd-77".to_string(),
            1714380001000,
            Some(1714380045000),
        )
        .unwrap()
        .unwrap();

        assert_eq!(command.thing_name, "power-1");
        assert_eq!(command.target.redcon, 3);
        assert_eq!(command.seq, 77);
        assert_eq!(command.deadline_ms, Some(1714380045000));
    }

    #[test]
    fn command_result_projects_to_sparkplug_metrics() {
        let result = CapabilityCommandResult {
            schema_version: SCHEMA_VERSION.to_string(),
            adapter_id: "dev.txing.rig.BleConnectivity".to_string(),
            command_id: "cmd-1".to_string(),
            thing_name: "power-1".to_string(),
            status: COMMAND_SUCCEEDED.to_string(),
            target: CapabilityCommandResultTarget { redcon: Some(3) },
            message: None,
            observed_at_ms: 1000,
            seq: 1,
        };

        let metrics = command_result_metrics(&result).unwrap();

        assert_eq!(
            metrics,
            vec![
                Metric::string("redconCommandStatus", "succeeded"),
                Metric::int32("redconCommandSeq", 1),
                Metric::uint64("redconCommandObservedAt", 1000),
                Metric::string("redconCommandId", "cmd-1"),
                Metric::int32("redconCommandTarget", 3),
            ]
        );
    }

    #[test]
    fn mqtt_session_specs_use_expected_lwt_topics() {
        let node =
            node_session_spec("town-1", "rig-1", &node_client_id("rig-1"), 12, 1000).unwrap();
        let device = device_session_spec("town-1", "rig-1", "power-1", 1000).unwrap();

        assert_eq!(node.client_id, "rig-1-sparkplug-manager");
        assert_eq!(node.will.topic, "spBv1.0/town-1/NDEATH/rig-1");
        assert_eq!(device.client_id, "power-1");
        assert_eq!(device.will.topic, "spBv1.0/town-1/DDEATH/rig-1/power-1");
    }
}
