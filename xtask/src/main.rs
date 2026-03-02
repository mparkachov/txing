use std::env;
use std::fs;
use std::path::Path;
use std::process::{Command, ExitCode};
use std::time::{Duration, Instant};

use btleplug::api::{Central, Manager as _, Peripheral as _, ScanFilter, WriteType};
use btleplug::platform::{Manager, Peripheral};
use tokio::runtime::Builder;
use uuid::Uuid;

const BIN_NAME: &str = "txing";
const UF2_BASE: &str = "0x27000";
const UF2_FAMILY: &str = "0xADA52840";
const TARGET_TRIPLE: &str = "thumbv7em-none-eabihf";
const UF2_MOUNT_DIR: &str = "/Volumes/XIAO-SENSE";

const SLEEP_COMMAND_UUID: &str = "f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100";
const STATE_REPORT_UUID: &str = "f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100";

struct BleSleepOptions {
    name: String,
    sleep: Option<bool>,
    scan_timeout_secs: u64,
}

impl Default for BleSleepOptions {
    fn default() -> Self {
        Self {
            name: "txing".to_string(),
            sleep: None,
            scan_timeout_secs: 12,
        }
    }
}

fn main() -> ExitCode {
    let mut args = env::args().skip(1);
    let cmd = args.next().unwrap_or_else(|| "uf2".to_string());
    let cmd_args: Vec<String> = args.collect();

    let workspace_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("xtask should live under workspace root");

    match cmd.as_str() {
        "build" => to_exit_code(run_build(workspace_root)),
        "bin" => to_exit_code(run_bin(workspace_root)),
        "uf2" => to_exit_code(run_uf2(workspace_root)),
        "flash" => to_exit_code(run_flash(workspace_root)),
        "sleep" => to_exit_code(run_ble_alias(&cmd_args, true)),
        "wakeup" => to_exit_code(run_ble_alias(&cmd_args, false)),
        "ble-sleep" => to_exit_code(run_ble_sleep(&cmd_args)),
        _ => {
            eprintln!("unknown command: {cmd}");
            print_usage();
            ExitCode::from(2)
        }
    }
}

fn print_usage() {
    eprintln!("usage: cargo fw [build|bin|uf2|flash|sleep|wakeup|ble-sleep]");
    eprintln!("  cargo fw sleep [--name <local_name>] [--scan-timeout <sec>]");
    eprintln!("  cargo fw wakeup [--name <local_name>] [--scan-timeout <sec>]");
    eprintln!("  cargo fw ble-sleep --sleep <true|false> [--name <local_name>] [--scan-timeout <sec>]");
}

fn print_ble_sleep_usage() {
    eprintln!("usage: cargo fw ble-sleep --sleep <true|false> [--name <local_name>] [--scan-timeout <sec>]");
    eprintln!("  --sleep         target state (true/false), required");
    eprintln!("  --name          BLE local name to match exactly (default: txing)");
    eprintln!("  --scan-timeout  scan timeout in seconds (default: 12)");
}

fn print_ble_alias_usage(cmd: &str) {
    eprintln!("usage: cargo fw {cmd} [--name <local_name>] [--scan-timeout <sec>]");
    eprintln!("  --name          BLE local name to match exactly (default: txing)");
    eprintln!("  --scan-timeout  scan timeout in seconds (default: 12)");
}

fn parse_ble_common_args(args: &[String]) -> Result<BleSleepOptions, String> {
    let mut opts = BleSleepOptions::default();

    let mut idx = 0usize;
    while idx < args.len() {
        match args[idx].as_str() {
            "--help" | "-h" => return Err(String::new()),
            "--name" => {
                let value = args
                    .get(idx + 1)
                    .ok_or_else(|| "--name requires a value".to_string())?;
                opts.name = value.clone();
                idx += 2;
            }
            "--scan-timeout" => {
                let value = args
                    .get(idx + 1)
                    .ok_or_else(|| "--scan-timeout requires a value".to_string())?;
                opts.scan_timeout_secs = value
                    .parse::<u64>()
                    .map_err(|_| format!("invalid --scan-timeout value: {value}"))?;
                idx += 2;
            }
            unknown => {
                return Err(format!("unknown flag: {unknown}"));
            }
        }
    }

    if opts.scan_timeout_secs == 0 {
        return Err("--scan-timeout must be > 0".to_string());
    }

    Ok(opts)
}

fn parse_bool_flag(raw: &str) -> Result<bool, String> {
    match raw {
        "true" | "1" | "yes" | "on" => Ok(true),
        "false" | "0" | "no" | "off" => Ok(false),
        _ => Err(format!("invalid boolean value: {raw}")),
    }
}

