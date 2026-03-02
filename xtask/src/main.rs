use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::collections::{HashMap, HashSet};
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
const TXING_SERVICE_UUID: &str = "f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100";
const BLE_INIT_TIMEOUT_SECS: u64 = 10;
const BLE_PERIPHERALS_TIMEOUT_MS: u64 = 600;
const BLE_PROPERTIES_TIMEOUT_MS: u64 = 200;
const BLE_GATT_PROBE_TIMEOUT_MS: u64 = 1_200;
const BLE_PROBE_RETRY_SECS: u64 = 5;
const MAX_PROBES_PER_LOOP: usize = 4;
const BLE_ID_FAST_PATH_SECS: u64 = 2;
const BLE_ID_CACHE_FILE: &str = ".txing_ble_id";
const TXING_MFG_ID: u16 = 0xFFFF;
const TXING_MFG_MAGIC: &[u8] = b"TX";

struct BleSleepOptions {
    name: String,
    id: Option<String>,
    sleep: Option<bool>,
    scan_timeout_secs: u64,
}

impl Default for BleSleepOptions {
    fn default() -> Self {
        Self {
            name: "txing".to_string(),
            id: None,
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
        "scan" => to_exit_code(run_scan(&cmd_args)),
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
    eprintln!("usage: cargo fw [build|bin|uf2|flash|scan|sleep|wakeup|ble-sleep]");
    eprintln!("  cargo fw scan [--scan-timeout <sec>]");
    eprintln!("  cargo fw sleep [--name <local_name>] [--id <peripheral_id>] [--scan-timeout <sec>]");
    eprintln!("  cargo fw wakeup [--name <local_name>] [--id <peripheral_id>] [--scan-timeout <sec>]");
    eprintln!(
        "  cargo fw ble-sleep --sleep <true|false> [--name <local_name>] [--id <peripheral_id>] [--scan-timeout <sec>]"
    );
}

fn print_scan_usage() {
    eprintln!("usage: cargo fw scan [--scan-timeout <sec>]");
    eprintln!("  --scan-timeout  scan timeout in seconds (default: 12)");
}

fn print_ble_sleep_usage() {
    eprintln!(
        "usage: cargo fw ble-sleep --sleep <true|false> [--name <local_name>] [--id <peripheral_id>] [--scan-timeout <sec>]"
    );
    eprintln!("  --sleep         target state (true/false), required");
    eprintln!("  --name          BLE local name fragment to match (default: txing)");
    eprintln!("  --id            BLE peripheral id to match exactly (example: 12C5364E-...)");
    eprintln!("  --scan-timeout  scan timeout in seconds (default: 12)");
}

fn print_ble_alias_usage(cmd: &str) {
    eprintln!("usage: cargo fw {cmd} [--name <local_name>] [--id <peripheral_id>] [--scan-timeout <sec>]");
    eprintln!("  --name          BLE local name fragment to match (default: txing)");
    eprintln!("  --id            BLE peripheral id to match exactly (example: 12C5364E-...)");
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
            "--id" => {
                let value = args
                    .get(idx + 1)
                    .ok_or_else(|| "--id requires a value".to_string())?;
                opts.id = Some(value.clone());
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
            "--id" => {
                let value = args
                    .get(idx + 1)
                    .ok_or_else(|| "--id requires a value".to_string())?;
                opts.id = Some(value.clone());
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

fn workspace_root() -> &'static Path {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("xtask should live under workspace root")
}

fn ble_id_cache_path() -> PathBuf {
    workspace_root().join(BLE_ID_CACHE_FILE)
}

fn load_cached_ble_id() -> Option<String> {
    let raw = fs::read_to_string(ble_id_cache_path()).ok()?;
    let id = raw.trim();
    if id.is_empty() {
        None
    } else {
        Some(id.to_string())
    }
}

fn save_cached_ble_id(id: &str) {
    if let Err(err) = fs::write(ble_id_cache_path(), format!("{id}\n")) {
        eprintln!("warning: failed to save BLE id cache: {err}");
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
    println!("Scanning BLE peripherals (timeout={}s)...", timeout.as_secs());
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

async fn run_ble_sleep_async(opts: BleSleepOptions) -> Result<(), String> {
    let sleep = opts.sleep.expect("validated above");
    let mut effective_id = opts.id.clone();
    if effective_id.is_none() {
        if let Some(cached_id) = load_cached_ble_id() {
            println!("Using cached BLE id='{}' (override with --id)", cached_id);
            effective_id = Some(cached_id);
        }
    }
    let service_uuid = Uuid::parse_str(TXING_SERVICE_UUID)
        .map_err(|err| format!("invalid Service UUID constant: {err}"))?;
    let sleep_cmd_uuid = Uuid::parse_str(SLEEP_COMMAND_UUID)
        .map_err(|err| format!("invalid Sleep Command UUID constant: {err}"))?;
    let state_report_uuid = Uuid::parse_str(STATE_REPORT_UUID)
        .map_err(|err| format!("invalid State Report UUID constant: {err}"))?;

    if let Some(id) = effective_id.as_deref() {
        println!(
            "Scanning for BLE id='{}' or service={} (timeout={}s)...",
            id, TXING_SERVICE_UUID, opts.scan_timeout_secs
        );
    } else {
        println!(
            "Scanning for BLE service={} (timeout={}s)...",
            TXING_SERVICE_UUID, opts.scan_timeout_secs
        );
    }

    let manager = tokio::time::timeout(
        Duration::from_secs(BLE_INIT_TIMEOUT_SECS),
        Manager::new(),
    )
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

    let peripheral = find_peripheral(
        &adapter,
        service_uuid,
        sleep_cmd_uuid,
        state_report_uuid,
        &opts.name,
        effective_id.as_deref(),
        Duration::from_secs(opts.scan_timeout_secs),
    )
    .await?
    .ok_or_else(|| {
        let hint = if effective_id.is_none() {
            " (tip: run once with --id <peripheral_id>, or increase --scan-timeout)"
        } else {
            ""
        };
        format!(
            "device not found before timeout (service={}, name='{}', id={}){}",
            TXING_SERVICE_UUID,
            opts.name,
            effective_id.as_deref().unwrap_or("<not-set>"),
            hint
        )
    })?;

    let found_id = peripheral.id().to_string();
    if effective_id
        .as_deref()
        .map(|id| !found_id.eq_ignore_ascii_case(id))
        .unwrap_or(true)
    {
        println!("Discovered target id='{}'", found_id);
    }
    save_cached_ble_id(&found_id);

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

    let mut characteristics = peripheral.characteristics();
    let has_sleep = characteristics.iter().any(|c| c.uuid == sleep_cmd_uuid);
    let has_state = characteristics.iter().any(|c| c.uuid == state_report_uuid);
    if !(has_sleep && has_state) {
        peripheral
            .discover_services()
            .await
            .map_err(|err| format!("failed to discover GATT services: {err}"))?;
        characteristics = peripheral.characteristics();
    }

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

async fn find_peripheral(
    adapter: &btleplug::platform::Adapter,
    service_uuid: Uuid,
    sleep_cmd_uuid: Uuid,
    state_report_uuid: Uuid,
    expected_name: &str,
    expected_id: Option<&str>,
    timeout: Duration,
) -> Result<Option<Peripheral>, String> {
    let deadline = Instant::now() + timeout;
    let id_fast_path_until = expected_id.map(|_| Instant::now() + Duration::from_secs(BLE_ID_FAST_PATH_SECS));
    let mut probe_attempts: usize = 0;
    let mut last_probe_at: HashMap<String, Instant> = HashMap::new();
    let mut announced_candidates: HashSet<String> = HashSet::new();
    let mut last_progress = Instant::now();
    let expected_name_lower = expected_name.to_ascii_lowercase();

    loop {
        let peripherals = match tokio::time::timeout(
            Duration::from_millis(BLE_PERIPHERALS_TIMEOUT_MS),
            adapter.peripherals(),
        )
        .await
        {
            Ok(Ok(p)) => p,
            Ok(Err(err)) => {
                return Err(format!("failed to read discovered peripherals: {err}"));
            }
            Err(_) => {
                if Instant::now() >= deadline {
                    return Ok(None);
                }
                tokio::time::sleep(Duration::from_millis(250)).await;
                continue;
            }
        };

        if last_progress.elapsed() >= Duration::from_secs(2) {
            println!(
                "scan progress: {} peripheral(s) seen, {} probe attempt(s), still searching...",
                peripherals.len(),
                probe_attempts
            );
            last_progress = Instant::now();
        }

        for peripheral in &peripherals {
            let id = peripheral.id().to_string();
            let id_match = expected_id
                .map(|expected| id.eq_ignore_ascii_case(expected))
                .unwrap_or(false);

            if id_match {
                if announced_candidates.insert(id.clone()) {
                    println!(
                        "scan candidate: id={} name='<id-match>' service_match=false name_exact=false name_contains=false mfg_match=false",
                        id
                    );
                }
                return Ok(Some(peripheral.clone()));
            }

            // Fast path for cached IDs: avoid slower property calls until grace window expires.
            if id_fast_path_until
                .map(|until| Instant::now() < until)
                .unwrap_or(false)
            {
                continue;
            }

            let props = match tokio::time::timeout(
                Duration::from_millis(BLE_PROPERTIES_TIMEOUT_MS),
                peripheral.properties(),
            )
            .await
            {
                Ok(Ok(p)) => p,
                _ => continue,
            };

            let (service_match, name_exact, name_contains, mfg_match, local_name) =
                if let Some(p) = props.as_ref() {
                    let service_match = p.services.contains(&service_uuid);
                    let local_name = p.local_name.clone();
                    let name_exact = local_name
                        .as_deref()
                        .map(|name| name == expected_name)
                        .unwrap_or(false);
                    let name_contains = local_name
                        .as_deref()
                        .map(|name| name.to_ascii_lowercase().contains(&expected_name_lower))
                        .unwrap_or(false);
                    let mfg_match = p
                        .manufacturer_data
                        .get(&TXING_MFG_ID)
                        .map(|data| data.starts_with(TXING_MFG_MAGIC))
                        .unwrap_or(false);
                    (service_match, name_exact, name_contains, mfg_match, local_name)
                } else {
                    (false, false, false, false, None)
                };

            if (id_match || service_match || name_contains || mfg_match)
                && announced_candidates.insert(id.clone())
            {
                println!(
                    "scan candidate: id={} name='{}' service_match={} name_exact={} name_contains={} mfg_match={}",
                    id,
                    local_name.as_deref().unwrap_or("<none>"),
                    service_match,
                    name_exact,
                    name_contains,
                    mfg_match
                );
            }

            if id_match || service_match || name_exact || name_contains || mfg_match {
                return Ok(Some(peripheral.clone()));
            }
        }

        // Fallback path for platforms where advertised name/services are often missing:
        // opportunistically connect and identify by GATT characteristic UUIDs.
        if expected_id.is_some() {
            if Instant::now() >= deadline {
                return Ok(None);
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
            continue;
        }

        let mut probes_this_loop = 0usize;
        let mut probe_candidates: Vec<Peripheral> = Vec::new();
        for peripheral in &peripherals {
            if probes_this_loop >= MAX_PROBES_PER_LOOP {
                break;
            }
            if Instant::now() >= deadline {
                return Ok(None);
            }

            let id = peripheral.id().to_string();
            let recently_probed = last_probe_at
                .get(&id)
                .map(|last| last.elapsed() < Duration::from_secs(BLE_PROBE_RETRY_SECS))
                .unwrap_or(false);
            if recently_probed {
                continue;
            }
            probe_candidates.push(peripheral.clone());
            probes_this_loop += 1;
        }

        if !probe_candidates.is_empty() {
            let _ = adapter.stop_scan().await;
        }

        for peripheral in probe_candidates {
            let id = peripheral.id().to_string();
            last_probe_at.insert(id, Instant::now());
            probe_attempts += 1;

            let connected = match tokio::time::timeout(
                Duration::from_millis(BLE_GATT_PROBE_TIMEOUT_MS),
                peripheral.is_connected(),
            )
            .await
            {
                Ok(Ok(v)) => v,
                _ => continue,
            };

            if !connected {
                match tokio::time::timeout(
                    Duration::from_millis(BLE_GATT_PROBE_TIMEOUT_MS),
                    peripheral.connect(),
                )
                .await
                {
                    Ok(Ok(())) => {}
                    _ => continue,
                }
            }

            match tokio::time::timeout(
                Duration::from_millis(BLE_GATT_PROBE_TIMEOUT_MS),
                peripheral.discover_services(),
            )
            .await
            {
                Ok(Ok(())) => {}
                _ => {
                    let _ = tokio::time::timeout(
                        Duration::from_millis(BLE_GATT_PROBE_TIMEOUT_MS),
                        peripheral.disconnect(),
                    )
                    .await;
                    continue;
                }
            }

            let characteristics = peripheral.characteristics();
            let has_sleep = characteristics.iter().any(|c| c.uuid == sleep_cmd_uuid);
            let has_state = characteristics.iter().any(|c| c.uuid == state_report_uuid);

            if has_sleep && has_state {
                return Ok(Some(peripheral.clone()));
            }

            let _ = tokio::time::timeout(
                Duration::from_millis(BLE_GATT_PROBE_TIMEOUT_MS),
                peripheral.disconnect(),
            )
            .await;
        }

        if probes_this_loop > 0 {
            let _ = adapter.start_scan(ScanFilter::default()).await;
        }

        if Instant::now() >= deadline {
            return Ok(None);
        }

        tokio::time::sleep(Duration::from_millis(100)).await;
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
