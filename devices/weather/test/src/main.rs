use std::path::PathBuf;
use std::time::{Duration, Instant};

use clap::Parser;
use weather_device_test::ble::{
    BleCentral, BleConnectConfig, TimedPowerMeasurement, TimedState, TimedWeatherMeasurement,
};
use weather_device_test::btleplug_ble::BtleplugBleCentral;
use weather_device_test::error::{Result, RigError};
use weather_device_test::event::{EventEmitter, local_timestamp_for_path, parse_event_line};
use weather_device_test::protocol::{REDCON_ACTIVE, REDCON_IDLE, RedconState};

const DEFAULT_NAME: &str = "weather-test";
const DEFAULT_IDLE_REPORT_MIN_DELAY: f64 = 55.0;
const DEFAULT_IDLE_REPORT_TIMEOUT: f64 = 75.0;
const DEFAULT_SCAN_TIMEOUT: f64 = 120.0;
const DEFAULT_CONNECT_TIMEOUT: f64 = 60.0;
const DEFAULT_CONNECT_ATTEMPTS: u32 = 3;
const DEFAULT_RETRY_DELAY: f64 = 5.0;

#[derive(Debug, Parser)]
#[command(name = "weather-device-test")]
#[command(about = "Physical BLE contract tests for txing weather devices")]
struct Args {
    #[arg(default_value_t = 1)]
    repetitions: u32,
    #[arg(default_value = DEFAULT_NAME)]
    name: String,
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
    #[arg(long)]
    require_service: bool,
    #[arg(long)]
    output_dir: Option<PathBuf>,
}

#[derive(Debug, Clone)]
struct WeatherTestConfig {
    repetitions: u32,
    name: String,
    idle_report_min_delay: f64,
    idle_report_timeout: f64,
    scan_timeout: f64,
    connect_timeout: f64,
    connect_attempts: u32,
    retry_delay: f64,
    require_service: bool,
    output_dir: PathBuf,
}

#[derive(Default)]
struct WeatherTestSummary {
    passed_cycles: u32,
    battery_values: Vec<u16>,
    weather_values: usize,
    rejected_redcon3: u32,
}

impl TryFrom<Args> for WeatherTestConfig {
    type Error = RigError;

    fn try_from(args: Args) -> Result<Self> {
        let output_dir = args.output_dir.unwrap_or_else(default_output_dir);
        let config = Self {
            repetitions: args.repetitions,
            name: args.name,
            idle_report_min_delay: args.idle_report_min_delay,
            idle_report_timeout: args.idle_report_timeout,
            scan_timeout: args.scan_timeout,
            connect_timeout: args.connect_timeout,
            connect_attempts: args.connect_attempts,
            retry_delay: args.retry_delay,
            require_service: args.require_service,
            output_dir,
        };
        config.validate()?;
        Ok(config)
    }
}