fn parse_ble_sleep_args(args: &[String]) -> Result<BleSleepOptions, String> {
    let mut opts = BleSleepOptions::default();

    let mut idx = 0usize;
    while idx < args.len() {
        match args[idx].as_str() {
            "--help" | "-h" => return Err(String::new()),
            "--name" => {
                let value = args
                    .get(idx + 1)
                    .ok_or_else(|| "--name requires a value".to_string())?;
                opts.name = value.clone();
                idx += 2;
            }
            "--sleep" => {
                let value = args
                    .get(idx + 1)
                    .ok_or_else(|| "--sleep requires a value".to_string())?;
                opts.sleep = Some(parse_bool_flag(value)?);
                idx += 2;
            }
            "--scan-timeout" => {
                let value = args
                    .get(idx + 1)
                    .ok_or_else(|| "--scan-timeout requires a value".to_string())?;
                opts.scan_timeout_secs = value
                    .parse::<u64>()
                    .map_err(|_| format!("invalid --scan-timeout value: {value}"))?;
                idx += 2;
            }
            unknown => {
                return Err(format!("unknown flag for ble-sleep: {unknown}"));
            }
        }
    }

    if opts.sleep.is_none() {
        return Err("--sleep <true|false> is required".to_string());
    }

    if opts.scan_timeout_secs == 0 {
        return Err("--scan-timeout must be > 0".to_string());
    }

    Ok(opts)
}

fn run_ble_alias(args: &[String], sleep: bool) -> bool {
    let cmd_name = if sleep { "sleep" } else { "wakeup" };
    let mut opts = match parse_ble_common_args(args) {
        Ok(opts) => opts,
        Err(err) if err.is_empty() => {
            print_ble_alias_usage(cmd_name);
            return true;
        }
        Err(err) => {
            eprintln!("{err}");
            print_ble_alias_usage(cmd_name);
            return false;
        }
    };
    opts.sleep = Some(sleep);
    run_ble_command(opts)
}

fn run_ble_sleep(args: &[String]) -> bool {
    let opts = match parse_ble_sleep_args(args) {
        Ok(opts) => opts,
        Err(err) if err.is_empty() => {
            print_ble_sleep_usage();
            return true;
        }
        Err(err) => {
            eprintln!("{err}");
            print_ble_sleep_usage();
            return false;
        }
    };

    run_ble_command(opts)
}

fn run_ble_command(opts: BleSleepOptions) -> bool {
    let runtime = match Builder::new_current_thread().enable_time().build() {
        Ok(runtime) => runtime,
        Err(err) => {
            eprintln!("failed to build tokio runtime: {err}");
            return false;
        }
    };

    match runtime.block_on(run_ble_sleep_async(opts)) {
        Ok(()) => true,
        Err(err) => {
            eprintln!("{err}");
            false
        }
    }
}

async fn run_ble_sleep_async(opts: BleSleepOptions) -> Result<(), String> {
    let sleep = opts.sleep.expect("validated above");
    let sleep_cmd_uuid = Uuid::parse_str(SLEEP_COMMAND_UUID)
        .map_err(|err| format!("invalid Sleep Command UUID constant: {err}"))?;
    let state_report_uuid = Uuid::parse_str(STATE_REPORT_UUID)
        .map_err(|err| format!("invalid State Report UUID constant: {err}"))?;

    println!(
        "Scanning for BLE device name='{}' (timeout={}s)...",
        opts.name, opts.scan_timeout_secs
    );

    let manager = Manager::new()
        .await
        .map_err(|err| format!("failed to create BLE manager: {err}"))?;
    let adapters = manager
        .adapters()
        .await
        .map_err(|err| format!("failed to enumerate BLE adapters: {err}"))?;
    let adapter = adapters
        .into_iter()
        .next()
        .ok_or_else(|| "no BLE adapters found".to_string())?;

    adapter
        .start_scan(ScanFilter::default())
        .await
        .map_err(|err| format!("failed to start BLE scan: {err}"))?;

    let peripheral =
        find_peripheral_by_name(&adapter, &opts.name, Duration::from_secs(opts.scan_timeout_secs))
            .await?
            .ok_or_else(|| format!("device '{}' not found before timeout", opts.name))?;

    let _ = adapter.stop_scan().await;

    if !peripheral
        .is_connected()
        .await
        .map_err(|err| format!("failed to read connection state: {err}"))?
    {
        peripheral
            .connect()
            .await
            .map_err(|err| format!("failed to connect to device: {err}"))?;
    }

    peripheral
        .discover_services()
        .await
        .map_err(|err| format!("failed to discover GATT services: {err}"))?;

    let characteristics = peripheral.characteristics();
    let sleep_characteristic = characteristics
        .iter()
        .find(|c| c.uuid == sleep_cmd_uuid)
        .ok_or_else(|| format!("Sleep Command characteristic not found ({sleep_cmd_uuid})"))?;
    let report_characteristic = characteristics
        .iter()
        .find(|c| c.uuid == state_report_uuid)
        .ok_or_else(|| format!("State Report characteristic not found ({state_report_uuid})"))?;

    let payload = [if sleep { 0x01 } else { 0x00 }];
    println!(
        "Writing Sleep Command: sleep={} payload=0x{:02x}",
        sleep, payload[0]
    );

    peripheral
        .write(sleep_characteristic, &payload, WriteType::WithResponse)
        .await
        .map_err(|err| format!("failed to write Sleep Command: {err}"))?;

    let report = peripheral
        .read(report_characteristic)
        .await
        .map_err(|err| format!("failed to read State Report: {err}"))?;

    if report.len() < 2 {
        return Err(format!(
            "unexpected State Report length: {} (expected >= 2)",
            report.len()
        ));
    }

    let battery_pct = report[0];
    let reported_sleep = report[1] == 0x01;
    println!(
        "State Report => battery_pct={}, sleep={}",
        battery_pct, reported_sleep
    );

    if let Ok(true) = peripheral.is_connected().await {
        let _ = peripheral.disconnect().await;
    }

    Ok(())
}

