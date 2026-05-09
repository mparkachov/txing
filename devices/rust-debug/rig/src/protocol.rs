use uuid::Uuid;

use crate::error::{Result, RigError};

pub const REDCON_SERVICE_UUID_STR: &str = "f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100";
pub const REDCON_COMMAND_UUID_STR: &str = "f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100";
pub const REDCON_STATE_UUID_STR: &str = "f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100";

pub const PROTOCOL_VERSION: u8 = 1;
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RedconState {
    pub redcon: u8,
    pub battery_mv: Option<u16>,
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
    if payload.len() != 4 {
        return Err(RigError::new(
            "state",
            format!("state payload length must be 4, got {}", payload.len()),
        ));
    }
    let version = payload[0];
    if version != PROTOCOL_VERSION {
        return Err(RigError::new(
            "state",
            format!("unsupported state protocol version: {version}"),
        ));
    }
    let battery_mv = u16::from_le_bytes([payload[2], payload[3]]);
    Ok(RedconState {
        redcon: payload[1],
        battery_mv: (battery_mv != 0).then_some(battery_mv),
    })
}

pub fn encode_state(redcon: u8, battery_mv: u16) -> Vec<u8> {
    let mut payload = vec![PROTOCOL_VERSION, redcon];
    payload.extend_from_slice(&battery_mv.to_le_bytes());
    payload
}

#[derive(Debug, Clone, PartialEq)]
pub struct CentralProfile {
    pub name: String,
    pub scan_timeout: f64,
    pub connect_timeout: f64,
    pub connect_attempts: u32,
    pub retry_delay: f64,
    pub disconnect_deadline: f64,
    pub require_service: bool,
}

pub fn default_central_profiles() -> Vec<CentralProfile> {
    vec![
        CentralProfile {
            name: "bluez-conservative-name".to_string(),
            scan_timeout: 120.0,
            connect_timeout: 60.0,
            connect_attempts: 5,
            retry_delay: 5.0,
            disconnect_deadline: 10.0,
            require_service: false,
        },
        CentralProfile {
            name: "bluez-conservative-service".to_string(),
            scan_timeout: 120.0,
            connect_timeout: 60.0,
            connect_attempts: 5,
            retry_delay: 5.0,
            disconnect_deadline: 10.0,
            require_service: true,
        },
        CentralProfile {
            name: "bluez-balanced-name".to_string(),
            scan_timeout: 90.0,
            connect_timeout: 45.0,
            connect_attempts: 4,
            retry_delay: 3.0,
            disconnect_deadline: 10.0,
            require_service: false,
        },
        CentralProfile {
            name: "bluez-balanced-service".to_string(),
            scan_timeout: 90.0,
            connect_timeout: 45.0,
            connect_attempts: 4,
            retry_delay: 3.0,
            disconnect_deadline: 10.0,
            require_service: true,
        },
        CentralProfile {
            name: "bluez-fast-service".to_string(),
            scan_timeout: 60.0,
            connect_timeout: 30.0,
            connect_attempts: 3,
            retry_delay: 2.0,
            disconnect_deadline: 5.0,
            require_service: true,
        },
    ]
}

pub fn default_central_profile_names() -> Vec<String> {
    vec![
        "bluez-conservative-name",
        "bluez-conservative-service",
        "bluez-balanced-name",
        "bluez-balanced-service",
    ]
    .into_iter()
    .map(str::to_string)
    .collect()
}
