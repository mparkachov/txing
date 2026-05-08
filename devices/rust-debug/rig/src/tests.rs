use std::time::Duration;

use crate::ble::BleCentral;
#[cfg(feature = "ble-real")]
use crate::btleplug_ble::BtleplugBleCentral;
use crate::component::BleConnectivityComponent;
use crate::cycle::{CycleConfig, TimeMode, run_cycle_test};
use crate::event::EventEmitter;
use crate::overnight::{Candidate, OvernightConfig, run_overnight};
use crate::protocol::{
    REDCON_ACTIVE, REDCON_IDLE, decode_state, encode_command, encode_state,
    validate_connection_params,
};
use crate::pubsub::{
    COMMAND_ACCEPTED, COMMAND_SUCCEEDED, ConnectivityCommand, ConnectivityCommandResult,
    ConnectivityState, InMemoryPubSub, build_command_result_topic, build_command_topic,
    build_state_topic,
};
use crate::sim_ble::{SimBleBehavior, SimBleCentral};

#[test]
fn protocol_round_trips_command_and_state() {
    let params = validate_connection_params("stable", 100, 0, 20000).unwrap();
    assert_eq!(encode_command(REDCON_ACTIVE, None), vec![1, REDCON_ACTIVE]);
    assert_eq!(
        encode_command(REDCON_ACTIVE, Some(&params)),
        vec![1, REDCON_ACTIVE, 100, 0, 0, 0, 32, 78]
    );

    let state = decode_state(&encode_state(REDCON_ACTIVE, 3795)).unwrap();
    assert_eq!(state.redcon, REDCON_ACTIVE);
    assert!(state.active);
    assert_eq!(state.battery_mv, Some(3795));

    let idle = decode_state(&encode_state(REDCON_IDLE, 0)).unwrap();
    assert_eq!(idle.redcon, REDCON_IDLE);
    assert!(!idle.active);
    assert_eq!(idle.battery_mv, None);
}

#[test]
fn protocol_rejects_invalid_state() {
    let err = decode_state(&[1, 3]).unwrap_err();
    assert_eq!(err.stage, "state");
    let err = decode_state(&[2, 3, 1, 0, 0]).unwrap_err();
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
        connection_profiles: Some("stable-100-0-20".to_string()),
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
    assert!(summary.contains("stable-100-0-20+bluez-balanced-service"));
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
async fn run_physical_ble_cycle(test_name: &str, conn_profile: &str, index: usize) {
    let mut config = focused_physical_config_from_env(conn_profile);
    apply_physical_extra_args(&mut config);
    config.repetitions = 1;
    let output_dir = physical_output_dir();
    std::fs::create_dir_all(&output_dir).unwrap();
    let log_path = output_dir.join("cycle.log");
    let mut events = EventEmitter::quiet();
    events.add_file_sink_append(&log_path).unwrap();
    events.emit(
        "test-start",
        &[
            ("test", test_name.to_string()),
            ("suite", conn_profile.to_string()),
            ("index", index.to_string()),
            ("log", log_path.display().to_string()),
            ("outputDir", output_dir.display().to_string()),
        ],
    );
    let mut central = BtleplugBleCentral::new();
    let summary = run_cycle_test(&mut central, &mut config, TimeMode::Real, &mut events)
        .await
        .unwrap();
    events.emit(
        "test-end",
        &[
            ("test", test_name.to_string()),
            ("suite", conn_profile.to_string()),
            ("index", index.to_string()),
            ("passedCycles", summary.passed_cycles.to_string()),
        ],
    );
    assert_eq!(summary.passed_cycles, 1);
}

#[cfg(feature = "ble-real")]
include!(concat!(env!("OUT_DIR"), "/physical_ble_tests.rs"));

#[cfg(feature = "ble-real")]
fn focused_physical_config_from_env(conn_profile: &str) -> CycleConfig {
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
    config.conn_profile = vec![conn_profile.to_string()];
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
            "--conn-profile" => {
                let _ = next_value();
            }
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
            "--conn-profile-cycles" => set_u32(&mut config.conn_profile_cycles, next_value()),
            "--conn-params" => {
                if let Some(value) = next_value() {
                    config.conn_params.push(value.to_string());
                }
            }
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