async fn find_peripheral_by_name(
    adapter: &btleplug::platform::Adapter,
    expected_name: &str,
    timeout: Duration,
) -> Result<Option<Peripheral>, String> {
    let deadline = Instant::now() + timeout;

    loop {
        let peripherals = adapter
            .peripherals()
            .await
            .map_err(|err| format!("failed to read discovered peripherals: {err}"))?;

        for peripheral in peripherals {
            let props = peripheral
                .properties()
                .await
                .map_err(|err| format!("failed reading peripheral properties: {err}"))?;

            let matched = props
                .as_ref()
                .and_then(|p| p.local_name.as_deref())
                .map(|name| name == expected_name)
                .unwrap_or(false);

            if matched {
                return Ok(Some(peripheral));
            }
        }

        if Instant::now() >= deadline {
            return Ok(None);
        }

        tokio::time::sleep(Duration::from_millis(250)).await;
    }
}

fn to_exit_code(ok: bool) -> ExitCode {
    if ok {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    }
}

fn run_build(workspace_root: &Path) -> bool {
    run(workspace_root, "cargo", ["build", "--release"].as_slice())
}

fn run_bin(workspace_root: &Path) -> bool {
    if !run_build(workspace_root) {
        return false;
    }

    let artifacts_dir = workspace_root.join("target").join(TARGET_TRIPLE).join("release");
    if let Err(err) = fs::create_dir_all(&artifacts_dir) {
        eprintln!("failed to create artifacts directory: {err}");
        return false;
    }
    let bin_path = artifacts_dir.join(format!("{BIN_NAME}.bin"));

    run(
        workspace_root,
        "cargo",
        [
            "objcopy",
            "--release",
            "--",
            "-O",
            "binary",
            &bin_path.display().to_string(),
        ]
        .as_slice(),
    )
}

fn run_uf2(workspace_root: &Path) -> bool {
    if !run_bin(workspace_root) {
        return false;
    }

    let artifacts_dir = workspace_root.join("target").join(TARGET_TRIPLE).join("release");
    let bin_path = artifacts_dir.join(format!("{BIN_NAME}.bin"));
    let uf2_path = artifacts_dir.join(format!("{BIN_NAME}.uf2"));

    run(
        workspace_root,
        "uf2conv",
        [
            &bin_path.display().to_string(),
            "--base",
            UF2_BASE,
            "--family",
            UF2_FAMILY,
            "--output",
            &uf2_path.display().to_string(),
        ]
        .as_slice(),
    )
}

fn run_flash(workspace_root: &Path) -> bool {
    if !run_uf2(workspace_root) {
        return false;
    }

    let artifacts_dir = workspace_root.join("target").join(TARGET_TRIPLE).join("release");
    let uf2_path = artifacts_dir.join(format!("{BIN_NAME}.uf2"));
    let mount_dir = Path::new(UF2_MOUNT_DIR);
    let destination = mount_dir.join(format!("{BIN_NAME}.uf2"));

    if !mount_dir.exists() {
        eprintln!("mount point not found: {}", mount_dir.display());
        return false;
    }

    println!("> cp {} {}", uf2_path.display(), destination.display());
    match fs::copy(&uf2_path, &destination) {
        Ok(_) => true,
        Err(err) => {
            eprintln!("failed to copy UF2: {err}");
            false
        }
    }
}

fn run(workspace_root: &Path, program: &str, args: &[&str]) -> bool {
    println!("> {} {}", program, args.join(" "));
    match Command::new(program)
        .args(args)
        .current_dir(workspace_root)
        .status()
    {
        Ok(status) if status.success() => true,
        Ok(_) => false,
        Err(err) => {
            eprintln!("failed to run {program}: {err}");
            false
        }
    }
}
