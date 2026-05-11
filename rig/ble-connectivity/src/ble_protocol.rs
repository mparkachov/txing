use std::collections::BTreeMap;
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Result, bail};
use serde_json::{Value, json};
use uuid::{Uuid, uuid};

use txing_capability_protocol::{CapabilityState, SCHEMA_VERSION, validate_segment};

pub const ADAPTER_ID: &str = "dev.txing.rig.BleConnectivity";

pub const SPARKPLUG_CAPABILITY: &str = "sparkplug";
pub const BLE_CAPABILITY: &str = "ble";
pub const POWER_CAPABILITY: &str = "power";
pub const WEATHER_CAPABILITY: &str = "weather";
pub const BLE_SHADOW_NAME: &str = "ble";
pub const POWER_SHADOW_NAME: &str = "power";
pub const WEATHER_SHADOW_NAME: &str = "weather";

pub const PROTOCOL_VERSION: u8 = 2;
pub const REDCON_ACTIVE: u8 = 3;
pub const REDCON_IDLE: u8 = 4;

pub const TXING_BLE_SERVICE_UUID: Uuid = uuid!("f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100");
pub const TXING_BLE_COMMAND_UUID: Uuid = uuid!("f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100");
pub const TXING_BLE_STATE_UUID: Uuid = uuid!("f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100");
pub const POWER_MEASUREMENT_UUID: Uuid = uuid!("f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100");
pub const WEATHER_MEASUREMENT_UUID: Uuid = uuid!("f6b4b004-7b32-4d2d-9f4b-4ff0a2b8f100");

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeviceKind {
    Power,
    Weather,
}

impl DeviceKind {
    pub fn supports_power(self) -> bool {
        true
    }

    pub fn supports_weather(self) -> bool {
        self == Self::Weather
    }

