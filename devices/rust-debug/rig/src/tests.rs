use std::time::Duration;

use crate::ble::BleCentral;
#[cfg(feature = "ble-real")]
use crate::btleplug_ble::BtleplugBleCentral;
use crate::component::BleConnectivityComponent;
use crate::cycle::{CycleConfig, TimeMode, run_cycle_test};
use crate::event::EventEmitter;
#[cfg(feature = "ble-real")]
use crate::event::{local_timestamp, parse_event_line};
use crate::overnight::{Candidate, OvernightConfig, run_overnight};
use crate::protocol::{REDCON_ACTIVE, REDCON_IDLE, decode_state, encode_command, encode_state};
use crate::pubsub::{
    COMMAND_ACCEPTED, COMMAND_SUCCEEDED, ConnectivityCommand, ConnectivityCommandResult,
    ConnectivityState, InMemoryPubSub, build_command_result_topic, build_command_topic,
    build_state_topic,
};
use crate::sim_ble::{SimBleBehavior, SimBleCentral};

#[test]
fn protocol_round_trips_command_and_state() {
    assert_eq!(encode_command(REDCON_ACTIVE), vec![1, REDCON_ACTIVE]);

    let state = decode_state(&encode_state(REDCON_ACTIVE, 3795)).unwrap();
    assert_eq!(state.redcon, REDCON_ACTIVE);
    assert!(state.active());
    assert_eq!(state.battery_mv, Some(3795));

    let idle = decode_state(&encode_state(REDCON_IDLE, 0)).unwrap();
    assert_eq!(idle.redcon, REDCON_IDLE);
    assert!(!idle.active());
    assert_eq!(idle.battery_mv, None);
}

#[test]
fn protocol_rejects_invalid_state() {
    let err = decode_state(&[1, 3]).unwrap_err();
    assert_eq!(err.stage, "state");
    let err = decode_state(&[2, 3, 0, 0]).unwrap_err();
    assert_eq!(err.stage, "state");
}

#[tokio::test]
async fn simulated_cycle_succeeds() {
    let mut config = CycleConfig::default_for_name("weather-q8zbgb").unwrap();
    config.repetitions = 2;
    let mut central = SimBleCentral::default();
    let mut events = EventEmitter::quiet();
    let summary = run_cycle_test(&mut central, &mut config, TimeMode::Virtual, &mut events)
        .await
        .unwrap();
    assert_eq!(summary.passed_cycles, 2);
    assert!(summary.battery_values.len() >= 6);
}

#[tokio::test]
async fn simulated_cycle_reports_expected_failure_modes() {
    let cases = [
        (
            SimBleBehavior {
                missing_advertisement: true,
                ..Default::default()
            },
            "discover",
        ),
        (
            SimBleBehavior {
                wake_timeout: true,
                ..Default::default()
            },
            "cycle 1: wake",
        ),
        (
            SimBleBehavior {
                low_battery_updates: true,
                ..Default::default()
            },
            "battery",
        ),
        (
            SimBleBehavior {
                invalid_state_on_wake: true,
                ..Default::default()
            },
            "state",
        ),
        (
            SimBleBehavior {
                unexpected_disconnect_on_wake: true,
                ..Default::default()
            },
            "cycle 1: wake",
        ),
    ];

    for (behavior, expected_stage) in cases {
        let mut config = CycleConfig::default_for_name("weather-q8zbgb").unwrap();
        let mut central = SimBleCentral::new(behavior);
        let mut events = EventEmitter::quiet();
        let err = run_cycle_test(&mut central, &mut config, TimeMode::Virtual, &mut events)
            .await
            .unwrap_err();
        assert_eq!(err.stage, expected_stage);
    }
}

#[tokio::test]
async fn pubsub_delivers_exact_and_wildcard_messages() {
    let bus = InMemoryPubSub::default();
    let mut exact = bus.subscribe(build_state_topic("thing-1")).await;
    let mut wildcard = bus.subscribe("dev/txing/rig/v1/connectivity/state/+").await;
    bus.publish(build_state_topic("thing-1"), b"payload".to_vec())
        .await
        .unwrap();

    assert_eq!(exact.recv().await.unwrap().payload, b"payload");
    assert_eq!(wildcard.recv().await.unwrap().payload, b"payload");
}

