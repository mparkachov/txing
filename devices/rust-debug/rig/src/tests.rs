use std::time::Duration;

use crate::ble::BleCentral;
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
