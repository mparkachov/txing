use std::path::PathBuf;
use std::time::{Duration, Instant};

mod ble;
mod btleplug_ble;
mod error;
mod event;
mod protocol;

use ble::{BleCentral, BleConnectConfig, TimedPowerMeasurement, TimedState};
use btleplug_ble::BtleplugBleCentral;
use clap::Parser;
use error::{Result, RigError};
use event::{EventEmitter, local_timestamp_for_path, parse_event_line};
use protocol::{REDCON_ACTIVE, REDCON_IDLE, RedconState};

const DEFAULT_NAME: &str = "power-test";
const DEFAULT_WAKE_SECONDS: f64 = 30.0;
const DEFAULT_MIN_ACTIVE_BATTERY: usize = 1;
const DEFAULT_IDLE_REPORT_MIN_DELAY: f64 = 55.0;
const DEFAULT_IDLE_REPORT_TIMEOUT: f64 = 75.0;
const DEFAULT_SCAN_TIMEOUT: f64 = 120.0;
const DEFAULT_CONNECT_TIMEOUT: f64 = 60.0;
const DEFAULT_CONNECT_ATTEMPTS: u32 = 3;
const DEFAULT_RETRY_DELAY: f64 = 5.0;
const DEFAULT_WAKE_DEADLINE: f64 = 10.0;
const DEFAULT_SLEEP_DEADLINE: f64 = 10.0;

#[derive(Debug, Parser)]
#[command(name = "power-device-test")]
#[command(about = "Physical BLE contract tests for txing power devices")]
struct Args {
    #[arg(default_value_t = 1)]
    repetitions: u32,
    #[arg(default_value = DEFAULT_NAME)]
    name: String,
    #[arg(long, default_value_t = DEFAULT_WAKE_SECONDS)]
    wake_seconds: f64,
    #[arg(long, default_value_t = DEFAULT_MIN_ACTIVE_BATTERY)]
    min_active_battery: usize,
    #[arg(long, default_value_t = DEFAULT_IDLE_REPORT_MIN_DELAY)]
    idle_report_min_delay: f64,
    #[arg(long, default_value_t = DEFAULT_IDLE_REPORT_TIMEOUT)]
    idle_report_timeout: f64,
    #[arg(long, default_value_t = DEFAULT_SCAN_TIMEOUT)]
    scan_timeout: f64,
    #[arg(long, default_value_t = DEFAULT_CONNECT_TIMEOUT)]
    connect_timeout: f64,
    #[arg(long, default_value_t = DEFAULT_CONNECT_ATTEMPTS)]
    connect_attempts: u32,
    #[arg(long, default_value_t = DEFAULT_RETRY_DELAY)]
    retry_delay: f64,
    #[arg(long, default_value_t = DEFAULT_WAKE_DEADLINE)]
    wake_deadline: f64,
    #[arg(long, default_value_t = DEFAULT_SLEEP_DEADLINE)]
    sleep_deadline: f64,
    #[arg(long)]
    require_service: bool,
    #[arg(long)]
    output_dir: Option<PathBuf>,
}

#[derive(Debug, Clone)]
struct PowerTestConfig {
    repetitions: u32,
    name: String,
    wake_seconds: f64,
    min_active_battery: usize,
    idle_report_min_delay: f64,
    idle_report_timeout: f64,
    scan_timeout: f64,
    connect_timeout: f64,
    connect_attempts: u32,
    retry_delay: f64,
    wake_deadline: f64,
    sleep_deadline: f64,
    require_service: bool,
    output_dir: PathBuf,
}

#[derive(Default)]
struct PowerTestSummary {
    passed_cycles: u32,
    active_battery_values: Vec<u16>,
    idle_battery_values: Vec<u16>,
}

impl TryFrom<Args> for PowerTestConfig {
    type Error = RigError;

    fn try_from(args: Args) -> Result<Self> {
        let output_dir = args.output_dir.unwrap_or_else(default_output_dir);
        let config = Self {
            repetitions: args.repetitions,
            name: args.name,
            wake_seconds: args.wake_seconds,
            min_active_battery: args.min_active_battery,
            idle_report_min_delay: args.idle_report_min_delay,
            idle_report_timeout: args.idle_report_timeout,
            scan_timeout: args.scan_timeout,
            connect_timeout: args.connect_timeout,
            connect_attempts: args.connect_attempts,
            retry_delay: args.retry_delay,
            wake_deadline: args.wake_deadline,
            sleep_deadline: args.sleep_deadline,
            require_service: args.require_service,
            output_dir,
        };
        config.validate()?;
        Ok(config)
    }
}