#[tokio::test]
async fn mock_component_accepts_command_and_publishes_state() {
    let bus = InMemoryPubSub::default();
    let mut results = bus.subscribe(build_command_result_topic("thing-1")).await;
    let mut states = bus.subscribe(build_state_topic("thing-1")).await;
    let mut component = BleConnectivityComponent::new(
        "rust-debug-ble-main",
        "thing-1",
        "weather-q8zbgb",
        bus.clone(),
        SimBleCentral::default(),
    );
    let command = ConnectivityCommand::new("cmd-1", "thing-1", true);
    component
        .handle_command_payload(&build_command_topic("thing-1"), &command.to_json().unwrap())
        .await
        .unwrap();

    let accepted: ConnectivityCommandResult =
        serde_json::from_slice(&results.recv().await.unwrap().payload).unwrap();
    let succeeded: ConnectivityCommandResult =
        serde_json::from_slice(&results.recv().await.unwrap().payload).unwrap();
    let state = ConnectivityState::from_slice(&states.recv().await.unwrap().payload).unwrap();
    assert_eq!(accepted.status, COMMAND_ACCEPTED);
    assert_eq!(succeeded.status, COMMAND_SUCCEEDED);
    assert_eq!(state.power, Some(true));
    assert_eq!(state.battery_mv, Some(3795));
}

#[tokio::test]
async fn virtual_overnight_writes_report_and_summary() {
    let temp = tempfile::tempdir().unwrap();
    let config = OvernightConfig {
        output_dir: Some(temp.path().to_path_buf()),
        duration_hours: 3.0 / 60.0,
        matrix_hours: 2.0 / 60.0,
        confirm_hours: 1.0 / 60.0,
        trial_cycles: 1,
        central_profiles: Some("bluez-balanced-service".to_string()),
        ..OvernightConfig::default()
    };
    let mut factory = |_candidate: &Candidate| -> Box<dyn BleCentral + Send> {
        Box::new(SimBleCentral::default())
    };
    let output = run_overnight(config, TimeMode::Virtual, &mut factory)
        .await
        .unwrap();
    let summary = std::fs::read_to_string(output.join("summary.json")).unwrap();
    let report = std::fs::read_to_string(output.join("report.md")).unwrap();
    assert!(summary.contains("\"phase\": \"complete\""));
    assert!(summary.contains("bluez-balanced-service"));
    assert!(report.contains("Selected Candidate"));
}

#[tokio::test]
#[ignore = "short wall-clock soak for manual scheduler validation"]
async fn ignored_wall_clock_simulated_cycle_soak() {
    let mut config = CycleConfig::default_for_name("weather-q8zbgb").unwrap();
    config.repetitions = 1;
    config.wake_seconds = 0.2;
    config.cycle_seconds = 0.4;
    config.min_battery = 1;
    let mut central = SimBleCentral::default();
    let mut events = EventEmitter::quiet();
    let summary = run_cycle_test(&mut central, &mut config, TimeMode::Real, &mut events)
        .await
        .unwrap();
    assert_eq!(summary.passed_cycles, 1);
    tokio::time::sleep(Duration::from_millis(1)).await;
}