impl WeatherTestConfig {
    fn validate(&self) -> Result<()> {
        if self.repetitions == 0 {
            return Err(RigError::args("repetitions must be greater than zero"));
        }
        if self.name.trim().is_empty() {
            return Err(RigError::args("device name must not be empty"));
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
    let config = WeatherTestConfig::try_from(Args::parse())?;
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
    let summary = run_weather_test(&mut central, &config, &mut events).await;
    let close_result = central.close().await;
    if let Err(err) = close_result {
        events.emit("close-warning", &[("message", err.to_string())]);
    }
    summary?;
    events.emit(
        "summary",
        &[
            ("command", "weather-test".to_string()),
            ("log", log_path.display().to_string()),
            ("outputDir", config.output_dir.display().to_string()),
        ],
    );
    println!("log={}", log_path.display());
    Ok(())
}

#[cfg(test)]
async fn run_physical_weather_cycle(test_name: &str, index: usize) {
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
    let result = run_weather_test(&mut central, &config, &mut events).await;
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
include!(concat!(env!("OUT_DIR"), "/physical_weather_tests.rs"));

async fn run_weather_test(
    central: &mut dyn BleCentral,
    config: &WeatherTestConfig,
    events: &mut EventEmitter,
) -> Result<WeatherTestSummary> {
    events.emit(
        "starting",
        &[
            ("command", "weather-test".to_string()),
            ("cycles", config.repetitions.to_string()),
            ("name", config.name.clone()),
            (
                "idleReportMinDelay",
                config.idle_report_min_delay.to_string(),
            ),
            ("idleReportTimeout", config.idle_report_timeout.to_string()),
            ("requireService", bool_field(config.require_service)),
        ],
    );

    let mut summary = WeatherTestSummary::default();
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
        }

        let state = central.read_state().await?;
        require_redcon4(&state, "state")?;
        emit_state(events, &state.state);

        let initial_power = central.read_power_measurement().await?;
        let initial_battery = require_battery(&initial_power, cycle, "initial-battery")?;
        summary.battery_values.push(initial_battery);
        events.emit(
            "initial-battery",
            &[
                ("cycle", cycle.to_string()),
                ("batteryMv", initial_battery.to_string()),
            ],
        );

        let initial_weather = central.read_weather_measurement().await?;
        summary.weather_values += 1;
        emit_weather(events, cycle, "initial-weather", &initial_weather);

        match central.write_redcon(REDCON_ACTIVE, events).await {
            Ok(_) => {
                return Err(RigError::new(
                    "command",
                    format!("cycle {cycle}: REDCON 3 command was unexpectedly accepted"),
                ));
            }
            Err(err) => {
                events.emit(
                    "redcon3-rejected",
                    &[
                        ("cycle", cycle.to_string()),
                        ("stage", err.stage),
                        ("message", err.message),
                    ],
                );
                summary.rejected_redcon3 += 1;
            }
        }

        let state = central.read_state().await?;
        require_redcon4(&state, "post-redcon3-state")?;

        let command_at = central.write_redcon(REDCON_IDLE, events).await?;
        let state = wait_for_redcon4(
            central,
            &format!("cycle {cycle}: redcon4 command"),
            Duration::from_secs(10),
            command_at,
            events,
        )
        .await?;
        events.emit(
            "redcon4-ok",
            &[
                ("cycle", cycle.to_string()),
                (
                    "latencyMs",
                    state
                        .received_at
                        .saturating_duration_since(command_at)
                        .as_millis()
                        .to_string(),
                ),
            ],
        );

        let not_before = command_at + Duration::from_secs_f64(config.idle_report_min_delay);
        let idle_power = wait_for_connected_idle_power(
            central,
            cycle,
            not_before,
            Duration::from_secs_f64(config.idle_report_timeout),
        )
        .await?;
        let idle_battery = require_battery(&idle_power, cycle, "idle-battery")?;
        summary.battery_values.push(idle_battery);
        events.emit(
            "idle-battery-ok",
            &[
                ("cycle", cycle.to_string()),
                ("batteryMv", idle_battery.to_string()),
                (
                    "latencyMs",
                    idle_power
                        .received_at
                        .saturating_duration_since(command_at)
                        .as_millis()
                        .to_string(),
                ),
            ],
        );

        let idle_weather = wait_for_connected_idle_weather(
            central,
            cycle,
            not_before,
            Duration::from_secs_f64(config.idle_report_timeout),
        )
        .await?;
        summary.weather_values += 1;
        emit_weather(events, cycle, "idle-weather-ok", &idle_weather);

        summary.passed_cycles += 1;
        events.emit(
            "summary",
            &[
                ("command", "cycle".to_string()),
                ("cycle", cycle.to_string()),
                ("cycles", config.repetitions.to_string()),
                ("batteryCount", summary.battery_values.len().to_string()),
                ("weatherCount", summary.weather_values.to_string()),
                ("redcon3Rejected", summary.rejected_redcon3.to_string()),
            ],
        );
    }

    events.emit(
        "summary",
        &[
            ("command", "test".to_string()),
            ("cycles", config.repetitions.to_string()),
            ("batteryCount", summary.battery_values.len().to_string()),
            ("weatherCount", summary.weather_values.to_string()),
            ("redcon3Rejected", summary.rejected_redcon3.to_string()),
        ],
    );
    Ok(summary)
}

async fn wait_for_redcon4(
    central: &mut dyn BleCentral,
    stage: &str,
    deadline: Duration,
    after: Instant,
    events: &mut EventEmitter,
) -> Result<TimedState> {
    let until = Instant::now() + deadline;
    loop {
        if Instant::now() >= until {
            return Err(RigError::new(stage, "state 4 deadline expired"));
        }
        let timeout = until
            .saturating_duration_since(Instant::now())
            .min(Duration::from_secs(1));
        match central.next_state(timeout).await {
            Ok(state) => {
                emit_state(events, &state.state);
                if state.received_at >= after && state.state.redcon == REDCON_IDLE {
                    return Ok(state);
                }
            }
            Err(err) if err.stage == "timeout" || err.stage == "state" => continue,
            Err(err) if err.stage == "disconnect" => {
                return Err(RigError::new(stage, "unexpected disconnect before state 4"));
            }
            Err(err) => return Err(err),
        }
    }
}

async fn wait_for_connected_idle_power(
    central: &mut dyn BleCentral,
    cycle: u32,
    not_before: Instant,
    timeout: Duration,
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
            Err(err) if err.stage == "timeout" || err.stage == "power measurement" => continue,
            Err(err) if err.stage == "disconnect" => {
                return Err(RigError::new(
                    "idle-battery",
                    format!("cycle {cycle}: unexpected disconnect during connected idle"),
                ));
            }
            Err(err) => return Err(err),
        }
    }
}

