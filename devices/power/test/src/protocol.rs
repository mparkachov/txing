use uuid::Uuid;

use crate::error::{Result, RigError};

pub const REDCON_SERVICE_UUID_STR: &str = "f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100";
pub const REDCON_COMMAND_UUID_STR: &str = "f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100";
pub const REDCON_STATE_UUID_STR: &str = "f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100";
pub const POWER_MEASUREMENT_UUID_STR: &str = "f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100";

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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RedconState {
    pub redcon: u8,
}

impl RedconState {
    pub fn active(&self) -> bool {
        self.redcon == REDCON_ACTIVE
    }
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
    Ok(RedconState { redcon: payload[1] })
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