impl PowerTestConfig {
    fn validate(&self) -> Result<()> {
        if self.repetitions == 0 {
            return Err(RigError::args("repetitions must be greater than zero"));
        }
        if self.name.trim().is_empty() {
            return Err(RigError::args("device name must not be empty"));
        }
        if self.wake_seconds <= 0.0 {
            return Err(RigError::args("wake-seconds must be greater than zero"));
        }
        if self.min_active_battery == 0 {
            return Err(RigError::args(
                "min-active-battery must be greater than zero",
            ));
        }
        if self.idle_report_min_delay <= 0.0 || self.idle_report_timeout <= 0.0 {
            return Err(RigError::args(
                "idle report delay and timeout must be greater than zero",
            ));
        }
        if self.scan_timeout <= 0.0 || self.connect_timeout <= 0.0 {
            return Err(RigError::args(
                "scan-timeout and connect-timeout must be greater than zero",
            ));
        }
        if self.connect_attempts == 0 {
            return Err(RigError::args("connect-attempts must be greater than zero"));
        }
        Ok(())
    }

    fn connect_config(&self) -> BleConnectConfig {
        BleConnectConfig {
            name: self.name.clone(),
            require_service: self.require_service,
            scan_timeout: Duration::from_secs_f64(self.scan_timeout),
            connect_timeout: Duration::from_secs_f64(self.connect_timeout),
            connect_attempts: self.connect_attempts,
            retry_delay: Duration::from_secs_f64(self.retry_delay),
        }
    }
}

#[tokio::main]
async fn main() {
    if let Err(err) = run().await {
        eprintln!("{} {}", err.stage, err.message);
        std::process::exit(2);
    }
}

async fn run() -> Result<()> {
    let config = PowerTestConfig::try_from(Args::parse())?;
    std::fs::create_dir_all(&config.output_dir).map_err(|err| {
        RigError::new(
            "log",
            format!(
                "failed to create output directory {}: {err}",
                config.output_dir.display()
            ),
        )
    })?;
    let log_path = config.output_dir.join("cycle.log");
    let mut events = EventEmitter::stdout();
    events
        .add_file_sink(&log_path)
        .map_err(|err| RigError::new("log", format!("failed to create cycle log: {err}")))?;
    events.emit(
        "log-file",
        &[
            ("path", log_path.display().to_string()),
            ("outputDir", config.output_dir.display().to_string()),
        ],
    );

    let mut central = BtleplugBleCentral::new();
    let summary = run_power_test(&mut central, &config, &mut events).await;
    let close_result = central.close().await;
    if let Err(err) = close_result {
        events.emit("close-warning", &[("message", err.to_string())]);
    }
    summary?;
    events.emit(
        "summary",
        &[
            ("command", "power-test".to_string()),
            ("log", log_path.display().to_string()),
            ("outputDir", config.output_dir.display().to_string()),
        ],
    );
    println!("log={}", log_path.display());
    Ok(())
}

#[cfg(test)]
async fn run_physical_power_cycle(test_name: &str, index: usize) {
    let mut config = focused_physical_config_from_env();
    apply_physical_extra_args(&mut config);
    config.repetitions = 1;
    config.validate().unwrap();
    let artifacts = physical_test_artifacts();
    if let Some(artifacts) = &artifacts {
        std::fs::create_dir_all(&artifacts.output_dir).unwrap();
    }

    let started = std::time::Instant::now();
    let capture = std::sync::Arc::new(std::sync::Mutex::new(PhysicalTestCapture::default()));
    let mut events = EventEmitter::quiet();
    if let Some(artifacts) = &artifacts {
        events.add_file_sink_append(&artifacts.log_path).unwrap();
    }
    events.add_sink({
        let capture = std::sync::Arc::clone(&capture);
        move |line| {
            if let Ok(mut capture) = capture.lock() {
                capture.record_line(line);
            }
        }
    });
    let mut start_fields = vec![
        ("test", test_name.to_string()),
        ("index", index.to_string()),
    ];
    if let Some(artifacts) = &artifacts {
        start_fields.push(("log", artifacts.log_path.display().to_string()));
        start_fields.push(("outputDir", artifacts.output_dir.display().to_string()));
    }
    events.emit("test-start", &start_fields);

    let mut central = BtleplugBleCentral::new();
    let result = run_power_test(&mut central, &config, &mut events).await;
    let close_result = central.close().await;
    if let Err(err) = close_result {
        events.emit("close-warning", &[("message", err.to_string())]);
    }
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

    let duration_ms = started.elapsed().as_millis();
    let capture_snapshot = capture.lock().unwrap().clone();
    print_physical_test_outcome(test_name, index, duration_ms, &capture_snapshot, &result);

    if let Err(err) = result {
        panic!("{err}");
    }
}

