use uuid::Uuid;

use crate::error::{Result, RigError};

pub const REDCON_SERVICE_UUID_STR: &str = "f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100";
pub const REDCON_COMMAND_UUID_STR: &str = "f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100";
pub const REDCON_STATE_UUID_STR: &str = "f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100";
pub const POWER_MEASUREMENT_UUID_STR: &str = "f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100";
pub const WEATHER_MEASUREMENT_UUID_STR: &str = "f6b4b004-7b32-4d2d-9f4b-4ff0a2b8f100";

pub const PROTOCOL_VERSION: u8 = 2;
pub const REDCON_ACTIVE: u8 = 3;
pub const REDCON_IDLE: u8 = 4;

pub fn redcon_service_uuid() -> Uuid {
    Uuid::parse_str(REDCON_SERVICE_UUID_STR).expect("static REDCON service UUID is valid")
}

pub fn redcon_command_uuid() -> Uuid {
    Uuid::parse_str(REDCON_COMMAND_UUID_STR).expect("static REDCON command UUID is valid")
}

pub fn redcon_state_uuid() -> Uuid {
    Uuid::parse_str(REDCON_STATE_UUID_STR).expect("static REDCON state UUID is valid")
}

pub fn power_measurement_uuid() -> Uuid {
    Uuid::parse_str(POWER_MEASUREMENT_UUID_STR).expect("static power measurement UUID is valid")
}

pub fn weather_measurement_uuid() -> Uuid {
    Uuid::parse_str(WEATHER_MEASUREMENT_UUID_STR).expect("static weather measurement UUID is valid")
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RedconState {
    pub redcon: u8,
}

pub fn encode_command(redcon: u8) -> Vec<u8> {
    vec![PROTOCOL_VERSION, redcon]
}

pub fn decode_state(payload: &[u8]) -> Result<RedconState> {
    if payload.len() != 2 {
        return Err(RigError::new(
            "state",
            format!("state payload length must be 2, got {}", payload.len()),
        ));
    }
    let version = payload[0];
    if version != PROTOCOL_VERSION {
        return Err(RigError::new(
            "state",
            format!("unsupported state protocol version: {version}"),
        ));
    }
    let redcon = payload[1];
    if redcon != REDCON_IDLE {
        return Err(RigError::new(
            "state",
            format!("weather device must report REDCON 4, got {redcon}"),
        ));
    }
    Ok(RedconState { redcon })
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PowerMeasurement {
    pub battery_mv: Option<u16>,
}

pub fn decode_power_measurement(payload: &[u8]) -> Result<PowerMeasurement> {
    if payload.len() != 3 {
        return Err(RigError::new(
            "power-measurement",
            format!(
                "power measurement payload length must be 3, got {}",
                payload.len()
            ),
        ));
    }
    let version = payload[0];
    if version != PROTOCOL_VERSION {
        return Err(RigError::new(
            "power-measurement",
            format!("unsupported power measurement protocol version: {version}"),
        ));
    }
    let battery_mv = u16::from_le_bytes([payload[1], payload[2]]);
    Ok(PowerMeasurement {
        battery_mv: (battery_mv != 0).then_some(battery_mv),
    })
}

#[derive(Debug, Clone, PartialEq)]
pub struct WeatherMeasurement {
    pub temperature_centi_c: i32,
    pub pressure_pa: u32,
    pub humidity_centi_percent: u16,
}

impl WeatherMeasurement {
    pub fn temperature_c(&self) -> f64 {
        f64::from(self.temperature_centi_c) / 100.0
    }

    pub fn pressure_kpa(&self) -> f64 {
        f64::from(self.pressure_pa) / 1000.0
    }

    pub fn humidity_percent(&self) -> f64 {
        f64::from(self.humidity_centi_percent) / 100.0
    }
}

pub fn decode_weather_measurement(payload: &[u8]) -> Result<WeatherMeasurement> {
    if payload.len() != 11 {
        return Err(RigError::new(
            "weather-measurement",
            format!(
                "weather measurement payload length must be 11, got {}",
                payload.len()
            ),
        ));
    }
    let version = payload[0];
    if version != PROTOCOL_VERSION {
        return Err(RigError::new(
            "weather-measurement",
            format!("unsupported weather measurement protocol version: {version}"),
        ));
    }
    Ok(WeatherMeasurement {
        temperature_centi_c: i32::from_le_bytes([payload[1], payload[2], payload[3], payload[4]]),
        pressure_pa: u32::from_le_bytes([payload[5], payload[6], payload[7], payload[8]]),
        humidity_centi_percent: u16::from_le_bytes([payload[9], payload[10]]),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn weather_protocol_decodes_redcon_four_only() {
        assert_eq!(encode_command(REDCON_IDLE), vec![2, 4]);
        assert_eq!(
            decode_state(&[2, 4]).unwrap(),
            RedconState {
                redcon: REDCON_IDLE
            }
        );
        assert!(decode_state(&[2, 3]).is_err());
        assert!(decode_state(&[1, 4]).is_err());
    }

    #[test]
    fn power_measurement_decodes_battery_mv() {
        assert_eq!(
            decode_power_measurement(&[2, 0x82, 0x0f]).unwrap(),
            PowerMeasurement {
                battery_mv: Some(3970)
            }
        );
        assert_eq!(
            decode_power_measurement(&[2, 0, 0]).unwrap(),
            PowerMeasurement { battery_mv: None }
        );
    }

    #[test]
    fn weather_measurement_decodes_payload() {
        let mut payload = vec![2];
        payload.extend_from_slice(&2155_i32.to_le_bytes());
        payload.extend_from_slice(&101_325_u32.to_le_bytes());
        payload.extend_from_slice(&4550_u16.to_le_bytes());
        let measurement = decode_weather_measurement(&payload).unwrap();
        assert_eq!(measurement.temperature_centi_c, 2155);
        assert_eq!(measurement.temperature_c(), 21.55);
        assert_eq!(measurement.pressure_pa, 101_325);
        assert_eq!(measurement.pressure_kpa(), 101.325);
        assert_eq!(measurement.humidity_centi_percent, 4550);
        assert_eq!(measurement.humidity_percent(), 45.5);
    }
}