#[cfg(feature = "ble-real")]
async fn run_physical_ble_cycle(test_name: &str, index: usize) {
    let mut config = focused_physical_config_from_env();
    apply_physical_extra_args(&mut config);
    config.repetitions = 1;
    let output_dir = physical_output_dir();
    std::fs::create_dir_all(&output_dir).unwrap();
    let log_path = output_dir.join("cycle.log");
    let started_at = local_timestamp();
    let started = std::time::Instant::now();
    let capture = std::sync::Arc::new(std::sync::Mutex::new(PhysicalTestCapture::default()));
    let mut events = EventEmitter::quiet();
    events.add_file_sink_append(&log_path).unwrap();
    events.add_sink({
        let capture = std::sync::Arc::clone(&capture);
        move |line| {
            if let Ok(mut capture) = capture.lock() {
                capture.record_line(line);
            }
        }
    });
    events.emit(
        "test-start",
        &[
            ("test", test_name.to_string()),
            ("index", index.to_string()),
            ("log", log_path.display().to_string()),
            ("outputDir", output_dir.display().to_string()),
        ],
    );
    let mut central = BtleplugBleCentral::new();
    let result = run_cycle_test(&mut central, &mut config, TimeMode::Real, &mut events).await;
    let ended_at = local_timestamp();
    let duration_ms = started.elapsed().as_millis();

    match &result {
        Ok(summary) => {
            events.emit(
                "test-end",
                &[
                    ("test", test_name.to_string()),
                    ("index", index.to_string()),
                    ("passedCycles", summary.passed_cycles.to_string()),
                ],
            );
        }
        Err(err) => {
            events.emit(
                "test-fail",
                &[
                    ("test", test_name.to_string()),
                    ("index", index.to_string()),
                    ("stage", err.stage.clone()),
                    ("message", err.message.clone()),
                ],
            );
        }
    }

    let record = physical_test_record(
        test_name,
        index,
        &config,
        &log_path,
        &output_dir,
        started_at,
        ended_at,
        duration_ms,
        capture.lock().unwrap().clone(),
        &result,
    );
    write_physical_result(&output_dir, &record).unwrap();

    if let Err(err) = result {
        panic!("{err}");
    }
    assert_eq!(record["summary"]["passedCycles"].as_u64().unwrap_or(0), 1);
}

#[cfg(feature = "ble-real")]
include!(concat!(env!("OUT_DIR"), "/physical_ble_tests.rs"));

#[cfg(feature = "ble-real")]
fn focused_physical_config_from_env() -> CycleConfig {
    let name = std::env::var("RUST_DEBUG_RIG_NAME").unwrap_or_else(|_| "weather-q8zbgb".into());
    let mut config = CycleConfig::default_for_name(name).unwrap();
    config.repetitions = 1;
    config.wake_seconds = env_parse("RUST_DEBUG_RIG_WAKE_SECONDS", 30.0);
    config.cycle_seconds = env_parse("RUST_DEBUG_RIG_CYCLE_SECONDS", 50.0);
    config.scan_timeout = env_parse("RUST_DEBUG_RIG_SCAN_TIMEOUT", 120.0);
    config.connect_timeout = env_parse("RUST_DEBUG_RIG_CONNECT_TIMEOUT", 60.0);
    config.connect_attempts = env_parse("RUST_DEBUG_RIG_CONNECT_ATTEMPTS", 5);
    config.retry_delay = env_parse("RUST_DEBUG_RIG_RETRY_DELAY", 5.0);
    config.disconnect_deadline = env_parse("RUST_DEBUG_RIG_DISCONNECT_DEADLINE", 10.0);
    config.require_service = false;
    config
}

#[cfg(feature = "ble-real")]
fn env_parse<T>(name: &str, default: T) -> T
where
    T: std::str::FromStr + Copy,
{
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(default)
}

#[cfg(feature = "ble-real")]
fn apply_physical_extra_args(config: &mut CycleConfig) {
    let Ok(args) = std::env::var("RUST_DEBUG_RIG_TEST_ARGS") else {
        return;
    };
    let mut tokens = args.split_whitespace();
    while let Some(token) = tokens.next() {
        let (flag, inline_value) = token
            .split_once('=')
            .map_or((token, None), |(flag, value)| (flag, Some(value)));
        let mut next_value = || inline_value.or_else(|| tokens.next());
        match flag {
            "--repetitions" => {
                let _ = next_value();
            }
            "--name" => {
                if let Some(value) = next_value() {
                    config.name = value.to_string();
                }
            }
            "--scan-timeout" => set_f64(&mut config.scan_timeout, next_value()),
            "--connect-timeout" => set_f64(&mut config.connect_timeout, next_value()),
            "--connect-attempts" => set_u32(&mut config.connect_attempts, next_value()),
            "--retry-delay" => set_f64(&mut config.retry_delay, next_value()),
            "--disconnect-deadline" => set_f64(&mut config.disconnect_deadline, next_value()),
            "--wake-seconds" => set_f64(&mut config.wake_seconds, next_value()),
            "--cycle-seconds" => set_f64(&mut config.cycle_seconds, next_value()),
            "--wake-deadline" => set_f64(&mut config.wake_deadline, next_value()),
            "--sleep-deadline" => set_f64(&mut config.sleep_deadline, next_value()),
            "--min-battery" => set_usize(&mut config.min_battery, next_value()),
            "--output-dir" => {
                let _ = next_value();
            }
            "--no-require-service" => config.require_service = false,
            "--require-service" => config.require_service = true,
            _ => {}
        }
    }
}