async fn wait_for_connected_idle_weather(
    central: &mut dyn BleCentral,
    cycle: u32,
    not_before: Instant,
    timeout: Duration,
) -> Result<TimedWeatherMeasurement> {
    let until = Instant::now() + timeout;
    loop {
        if Instant::now() >= until {
            return Err(RigError::new(
                "idle-weather",
                format!("cycle {cycle}: REDCON 4 idle weather report deadline expired"),
            ));
        }
        let wait = until
            .saturating_duration_since(Instant::now())
            .min(Duration::from_secs(1));
        match central.next_weather_measurement(wait).await {
            Ok(measurement) => {
                if measurement.received_at >= not_before {
                    return Ok(measurement);
                }
            }
            Err(err) if err.stage == "timeout" || err.stage == "weather measurement" => continue,
            Err(err) if err.stage == "disconnect" => {
                return Err(RigError::new(
                    "idle-weather",
                    format!("cycle {cycle}: unexpected disconnect during connected idle"),
                ));
            }
            Err(err) => return Err(err),
        }
    }
}

fn require_redcon4(state: &TimedState, stage: &str) -> Result<()> {
    if state.state.redcon != REDCON_IDLE {
        return Err(RigError::new(
            stage,
            format!("expected REDCON 4, got {}", state.state.redcon),
        ));
    }
    Ok(())
}

fn require_battery(measurement: &TimedPowerMeasurement, cycle: u32, stage: &str) -> Result<u16> {
    measurement.measurement.battery_mv.ok_or_else(|| {
        RigError::new(
            stage,
            format!("cycle {cycle}: expected nonzero battery measurement"),
        )
    })
}

fn emit_state(events: &mut EventEmitter, state: &RedconState) {
    events.emit("state", &[("redcon", state.redcon.to_string())]);
}

fn emit_weather(
    events: &mut EventEmitter,
    cycle: u32,
    event: &str,
    measurement: &TimedWeatherMeasurement,
) {
    events.emit(
        event,
        &[
            ("cycle", cycle.to_string()),
            (
                "temperatureC",
                measurement.measurement.temperature_c().to_string(),
            ),
            (
                "pressureKpa",
                measurement.measurement.pressure_kpa().to_string(),
            ),
            (
                "humidityPercent",
                measurement.measurement.humidity_percent().to_string(),
            ),
        ],
    );
}

fn default_output_dir() -> PathBuf {
    std::env::temp_dir()
        .join("weather-device-test-results")
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
    battery_mv: Vec<u16>,
    weather_samples: usize,
    redcon3_rejections: usize,
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
            "initial-battery" | "idle-battery-ok" => {
                if let Some(value) = field_u16(&fields, "batteryMv") {
                    self.battery_mv.push(value);
                }
            }
            "initial-weather" | "idle-weather-ok" => self.weather_samples += 1,
            "redcon3-rejected" => self.redcon3_rejections += 1,
            _ => {}
        }
    }
}

