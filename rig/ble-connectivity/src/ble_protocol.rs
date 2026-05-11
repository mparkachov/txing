use std::collections::BTreeMap;
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Result, bail};
use uuid::{Uuid, uuid};

use txing_capability_protocol::{CapabilityState, MetricValue, SCHEMA_VERSION};

pub const ADAPTER_ID: &str = "dev.txing.rig.BleConnectivity";

pub const SPARKPLUG_CAPABILITY: &str = "sparkplug";
pub const BLE_CAPABILITY: &str = "ble";
pub const POWER_CAPABILITY: &str = "power";
pub const WEATHER_CAPABILITY: &str = "weather";

pub const PROTOCOL_VERSION: u8 = 1;
pub const REDCON_ACTIVE: u8 = 3;
pub const REDCON_IDLE: u8 = 4;
pub const STATE_FLAG_BME280_VALID: u8 = 0x02;

pub const TXING_BLE_SERVICE_UUID: Uuid = uuid!("f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100");
pub const TXING_BLE_COMMAND_UUID: Uuid = uuid!("f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100");
pub const TXING_BLE_STATE_UUID: Uuid = uuid!("f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100");
pub const WEATHER_MEASUREMENT_UUID: Uuid = uuid!("f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100");

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeviceKind {
    Power,
    Weather,
}