#[cfg(feature = "ble-real")]
fn physical_output_dir() -> std::path::PathBuf {
    if let Some(path) = std::env::var_os("RUST_DEBUG_RIG_OUTPUT_DIR") {
        return std::path::PathBuf::from(path);
    }
    let args = std::env::var("RUST_DEBUG_RIG_TEST_ARGS").unwrap_or_default();
    let mut tokens = args.split_whitespace();
    while let Some(token) = tokens.next() {
        if let Some(value) = token.strip_prefix("--output-dir=") {
            return std::path::PathBuf::from(value);
        }
        if token == "--output-dir" {
            if let Some(value) = tokens.next() {
                return std::path::PathBuf::from(value);
            }
        }
    }
    std::env::var_os("RUST_DEBUG_RIG_RUN_OUTPUT_DIR")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::env::temp_dir().join("rust-debug-rig-test-results"))
}

#[cfg(feature = "ble-real")]
fn set_f64(target: &mut f64, value: Option<&str>) {
    if let Some(parsed) = value.and_then(|value| value.parse().ok()) {
        *target = parsed;
    }
}

#[cfg(feature = "ble-real")]
fn set_u32(target: &mut u32, value: Option<&str>) {
    if let Some(parsed) = value.and_then(|value| value.parse().ok()) {
        *target = parsed;
    }
}

#[cfg(feature = "ble-real")]
fn set_usize(target: &mut usize, value: Option<&str>) {
    if let Some(parsed) = value.and_then(|value| value.parse().ok()) {
        *target = parsed;
    }
}

#[cfg(feature = "ble-real")]
#[derive(Debug, Clone, Default)]
struct PhysicalTestCapture {
    adv_count: u64,
    adv_service_matches: u64,
    adv_rssi_values: Vec<i64>,
    connect_retries: Vec<serde_json::Value>,
    connect_ms: Vec<u128>,
    wake_latencies_ms: Vec<u128>,
    sleep_latencies_ms: Vec<u128>,
    sleep_disconnect_ms: Vec<u128>,
    active_battery_mv: Vec<u64>,
    state_count: u64,
    last_event: Option<serde_json::Value>,
}

#[cfg(feature = "ble-real")]
impl PhysicalTestCapture {
    fn record_line(&mut self, line: &str) {
        let (event, fields) = parse_event_line(line);
        if event.is_empty() {
            return;
        }
        let fields = fields
            .into_iter()
            .collect::<std::collections::BTreeMap<_, _>>();
        self.last_event = Some(serde_json::json!({
            "event": event,
            "fields": fields,
        }));
        match self
            .last_event
            .as_ref()
            .and_then(|value| value["event"].as_str())
            .unwrap_or_default()
        {
            "adv" => {
                self.adv_count += 1;
                if field_u64(&fields, "service") == Some(1) {
                    self.adv_service_matches += 1;
                }
                if let Some(rssi) = field_i64(&fields, "rssi") {
                    self.adv_rssi_values.push(rssi);
                }
            }
            "connect-retry" => {
                self.connect_retries.push(serde_json::json!({
                    "attempt": field_u64(&fields, "attempt"),
                    "attempts": field_u64(&fields, "attempts"),
                    "message": fields.get("message").cloned().unwrap_or_default(),
                }));
            }
            "connected" => {
                if let Some(value) = field_u128(&fields, "connectMs") {
                    self.connect_ms.push(value);
                }
            }
            "state" => {
                self.state_count += 1;
            }
            "wake-ok" => {
                if let Some(value) = field_u128(&fields, "latencyMs") {
                    self.wake_latencies_ms.push(value);
                }
            }
            "battery" => {
                if let Some(value) = field_u64(&fields, "batteryMv") {
                    self.active_battery_mv.push(value);
                }
            }
            "sleep-ok" => {
                if let Some(value) = field_u128(&fields, "latencyMs") {
                    self.sleep_latencies_ms.push(value);
                }
            }
            "sleep-disconnect" => {
                if let Some(value) = field_u128(&fields, "latencyMs") {
                    self.sleep_disconnect_ms.push(value);
                }
            }
            _ => {}
        }
    }
}