#[cfg(test)]
fn focused_physical_config_from_env() -> WeatherTestConfig {
    let output_dir = std::env::var_os("WEATHER_DEVICE_TEST_RUN_OUTPUT_DIR")
        .or_else(|| std::env::var_os("WEATHER_DEVICE_TEST_OUTPUT_DIR"))
        .map(PathBuf::from)
        .unwrap_or_else(default_output_dir);
    WeatherTestConfig {
        repetitions: 1,
        name: std::env::var("WEATHER_DEVICE_TEST_NAME").unwrap_or_else(|_| DEFAULT_NAME.into()),
        idle_report_min_delay: env_parse(
            "WEATHER_DEVICE_TEST_IDLE_REPORT_MIN_DELAY",
            DEFAULT_IDLE_REPORT_MIN_DELAY,
        ),
        idle_report_timeout: env_parse(
            "WEATHER_DEVICE_TEST_IDLE_REPORT_TIMEOUT",
            DEFAULT_IDLE_REPORT_TIMEOUT,
        ),
        scan_timeout: env_parse("WEATHER_DEVICE_TEST_SCAN_TIMEOUT", DEFAULT_SCAN_TIMEOUT),
        connect_timeout: env_parse(
            "WEATHER_DEVICE_TEST_CONNECT_TIMEOUT",
            DEFAULT_CONNECT_TIMEOUT,
        ),
        connect_attempts: env_parse(
            "WEATHER_DEVICE_TEST_CONNECT_ATTEMPTS",
            DEFAULT_CONNECT_ATTEMPTS,
        ),
        retry_delay: env_parse("WEATHER_DEVICE_TEST_RETRY_DELAY", DEFAULT_RETRY_DELAY),
        require_service: env_bool("WEATHER_DEVICE_TEST_REQUIRE_SERVICE", false),
        output_dir,
    }
}

#[cfg(test)]
fn apply_physical_extra_args(config: &mut WeatherTestConfig) {
    let Ok(args) = std::env::var("WEATHER_DEVICE_TEST_ARGS") else {
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
            "--idle-report-min-delay" => set_f64(&mut config.idle_report_min_delay, next_value()),
            "--idle-report-timeout" => set_f64(&mut config.idle_report_timeout, next_value()),
            "--scan-timeout" => set_f64(&mut config.scan_timeout, next_value()),
            "--connect-timeout" => set_f64(&mut config.connect_timeout, next_value()),
            "--connect-attempts" => set_u32(&mut config.connect_attempts, next_value()),
            "--retry-delay" => set_f64(&mut config.retry_delay, next_value()),
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
    let output_dir = std::env::var_os("WEATHER_DEVICE_TEST_RUN_OUTPUT_DIR")
        .or_else(|| std::env::var_os("WEATHER_DEVICE_TEST_OUTPUT_DIR"))
        .map(PathBuf::from)
        .unwrap_or_else(default_output_dir);
    Some(PhysicalTestArtifacts {
        log_path: output_dir.join("cycle.log"),
        output_dir,
    })
}

#[cfg(test)]
fn physical_logs_enabled() -> bool {
    if env_bool("WEATHER_DEVICE_TEST_WRITE_LOGS", false) {
        return true;
    }
    std::env::var_os("WEATHER_DEVICE_TEST_OUTPUT_DIR").is_some()
        || std::env::var_os("WEATHER_DEVICE_TEST_RUN_OUTPUT_DIR").is_some()
        || std::env::var("WEATHER_DEVICE_TEST_ARGS")
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
    result: &Result<WeatherTestSummary>,
) {
    let retries = capture.connect_retries.len();
    let connect_max_ms = capture.connect_ms.iter().max().copied().unwrap_or(0);
    let battery_count = match result {
        Ok(summary) => summary.battery_values.len(),
        Err(_) => capture.battery_mv.len(),
    };
    let weather_count = match result {
        Ok(summary) => summary.weather_values,
        Err(_) => capture.weather_samples,
    };
    if retries > 0 {
        let last_message = capture
            .connect_retries
            .last()
            .map(String::as_str)
            .unwrap_or("connect retry");
        eprintln!(
            "warning: {test_name} index={index} recovered connect retry count={retries} connectMaxMs={connect_max_ms} batterySamples={battery_count} weatherSamples={weather_count} durationMs={duration_ms} last={last_message:?}"
        );
    }
    if let Err(err) = result {
        eprintln!(
            "failure: {test_name} index={index} durationMs={duration_ms} connectRetries={retries} connectMaxMs={connect_max_ms} batterySamples={battery_count} weatherSamples={weather_count} redcon3Rejections={} stage={} message={:?}",
            capture.redcon3_rejections, err.stage, err.message
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
fn field_u128(fields: &std::collections::BTreeMap<String, String>, key: &str) -> Option<u128> {
    fields.get(key).and_then(|value| value.parse().ok())
}

#[cfg(test)]
fn field_u16(fields: &std::collections::BTreeMap<String, String>, key: &str) -> Option<u16> {
    fields.get(key).and_then(|value| value.parse().ok())
}