impl DeviceKind {
    pub fn domain_capability(self) -> &'static str {
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
    pub battery_mv: Option<u16>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WeatherState {
    pub redcon: u8,
    pub battery_mv: Option<u16>,
    pub bme280_valid: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WeatherMeasurement {
    pub measured_temperature: f64,
    pub measured_pressure: f64,
    pub measured_humidity: f64,
    pub battery_mv: Option<u16>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct CapabilitySample {
    pub thing_name: String,
    pub kind: DeviceKind,
    pub sparkplug_available: bool,
    pub ble_available: bool,
    pub domain_available: bool,
    pub ble_local_name: Option<String>,
    pub ble_address: Option<String>,
    pub battery_mv: Option<u16>,
    pub weather: Option<WeatherMeasurement>,
    pub observed_at_ms: u64,
    pub seq: u64,
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
    if payload.len() < 4 {
        bail!("power BLE state report is too short");
    }
    let version = payload[0];
    if version != PROTOCOL_VERSION {
        bail!("unsupported power BLE state version {version}");
    }
    let redcon = normalize_state_redcon(payload[1], "power")?;
    let battery_mv = u16::from_le_bytes([payload[2], payload[3]]);
    Ok(PowerState {
        redcon,
        battery_mv: nonzero_battery(battery_mv),
    })
}

pub fn parse_weather_state(payload: &[u8]) -> Result<WeatherState> {
    if payload.len() < 5 {
        bail!("weather BLE state report is too short");
    }
    let version = payload[0];
    if version != PROTOCOL_VERSION {
        bail!("unsupported weather BLE state version {version}");
    }
    let redcon = normalize_state_redcon(payload[1], "weather")?;
    let flags = payload[2];
    let battery_mv = u16::from_le_bytes([payload[3], payload[4]]);
    Ok(WeatherState {
        redcon,
        battery_mv: nonzero_battery(battery_mv),
        bme280_valid: flags & STATE_FLAG_BME280_VALID != 0,
    })
}

pub fn parse_weather_measurement(payload: &[u8]) -> Result<WeatherMeasurement> {
    if payload.len() < 13 {
        bail!("weather BLE measurement report is too short");
    }
    let version = payload[0];
    if version != PROTOCOL_VERSION {
        bail!("unsupported weather BLE measurement version {version}");
    }
    let temperature_centi = i32::from_le_bytes([payload[1], payload[2], payload[3], payload[4]]);
    let pressure_pa = u32::from_le_bytes([payload[5], payload[6], payload[7], payload[8]]);
    let humidity_centi = u16::from_le_bytes([payload[9], payload[10]]);
    let battery_mv = u16::from_le_bytes([payload[11], payload[12]]);
    Ok(WeatherMeasurement {
        measured_temperature: f64::from(temperature_centi) / 100.0,
        measured_pressure: f64::from(pressure_pa) / 1000.0,
        measured_humidity: f64::from(humidity_centi) / 100.0,
        battery_mv: nonzero_battery(battery_mv),
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
        domain_available: false,
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
        domain_available: false,
        ble_local_name: Some(spec.thing_name.clone()),
        ble_address: None,
        battery_mv: None,
        weather: None,
        observed_at_ms: now_ms,
        seq,
    }
}

pub fn power_state_sample(
    spec: &DeviceSpec,
    state: &PowerState,
    ble_address: Option<String>,
    seq: u64,
    now_ms: u64,
) -> CapabilitySample {
    CapabilitySample {
        thing_name: spec.thing_name.clone(),
        kind: DeviceKind::Power,
        sparkplug_available: true,
        ble_available: true,
        domain_available: state.redcon < REDCON_IDLE,
        ble_local_name: Some(spec.thing_name.clone()),
        ble_address,
        battery_mv: state.battery_mv,
        weather: None,
        observed_at_ms: now_ms,
        seq,
    }
}

pub fn weather_state_sample(
    spec: &DeviceSpec,
    state: &WeatherState,
    measurement: Option<WeatherMeasurement>,
    ble_address: Option<String>,
    seq: u64,
    now_ms: u64,
) -> CapabilitySample {
    let battery_mv = measurement
        .as_ref()
        .and_then(|item| item.battery_mv)
        .or(state.battery_mv);
    CapabilitySample {
        thing_name: spec.thing_name.clone(),
        kind: DeviceKind::Weather,
        sparkplug_available: true,
        ble_available: true,
        domain_available: state.redcon < REDCON_IDLE,
        ble_local_name: Some(spec.thing_name.clone()),
        ble_address,
        battery_mv,
        weather: measurement,
        observed_at_ms: now_ms,
        seq,
    }
}

pub fn capability_state_from_sample(adapter_id: &str, sample: CapabilitySample) -> CapabilityState {
    let mut capabilities = BTreeMap::new();
    capabilities.insert(SPARKPLUG_CAPABILITY.to_string(), sample.sparkplug_available);
    capabilities.insert(BLE_CAPABILITY.to_string(), sample.ble_available);
    capabilities.insert(
        sample.kind.domain_capability().to_string(),
        sample.domain_available,
    );

    let mut metrics = BTreeMap::new();
    if let Some(value) = sample.ble_local_name {
        metrics.insert("bleLocalName".to_string(), MetricValue::string(value));
    }
    if let Some(value) = sample.ble_address {
        metrics.insert("bleAddress".to_string(), MetricValue::string(value));
    }
    if let Some(value) = sample.battery_mv {
        metrics.insert(
            "batteryMv".to_string(),
            MetricValue::int32(i32::from(value)),
        );
    }
    if let Some(weather) = sample.weather {
        metrics.insert(
            "measuredTemperature".to_string(),
            MetricValue::double(weather.measured_temperature),
        );
        metrics.insert(
            "measuredPressure".to_string(),
            MetricValue::double(weather.measured_pressure),
        );
        metrics.insert(
            "measuredHumidity".to_string(),
            MetricValue::double(weather.measured_humidity),
        );
    }

    CapabilityState {
        schema_version: SCHEMA_VERSION.to_string(),
        adapter_id: adapter_id.to_string(),
        thing_name: sample.thing_name,
        capabilities,
        metrics,
        observed_at_ms: sample.observed_at_ms,
        seq: sample.seq,
    }
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
        assert_eq!(encode_redcon_command(1).unwrap(), vec![1, 3]);
        assert_eq!(encode_redcon_command(4).unwrap(), vec![1, 4]);

        let state = parse_power_state(&[1, 4, 0x82, 0x0f]).unwrap();
        assert_eq!(
            state,
            PowerState {
                redcon: 4,
                battery_mv: Some(3970)
            }
        );
    }

    #[test]
    fn weather_payload_parses_state_and_measurement() {
        let state = parse_weather_state(&[1, 3, STATE_FLAG_BME280_VALID, 0x74, 0x0e]).unwrap();
        assert_eq!(
            state,
            WeatherState {
                redcon: 3,
                battery_mv: Some(3700),
                bme280_valid: true,
            }
        );

        let mut payload = vec![1];
        payload.extend_from_slice(&2155_i32.to_le_bytes());
        payload.extend_from_slice(&101_325_u32.to_le_bytes());
        payload.extend_from_slice(&4550_u16.to_le_bytes());
        payload.extend_from_slice(&3700_u16.to_le_bytes());
        let measurement = parse_weather_measurement(&payload).unwrap();
        assert_eq!(measurement.measured_temperature, 21.55);
        assert_eq!(measurement.measured_pressure, 101.325);
        assert_eq!(measurement.measured_humidity, 45.5);
        assert_eq!(measurement.battery_mv, Some(3700));
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
        let state = capability_state_from_sample(
            ADAPTER_ID,
            advertisement_sample(&spec, &advertisement, 1),
        );

        assert_eq!(state.capabilities[SPARKPLUG_CAPABILITY], true);
        assert_eq!(state.capabilities[BLE_CAPABILITY], true);
        assert_eq!(state.capabilities[POWER_CAPABILITY], false);
        assert!(!state.metrics.contains_key("bleConnected"));

        let offline = capability_state_from_sample(ADAPTER_ID, offline_sample(&spec, 2, 100));
        assert_eq!(offline.capabilities[SPARKPLUG_CAPABILITY], false);
    }
}