#[cfg(test)]
include!(concat!(env!("OUT_DIR"), "/physical_power_tests.rs"));

async fn run_power_test(
    central: &mut dyn BleCentral,
    config: &PowerTestConfig,
    events: &mut EventEmitter,
) -> Result<PowerTestSummary> {
    events.emit(
        "starting",
        &[
            ("command", "power-test".to_string()),
            ("cycles", config.repetitions.to_string()),
            ("name", config.name.clone()),
            ("wakeSeconds", config.wake_seconds.to_string()),
            (
                "idleReportMinDelay",
                config.idle_report_min_delay.to_string(),
            ),
            ("idleReportTimeout", config.idle_report_timeout.to_string()),
            ("requireService", bool_field(config.require_service)),
        ],
    );

    let mut summary = PowerTestSummary::default();
    let test_started = Instant::now();
    for cycle in 1..=config.repetitions {
        let cycle_started = Instant::now();
        events.emit(
            "cycle-start",
            &[
                ("cycle", cycle.to_string()),
                ("cycles", config.repetitions.to_string()),
                (
                    "sinceStartMs",
                    cycle_started
                        .saturating_duration_since(test_started)
                        .as_millis()
                        .to_string(),
                ),
            ],
        );

        if !central.is_connected().await {
            central.connect(&config.connect_config(), events).await?;
            let state = central.read_state().await?;
            emit_state(events, &state.state);
        }

        let wake_command_at = central.write_redcon(REDCON_ACTIVE, events).await?;
        let wake_state = wait_for_redcon(
            central,
            REDCON_ACTIVE,
            &format!("cycle {cycle}: wake"),
            Duration::from_secs_f64(config.wake_deadline),
            wake_command_at,
            events,
        )
        .await?;
        events.emit(
            "wake-ok",
            &[
                ("cycle", cycle.to_string()),
                (
                    "latencyMs",
                    wake_state
                        .received_at
                        .saturating_duration_since(wake_command_at)
                        .as_millis()
                        .to_string(),
                ),
            ],
        );

        let active_battery = collect_active_battery(
            central,
            cycle,
            wake_command_at + Duration::from_secs_f64(config.wake_seconds),
            events,
        )
        .await?;
        if active_battery.len() < config.min_active_battery {
            return Err(RigError::new(
                "battery",
                format!(
                    "cycle {cycle}: got {} active battery updates, need {}",
                    active_battery.len(),
                    config.min_active_battery
                ),
            ));
        }
        summary
            .active_battery_values
            .extend(active_battery.iter().copied());

        let sleep_command_at = central.write_redcon(REDCON_IDLE, events).await?;
        let sleep_state = wait_for_redcon(
            central,
            REDCON_IDLE,
            &format!("cycle {cycle}: sleep"),
            Duration::from_secs_f64(config.sleep_deadline),
            sleep_command_at,
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
            ],
        );

        let idle_state = wait_for_connected_idle_battery(
            central,
            cycle,
            sleep_command_at + Duration::from_secs_f64(config.idle_report_min_delay),
            Duration::from_secs_f64(config.idle_report_timeout),
            events,
        )
        .await?;
        let idle_battery = idle_state.measurement.battery_mv.unwrap_or(0);
        summary.idle_battery_values.push(idle_battery);
        events.emit(
            "idle-battery-ok",
            &[
                ("cycle", cycle.to_string()),
                ("batteryMv", idle_battery.to_string()),
                (
                    "latencyMs",
                    idle_state
                        .received_at
                        .saturating_duration_since(sleep_command_at)
                        .as_millis()
                        .to_string(),
                ),
            ],
        );

        summary.passed_cycles += 1;
        events.emit(
            "summary",
            &[
                ("command", "cycle".to_string()),
                ("cycle", cycle.to_string()),
                ("cycles", config.repetitions.to_string()),
                ("activeBatteryCount", active_battery.len().to_string()),
                ("idleBatteryMv", idle_battery.to_string()),
                ("sleepLink", "connected".to_string()),
            ],
        );
    }

    events.emit(
        "summary",
        &[
            ("command", "test".to_string()),
            ("cycles", config.repetitions.to_string()),
            (
                "activeBatteryCount",
                summary.active_battery_values.len().to_string(),
            ),
            (
                "idleBatteryCount",
                summary.idle_battery_values.len().to_string(),
            ),
        ],
    );
    Ok(summary)
}

