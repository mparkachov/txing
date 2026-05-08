use std::env;
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

const IPC_SOCKET_ENV: &str = "AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT";
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

pub fn run_greengrass_doctor(no_connect: bool) -> Result<()> {
    println!("greengrass.ipc.doctor=rust-debug");
    println!("platform.os={}", env::consts::OS);
    println!("platform.arch={}", env::consts::ARCH);
    print_identity();

    let socket_path = env::var(IPC_SOCKET_ENV)
        .ok()
        .filter(|value| !value.is_empty());
    let auth_token = env::var_os(IPC_AUTH_TOKEN_ENV).filter(|value| !value.is_empty());

    match &socket_path {
        Some(path) => println!("{IPC_SOCKET_ENV}={path}"),
        None => println!("{IPC_SOCKET_ENV}=missing"),
    }
    match &auth_token {
        Some(value) => println!(
            "{IPC_AUTH_TOKEN_ENV}=set({} bytes)",
            value.to_string_lossy().len()
        ),
        None => println!("{IPC_AUTH_TOKEN_ENV}=missing"),
    }
    print_optional_env("AWS_IOT_THING_NAME");
    print_optional_env("GGC_VERSION");

    let Some(path) = socket_path else {
        println!(
            "diagnosis=not running in a Greengrass component lifecycle; this is not a socket permission/user failure yet"
        );
        return Ok(());
    };

    print_socket_metadata(&path);

    if auth_token.is_none() {
        println!(
            "diagnosis=Greengrass IPC socket env is present, but SVCUID is missing; the lifecycle environment is incomplete"
        );
    }

    if no_connect {
        println!("socket.connect=skipped");
    } else {
        probe_socket_connect(&path);
    }

    Ok(())
}

fn print_optional_env(name: &str) {
    match env::var(name).ok().filter(|value| !value.is_empty()) {
        Some(value) => println!("{name}={value}"),
        None => println!("{name}=missing"),
    }
}

fn command_output(program: &str, args: &[&str]) -> Option<String> {
    let output = std::process::Command::new(program)
        .args(args)
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let value = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if value.is_empty() { None } else { Some(value) }
}

fn print_identity() {
    let uid = command_output("id", &["-u"]).unwrap_or_else(|| "unavailable".to_string());
    let gid = command_output("id", &["-g"]).unwrap_or_else(|| "unavailable".to_string());
    let user = command_output("id", &["-un"]).unwrap_or_else(|| "unavailable".to_string());
    let groups = command_output("id", &["-Gn"]).unwrap_or_else(|| "unavailable".to_string());
    println!("process.user={user}");
    println!("process.uid={uid}");
    println!("process.gid={gid}");
    println!("process.groups={groups}");
}

fn print_socket_metadata(path: &str) {
    let socket = PathBuf::from(path);
    match std::fs::metadata(&socket) {
        Ok(metadata) => {
            println!("socket.exists=true");
            #[cfg(unix)]
            {
                use std::os::unix::fs::{FileTypeExt, MetadataExt, PermissionsExt};

                let file_type = metadata.file_type();
                let kind = if file_type.is_socket() {
                    "unix-socket"
                } else if file_type.is_file() {
                    "file"
                } else if file_type.is_dir() {
                    "directory"
                } else {
                    "other"
                };
                println!("socket.type={kind}");
                println!("socket.mode=0o{:o}", metadata.permissions().mode() & 0o7777);
                println!("socket.uid={}", metadata.uid());
                println!("socket.gid={}", metadata.gid());
            }
            #[cfg(not(unix))]
            {
                println!("socket.type=unknown");
            }
        }
        Err(err) => {
            println!("socket.exists=false");
            println!("socket.metadata_error.kind={:?}", err.kind());
            println!("socket.metadata_error.message={err}");
        }
    }
}

#[cfg(unix)]
fn probe_socket_connect(path: &str) {
    use std::os::unix::net::UnixStream;

    match UnixStream::connect(path) {
        Ok(_) => {
            println!("socket.connect=ok");
            println!("diagnosis=Greengrass IPC socket is reachable by this user");
        }
        Err(err) => {
            println!("socket.connect=failed");
            println!("socket.connect_error.kind={:?}", err.kind());
            println!("socket.connect_error.message={err}");
            if err.kind() == std::io::ErrorKind::PermissionDenied {
                println!(
                    "diagnosis=Greengrass IPC environment is present, but the current user cannot connect to the socket; check component RunWith/default user and socket directory permissions"
                );
            } else {
                println!(
                    "diagnosis=Greengrass IPC environment is present, but the socket is not connectable; check nucleus status and the socket path"
                );
            }
        }
    }
}

#[cfg(not(unix))]
fn probe_socket_connect(_path: &str) {
    println!("socket.connect=unsupported");
    println!("diagnosis=Greengrass IPC Unix socket checks require a Unix-like host");
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
