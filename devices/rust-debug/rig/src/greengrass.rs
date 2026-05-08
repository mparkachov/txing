#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
use std::env;
#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
use std::path::PathBuf;
#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
use std::thread;
#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
use std::time::Duration;

use crate::error::{Result, RigError};
#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
use crate::pubsub::{ConnectivityHeartbeat, build_heartbeat_topic, now_ms};
#[cfg(not(all(feature = "greengrass-sdk", target_os = "linux")))]
use crate::pubsub::{ConnectivityHeartbeat, build_heartbeat_topic, now_ms};

#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
const IPC_SOCKET_ENV: &str = "AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT";
#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
const IPC_AUTH_TOKEN_ENV: &str = "SVCUID";

pub fn run_mock_component(adapter_id: &str) -> Result<()> {
    let heartbeat = ConnectivityHeartbeat {
        schema_version: crate::pubsub::SCHEMA_VERSION.to_string(),
        adapter_id: adapter_id.to_string(),
        status: "running".to_string(),
        active_thing_name: None,
        observed_at_ms: now_ms(),
        seq: 1,
    }
    .to_json()?;
    println!(
        "mock-greengrass publish topic={} payload={}",
        build_heartbeat_topic(adapter_id),
        String::from_utf8_lossy(&heartbeat)
    );
    Ok(())
}

#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
pub fn run_greengrass_component(adapter_id: &str) -> Result<()> {
    validate_greengrass_ipc_environment()?;

    let sdk = gg_sdk::Sdk::init();
    sdk.connect()
        .map_err(|err| RigError::new("greengrass", format!("failed to connect IPC: {err:?}")))?;
    sdk.update_state(gg_sdk::ComponentState::Running)
        .map_err(|err| RigError::new("greengrass", format!("failed to update state: {err:?}")))?;

    let mut seq = 0u64;
    loop {
        seq += 1;
        let heartbeat = ConnectivityHeartbeat {
            schema_version: crate::pubsub::SCHEMA_VERSION.to_string(),
            adapter_id: adapter_id.to_string(),
            status: "running".to_string(),
            active_thing_name: None,
            observed_at_ms: now_ms(),
            seq,
        }
        .to_json()?;
        sdk.publish_to_topic_binary(&build_heartbeat_topic(adapter_id), &heartbeat)
            .map_err(|err| {
                RigError::new(
                    "greengrass",
                    format!("failed to publish heartbeat: {err:?}"),
                )
            })?;
        thread::sleep(Duration::from_secs(10));
    }
}

#[cfg(all(feature = "greengrass-sdk", target_os = "linux"))]
fn validate_greengrass_ipc_environment() -> Result<()> {
    let socket_path = env::var_os(IPC_SOCKET_ENV).filter(|value| !value.is_empty());
    let auth_token = env::var_os(IPC_AUTH_TOKEN_ENV).filter(|value| !value.is_empty());

    let mut missing = Vec::new();
    if socket_path.is_none() {
        missing.push(IPC_SOCKET_ENV);
    }
    if auth_token.is_none() {
        missing.push(IPC_AUTH_TOKEN_ENV);
    }

    if !missing.is_empty() {
        return Err(RigError::new(
            "greengrass",
            format!(
                "missing Greengrass IPC environment variable(s): {}. Run this command as a Greengrass component lifecycle process, or use `just rust-debug::rig::mock-component` for local SDK-free development.",
                missing.join(", ")
            ),
        ));
    }

    let socket = PathBuf::from(socket_path.expect("checked above"));
    if !socket.exists() {
        return Err(RigError::new(
            "greengrass",
            format!(
                "Greengrass IPC socket does not exist at {}. Run under a Greengrass nucleus component lifecycle, or use `just rust-debug::rig::mock-component` for local SDK-free development.",
                socket.display()
            ),
        ));
    }

    Ok(())
}

#[cfg(not(all(feature = "greengrass-sdk", target_os = "linux")))]
pub fn run_greengrass_component(_adapter_id: &str) -> Result<()> {
    Err(RigError::new(
        "greengrass",
        "build with --features greengrass-sdk on Linux to run the real Greengrass SDK entrypoint",
    ))
}