async fn wait_for_redcon(
    central: &mut dyn BleCentral,
    redcon: u8,
    stage: &str,
    deadline: Duration,
    after: Instant,
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
        let timeout = until
            .saturating_duration_since(Instant::now())
            .min(Duration::from_secs(1));
        match central.next_state(timeout).await {
            Ok(state) => {
                emit_state(events, &state.state);
                if state.received_at >= after && state.state.redcon == redcon {
                    return Ok(state);
                }
            }
            Err(err) if err.stage == "timeout" => continue,
            Err(err) if err.stage == "disconnect" => {
                return Err(RigError::new(
                    stage,
                    format!("unexpected disconnect before state {redcon}"),
                ));
            }
            Err(err) => return Err(err),
        }
    }
}

async fn collect_active_battery(
    central: &mut dyn BleCentral,
    cycle: u32,
    active_until: Instant,
    events: &mut EventEmitter,
) -> Result<Vec<u16>> {
    let mut values = Vec::new();
    while Instant::now() < active_until {
        let timeout = active_until
            .saturating_duration_since(Instant::now())
            .min(Duration::from_secs(1));
        match central.next_power_measurement(timeout).await {
            Ok(measurement) => {
                if let Some(battery_mv) = measurement.measurement.battery_mv {
                    values.push(battery_mv);
                    events.emit(
                        "active-battery",
                        &[
                            ("cycle", cycle.to_string()),
                            ("count", values.len().to_string()),
                            ("batteryMv", battery_mv.to_string()),
                        ],
                    );
                }
            }
            Err(err) if err.stage == "timeout" => continue,
            Err(err) if err.stage == "disconnect" => {
                return Err(RigError::new(
                    "wake",
                    format!("cycle {cycle}: unexpected disconnect during wake window"),
                ));
            }
            Err(err) => return Err(err),
        }
    }
    Ok(values)
}

async fn wait_for_connected_idle_battery(
    central: &mut dyn BleCentral,
    cycle: u32,
    not_before: Instant,
    timeout: Duration,
    _events: &mut EventEmitter,
) -> Result<TimedPowerMeasurement> {
    let until = Instant::now() + timeout;
    loop {
        if Instant::now() >= until {
            return Err(RigError::new(
                "idle-battery",
                format!("cycle {cycle}: REDCON 4 idle battery report deadline expired"),
            ));
        }
        let wait = until
            .saturating_duration_since(Instant::now())
            .min(Duration::from_secs(1));
        match central.next_power_measurement(wait).await {
            Ok(measurement) => {
                if measurement.received_at >= not_before
                    && measurement.measurement.battery_mv.is_some()
                {
                    return Ok(measurement);
                }
            }
            Err(err) if err.stage == "timeout" => continue,
            Err(err) if err.stage == "disconnect" => {
                return Err(RigError::new(
                    "sleep",
                    format!("cycle {cycle}: unexpected disconnect during connected idle"),
                ));
            }
            Err(err) => return Err(err),
        }
    }
}

fn emit_state(events: &mut EventEmitter, state: &RedconState) {
    events.emit(
        "state",
        &[
            ("redcon", state.redcon.to_string()),
            ("active", bool_field(state.active())),
        ],
    );
}

fn default_output_dir() -> PathBuf {
    std::env::temp_dir()
        .join("power-device-test-results")
        .join(format!(
            "{}-{}",
            local_timestamp_for_path(),
            std::process::id()
        ))
}

fn bool_field(value: bool) -> String {
    (if value { "1" } else { "0" }).to_string()
}

#[cfg(test)]
#[derive(Debug, Clone)]
struct PhysicalTestArtifacts {
    output_dir: PathBuf,
    log_path: PathBuf,
}