    pub fn primary_capability(self) -> &'static str {
        match self {
            Self::Power => POWER_CAPABILITY,
            Self::Weather => WEATHER_CAPABILITY,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeviceSpec {
    pub thing_name: String,
    pub kind: DeviceKind,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Advertisement {
    pub address: String,
    pub local_name: Option<String>,
    pub services: Vec<Uuid>,
    pub rssi: Option<i16>,
    pub observed_at_ms: u64,
    pub seq: u64,
}

impl Advertisement {
    pub fn matches_thing(&self, thing_name: &str) -> bool {
        self.local_name.as_deref() == Some(thing_name)
    }

    pub fn has_txing_service(&self) -> bool {
        self.services.contains(&TXING_BLE_SERVICE_UUID)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PowerState {
    pub redcon: u8,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WeatherState {
    pub redcon: u8,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PowerMeasurement {
    pub battery_mv: Option<u16>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WeatherMeasurement {
    pub measured_temperature: f64,
    pub measured_pressure: f64,
    pub measured_humidity: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct CapabilitySample {
    pub thing_name: String,
    pub kind: DeviceKind,
    pub sparkplug_available: bool,
    pub ble_available: bool,
    pub power_available: bool,
    pub weather_available: bool,
    pub ble_local_name: Option<String>,
    pub ble_address: Option<String>,
    pub battery_mv: Option<u16>,
    pub weather: Option<WeatherMeasurement>,
    pub observed_at_ms: u64,
    pub seq: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ShadowUpdate {
    pub topic: String,
    pub payload: Vec<u8>,
}

pub fn encode_redcon_command(target_redcon: u8) -> Result<Vec<u8>> {
    let target_redcon = match target_redcon {
        1 | 2 => REDCON_ACTIVE,
        REDCON_ACTIVE | REDCON_IDLE => target_redcon,
        _ => bail!("unsupported BLE target REDCON {target_redcon}"),
    };
    Ok(vec![PROTOCOL_VERSION, target_redcon])
}

pub fn parse_power_state(payload: &[u8]) -> Result<PowerState> {
    if payload.len() != 2 {
        bail!(
            "power BLE state report length must be 2, got {}",
            payload.len()
        );
    }
    let version = payload[0];
    if version != PROTOCOL_VERSION {
        bail!("unsupported power BLE state version {version}");
    }
    let redcon = normalize_state_redcon(payload[1], "power")?;
    Ok(PowerState { redcon })
}

pub fn parse_weather_state(payload: &[u8]) -> Result<WeatherState> {
    if payload.len() != 2 {
        bail!(
            "weather BLE state report length must be 2, got {}",
            payload.len()
        );
    }
    let version = payload[0];
    if version != PROTOCOL_VERSION {
        bail!("unsupported weather BLE state version {version}");
    }
    let redcon = normalize_state_redcon(payload[1], "weather")?;
    Ok(WeatherState { redcon })
}

pub fn parse_power_measurement(payload: &[u8]) -> Result<PowerMeasurement> {
    if payload.len() != 3 {
        bail!(
            "power BLE measurement report length must be 3, got {}",
            payload.len()
        );
    }
    let version = payload[0];
    if version != PROTOCOL_VERSION {
        bail!("unsupported power BLE measurement version {version}");
    }
    let battery_mv = u16::from_le_bytes([payload[1], payload[2]]);
    Ok(PowerMeasurement {
        battery_mv: nonzero_battery(battery_mv),
    })
}

pub fn parse_weather_measurement(payload: &[u8]) -> Result<WeatherMeasurement> {
    if payload.len() != 11 {
        bail!(
            "weather BLE measurement report length must be 11, got {}",
            payload.len()
        );
    }
    let version = payload[0];
    if version != PROTOCOL_VERSION {
        bail!("unsupported weather BLE measurement version {version}");
    }
    let temperature_centi = i32::from_le_bytes([payload[1], payload[2], payload[3], payload[4]]);
    let pressure_pa = u32::from_le_bytes([payload[5], payload[6], payload[7], payload[8]]);
    let humidity_centi = u16::from_le_bytes([payload[9], payload[10]]);
    Ok(WeatherMeasurement {
        measured_temperature: f64::from(temperature_centi) / 100.0,
        measured_pressure: f64::from(pressure_pa) / 1000.0,
        measured_humidity: f64::from(humidity_centi) / 100.0,
    })
}

fn normalize_state_redcon(redcon: u8, label: &str) -> Result<u8> {
    match redcon {
        1 | 2 => Ok(REDCON_ACTIVE),
        REDCON_ACTIVE | REDCON_IDLE => Ok(redcon),
        _ => bail!("unsupported {label} BLE state REDCON {redcon}"),
    }
}

fn nonzero_battery(value: u16) -> Option<u16> {
    (value != 0).then_some(value)
}

pub fn advertisement_sample(
    spec: &DeviceSpec,
    advertisement: &Advertisement,
    seq: u64,
) -> CapabilitySample {
    CapabilitySample {
        thing_name: spec.thing_name.clone(),
        kind: spec.kind,
        sparkplug_available: true,
        ble_available: true,
        power_available: false,
        weather_available: false,
        ble_local_name: advertisement.local_name.clone(),
        ble_address: Some(advertisement.address.clone()),
        battery_mv: None,
        weather: None,
        observed_at_ms: advertisement.observed_at_ms,
        seq,
    }
}

pub fn offline_sample(spec: &DeviceSpec, seq: u64, now_ms: u64) -> CapabilitySample {
    CapabilitySample {
        thing_name: spec.thing_name.clone(),
        kind: spec.kind,
        sparkplug_available: false,
        ble_available: false,
        power_available: false,
        weather_available: false,
        ble_local_name: None,
        ble_address: None,
        battery_mv: None,
        weather: None,
        observed_at_ms: now_ms,
        seq,
    }
}

pub fn power_state_sample(
    spec: &DeviceSpec,
    redcon: u8,
    measurement: Option<&PowerMeasurement>,
    ble_address: Option<String>,
    seq: u64,
    now_ms: u64,
) -> CapabilitySample {
    CapabilitySample {
        thing_name: spec.thing_name.clone(),
        kind: DeviceKind::Power,
        sparkplug_available: true,
        ble_available: true,
        power_available: redcon < REDCON_IDLE
            && measurement.and_then(|item| item.battery_mv).is_some(),
        weather_available: false,
        ble_local_name: Some(spec.thing_name.clone()),
        ble_address,
        battery_mv: measurement.and_then(|item| item.battery_mv),
        weather: None,
        observed_at_ms: now_ms,
        seq,
    }
}

pub fn weather_state_sample(
    spec: &DeviceSpec,
    redcon: u8,
    power_measurement: Option<&PowerMeasurement>,
    weather_measurement: Option<WeatherMeasurement>,
    ble_address: Option<String>,
    seq: u64,
    now_ms: u64,
) -> CapabilitySample {
    CapabilitySample {
        thing_name: spec.thing_name.clone(),
        kind: DeviceKind::Weather,
        sparkplug_available: true,
        ble_available: true,
        power_available: redcon < REDCON_IDLE
            && power_measurement.and_then(|item| item.battery_mv).is_some(),
        weather_available: redcon < REDCON_IDLE && weather_measurement.is_some(),
        ble_local_name: Some(spec.thing_name.clone()),
        ble_address,
        battery_mv: power_measurement.and_then(|item| item.battery_mv),
        weather: weather_measurement,
        observed_at_ms: now_ms,
        seq,
    }
}

pub fn capability_state_from_sample(
    adapter_id: &str,
    sample: &CapabilitySample,
) -> CapabilityState {
    let mut capabilities = BTreeMap::new();
    capabilities.insert(SPARKPLUG_CAPABILITY.to_string(), sample.sparkplug_available);
    capabilities.insert(BLE_CAPABILITY.to_string(), sample.ble_available);
    if sample.kind.supports_power() {
        capabilities.insert(POWER_CAPABILITY.to_string(), sample.power_available);
    }
    if sample.kind.supports_weather() {
        capabilities.insert(WEATHER_CAPABILITY.to_string(), sample.weather_available);
    }

    CapabilityState {
        schema_version: SCHEMA_VERSION.to_string(),
        adapter_id: adapter_id.to_string(),
        thing_name: sample.thing_name.clone(),
        capabilities,
        metrics: BTreeMap::new(),
        observed_at_ms: sample.observed_at_ms,
        seq: sample.seq,
    }
}

pub fn shadow_updates_from_sample(sample: &CapabilitySample) -> Result<Vec<ShadowUpdate>> {
    let mut updates = vec![build_shadow_update(
        &sample.thing_name,
        BLE_SHADOW_NAME,
        BTreeMap::from([
            (
                "bleAddress".to_string(),
                optional_string(sample.ble_address.as_deref()),
            ),
            (
                "bleLocalName".to_string(),
                optional_string(sample.ble_local_name.as_deref()),
            ),
            ("observedAtMs".to_string(), Value::Null),
            ("seq".to_string(), Value::Null),
        ]),
    )?];

    if sample.kind.supports_power() {
        updates.push(build_shadow_update(
            &sample.thing_name,
            POWER_SHADOW_NAME,
            BTreeMap::from([
                ("batteryMv".to_string(), optional_u16_i32(sample.battery_mv)),
                ("observedAtMs".to_string(), Value::Null),
                ("seq".to_string(), Value::Null),
            ]),
        )?);
    }

    if sample.kind.supports_weather() {
        let weather = sample.weather.as_ref();
        updates.push(build_shadow_update(
            &sample.thing_name,
            WEATHER_SHADOW_NAME,
            BTreeMap::from([
                (
                    "measuredTemperature".to_string(),
                    optional_f64(weather.map(|value| value.measured_temperature)),
                ),
                (
                    "measuredPressure".to_string(),
                    optional_f64(weather.map(|value| value.measured_pressure)),
                ),
                (
                    "measuredHumidity".to_string(),
                    optional_f64(weather.map(|value| value.measured_humidity)),
                ),
                ("observedAtMs".to_string(), Value::Null),
                ("seq".to_string(), Value::Null),
            ]),
        )?);
    }

    Ok(updates)
}

pub fn build_shadow_update(
    thing_name: &str,
    shadow_name: &str,
    reported: BTreeMap<String, Value>,
) -> Result<ShadowUpdate> {
    validate_segment(thing_name, "thingName")?;
    validate_segment(shadow_name, "shadowName")?;
    let topic = format!("$aws/things/{thing_name}/shadow/name/{shadow_name}/update");
    let payload = serde_json::to_vec(&json!({
        "state": {
            "reported": reported,
        },
    }))?;
    Ok(ShadowUpdate { topic, payload })
}

fn optional_string(value: Option<&str>) -> Value {
    value.map(Value::from).unwrap_or(Value::Null)
}

fn optional_u16_i32(value: Option<u16>) -> Value {
    value
        .map(|value| Value::from(i32::from(value)))
        .unwrap_or(Value::Null)
}

fn optional_f64(value: Option<f64>) -> Value {
    value.map(Value::from).unwrap_or(Value::Null)
}

pub fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system time is after unix epoch")
        .as_millis() as u64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn power_payload_round_trips_current_protocol() {
        assert_eq!(encode_redcon_command(1).unwrap(), vec![2, 3]);
        assert_eq!(encode_redcon_command(4).unwrap(), vec![2, 4]);

        let state = parse_power_state(&[2, 4]).unwrap();
        assert_eq!(state, PowerState { redcon: 4 });

        let measurement = parse_power_measurement(&[2, 0x82, 0x0f]).unwrap();
        assert_eq!(
            measurement,
            PowerMeasurement {
                battery_mv: Some(3970)
            }
        );
    }

    #[test]
    fn weather_payload_parses_state_and_measurement() {
        let state = parse_weather_state(&[2, 3]).unwrap();
        assert_eq!(state, WeatherState { redcon: 3 });

        let mut payload = vec![2];
        payload.extend_from_slice(&2155_i32.to_le_bytes());
        payload.extend_from_slice(&101_325_u32.to_le_bytes());
        payload.extend_from_slice(&4550_u16.to_le_bytes());
        let measurement = parse_weather_measurement(&payload).unwrap();
        assert_eq!(measurement.measured_temperature, 21.55);
        assert_eq!(measurement.measured_pressure, 101.325);
        assert_eq!(measurement.measured_humidity, 45.5);
    }

    #[test]
    fn old_version_one_payloads_are_rejected() {
        assert!(parse_power_state(&[1, 3]).is_err());
        assert!(parse_power_measurement(&[1, 0x82, 0x0f]).is_err());

        let mut payload = vec![1];
        payload.extend_from_slice(&2155_i32.to_le_bytes());
        payload.extend_from_slice(&101_325_u32.to_le_bytes());
        payload.extend_from_slice(&4550_u16.to_le_bytes());
        assert!(parse_weather_measurement(&payload).is_err());
    }

    #[test]
    fn samples_map_to_v2_capabilities() {
        let spec = DeviceSpec {
            thing_name: "power-1".to_string(),
            kind: DeviceKind::Power,
        };
        let advertisement = Advertisement {
            address: "AA:BB:CC:DD:EE:FF".to_string(),
            local_name: Some("power-1".to_string()),
            services: vec![TXING_BLE_SERVICE_UUID],
            rssi: Some(-50),
            observed_at_ms: 42,
            seq: 7,
        };
        let sample = advertisement_sample(&spec, &advertisement, 1);
        let state = capability_state_from_sample(ADAPTER_ID, &sample);

        assert_eq!(state.capabilities[SPARKPLUG_CAPABILITY], true);
        assert_eq!(state.capabilities[BLE_CAPABILITY], true);
        assert_eq!(state.capabilities[POWER_CAPABILITY], false);
        assert!(state.metrics.is_empty());

        let offline_sample = offline_sample(&spec, 2, 100);
        let offline = capability_state_from_sample(ADAPTER_ID, &offline_sample);
        assert_eq!(offline.capabilities[SPARKPLUG_CAPABILITY], false);
    }

    #[test]
    fn advertisement_sample_publishes_ble_shadow() {
        let spec = DeviceSpec {
            thing_name: "power-1".to_string(),
            kind: DeviceKind::Power,
        };
        let advertisement = Advertisement {
            address: "AA:BB:CC:DD:EE:FF".to_string(),
            local_name: Some("power-1".to_string()),
            services: vec![TXING_BLE_SERVICE_UUID],
            rssi: Some(-50),
            observed_at_ms: 42,
            seq: 7,
        };
        let updates =
            shadow_updates_from_sample(&advertisement_sample(&spec, &advertisement, 1)).unwrap();

        assert_eq!(updates.len(), 2);
        assert_eq!(
            updates[0].topic,
            "$aws/things/power-1/shadow/name/ble/update"
        );
        let payload: Value = serde_json::from_slice(&updates[0].payload).unwrap();
        assert_eq!(
            payload["state"]["reported"]["bleAddress"],
            Value::from("AA:BB:CC:DD:EE:FF")
        );
        assert_eq!(
            payload["state"]["reported"]["bleLocalName"],
            Value::from("power-1")
        );
        assert!(payload["state"]["reported"]["observedAtMs"].is_null());
        assert!(payload["state"]["reported"]["seq"].is_null());
        assert_eq!(
            updates[1].topic,
            "$aws/things/power-1/shadow/name/power/update"
        );
        let payload: Value = serde_json::from_slice(&updates[1].payload).unwrap();
        assert!(payload["state"]["reported"]["batteryMv"].is_null());
        assert!(payload["state"]["reported"]["observedAtMs"].is_null());
        assert!(payload["state"]["reported"]["seq"].is_null());
    }

    #[test]
    fn power_state_sample_publishes_power_shadow() {
        let spec = DeviceSpec {
            thing_name: "power-1".to_string(),
            kind: DeviceKind::Power,
        };
        let sample = power_state_sample(
            &spec,
            REDCON_ACTIVE,
            Some(&PowerMeasurement {
                battery_mv: Some(3970),
            }),
            Some("AA:BB:CC:DD:EE:FF".to_string()),
            3,
            1000,
        );
        let updates = shadow_updates_from_sample(&sample).unwrap();

        assert_eq!(updates.len(), 2);
        assert_eq!(
            updates[1].topic,
            "$aws/things/power-1/shadow/name/power/update"
        );
        let payload: Value = serde_json::from_slice(&updates[1].payload).unwrap();
        assert_eq!(payload["state"]["reported"]["batteryMv"], Value::from(3970));
        assert!(payload["state"]["reported"]["observedAtMs"].is_null());
        assert!(payload["state"]["reported"]["seq"].is_null());
    }

    #[test]
    fn weather_state_sample_publishes_weather_shadow() {
        let spec = DeviceSpec {
            thing_name: "weather-1".to_string(),
            kind: DeviceKind::Weather,
        };
        let sample = weather_state_sample(
            &spec,
            REDCON_ACTIVE,
            Some(&PowerMeasurement {
                battery_mv: Some(3710),
            }),
            Some(WeatherMeasurement {
                measured_temperature: 21.625,
                measured_pressure: 100.8,
                measured_humidity: 44.5,
            }),
            Some("AA:BB:CC:DD:EE:FF".to_string()),
            4,
            2000,
        );
        let updates = shadow_updates_from_sample(&sample).unwrap();

        assert_eq!(updates.len(), 3);
        assert_eq!(
            updates[1].topic,
            "$aws/things/weather-1/shadow/name/power/update"
        );
        let payload: Value = serde_json::from_slice(&updates[1].payload).unwrap();
        assert_eq!(payload["state"]["reported"]["batteryMv"], Value::from(3710));
        assert!(payload["state"]["reported"]["observedAtMs"].is_null());
        assert!(payload["state"]["reported"]["seq"].is_null());

        assert_eq!(
            updates[2].topic,
            "$aws/things/weather-1/shadow/name/weather/update"
        );
        let payload: Value = serde_json::from_slice(&updates[2].payload).unwrap();
        assert!(payload["state"]["reported"].get("batteryMv").is_none());
        assert_eq!(
            payload["state"]["reported"]["measuredTemperature"],
            Value::from(21.625)
        );
        assert_eq!(
            payload["state"]["reported"]["measuredPressure"],
            Value::from(100.8)
        );
        assert_eq!(
            payload["state"]["reported"]["measuredHumidity"],
            Value::from(44.5)
        );
        assert!(payload["state"]["reported"]["observedAtMs"].is_null());
        assert!(payload["state"]["reported"]["seq"].is_null());
    }
}
