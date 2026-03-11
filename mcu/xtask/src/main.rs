use std::collections::HashSet;
use std::env;
use std::fs;
use std::path::Path;
use std::process::{Command, ExitCode};
use std::time::{Duration, Instant};

use btleplug::api::{Central, Manager as _, Peripheral as _, ScanFilter};
use btleplug::platform::Manager;
use tokio::runtime::Builder;
use uuid::Uuid;

const BIN_NAME: &str = "txing";
const UF2_BASE: &str = "0x27000";
const UF2_FAMILY: &str = "0xADA52840";
const TARGET_TRIPLE: &str = "thumbv7em-none-eabihf";
const UF2_MOUNT_DIR: &str = "/Volumes/XIAO-SENSE";
const PROBE_RS_CHIP: &str = "nRF52840_xxAA";
const PROBE_RS_PROTOCOL: &str = "swd";

const TXING_SERVICE_UUID: &str = "f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100";
const BLE_INIT_TIMEOUT_SECS: u64 = 10;
const TXING_MFG_ID: u16 = 0xFFFF;
const TXING_MFG_MAGIC: &[u8] = b"TX";

fn main() -> ExitCode {
    let mut args = env::args().skip(1);
    let cmd = args.next().unwrap_or_else(|| "uf2".to_string());
    let cmd_args: Vec<String> = args.collect();

    let workspace_root = workspace_root();

    match cmd.as_str() {
        "build" => to_exit_code(run_build(workspace_root)),
        "bin" => to_exit_code(run_bin(workspace_root)),
        "uf2" => to_exit_code(run_uf2(workspace_root)),
        "flash" => to_exit_code(run_flash(workspace_root)),
        "probe-flash" => to_exit_code(run_flash(workspace_root)),
        "flash-uf2" => to_exit_code(run_flash_uf2(workspace_root)),
        "scan" => to_exit_code(run_scan(&cmd_args)),
        _ => {
            eprintln!("unknown command: {cmd}");
            print_usage();
            ExitCode::from(2)
        }
    }
}

fn print_usage() {
    eprintln!(
        "usage (from repo root): just mcu::[build|bin|uf2|flash|probe-flash|flash-uf2|scan]"
    );
    eprintln!(
        "usage (from mcu/):      just [build|bin|uf2|flash|probe-flash|flash-uf2|scan]"
    );
    eprintln!("  just mcu::scan [--scan-timeout <sec>]");
    eprintln!("  just mcu::flash       # safe SWD flash via probe-rs");
    eprintln!("  just mcu::flash-uf2   # legacy copy-to-mass-storage flash");
}

fn print_scan_usage() {
    eprintln!("usage: just mcu::scan [--scan-timeout <sec>] (or `just scan` from mcu/)");
    eprintln!("  --scan-timeout  scan timeout in seconds (default: 12)");
}

fn workspace_root() -> &'static Path {
    let mut dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    loop {
        if dir.join("Cargo.toml").is_file() && dir.join("memory.x").is_file() {
            return dir;
        }

        dir = dir
            .parent()
            .expect("failed to locate firmware workspace root for xtask");
    }
}

fn parse_scan_args(args: &[String]) -> Result<u64, String> {
    let mut scan_timeout_secs = 12u64;
    let mut idx = 0usize;
    while idx < args.len() {
        match args[idx].as_str() {
            "--help" | "-h" => return Err(String::new()),
            "--scan-timeout" => {
                let value = args
                    .get(idx + 1)
                    .ok_or_else(|| "--scan-timeout requires a value".to_string())?;
                scan_timeout_secs = value
                    .parse::<u64>()
                    .map_err(|_| format!("invalid --scan-timeout value: {value}"))?;
                idx += 2;
            }
            unknown => {
                return Err(format!("unknown flag: {unknown}"));
            }
        }
    }

    if scan_timeout_secs == 0 {
        return Err("--scan-timeout must be > 0".to_string());
    }
    Ok(scan_timeout_secs)
}

fn run_scan(args: &[String]) -> bool {
    let scan_timeout_secs = match parse_scan_args(args) {
        Ok(v) => v,
        Err(err) if err.is_empty() => {
            print_scan_usage();
            return true;
        }
        Err(err) => {
            eprintln!("{err}");
            print_scan_usage();
            return false;
        }
    };

    let runtime = match Builder::new_current_thread().enable_time().build() {
        Ok(runtime) => runtime,
        Err(err) => {
            eprintln!("failed to build tokio runtime: {err}");
            return false;
        }
    };

    match runtime.block_on(run_scan_async(Duration::from_secs(scan_timeout_secs))) {
        Ok(()) => true,
        Err(err) => {
            eprintln!("{err}");
            false
        }
    }
}