#[cfg(test)]
#[derive(Debug, Clone, Default)]
struct PhysicalTestCapture {
    connect_retries: Vec<String>,
    connect_ms: Vec<u128>,
    active_battery_mv: Vec<u16>,
    idle_battery_mv: Vec<u16>,
}

#[cfg(test)]
impl PhysicalTestCapture {
    fn record_line(&mut self, line: &str) {
        let (event, fields) = parse_event_line(line);
        let fields = fields
            .into_iter()
            .collect::<std::collections::BTreeMap<_, _>>();
        match event.as_str() {
            "connect-retry" => {
                self.connect_retries
                    .push(fields.get("message").cloned().unwrap_or_default());
            }
            "connected" => {
                if let Some(value) = field_u128(&fields, "connectMs") {
                    self.connect_ms.push(value);
                }
            }
            "active-battery" => {
                if let Some(value) = field_u16(&fields, "batteryMv") {
                    self.active_battery_mv.push(value);
                }
            }
            "idle-battery-ok" => {
                if let Some(value) = field_u16(&fields, "batteryMv") {
                    self.idle_battery_mv.push(value);
                }
            }
            _ => {}
        }
    }
}

#[cfg(test)]
fn focused_physical_config_from_env() -> PowerTestConfig {
    let output_dir = std::env::var_os("POWER_DEVICE_TEST_RUN_OUTPUT_DIR")
        .or_else(|| std::env::var_os("POWER_DEVICE_TEST_OUTPUT_DIR"))
        .map(PathBuf::from)
        .unwrap_or_else(default_output_dir);
    PowerTestConfig {
        repetitions: 1,
        name: std::env::var("POWER_DEVICE_TEST_NAME").unwrap_or_else(|_| DEFAULT_NAME.into()),
        wake_seconds: env_parse("POWER_DEVICE_TEST_WAKE_SECONDS", DEFAULT_WAKE_SECONDS),
        min_active_battery: env_parse(
            "POWER_DEVICE_TEST_MIN_ACTIVE_BATTERY",
            DEFAULT_MIN_ACTIVE_BATTERY,
        ),
        idle_report_min_delay: env_parse(
            "POWER_DEVICE_TEST_IDLE_REPORT_MIN_DELAY",
            DEFAULT_IDLE_REPORT_MIN_DELAY,
        ),
        idle_report_timeout: env_parse(
            "POWER_DEVICE_TEST_IDLE_REPORT_TIMEOUT",
            DEFAULT_IDLE_REPORT_TIMEOUT,
        ),
        scan_timeout: env_parse("POWER_DEVICE_TEST_SCAN_TIMEOUT", DEFAULT_SCAN_TIMEOUT),
        connect_timeout: env_parse("POWER_DEVICE_TEST_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT),
        connect_attempts: env_parse(
            "POWER_DEVICE_TEST_CONNECT_ATTEMPTS",
            DEFAULT_CONNECT_ATTEMPTS,
        ),
        retry_delay: env_parse("POWER_DEVICE_TEST_RETRY_DELAY", DEFAULT_RETRY_DELAY),
        wake_deadline: env_parse("POWER_DEVICE_TEST_WAKE_DEADLINE", DEFAULT_WAKE_DEADLINE),
        sleep_deadline: env_parse("POWER_DEVICE_TEST_SLEEP_DEADLINE", DEFAULT_SLEEP_DEADLINE),
        require_service: env_bool("POWER_DEVICE_TEST_REQUIRE_SERVICE", false),
        output_dir,
    }
}

#[cfg(test)]
fn apply_physical_extra_args(config: &mut PowerTestConfig) {
    let Ok(args) = std::env::var("POWER_DEVICE_TEST_ARGS") else {
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
            "--wake-seconds" => set_f64(&mut config.wake_seconds, next_value()),
            "--min-active-battery" => set_usize(&mut config.min_active_battery, next_value()),
            "--idle-report-min-delay" => set_f64(&mut config.idle_report_min_delay, next_value()),
            "--idle-report-timeout" => set_f64(&mut config.idle_report_timeout, next_value()),
            "--scan-timeout" => set_f64(&mut config.scan_timeout, next_value()),
            "--connect-timeout" => set_f64(&mut config.connect_timeout, next_value()),
            "--connect-attempts" => set_u32(&mut config.connect_attempts, next_value()),
            "--retry-delay" => set_f64(&mut config.retry_delay, next_value()),
            "--wake-deadline" => set_f64(&mut config.wake_deadline, next_value()),
            "--sleep-deadline" => set_f64(&mut config.sleep_deadline, next_value()),
            "--require-service" => config.require_service = true,
            "--no-require-service" => config.require_service = false,
            "--output-dir" => {
                let _ = next_value();
            }
            "--logs" => {}
            _ => {}
        }
    }
}

