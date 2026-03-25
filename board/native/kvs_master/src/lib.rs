pub mod aws_env;
pub mod cli;
pub mod ffi;
pub mod h264;
pub mod rpicam;

use anyhow::{Context, Result, anyhow};
use signal_hook::consts::signal::{SIGINT, SIGTERM};
use signal_hook::flag;
use std::io::{Read, Write};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

pub use cli::Cli;
pub use rpicam::CameraConfig;

#[derive(Debug, Clone)]
pub struct RuntimeConfig {
    pub region: String,
    pub channel_name: String,
    pub client_id: String,
    pub camera: CameraConfig,
}

pub fn run(config: RuntimeConfig) -> Result<()> {
    let credentials = aws_env::resolve_credentials()
        .context("failed to resolve AWS credentials for the KVS sender")?;
    let stop_requested = Arc::new(AtomicBool::new(false));
    flag::register(SIGINT, Arc::clone(&stop_requested))
        .context("failed to register SIGINT handler")?;
    flag::register(SIGTERM, Arc::clone(&stop_requested))
        .context("failed to register SIGTERM handler")?;

    let mut kvs_master = ffi::KvsMaster::new(&ffi::KvsConfig {
        region: config.region.clone(),
        channel_name: config.channel_name.clone(),
        client_id: config.client_id.clone(),
        video_bitrate_bps: config.camera.bitrate,
        access_key_id: credentials.access_key_id,
        secret_access_key: credentials.secret_access_key,
        session_token: credentials.session_token,
    })?;
    kvs_master.start()?;

    let mut camera_child = rpicam::spawn(&config.camera)?;
    let stdout = rpicam::take_stdout(&mut camera_child)?;
    let mut parser = h264::AnnexBAccessUnitParser::new();
    let mut reader = std::io::BufReader::with_capacity(64 * 1024, stdout);
    let frame_duration = 10_000_000_u64
        .checked_div(u64::from(config.camera.framerate.max(1)))
        .unwrap_or(333_333);
    let mut presentation_ts = 0_u64;
    let mut read_buffer = [0_u8; 64 * 1024];
    let mut result = Ok(());

    loop {
        if stop_requested.load(Ordering::Relaxed) {
            break;
        }
        if let Some(error) = kvs_master.take_fatal_error() {
            result = Err(anyhow!(error));
            break;
        }

        match reader.read(&mut read_buffer) {
            Ok(0) => {
                match camera_child
                    .try_wait()
                    .context("failed to poll rpicam-vid status")?
                {
                    Some(status) if status.success() => break,
                    Some(status) => {
                        result = Err(anyhow!("rpicam-vid exited with status {status}"));
                        break;
                    }
                    None => {
                        result = Err(anyhow!("rpicam-vid stdout closed unexpectedly"));
                        break;
                    }
                }
            }
            Ok(size) => {
                for access_unit in parser.push(&read_buffer[..size]) {
                    kvs_master.push_h264_access_unit(
                        &access_unit.bytes,
                        presentation_ts,
                        frame_duration,
                        access_unit.is_keyframe,
                    )?;
                    presentation_ts = presentation_ts.saturating_add(frame_duration);
                }
            }
            Err(err) => {
                result = Err(err).context("failed to read rpicam-vid output");
                break;
            }
        }
    }

    for access_unit in parser.finish() {
        kvs_master.push_h264_access_unit(
            &access_unit.bytes,
            presentation_ts,
            frame_duration,
            access_unit.is_keyframe,
        )?;
        presentation_ts = presentation_ts.saturating_add(frame_duration);
    }

    rpicam::terminate(&mut camera_child).context("failed to terminate rpicam-vid")?;
    kvs_master.stop();
    result
}

pub fn emit_marker(prefix: &str, fields: &[(&str, &str)]) {
    let mut line = String::from(prefix);
    for (key, value) in fields {
        line.push(' ');
        line.push_str(key);
        line.push('=');
        line.push_str(&sanitize_marker_value(value));
    }
    println!("{line}");
    let _ = std::io::stdout().flush();
}

fn sanitize_marker_value(value: &str) -> String {
    value
        .chars()
        .map(|character| match character {
            '\n' | '\r' | '\t' => ' ',
            _ => character,
        })
        .collect()
}