async fn run_scan_async(timeout: Duration) -> Result<(), String> {
    println!(
        "Scanning BLE peripherals (timeout={}s)...",
        timeout.as_secs()
    );
    let txing_service_uuid = Uuid::parse_str(TXING_SERVICE_UUID)
        .map_err(|err| format!("invalid Service UUID constant: {err}"))?;

    let manager = tokio::time::timeout(Duration::from_secs(BLE_INIT_TIMEOUT_SECS), Manager::new())
        .await
        .map_err(|_| "timeout creating BLE manager".to_string())?
        .map_err(|err| format!("failed to create BLE manager: {err}"))?;
    let adapters = tokio::time::timeout(
        Duration::from_secs(BLE_INIT_TIMEOUT_SECS),
        manager.adapters(),
    )
    .await
    .map_err(|_| "timeout enumerating BLE adapters".to_string())?
    .map_err(|err| format!("failed to enumerate BLE adapters: {err}"))?;
    let adapter = adapters
        .into_iter()
        .next()
        .ok_or_else(|| "no BLE adapters found".to_string())?;

    let _ = adapter.stop_scan().await;
    tokio::time::timeout(
        Duration::from_secs(BLE_INIT_TIMEOUT_SECS),
        adapter.start_scan(ScanFilter::default()),
    )
    .await
    .map_err(|_| "timeout starting BLE scan".to_string())?
    .map_err(|err| format!("failed to start BLE scan: {err}"))?;

    let deadline = Instant::now() + timeout;
    let mut seen: HashSet<String> = HashSet::new();
    let mut tick = 0usize;

    while Instant::now() < deadline {
        let peripherals = adapter
            .peripherals()
            .await
            .map_err(|err| format!("failed to read discovered peripherals: {err}"))?;

        for peripheral in peripherals {
            let id = peripheral.id().to_string();
            let props = match peripheral.properties().await {
                Ok(v) => v,
                Err(_) => continue,
            };
            if !seen.insert(id.clone()) {
                continue;
            }

            if let Some(p) = props {
                let name = p.local_name.unwrap_or_else(|| "<none>".to_string());
                let services: Vec<String> = p.services.iter().map(|u| u.to_string()).collect();
                let service_field = if services.is_empty() {
                    "<none>".to_string()
                } else {
                    services.join(",")
                };
                let is_txing_service = p.services.iter().any(|u| *u == txing_service_uuid);
                let has_txing_mfg = p
                    .manufacturer_data
                    .get(&TXING_MFG_ID)
                    .map(|data| data.starts_with(TXING_MFG_MAGIC))
                    .unwrap_or(false);
                println!(
                    "seen: id={} name='{}' rssi={:?} services={} txing_service={} txing_mfg={}",
                    id, name, p.rssi, service_field, is_txing_service, has_txing_mfg
                );
            } else {
                println!("seen: id={} properties=<none>", id);
            }
        }

        if tick % 4 == 0 {
            println!("scan summary: {} unique peripheral(s)", seen.len());
        }
        tick += 1;
        tokio::time::sleep(Duration::from_millis(500)).await;
    }

    let _ = adapter.stop_scan().await;
    println!(
        "scan finished: {} unique peripheral(s) observed in {}s",
        seen.len(),
        timeout.as_secs()
    );
    Ok(())
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

    let artifacts_dir = workspace_root
        .join("target")
        .join(TARGET_TRIPLE)
        .join("release");
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

    let artifacts_dir = workspace_root
        .join("target")
        .join(TARGET_TRIPLE)
        .join("release");
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
    if !run_bin(workspace_root) {
        return false;
    }

    let artifacts_dir = workspace_root
        .join("target")
        .join(TARGET_TRIPLE)
        .join("release");
    let bin_path = artifacts_dir.join(format!("{BIN_NAME}.bin"));

    if !run(
        workspace_root,
        "probe-rs",
        [
            "download",
            "--chip",
            PROBE_RS_CHIP,
            "--protocol",
            PROBE_RS_PROTOCOL,
            "--binary-format",
            "bin",
            "--base-address",
            UF2_BASE,
            "--preverify",
            "--verify",
            "--restore-unwritten",
            &bin_path.display().to_string(),
        ]
        .as_slice(),
    ) {
        return false;
    }

    run(
        workspace_root,
        "probe-rs",
        [
            "reset",
            "--chip",
            PROBE_RS_CHIP,
            "--protocol",
            PROBE_RS_PROTOCOL,
        ]
        .as_slice(),
    )
}

fn run_flash_uf2(workspace_root: &Path) -> bool {
    if !run_uf2(workspace_root) {
        return false;
    }

    let artifacts_dir = workspace_root
        .join("target")
        .join(TARGET_TRIPLE)
        .join("release");
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