#[cfg(feature = "ble-real")]
#[allow(clippy::too_many_arguments)]
fn physical_test_record(
    test_name: &str,
    index: usize,
    config: &CycleConfig,
    log_path: &std::path::Path,
    output_dir: &std::path::Path,
    started_at: String,
    ended_at: String,
    duration_ms: u128,
    capture: PhysicalTestCapture,
    result: &crate::error::Result<crate::cycle::CycleSummary>,
) -> serde_json::Value {
    let failure = result.as_ref().err().map(|err| {
        serde_json::json!({
            "stage": err.stage,
            "message": err.message,
        })
    });
    let summary = match result {
        Ok(summary) => serde_json::json!({
            "passedCycles": summary.passed_cycles,
            "batteryCount": summary.battery_values.len(),
            "batteryMinMv": summary.battery_values.iter().min().copied(),
            "batteryMaxMv": summary.battery_values.iter().max().copied(),
            "wakeLatenciesMs": summary.wake_latencies_ms,
            "connectMs": summary.connect_ms,
        }),
        Err(_) => serde_json::json!({
            "passedCycles": 0,
            "batteryCount": capture.active_battery_mv.len(),
            "batteryMinMv": capture.active_battery_mv.iter().min().copied(),
            "batteryMaxMv": capture.active_battery_mv.iter().max().copied(),
            "wakeLatenciesMs": capture.wake_latencies_ms,
            "connectMs": capture.connect_ms,
        }),
    };
    serde_json::json!({
        "schemaVersion": "txing.rust-debug.physical-ble-testcase.v1",
        "framework": "rust-test",
        "test": {
            "name": test_name,
            "suite": "redcon",
            "index": index,
            "status": if failure.is_some() { "failed" } else { "passed" },
            "startedAt": started_at,
            "endedAt": ended_at,
            "durationMs": duration_ms,
        },
        "config": {
            "name": config.name,
            "wakeSeconds": config.wake_seconds,
            "cycleSeconds": config.cycle_seconds,
            "minBattery": config.min_battery,
            "wakeDeadline": config.wake_deadline,
            "sleepDeadline": config.sleep_deadline,
            "scanTimeout": config.scan_timeout,
            "connectTimeout": config.connect_timeout,
            "connectAttempts": config.connect_attempts,
            "retryDelay": config.retry_delay,
            "disconnectDeadline": config.disconnect_deadline,
            "requireService": config.require_service,
        },
        "summary": summary,
        "observed": {
            "advertisements": {
                "count": capture.adv_count,
                "serviceMatches": capture.adv_service_matches,
                "rssiValues": capture.adv_rssi_values,
            },
            "connectRetries": capture.connect_retries,
            "connectMs": capture.connect_ms,
            "wakeLatenciesMs": capture.wake_latencies_ms,
            "sleepLatenciesMs": capture.sleep_latencies_ms,
            "sleepDisconnectMs": capture.sleep_disconnect_ms,
            "activeBatteryMv": capture.active_battery_mv,
            "stateCount": capture.state_count,
            "lastEvent": capture.last_event,
        },
        "failure": failure,
        "artifacts": {
            "outputDir": output_dir.display().to_string(),
            "cycleLog": log_path.display().to_string(),
            "jsonl": output_dir.join("results.jsonl").display().to_string(),
            "json": output_dir.join("results.json").display().to_string(),
            "junit": output_dir.join("junit.xml").display().to_string(),
        },
    })
}

#[cfg(feature = "ble-real")]
fn write_physical_result(
    output_dir: &std::path::Path,
    record: &serde_json::Value,
) -> std::io::Result<()> {
    use std::io::Write;

    let jsonl_path = output_dir.join("results.jsonl");
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&jsonl_path)?;
    serde_json::to_writer(&mut file, record)?;
    writeln!(file)?;
    rebuild_physical_result_artifacts(output_dir)
}

#[cfg(feature = "ble-real")]
fn rebuild_physical_result_artifacts(output_dir: &std::path::Path) -> std::io::Result<()> {
    let records = read_physical_result_records(&output_dir.join("results.jsonl"))?;
    let aggregate = physical_result_aggregate(output_dir, &records);
    std::fs::write(
        output_dir.join("results.json"),
        serde_json::to_vec_pretty(&aggregate)?,
    )?;
    std::fs::write(output_dir.join("junit.xml"), physical_junit_xml(&records))?;
    Ok(())
}

