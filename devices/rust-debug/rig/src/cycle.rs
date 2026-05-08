use std::time::{Duration, Instant};

use crate::ble::{BleCentral, BleConnectConfig, TimedState};
use crate::error::{Result, RigError};
use crate::event::EventEmitter;
use crate::protocol::{
    ConnectionParams, REDCON_ACTIVE, REDCON_IDLE, WeatherState, connection_fields,
    resolve_connection_profiles,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TimeMode {
    Real,
    Virtual,
}

#[derive(Debug, Clone)]
pub struct CycleConfig {
    pub repetitions: u32,
    pub name: String,
    pub wake_seconds: f64,
    pub cycle_seconds: f64,
    pub min_battery: usize,
    pub wake_deadline: f64,
    pub sleep_deadline: f64,
    pub scan_timeout: f64,
    pub connect_timeout: f64,
    pub connect_attempts: u32,
    pub retry_delay: f64,
    pub disconnect_deadline: f64,
    pub keep_connected_during_sleep: bool,
    pub require_service: bool,
    pub conn_profile: Vec<String>,
    pub conn_params: Vec<String>,
    pub conn_profile_cycles: u32,
    pub resolved_conn_profiles: Vec<Option<ConnectionParams>>,
}

#[derive(Debug, Clone, Default)]
pub struct CycleSummary {
    pub passed_cycles: u32,
    pub battery_values: Vec<u16>,
    pub wake_latencies_ms: Vec<u128>,
    pub connect_ms: Vec<u128>,
}

impl CycleConfig {
    pub fn default_for_name(name: impl Into<String>) -> Result<Self> {
        let conn_profile = Vec::new();
        let conn_params = Vec::new();
        Ok(Self {
            repetitions: 1,
            name: name.into(),
            wake_seconds: 30.0,
            cycle_seconds: 60.0,
            min_battery: 3,
            wake_deadline: 10.0,
            sleep_deadline: 10.0,
            scan_timeout: 60.0,
            connect_timeout: 30.0,
            connect_attempts: 3,
            retry_delay: 2.0,
            disconnect_deadline: 5.0,
            keep_connected_during_sleep: false,
            require_service: true,
            conn_profile,
            conn_params,
            conn_profile_cycles: 1,
            resolved_conn_profiles: resolve_connection_profiles(&[], &[])?,
        })
    }

    pub fn validate_and_resolve(&mut self) -> Result<()> {
        if self.repetitions == 0 {
            return Err(RigError::args("repetitions must be greater than zero"));
        }
        if self.wake_seconds <= 0.0 || self.cycle_seconds <= 0.0 {
            return Err(RigError::args(
                "wake-seconds and cycle-seconds must be greater than zero",
            ));
        }
        if self.wake_seconds >= self.cycle_seconds {
            return Err(RigError::args(
                "wake-seconds must be less than cycle-seconds",
            ));
        }
        if self.min_battery == 0 {
            return Err(RigError::args("min-battery must be greater than zero"));
        }
        if self.conn_profile_cycles == 0 {
            return Err(RigError::args(
                "conn-profile-cycles must be greater than zero",
            ));
        }
        self.resolved_conn_profiles =
            resolve_connection_profiles(&self.conn_profile, &self.conn_params)?;
        Ok(())
    }

    pub fn connect_config(&self) -> BleConnectConfig {
        BleConnectConfig {
            name: self.name.clone(),
            require_service: self.require_service,
            scan_timeout: Duration::from_secs_f64(self.scan_timeout),
            connect_timeout: Duration::from_secs_f64(self.connect_timeout),
            connect_attempts: self.connect_attempts,
            retry_delay: Duration::from_secs_f64(self.retry_delay),
        }
    }

    pub fn conn_params_for_cycle(&self, cycle: u32) -> Option<&ConnectionParams> {
        let block = self.conn_profile_cycles.max(1);
        let index = ((cycle - 1) / block) as usize % self.resolved_conn_profiles.len();
        self.resolved_conn_profiles[index].as_ref()
    }
}

pub async fn run_cycle_test(
    central: &mut dyn BleCentral,
    config: &mut CycleConfig,
    time_mode: TimeMode,
    events: &mut EventEmitter,
) -> Result<CycleSummary> {
    config.validate_and_resolve()?;
    events.emit(
        "starting",
        &[
            ("command", "test".to_string()),
            ("cycles", config.repetitions.to_string()),
            ("name", config.name.clone()),
            ("wakeSeconds", config.wake_seconds.to_string()),
            ("cycleSeconds", config.cycle_seconds.to_string()),
            ("minBattery", config.min_battery.to_string()),
            (
                "connProfiles",
                config
                    .resolved_conn_profiles
                    .iter()
                    .map(|profile| {
                        profile
                            .as_ref()
                            .map(|params| params.name.clone())
                            .unwrap_or_else(|| "central-default".to_string())
                    })
                    .collect::<Vec<_>>()
                    .join(","),
            ),
            ("connProfileCycles", config.conn_profile_cycles.to_string()),
        ],
    );

    let mut summary = CycleSummary::default();
    let test_started = Instant::now();
    for cycle in 1..=config.repetitions {
        let cycle_started = Instant::now();
        let conn_params = config.conn_params_for_cycle(cycle);
        let mut start_fields = vec![
            ("cycle", cycle.to_string()),
            ("cycles", config.repetitions.to_string()),
            (
                "sinceStartMs",
                test_started.elapsed().as_millis().to_string(),
            ),
        ];
        start_fields.extend(connection_fields(conn_params));
        events.emit("cycle-start", &start_fields);

        if !central.is_connected().await {
            central.connect(&config.connect_config(), events).await?;
            let state = central.read_state().await?;
            emit_state(events, &state.state);
        }

        let wake_command_at = central
            .write_redcon(REDCON_ACTIVE, conn_params, events)
            .await?;
        let wake_state = wait_for_redcon(
            central,
            REDCON_ACTIVE,
            &format!("cycle {cycle}: wake"),
            Duration::from_secs_f64(config.wake_deadline),
            wake_command_at,
            time_mode,
            events,
        )
        .await?;
        let wake_latency_ms = wake_state
            .received_at
            .saturating_duration_since(wake_command_at)
            .as_millis();
        summary.wake_latencies_ms.push(wake_latency_ms);
        let mut wake_fields = vec![
            ("cycle", cycle.to_string()),
            ("latencyMs", wake_latency_ms.to_string()),
            (
                "cycleElapsedMs",
                wake_state
                    .received_at
                    .saturating_duration_since(cycle_started)
                    .as_millis()
                    .to_string(),
            ),
            (
                "sinceStartMs",
                wake_state
                    .received_at
                    .saturating_duration_since(test_started)
                    .as_millis()
                    .to_string(),
            ),
            (
                "batteryMv",
                wake_state.state.battery_mv.unwrap_or(0).to_string(),
            ),
        ];
        wake_fields.extend(connection_fields(conn_params));
        events.emit("wake-ok", &wake_fields);

        let battery_states = collect_active_battery_states(
            central,
            config,
            cycle,
            wake_state,
            wake_command_at + Duration::from_secs_f64(config.wake_seconds),
            time_mode,
            events,
        )
        .await?;
        let battery_values: Vec<u16> = battery_states
            .iter()
            .filter_map(|state| state.state.battery_mv)
            .collect();
        if battery_values.len() < config.min_battery {
            return Err(RigError::new(
                "battery",
                format!(
                    "cycle {cycle}: got {} active battery updates, need {}",
                    battery_values.len(),
                    config.min_battery
                ),
            ));
        }
        summary
            .battery_values
            .extend(battery_values.iter().copied());

        let sleep_command_at = central.write_redcon(REDCON_IDLE, None, events).await?;
        let sleep_state = wait_for_redcon(
            central,
            REDCON_IDLE,
            &format!("cycle {cycle}: sleep"),
            Duration::from_secs_f64(config.sleep_deadline),
            sleep_command_at,
            time_mode,
            events,
        )
        .await?;
        events.emit(
            "sleep-ok",
            &[
                ("cycle", cycle.to_string()),
                (
                    "latencyMs",
                    sleep_state
                        .received_at
                        .saturating_duration_since(sleep_command_at)
                        .as_millis()
                        .to_string(),
                ),
                (
                    "batteryMv",
                    sleep_state.state.battery_mv.unwrap_or(0).to_string(),
                ),
            ],
        );

        let cycle_deadline = cycle_started + Duration::from_secs_f64(config.cycle_seconds);
        if config.keep_connected_during_sleep {
            monitor_sleep_window(central, cycle, cycle_deadline, time_mode).await?;
        } else {
            let started = Instant::now();
            central
                .wait_for_disconnect(Duration::from_secs_f64(config.disconnect_deadline))
                .await?;
            events.emit(
                "sleep-disconnect",
                &[
                    ("cycle", cycle.to_string()),
                    ("source", "device".to_string()),
                    (
                        "latencyMs",
                        Instant::now()
                            .saturating_duration_since(sleep_state.received_at)
                            .as_millis()
                            .to_string(),
                    ),
                    ("waitMs", started.elapsed().as_millis().to_string()),
                ],
            );
            sleep_disconnected_window(cycle, cycle_deadline, time_mode, events).await;
        }

        summary.passed_cycles += 1;
        events.emit(
            "summary",
            &[
                ("command", "cycle".to_string()),
                ("cycle", cycle.to_string()),
                ("cycles", config.repetitions.to_string()),
                ("batteryCount", battery_values.len().to_string()),
                (
                    "batteryMinMv",
                    battery_values
                        .iter()
                        .min()
                        .copied()
                        .unwrap_or(0)
                        .to_string(),
                ),
                (
                    "batteryMaxMv",
                    battery_values
                        .iter()
                        .max()
                        .copied()
                        .unwrap_or(0)
                        .to_string(),
                ),
                (
                    "sleepLink",
                    if config.keep_connected_during_sleep {
                        "connected"
                    } else {
                        "disconnected"
                    }
                    .to_string(),
                ),
            ],
        );
    }
    events.emit(
        "summary",
        &[
            ("command", "test".to_string()),
            ("cycles", config.repetitions.to_string()),
            ("elapsedSec", test_started.elapsed().as_secs().to_string()),
            ("batteryCount", summary.battery_values.len().to_string()),
            (
                "batteryMinMv",
                summary
                    .battery_values
                    .iter()
                    .min()
                    .copied()
                    .unwrap_or(0)
                    .to_string(),
            ),
            (
                "batteryMaxMv",
                summary
                    .battery_values
                    .iter()
                    .max()
                    .copied()
                    .unwrap_or(0)
                    .to_string(),
            ),
        ],
    );
    central.close().await?;
    Ok(summary)
}

async fn wait_for_redcon(
    central: &mut dyn BleCentral,
    redcon: u8,
    stage: &str,
    deadline: Duration,
    after: Instant,
    time_mode: TimeMode,
    events: &mut EventEmitter,
) -> Result<TimedState> {
    let until = Instant::now() + deadline;
    loop {
        if Instant::now() >= until {
            return Err(RigError::new(
                stage,
                format!("state {redcon} deadline expired"),
            ));
        }
        let timeout = (until - Instant::now()).min(Duration::from_millis(1000));
        match central.next_state(timeout).await {
            Ok(state) => {
                emit_state(events, &state.state);
                if state.received_at >= after && state.state.redcon == redcon {
                    return Ok(state);
                }
            }
            Err(err) if err.stage == "disconnect" => {
                return Err(RigError::new(
                    stage,
                    format!("disconnected before state {redcon}"),
                ));
            }
            Err(err) if err.stage == "timeout" && time_mode == TimeMode::Virtual => {
                return Err(RigError::new(
                    stage,
                    format!("state {redcon} deadline expired"),
                ));
            }
            Err(err) if err.stage == "timeout" => continue,
            Err(err) => return Err(err),
        }
    }
}

async fn collect_active_battery_states(
    central: &mut dyn BleCentral,
    config: &CycleConfig,
    cycle: u32,
    first_state: TimedState,
    active_until: Instant,
    time_mode: TimeMode,
    events: &mut EventEmitter,
) -> Result<Vec<TimedState>> {
    let mut states = Vec::new();
    if is_active_battery_state(&first_state.state) {
        states.push(first_state);
    }
    if time_mode == TimeMode::Virtual {
        while states.len() < config.min_battery {
            match central.next_state(Duration::from_millis(1)).await {
                Ok(state) => {
                    emit_state(events, &state.state);
                    if state.state.redcon == REDCON_IDLE {
                        break;
                    }
                    if is_active_battery_state(&state.state) {
                        states.push(state);
                        events.emit(
                            "battery",
                            &[
                                ("cycle", cycle.to_string()),
                                ("count", states.len().to_string()),
                                (
                                    "batteryMv",
                                    states
                                        .last()
                                        .and_then(|state| state.state.battery_mv)
                                        .unwrap_or(0)
                                        .to_string(),
                                ),
                            ],
                        );
                    }
                }
                Err(err) if err.stage == "timeout" => break,
                Err(err) if err.stage == "disconnect" => {
                    return Err(RigError::new(
                        "active",
                        format!(
                            "cycle {cycle}: unexpected disconnect during active battery window"
                        ),
                    ));
                }
                Err(err) => return Err(err),
            }
        }
        return Ok(states);
    }

    while Instant::now() < active_until {
        let timeout = (active_until - Instant::now()).min(Duration::from_secs(1));
        match central.next_state(timeout).await {
            Ok(state) => {
                emit_state(events, &state.state);
                if state.state.redcon == REDCON_IDLE && state.received_at < active_until {
                    return Err(RigError::new(
                        "wake",
                        format!("cycle {cycle}: device returned to sleep during wake window"),
                    ));
                }
                if is_active_battery_state(&state.state) {
                    states.push(state);
                    events.emit(
                        "battery",
                        &[
                            ("cycle", cycle.to_string()),
                            ("count", states.len().to_string()),
                            (
                                "batteryMv",
                                states
                                    .last()
                                    .and_then(|state| state.state.battery_mv)
                                    .unwrap_or(0)
                                    .to_string(),
                            ),
                        ],
                    );
                }
            }
            Err(err) if err.stage == "timeout" => continue,
            Err(err) if err.stage == "disconnect" => {
                return Err(RigError::new(
                    "active",
                    format!("cycle {cycle}: unexpected disconnect during active battery window"),
                ));
            }
            Err(err) => return Err(err),
        }
    }
    Ok(states)
}

async fn monitor_sleep_window(
    central: &mut dyn BleCentral,
    cycle: u32,
    until: Instant,
    time_mode: TimeMode,
) -> Result<()> {
    if time_mode == TimeMode::Virtual {
        return Ok(());
    }
    while Instant::now() < until {
        let timeout = (until - Instant::now()).min(Duration::from_secs(1));
        match central.next_state(timeout).await {
            Ok(state) => {
                if state.state.redcon == REDCON_ACTIVE || state.state.active {
                    return Err(RigError::new(
                        "sleep",
                        format!("cycle {cycle}: active state observed during sleep window"),
                    ));
                }
            }
            Err(err) if err.stage == "timeout" => continue,
            Err(err) if err.stage == "disconnect" => {
                return Err(RigError::new(
                    "sleep",
                    format!("cycle {cycle}: unexpected disconnect during connected sleep window"),
                ));
            }
            Err(err) => return Err(err),
        }
    }
    Ok(())
}

async fn sleep_disconnected_window(
    cycle: u32,
    until: Instant,
    time_mode: TimeMode,
    events: &mut EventEmitter,
) {
    let remaining = until.saturating_duration_since(Instant::now());
    if remaining.is_zero() {
        return;
    }
    events.emit(
        "sleep-idle",
        &[
            ("cycle", cycle.to_string()),
            ("mode", "advertising".to_string()),
            ("durationMs", remaining.as_millis().to_string()),
        ],
    );
    if time_mode == TimeMode::Real {
        tokio::time::sleep(remaining).await;
    }
}

fn emit_state(events: &mut EventEmitter, state: &WeatherState) {
    events.emit(
        "state",
        &[
            ("redcon", state.redcon.to_string()),
            ("active", if state.active { "1" } else { "0" }.to_string()),
            ("batteryMv", state.battery_mv.unwrap_or(0).to_string()),
        ],
    );
}

fn is_active_battery_state(state: &WeatherState) -> bool {
    state.redcon == REDCON_ACTIVE && state.active && state.battery_mv.is_some()
}
