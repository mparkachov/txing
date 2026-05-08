use std::collections::BTreeMap;

use uuid::Uuid;

use crate::error::{Result, RigError};

pub const WEATHER_SERVICE_UUID_STR: &str = "f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100";
pub const WEATHER_COMMAND_UUID_STR: &str = "f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100";
pub const WEATHER_STATE_UUID_STR: &str = "f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100";

pub const PROTOCOL_VERSION: u8 = 1;
pub const REDCON_ACTIVE: u8 = 3;
pub const REDCON_IDLE: u8 = 4;
pub const STATE_ACTIVE_FLAG: u8 = 0x01;

pub fn weather_service_uuid() -> Uuid {
    Uuid::parse_str(WEATHER_SERVICE_UUID_STR).expect("static weather service UUID is valid")
}

pub fn weather_command_uuid() -> Uuid {
    Uuid::parse_str(WEATHER_COMMAND_UUID_STR).expect("static weather command UUID is valid")
}

pub fn weather_state_uuid() -> Uuid {
    Uuid::parse_str(WEATHER_STATE_UUID_STR).expect("static weather state UUID is valid")
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WeatherState {
    pub redcon: u8,
    pub active: bool,
    pub battery_mv: Option<u16>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConnectionParams {
    pub name: String,
    pub interval_ms: u16,
    pub latency: u16,
    pub supervision_ms: u16,
}

pub fn encode_command(redcon: u8, conn_params: Option<&ConnectionParams>) -> Vec<u8> {
    if redcon != REDCON_ACTIVE {
        return vec![PROTOCOL_VERSION, redcon];
    }
    match conn_params {
        None => vec![PROTOCOL_VERSION, redcon],
        Some(params) => {
            let mut payload = Vec::with_capacity(8);
            payload.push(PROTOCOL_VERSION);
            payload.push(redcon);
            payload.extend_from_slice(&params.interval_ms.to_le_bytes());
            payload.extend_from_slice(&params.latency.to_le_bytes());
            payload.extend_from_slice(&params.supervision_ms.to_le_bytes());
            payload
        }
    }
}

pub fn decode_state(payload: &[u8]) -> Result<WeatherState> {
    if payload.len() < 5 {
        return Err(RigError::new(
            "state",
            format!("state payload too short: {}", payload.len()),
        ));
    }
    let version = payload[0];
    if version != PROTOCOL_VERSION {
        return Err(RigError::new(
            "state",
            format!("unsupported state protocol version: {version}"),
        ));
    }
    let battery_mv = u16::from_le_bytes([payload[3], payload[4]]);
    Ok(WeatherState {
        redcon: payload[1],
        active: payload[2] & STATE_ACTIVE_FLAG != 0,
        battery_mv: (battery_mv != 0).then_some(battery_mv),
    })
}

pub fn encode_state(redcon: u8, battery_mv: u16) -> Vec<u8> {
    let active = if redcon < REDCON_IDLE {
        STATE_ACTIVE_FLAG
    } else {
        0
    };
    let mut payload = vec![PROTOCOL_VERSION, redcon, active];
    payload.extend_from_slice(&battery_mv.to_le_bytes());
    payload
}

pub fn validate_connection_params(
    name: impl Into<String>,
    interval_ms: u16,
    latency: u16,
    supervision_ms: u16,
) -> Result<ConnectionParams> {
    let name = name.into();
    if !(8..=4000).contains(&interval_ms) {
        return Err(RigError::args(format!(
            "{name}: interval_ms must be 8..4000"
        )));
    }
    if latency > 499 {
        return Err(RigError::args(format!("{name}: latency must be 0..499")));
    }
    if !(100..=32000).contains(&supervision_ms) {
        return Err(RigError::args(format!(
            "{name}: supervision_ms must be 100..32000"
        )));
    }
    let minimum_supervision_ms = interval_ms as u32 * (latency as u32 + 1) * 2;
    if supervision_ms as u32 <= minimum_supervision_ms {
        return Err(RigError::args(format!(
            "{name}: supervision_ms must be > interval_ms * (latency + 1) * 2"
        )));
    }
    Ok(ConnectionParams {
        name,
        interval_ms,
        latency,
        supervision_ms,
    })
}

pub fn built_in_connection_profiles() -> BTreeMap<&'static str, Option<(u16, u16, u16)>> {
    BTreeMap::from([
        ("central-default", None),
        ("fast-50-0-10", Some((50, 0, 10000))),
        ("fast-50-0-20", Some((50, 0, 20000))),
        ("stable-75-0-20", Some((75, 0, 20000))),
        ("stable-100-0-10", Some((100, 0, 10000))),
        ("stable-100-0-20", Some((100, 0, 20000))),
        ("stable-100-0-30", Some((100, 0, 30000))),
        ("stable-125-0-20", Some((125, 0, 20000))),
        ("stable-150-0-20", Some((150, 0, 20000))),
        ("stable-200-0-10", Some((200, 0, 10000))),
        ("stable-200-0-20", Some((200, 0, 20000))),
        ("slow-500-0-20", Some((500, 0, 20000))),
    ])
}

pub fn default_connection_profile_names() -> Vec<String> {
    vec![
        "stable-100-0-20",
        "stable-75-0-20",
        "stable-125-0-20",
        "stable-150-0-20",
        "stable-100-0-30",
        "stable-200-0-20",
        "fast-50-0-20",
        "central-default",
    ]
    .into_iter()
    .map(str::to_string)
    .collect()
}

pub fn parse_custom_connection_profile(raw: &str) -> Result<(String, (u16, u16, u16))> {
    let (name, values) = raw.split_once('=').ok_or_else(|| {
        RigError::args("--conn-params must use NAME=INTERVAL_MS,LATENCY,SUPERVISION_MS")
    })?;
    let name = name.trim();
    let parts: Vec<&str> = values.split(',').map(str::trim).collect();
    if name.is_empty() || parts.len() != 3 {
        return Err(RigError::args(
            "--conn-params must use NAME=INTERVAL_MS,LATENCY,SUPERVISION_MS",
        ));
    }
    let interval_ms = parts[0]
        .parse::<u16>()
        .map_err(|err| RigError::args(format!("{name}: invalid interval_ms: {err}")))?;
    let latency = parts[1]
        .parse::<u16>()
        .map_err(|err| RigError::args(format!("{name}: invalid latency: {err}")))?;
    let supervision_ms = parts[2]
        .parse::<u16>()
        .map_err(|err| RigError::args(format!("{name}: invalid supervision_ms: {err}")))?;
    validate_connection_params(name, interval_ms, latency, supervision_ms)?;
    Ok((name.to_string(), (interval_ms, latency, supervision_ms)))
}

pub fn resolve_connection_profiles(
    profile_args: &[String],
    custom_args: &[String],
) -> Result<Vec<Option<ConnectionParams>>> {
    let mut profiles = built_in_connection_profiles()
        .into_iter()
        .map(|(name, params)| (name.to_string(), params))
        .collect::<BTreeMap<String, Option<(u16, u16, u16)>>>();
    for raw in custom_args {
        let (name, params) = parse_custom_connection_profile(raw)?;
        profiles.insert(name, Some(params));
    }

    let mut requested = Vec::new();
    for raw in profile_args {
        requested.extend(
            raw.split(',')
                .map(str::trim)
                .filter(|part| !part.is_empty())
                .map(str::to_string),
        );
    }
    if requested.is_empty() {
        requested.push("central-default".to_string());
    }

    let mut resolved = Vec::new();
    for name in requested {
        let values = profiles.get(&name).ok_or_else(|| {
            RigError::args(format!(
                "unknown connection profile {name:?}. Options: {}",
                profiles.keys().cloned().collect::<Vec<_>>().join(", ")
            ))
        })?;
        match values {
            None => resolved.push(None),
            Some((interval_ms, latency, supervision_ms)) => resolved.push(Some(
                validate_connection_params(&name, *interval_ms, *latency, *supervision_ms)?,
            )),
        }
    }
    Ok(resolved)
}

pub fn connection_fields(conn_params: Option<&ConnectionParams>) -> Vec<(&'static str, String)> {
    match conn_params {
        None => vec![("connProfile", "central-default".to_string())],
        Some(params) => vec![
            ("connProfile", params.name.clone()),
            ("connIntervalMs", params.interval_ms.to_string()),
            ("connLatency", params.latency.to_string()),
            ("connSupervisionMs", params.supervision_ms.to_string()),
        ],
    }
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