#[cfg(feature = "ble-real")]
fn read_physical_result_records(path: &std::path::Path) -> std::io::Result<Vec<serde_json::Value>> {
    use std::io::BufRead;

    let file = std::fs::File::open(path)?;
    let mut records = Vec::new();
    for line in std::io::BufReader::new(file).lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let value = serde_json::from_str(&line).map_err(std::io::Error::other)?;
        records.push(value);
    }
    Ok(records)
}

#[cfg(feature = "ble-real")]
fn physical_result_aggregate(
    output_dir: &std::path::Path,
    records: &[serde_json::Value],
) -> serde_json::Value {
    let mut suites = std::collections::BTreeMap::<String, serde_json::Value>::new();
    for record in records {
        let suite = record["test"]["suite"]
            .as_str()
            .unwrap_or("unknown")
            .to_string();
        let entry = suites.entry(suite.clone()).or_insert_with(|| {
            serde_json::json!({
                "name": suite,
                "tests": 0,
                "failures": 0,
                "retries": 0,
                "durationMs": 0_u64,
            })
        });
        entry["tests"] = serde_json::json!(entry["tests"].as_u64().unwrap_or(0) + 1);
        if record["test"]["status"].as_str() != Some("passed") {
            entry["failures"] = serde_json::json!(entry["failures"].as_u64().unwrap_or(0) + 1);
        }
        entry["retries"] = serde_json::json!(
            entry["retries"].as_u64().unwrap_or(0)
                + record["observed"]["connectRetries"]
                    .as_array()
                    .map_or(0, |items| items.len() as u64)
        );
        entry["durationMs"] = serde_json::json!(
            entry["durationMs"].as_u64().unwrap_or(0)
                + record["test"]["durationMs"].as_u64().unwrap_or(0)
        );
    }
    let failures = records
        .iter()
        .filter(|record| record["test"]["status"].as_str() != Some("passed"))
        .count();
    let retries: usize = records
        .iter()
        .map(|record| {
            record["observed"]["connectRetries"]
                .as_array()
                .map_or(0, Vec::len)
        })
        .sum();
    serde_json::json!({
        "schemaVersion": "txing.rust-debug.physical-ble-results.v1",
        "format": "txing-json+junit",
        "generatedAt": local_timestamp(),
        "outputDir": output_dir.display().to_string(),
        "artifacts": {
            "cycleLog": output_dir.join("cycle.log").display().to_string(),
            "jsonl": output_dir.join("results.jsonl").display().to_string(),
            "json": output_dir.join("results.json").display().to_string(),
            "junit": output_dir.join("junit.xml").display().to_string(),
        },
        "summary": {
            "tests": records.len(),
            "passed": records.len().saturating_sub(failures),
            "failed": failures,
            "connectRetries": retries,
        },
        "suites": suites.into_values().collect::<Vec<_>>(),
        "testCases": records,
    })
}