#[cfg(test)]
fn physical_test_artifacts() -> Option<PhysicalTestArtifacts> {
    if !physical_logs_enabled() {
        return None;
    }
    let output_dir = std::env::var_os("POWER_DEVICE_TEST_RUN_OUTPUT_DIR")
        .or_else(|| std::env::var_os("POWER_DEVICE_TEST_OUTPUT_DIR"))
        .map(PathBuf::from)
        .unwrap_or_else(default_output_dir);
    Some(PhysicalTestArtifacts {
        log_path: output_dir.join("cycle.log"),
        output_dir,
    })
}

#[cfg(test)]
fn physical_logs_enabled() -> bool {
    if env_bool("POWER_DEVICE_TEST_WRITE_LOGS", false) {
        return true;
    }
    std::env::var_os("POWER_DEVICE_TEST_OUTPUT_DIR").is_some()
        || std::env::var_os("POWER_DEVICE_TEST_RUN_OUTPUT_DIR").is_some()
        || std::env::var("POWER_DEVICE_TEST_ARGS")
            .map(|args| {
                args.split_whitespace()
                    .any(|arg| arg == "--logs" || arg.starts_with("--output-dir"))
            })
            .unwrap_or(false)
}

#[cfg(test)]
fn print_physical_test_outcome(
    test_name: &str,
    index: usize,
    duration_ms: u128,
    capture: &PhysicalTestCapture,
    result: &Result<PowerTestSummary>,
) {
    let retries = capture.connect_retries.len();
    let connect_max_ms = capture.connect_ms.iter().max().copied().unwrap_or(0);
    let battery_count = match result {
        Ok(summary) => summary.active_battery_values.len() + summary.idle_battery_values.len(),
        Err(_) => capture.active_battery_mv.len() + capture.idle_battery_mv.len(),
    };
    if retries > 0 {
        let last_message = capture
            .connect_retries
            .last()
            .map(String::as_str)
            .unwrap_or("connect retry");
        eprintln!(
            "warning: {test_name} index={index} recovered connect retry count={retries} connectMaxMs={connect_max_ms} batterySamples={battery_count} durationMs={duration_ms} last={last_message:?}"
        );
    }
    if let Err(err) = result {
        eprintln!(
            "failure: {test_name} index={index} durationMs={duration_ms} connectRetries={retries} connectMaxMs={connect_max_ms} batterySamples={battery_count} stage={} message={:?}",
            err.stage, err.message
        );
    }
}

#[cfg(test)]
fn env_parse<T>(name: &str, default: T) -> T
where
    T: std::str::FromStr + Copy,
{
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(default)
}

#[cfg(test)]
fn env_bool(name: &str, default: bool) -> bool {
    std::env::var(name)
        .ok()
        .map(|value| {
            matches!(
                value.to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(default)
}

#[cfg(test)]
fn set_f64(target: &mut f64, value: Option<&str>) {
    if let Some(parsed) = value.and_then(|value| value.parse().ok()) {
        *target = parsed;
    }
}

#[cfg(test)]
fn set_u32(target: &mut u32, value: Option<&str>) {
    if let Some(parsed) = value.and_then(|value| value.parse().ok()) {
        *target = parsed;
    }
}

#[cfg(test)]
fn set_usize(target: &mut usize, value: Option<&str>) {
    if let Some(parsed) = value.and_then(|value| value.parse().ok()) {
        *target = parsed;
    }
}

#[cfg(test)]
fn field_u128(fields: &std::collections::BTreeMap<String, String>, key: &str) -> Option<u128> {
    fields.get(key).and_then(|value| value.parse().ok())
}

#[cfg(test)]
fn field_u16(fields: &std::collections::BTreeMap<String, String>, key: &str) -> Option<u16> {
    fields.get(key).and_then(|value| value.parse().ok())
}