#[cfg(feature = "ble-real")]
fn physical_junit_xml(records: &[serde_json::Value]) -> String {
    let mut by_suite = std::collections::BTreeMap::<String, Vec<&serde_json::Value>>::new();
    for record in records {
        by_suite
            .entry(
                record["test"]["suite"]
                    .as_str()
                    .unwrap_or("unknown")
                    .to_string(),
            )
            .or_default()
            .push(record);
    }
    let tests = records.len();
    let failures = records
        .iter()
        .filter(|record| record["test"]["status"].as_str() != Some("passed"))
        .count();
    let total_time = records
        .iter()
        .map(|record| record["test"]["durationMs"].as_f64().unwrap_or(0.0) / 1000.0)
        .sum::<f64>();
    let mut xml = format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<testsuites name=\"rust-debug physical BLE\" tests=\"{tests}\" failures=\"{failures}\" errors=\"0\" time=\"{total_time:.3}\">\n"
    );
    for (suite, suite_records) in by_suite {
        let suite_tests = suite_records.len();
        let suite_failures = suite_records
            .iter()
            .filter(|record| record["test"]["status"].as_str() != Some("passed"))
            .count();
        let suite_time = suite_records
            .iter()
            .map(|record| record["test"]["durationMs"].as_f64().unwrap_or(0.0) / 1000.0)
            .sum::<f64>();
        xml.push_str(&format!(
            "  <testsuite name=\"{}\" tests=\"{}\" failures=\"{}\" errors=\"0\" time=\"{:.3}\">\n",
            xml_escape(&format!("physical_ble.{suite}")),
            suite_tests,
            suite_failures,
            suite_time
        ));
        for record in suite_records {
            let name = record["test"]["name"].as_str().unwrap_or("unknown");
            let case_time = record["test"]["durationMs"].as_f64().unwrap_or(0.0) / 1000.0;
            xml.push_str(&format!(
                "    <testcase classname=\"{}\" name=\"{}\" time=\"{:.3}\">",
                xml_escape(&format!("rust_debug_rig.physical_ble.{suite}")),
                xml_escape(name),
                case_time
            ));
            if record["test"]["status"].as_str() != Some("passed") {
                let stage = record["failure"]["stage"].as_str().unwrap_or("failure");
                let message = record["failure"]["message"]
                    .as_str()
                    .unwrap_or("test failed");
                xml.push_str(&format!(
                    "\n      <failure type=\"{}\" message=\"{}\">{}</failure>\n    ",
                    xml_escape(stage),
                    xml_escape(message),
                    xml_escape(&serde_json::to_string_pretty(record).unwrap_or_default())
                ));
            }
            let retries = record["observed"]["connectRetries"]
                .as_array()
                .map_or(0, Vec::len);
            let connect_max = record["observed"]["connectMs"]
                .as_array()
                .and_then(|items| items.iter().filter_map(serde_json::Value::as_u64).max())
                .unwrap_or(0);
            xml.push_str(&format!(
                "<system-out>{}</system-out></testcase>\n",
                xml_escape(&format!(
                    "connectRetries={retries} connectMaxMs={connect_max}"
                ))
            ));
        }
        xml.push_str("  </testsuite>\n");
    }
    xml.push_str("</testsuites>\n");
    xml
}

#[cfg(feature = "ble-real")]
fn xml_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

#[cfg(feature = "ble-real")]
fn field_u64(fields: &std::collections::BTreeMap<String, String>, key: &str) -> Option<u64> {
    fields.get(key)?.parse().ok()
}

#[cfg(feature = "ble-real")]
fn field_i64(fields: &std::collections::BTreeMap<String, String>, key: &str) -> Option<i64> {
    fields.get(key)?.parse().ok()
}

#[cfg(feature = "ble-real")]
fn field_u128(fields: &std::collections::BTreeMap<String, String>, key: &str) -> Option<u128> {
    fields.get(key)?.parse().ok()
}

#[cfg(feature = "ble-real")]
#[test]
fn physical_result_artifacts_are_junit_and_json() {
    let temp = tempfile::tempdir().unwrap();
    let first = serde_json::json!({
        "test": {
            "name": "physical_ble_redcon_001",
            "suite": "redcon",
            "status": "passed",
            "durationMs": 50000,
        },
        "observed": {
            "connectRetries": [],
            "connectMs": [1234],
        },
        "failure": null,
    });
    let second = serde_json::json!({
        "test": {
            "name": "physical_ble_redcon_002",
            "suite": "redcon",
            "status": "failed",
            "durationMs": 32000,
        },
        "observed": {
            "connectRetries": [{"attempt": 1, "attempts": 4, "message": "connect failed"}],
            "connectMs": [2500],
        },
        "failure": {
            "stage": "battery",
            "message": "got 2 active battery updates, need 3",
        },
    });
    write_physical_result(temp.path(), &first).unwrap();
    write_physical_result(temp.path(), &second).unwrap();

    let aggregate = std::fs::read_to_string(temp.path().join("results.json")).unwrap();
    let junit = std::fs::read_to_string(temp.path().join("junit.xml")).unwrap();
    assert!(aggregate.contains("\"tests\": 2"));
    assert!(aggregate.contains("\"failed\": 1"));
    assert!(junit.contains("<testsuites"));
    assert!(junit.contains("failures=\"1\""));
    assert!(junit.contains("<failure"));
}
