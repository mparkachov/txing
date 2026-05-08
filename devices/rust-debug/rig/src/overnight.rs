use std::cmp::Ordering;
use std::collections::{BTreeMap, VecDeque};
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::json;

use crate::ble::BleCentral;
use crate::cycle::{CycleConfig, TimeMode, run_cycle_test};
use crate::error::{Result, RigError};
use crate::event::{EventEmitter, parse_event_line};
use crate::protocol::{
    CentralProfile, built_in_connection_profiles, default_central_profile_names,
    default_central_profiles, default_connection_profile_names,
};

#[derive(Debug, Clone)]
pub struct OvernightConfig {
    pub name: String,
    pub output_dir: Option<PathBuf>,
    pub duration_hours: f64,
    pub matrix_hours: f64,
    pub confirm_hours: f64,
    pub trial_cycles: u32,
    pub wake_seconds: f64,
    pub cycle_seconds: f64,
    pub min_battery: usize,
    pub wake_deadline: f64,
    pub sleep_deadline: f64,
    pub failure_recovery_delay: f64,
    pub connection_profiles: Option<String>,
    pub central_profiles: Option<String>,
    pub dry_run: bool,
}

#[derive(Debug, Clone)]
pub struct Candidate {
    pub name: String,
    pub conn_profile: String,
    pub central_profile: CentralProfile,
    pub order: usize,
}

#[derive(Debug, Clone, Default)]
pub struct TrialCapture {
    pub passed_cycles: u32,
    pub errors: u32,
    pub unexpected_disconnects: u32,
    pub wake_latencies_ms: Vec<u128>,
    pub connect_ms: Vec<u128>,
    pub rssi_values: Vec<i32>,
    pub failure_stages: BTreeMap<String, u32>,
    pub disconnect_phases: BTreeMap<String, u32>,
}

#[derive(Debug, Clone)]
pub struct TrialResult {
    pub candidate: String,
    pub conn_profile: String,
    pub central_profile: String,
    pub requested_cycles: u32,
    pub passed_cycles: u32,
    pub errors: u32,
    pub unexpected_disconnects: u32,
    pub wake_latencies_ms: Vec<u128>,
    pub connect_ms: Vec<u128>,
    pub rssi_values: Vec<i32>,
    pub failure_stages: BTreeMap<String, u32>,
    pub disconnect_phases: BTreeMap<String, u32>,
    pub success: bool,
    pub error_stage: String,
    pub error_message: String,
    pub failure_stage: String,
    pub elapsed_sec: f64,
}

#[derive(Debug, Clone)]
pub struct CandidateStats {
    pub candidate: Candidate,
    pub trials: u32,
    pub successful_trials: u32,
    pub failed_trials: u32,
    pub requested_cycles: u32,
    pub passed_cycles: u32,
    pub errors: u32,
    pub unexpected_disconnects: u32,
    pub wake_latencies_ms: Vec<u128>,
    pub connect_ms: Vec<u128>,
    pub rssi_values: Vec<i32>,
    pub failure_stages: BTreeMap<String, u32>,
    pub disconnect_phases: BTreeMap<String, u32>,
    pub failed_trial_cycles: Vec<u32>,
}

impl Default for OvernightConfig {
    fn default() -> Self {
        Self {
            name: "weather-q8zbgb".to_string(),
            output_dir: None,
            duration_hours: 8.0,
            matrix_hours: 7.0,
            confirm_hours: 1.0,
            trial_cycles: 5,
            wake_seconds: 30.0,
            cycle_seconds: 60.0,
            min_battery: 3,
            wake_deadline: 10.0,
            sleep_deadline: 10.0,
            failure_recovery_delay: 10.0,
            connection_profiles: None,
            central_profiles: None,
            dry_run: false,
        }
    }
}

impl CandidateStats {
    pub fn new(candidate: Candidate) -> Self {
        Self {
            candidate,
            trials: 0,
            successful_trials: 0,
            failed_trials: 0,
            requested_cycles: 0,
            passed_cycles: 0,
            errors: 0,
            unexpected_disconnects: 0,
            wake_latencies_ms: Vec::new(),
            connect_ms: Vec::new(),
            rssi_values: Vec::new(),
            failure_stages: BTreeMap::new(),
            disconnect_phases: BTreeMap::new(),
            failed_trial_cycles: Vec::new(),
        }
    }

    pub fn record(&mut self, result: TrialResult) {
        self.trials += 1;
        self.requested_cycles += result.requested_cycles;
        self.passed_cycles += result.passed_cycles;
        self.errors += result.errors;
        self.unexpected_disconnects += result.unexpected_disconnects;
        self.wake_latencies_ms.extend(result.wake_latencies_ms);
        self.connect_ms.extend(result.connect_ms);
        self.rssi_values.extend(result.rssi_values);
        merge_counts(&mut self.failure_stages, result.failure_stages);
        merge_counts(&mut self.disconnect_phases, result.disconnect_phases);
        if result.success {
            self.successful_trials += 1;
        } else {
            self.failed_trials += 1;
            self.failed_trial_cycles.push(result.passed_cycles);
            if !result.failure_stage.is_empty() {
                *self.failure_stages.entry(result.failure_stage).or_default() += 1;
            }
        }
    }

    pub fn failure_count(&self) -> u32 {
        self.failed_trials + self.errors + self.unexpected_disconnects
    }

    pub fn pass_ratio(&self) -> f64 {
        if self.requested_cycles == 0 {
            0.0
        } else {
            self.passed_cycles as f64 / self.requested_cycles as f64
        }
    }

    pub fn primary_failure_stage(&self) -> String {
        self.failure_stages
            .iter()
            .max_by_key(|(_, count)| *count)
            .map(|(stage, _)| stage.clone())
            .unwrap_or_default()
    }

    pub fn wake_p95_ms(&self) -> u128 {
        percentile(&self.wake_latencies_ms, 95, 999999)
    }

    pub fn connect_p95_ms(&self) -> u128 {
        percentile(&self.connect_ms, 95, 999999)
    }

    pub fn mean_cycles_before_failure(&self) -> Option<f64> {
        if self.failed_trial_cycles.is_empty() {
            None
        } else {
            Some(
                self.failed_trial_cycles
                    .iter()
                    .map(|value| *value as f64)
                    .sum::<f64>()
                    / self.failed_trial_cycles.len() as f64,
            )
        }
    }

    pub fn to_json(&self) -> serde_json::Value {
        json!({
            "candidate": self.candidate.name,
            "connProfile": self.candidate.conn_profile,
            "centralProfile": self.candidate.central_profile.name,
            "trials": self.trials,
            "successfulTrials": self.successful_trials,
            "failedTrials": self.failed_trials,
            "requestedCycles": self.requested_cycles,
            "passedCycles": self.passed_cycles,
            "passRatio": self.pass_ratio(),
            "errors": self.errors,
            "unexpectedDisconnects": self.unexpected_disconnects,
            "failureStage": null_if_empty(self.primary_failure_stage()),
            "failureStages": self.failure_stages,
            "disconnectPhases": self.disconnect_phases,
            "meanCyclesBeforeFailure": self.mean_cycles_before_failure(),
            "wakeP95Ms": if self.wake_latencies_ms.is_empty() { None } else { Some(self.wake_p95_ms()) },
            "wakeMaxMs": self.wake_latencies_ms.iter().max().copied(),
            "connectP95Ms": if self.connect_ms.is_empty() { None } else { Some(self.connect_p95_ms()) },
            "connectMaxMs": self.connect_ms.iter().max().copied(),
            "rssiMin": self.rssi_values.iter().min().copied(),
            "rssiAvg": rssi_avg(&self.rssi_values),
            "rssiMax": self.rssi_values.iter().max().copied(),
        })
    }
}

pub type CentralFactory = dyn FnMut(&Candidate) -> Box<dyn BleCentral + Send>;

pub async fn run_overnight(
    config: OvernightConfig,
    time_mode: TimeMode,
    central_factory: &mut CentralFactory,
) -> Result<PathBuf> {
    if config.failure_recovery_delay < 0.0 {
        return Err(RigError::args(
            "failure-recovery-delay must be zero or greater",
        ));
    }
    let output_dir = config.output_dir.clone().unwrap_or_else(default_output_dir);
    std::fs::create_dir_all(&output_dir)
        .map_err(|err| RigError::new("overnight", format!("failed to create output dir: {err}")))?;
    let file = Arc::new(Mutex::new(
        File::create(output_dir.join("overnight.log"))
            .map_err(|err| RigError::new("overnight", err.to_string()))?,
    ));

    let candidates = build_candidates(&config)?;
    let mut stats_by_candidate: BTreeMap<String, CandidateStats> = candidates
        .iter()
        .cloned()
        .map(|candidate| (candidate.name.clone(), CandidateStats::new(candidate)))
        .collect();
    let mut best: Option<String> = None;

    let mut events = emitter_with_file(file.clone());
    events.emit(
        "starting",
        &[
            ("command", "overnight".to_string()),
            ("name", config.name.clone()),
            ("outputDir", output_dir.display().to_string()),
            ("durationHours", config.duration_hours.to_string()),
            ("matrixHours", config.matrix_hours.to_string()),
            ("confirmHours", config.confirm_hours.to_string()),
            ("trialCycles", config.trial_cycles.to_string()),
            (
                "failureRecoveryDelay",
                config.failure_recovery_delay.to_string(),
            ),
            ("candidates", candidates.len().to_string()),
        ],
    );
    for candidate in &candidates {
        events.emit(
            "matrix-candidate",
            &[
                ("candidate", candidate.name.clone()),
                ("connProfile", candidate.conn_profile.clone()),
                ("centralProfile", candidate.central_profile.name.clone()),
                (
                    "scanTimeout",
                    candidate.central_profile.scan_timeout.to_string(),
                ),
                (
                    "connectTimeout",
                    candidate.central_profile.connect_timeout.to_string(),
                ),
                (
                    "connectAttempts",
                    candidate.central_profile.connect_attempts.to_string(),
                ),
                (
                    "retryDelay",
                    candidate.central_profile.retry_delay.to_string(),
                ),
                (
                    "disconnectDeadline",
                    candidate.central_profile.disconnect_deadline.to_string(),
                ),
                (
                    "requireService",
                    if candidate.central_profile.require_service {
                        "1"
                    } else {
                        "0"
                    }
                    .to_string(),
                ),
            ],
        );
    }
    write_outputs(
        &output_dir,
        &config,
        &candidates,
        &stats_by_candidate,
        best.as_deref(),
        "planned",
    )?;
    if config.dry_run {
        write_outputs(
            &output_dir,
            &config,
            &candidates,
            &stats_by_candidate,
            best.as_deref(),
            "dry-run",
        )?;
        events.emit(
            "summary",
            &[
                ("command", "overnight".to_string()),
                ("phase", "dry-run".to_string()),
                ("outputDir", output_dir.display().to_string()),
            ],
        );
        return Ok(output_dir);
    }

    match time_mode {
        TimeMode::Virtual => {
            run_virtual_matrix(
                &config,
                &candidates,
                &mut stats_by_candidate,
                &mut best,
                file.clone(),
                central_factory,
            )
            .await?;
        }
        TimeMode::Real => {
            run_real_matrix(
                &config,
                &candidates,
                &mut stats_by_candidate,
                &mut best,
                file.clone(),
                central_factory,
            )
            .await?;
        }
    }

    write_outputs(
        &output_dir,
        &config,
        &candidates,
        &stats_by_candidate,
        best.as_deref(),
        "complete",
    )?;
    let mut events = emitter_with_file(file);
    events.emit(
        "summary",
        &[
            ("command", "overnight".to_string()),
            ("outputDir", output_dir.display().to_string()),
            ("report", output_dir.join("report.md").display().to_string()),
            (
                "summaryJson",
                output_dir.join("summary.json").display().to_string(),
            ),
            ("best", best.unwrap_or_default()),
        ],
    );
    Ok(output_dir)
}

async fn run_virtual_matrix(
    config: &OvernightConfig,
    candidates: &[Candidate],
    stats_by_candidate: &mut BTreeMap<String, CandidateStats>,
    best: &mut Option<String>,
    file: Arc<Mutex<File>>,
    central_factory: &mut CentralFactory,
) -> Result<()> {
    let total_cycles = ((config.duration_hours * 3600.0) / config.cycle_seconds).floor() as u32;
    let confirm_cycles = ((config.confirm_hours * 3600.0) / config.cycle_seconds).floor() as u32;
    let matrix_cycles = (((config.matrix_hours * 3600.0) / config.cycle_seconds).floor() as u32)
        .min(total_cycles.saturating_sub(confirm_cycles));
    let trial_count = matrix_cycles / config.trial_cycles.max(1);
    let mut queue: VecDeque<Candidate> = candidates.iter().cloned().collect();
    for _ in 0..trial_count {
        let Some(candidate) = queue.pop_front() else {
            break;
        };
        queue.push_back(candidate.clone());
        let result = run_trial(
            config,
            &candidate,
            config.trial_cycles,
            "matrix",
            TimeMode::Virtual,
            file.clone(),
            central_factory,
        )
        .await;
        stats_by_candidate
            .get_mut(&candidate.name)
            .expect("candidate stats exist")
            .record(result);
        *best = choose_best(stats_by_candidate).map(|stats| stats.candidate.name.clone());
    }
    confirm_best(
        config,
        stats_by_candidate,
        best,
        confirm_cycles,
        file,
        central_factory,
        TimeMode::Virtual,
    )
    .await
}

async fn run_real_matrix(
    config: &OvernightConfig,
    candidates: &[Candidate],
    stats_by_candidate: &mut BTreeMap<String, CandidateStats>,
    best: &mut Option<String>,
    file: Arc<Mutex<File>>,
    central_factory: &mut CentralFactory,
) -> Result<()> {
    let started = Instant::now();
    let total_seconds = config.duration_hours * 3600.0;
    let matrix_seconds = (config.matrix_hours * 3600.0)
        .min((total_seconds - config.confirm_hours * 3600.0).max(0.0));
    let matrix_deadline =
        started + Duration::from_secs_f64(matrix_seconds.max(config.cycle_seconds));
    let overall_deadline =
        started + Duration::from_secs_f64(total_seconds.max(config.cycle_seconds));
    let mut candidate_index = 0usize;
    while Instant::now()
        + Duration::from_secs_f64(config.trial_cycles as f64 * config.cycle_seconds)
        <= matrix_deadline
        && !candidates.is_empty()
    {
        let candidate = candidates[candidate_index % candidates.len()].clone();
        let result = run_trial(
            config,
            &candidate,
            config.trial_cycles,
            "matrix",
            TimeMode::Real,
            file.clone(),
            central_factory,
        )
        .await;
        let failed = !result.success;
        stats_by_candidate
            .get_mut(&candidate.name)
            .expect("candidate stats exist")
            .record(result);
        *best = choose_best(stats_by_candidate).map(|stats| stats.candidate.name.clone());
        if failed && config.failure_recovery_delay > 0.0 {
            tokio::time::sleep(Duration::from_secs_f64(config.failure_recovery_delay)).await;
        }
        candidate_index += 1;
    }
    let remaining_cycles = ((overall_deadline
        .saturating_duration_since(Instant::now())
        .as_secs_f64())
        / config.cycle_seconds)
        .floor() as u32;
    confirm_best(
        config,
        stats_by_candidate,
        best,
        remaining_cycles,
        file,
        central_factory,
        TimeMode::Real,
    )
    .await
}

async fn confirm_best(
    config: &OvernightConfig,
    stats_by_candidate: &mut BTreeMap<String, CandidateStats>,
    best: &mut Option<String>,
    confirm_cycles: u32,
    file: Arc<Mutex<File>>,
    central_factory: &mut CentralFactory,
    time_mode: TimeMode,
) -> Result<()> {
    let selected = best
        .clone()
        .or_else(|| stats_by_candidate.keys().next().cloned());
    let Some(candidate_name) = selected else {
        return Ok(());
    };
    let candidate = stats_by_candidate
        .get(&candidate_name)
        .expect("selected candidate exists")
        .candidate
        .clone();
    let mut events = emitter_with_file(file.clone());
    events.emit(
        "confirm-selected",
        &[
            ("candidate", candidate.name.clone()),
            ("connProfile", candidate.conn_profile.clone()),
            ("centralProfile", candidate.central_profile.name.clone()),
        ],
    );
    if confirm_cycles > 0 {
        let result = run_trial(
            config,
            &candidate,
            confirm_cycles,
            "confirm",
            time_mode,
            file,
            central_factory,
        )
        .await;
        stats_by_candidate
            .get_mut(&candidate.name)
            .expect("candidate stats exist")
            .record(result);
        *best = choose_best(stats_by_candidate).map(|stats| stats.candidate.name.clone());
    }
    Ok(())
}

async fn run_trial(
    config: &OvernightConfig,
    candidate: &Candidate,
    cycles: u32,
    phase: &str,
    time_mode: TimeMode,
    file: Arc<Mutex<File>>,
    central_factory: &mut CentralFactory,
) -> TrialResult {
    let capture = Arc::new(Mutex::new(TrialCapture::default()));
    let mut events = emitter_with_file(file);
    let capture_sink = capture.clone();
    events.add_sink(move |line| {
        if let Ok(mut capture) = capture_sink.lock() {
            capture.record_line(line);
        }
    });
    let started = Instant::now();
    let mut success = false;
    let mut error_stage = String::new();
    let mut error_message = String::new();
    events.emit(
        "trial-start",
        &[
            ("phase", phase.to_string()),
            ("candidate", candidate.name.clone()),
            ("connProfile", candidate.conn_profile.clone()),
            ("centralProfile", candidate.central_profile.name.clone()),
            ("cycles", cycles.to_string()),
            (
                "scanTimeout",
                candidate.central_profile.scan_timeout.to_string(),
            ),
            (
                "connectTimeout",
                candidate.central_profile.connect_timeout.to_string(),
            ),
            (
                "connectAttempts",
                candidate.central_profile.connect_attempts.to_string(),
            ),
            (
                "retryDelay",
                candidate.central_profile.retry_delay.to_string(),
            ),
            (
                "disconnectDeadline",
                candidate.central_profile.disconnect_deadline.to_string(),
            ),
            (
                "requireService",
                if candidate.central_profile.require_service {
                    "1"
                } else {
                    "0"
                }
                .to_string(),
            ),
        ],
    );
    let mut central = central_factory(candidate);
    let mut cycle_config = cycle_args_for_candidate(config, candidate, cycles);
    match run_cycle_test(central.as_mut(), &mut cycle_config, time_mode, &mut events).await {
        Ok(_) => success = true,
        Err(err) => {
            error_stage = err.stage;
            error_message = err.message;
            events.emit(
                "error",
                &[
                    ("stage", error_stage.clone()),
                    ("message", error_message.clone()),
                ],
            );
        }
    }
    let capture = capture.lock().expect("capture lock").clone();
    let mut failure_stage = if !error_stage.is_empty() || !error_message.is_empty() {
        normalize_failure_stage(&error_stage, &error_message)
    } else {
        capture
            .failure_stages
            .iter()
            .max_by_key(|(_, count)| *count)
            .map(|(stage, _)| stage.clone())
            .unwrap_or_default()
    };
    if success
        && (capture.errors > 0
            || capture.unexpected_disconnects > 0
            || capture.passed_cycles < cycles)
    {
        success = false;
        if failure_stage.is_empty() {
            failure_stage = "incomplete".to_string();
        }
    }
    let result = TrialResult {
        candidate: candidate.name.clone(),
        conn_profile: candidate.conn_profile.clone(),
        central_profile: candidate.central_profile.name.clone(),
        requested_cycles: cycles,
        passed_cycles: capture.passed_cycles,
        errors: capture.errors,
        unexpected_disconnects: capture.unexpected_disconnects,
        wake_latencies_ms: capture.wake_latencies_ms,
        connect_ms: capture.connect_ms,
        rssi_values: capture.rssi_values,
        failure_stages: capture.failure_stages,
        disconnect_phases: capture.disconnect_phases,
        success,
        error_stage,
        error_message,
        failure_stage,
        elapsed_sec: started.elapsed().as_secs_f64(),
    };
    events.emit(
        "trial-summary",
        &[
            ("phase", phase.to_string()),
            ("candidate", result.candidate.clone()),
            ("connProfile", result.conn_profile.clone()),
            ("centralProfile", result.central_profile.clone()),
            (
                "success",
                if result.success { "1" } else { "0" }.to_string(),
            ),
            ("requestedCycles", result.requested_cycles.to_string()),
            ("passedCycles", result.passed_cycles.to_string()),
            ("errors", result.errors.to_string()),
            (
                "unexpectedDisconnects",
                result.unexpected_disconnects.to_string(),
            ),
            (
                "wakeP95Ms",
                percentile(&result.wake_latencies_ms, 95, 0).to_string(),
            ),
            (
                "connectP95Ms",
                percentile(&result.connect_ms, 95, 0).to_string(),
            ),
            ("failureStage", result.failure_stage.clone()),
            ("elapsedSec", (result.elapsed_sec as u64).to_string()),
            ("message", result.error_message.clone()),
        ],
    );
    result
}

impl TrialCapture {
    fn record_line(&mut self, line: &str) {
        let (event, fields_vec) = parse_event_line(line);
        let fields: BTreeMap<String, String> = fields_vec.into_iter().collect();
        match event.as_str() {
            "summary" if fields.get("command").map(String::as_str) == Some("cycle") => {
                self.passed_cycles += 1;
            }
            "adv" => {
                append_i32(&mut self.rssi_values, fields.get("rssi"));
            }
            "wake-ok" => {
                append_u128(&mut self.wake_latencies_ms, fields.get("latencyMs"));
            }
            "connected" => {
                append_u128(&mut self.connect_ms, fields.get("connectMs"));
            }
            "disconnect" if fields.get("unexpected").map(String::as_str) == Some("1") => {
                self.unexpected_disconnects += 1;
                let phase = fields
                    .get("phase")
                    .cloned()
                    .unwrap_or_else(|| "unknown".to_string());
                *self.disconnect_phases.entry(phase).or_default() += 1;
            }
            "error" => {
                self.errors += 1;
                let stage = normalize_failure_stage(
                    fields.get("stage").map(String::as_str).unwrap_or_default(),
                    fields
                        .get("message")
                        .map(String::as_str)
                        .unwrap_or_default(),
                );
                *self.failure_stages.entry(stage).or_default() += 1;
            }
            _ => {}
        }
    }
}

fn cycle_args_for_candidate(
    args: &OvernightConfig,
    candidate: &Candidate,
    cycles: u32,
) -> CycleConfig {
    let mut config = CycleConfig::default_for_name(&args.name).expect("default config valid");
    config.repetitions = cycles;
    config.wake_seconds = args.wake_seconds;
    config.cycle_seconds = args.cycle_seconds;
    config.min_battery = args.min_battery;
    config.wake_deadline = args.wake_deadline;
    config.sleep_deadline = args.sleep_deadline;
    config.scan_timeout = candidate.central_profile.scan_timeout;
    config.connect_timeout = candidate.central_profile.connect_timeout;
    config.connect_attempts = candidate.central_profile.connect_attempts;
    config.retry_delay = candidate.central_profile.retry_delay;
    config.disconnect_deadline = candidate.central_profile.disconnect_deadline;
    config.keep_connected_during_sleep = false;
    config.require_service = candidate.central_profile.require_service;
    config.conn_profile = vec![candidate.conn_profile.clone()];
    config
}

pub fn build_candidates(args: &OvernightConfig) -> Result<Vec<Candidate>> {
    let connection_profiles = parse_csv(
        args.connection_profiles.as_deref(),
        default_connection_profile_names(),
    );
    let built_ins = built_in_connection_profiles();
    let unknown: Vec<String> = connection_profiles
        .iter()
        .filter(|name| !built_ins.contains_key(name.as_str()))
        .cloned()
        .collect();
    if !unknown.is_empty() {
        return Err(RigError::args(format!(
            "unknown connection profile(s): {}. Options: {}",
            unknown.join(", "),
            built_ins.keys().copied().collect::<Vec<_>>().join(", ")
        )));
    }

    let central_profiles = default_central_profiles();
    let central_by_name: BTreeMap<String, CentralProfile> = central_profiles
        .into_iter()
        .map(|profile| (profile.name.clone(), profile))
        .collect();
    let requested_central = parse_csv(
        args.central_profiles.as_deref(),
        default_central_profile_names(),
    );
    let unknown_central: Vec<String> = requested_central
        .iter()
        .filter(|name| !central_by_name.contains_key(*name))
        .cloned()
        .collect();
    if !unknown_central.is_empty() {
        return Err(RigError::args(format!(
            "unknown central profile(s): {}. Options: {}",
            unknown_central.join(", "),
            central_by_name
                .keys()
                .cloned()
                .collect::<Vec<_>>()
                .join(", ")
        )));
    }

    let mut candidates = Vec::new();
    let mut order = 0usize;
    for conn_profile in connection_profiles {
        for central_name in &requested_central {
            let central_profile = central_by_name
                .get(central_name)
                .expect("central profile validated")
                .clone();
            candidates.push(Candidate {
                name: format!("{}+{}", conn_profile, central_profile.name),
                conn_profile: conn_profile.clone(),
                central_profile,
                order,
            });
            order += 1;
        }
    }
    Ok(candidates)
}

fn parse_csv(value: Option<&str>, defaults: Vec<String>) -> Vec<String> {
    let Some(value) = value else {
        return defaults;
    };
    let parsed: Vec<String> = value
        .split(',')
        .map(str::trim)
        .filter(|part| !part.is_empty())
        .map(str::to_string)
        .collect();
    if parsed.is_empty() { defaults } else { parsed }
}

fn choose_best(stats_by_candidate: &BTreeMap<String, CandidateStats>) -> Option<&CandidateStats> {
    stats_by_candidate
        .values()
        .filter(|stats| stats.trials > 0)
        .min_by(|left, right| compare_stats(left, right))
}

fn sorted_tested(stats_by_candidate: &BTreeMap<String, CandidateStats>) -> Vec<&CandidateStats> {
    let mut stats: Vec<&CandidateStats> = stats_by_candidate
        .values()
        .filter(|stats| stats.trials > 0)
        .collect();
    stats.sort_by(|left, right| compare_stats(left, right));
    stats
}

fn sorted_untested(stats_by_candidate: &BTreeMap<String, CandidateStats>) -> Vec<&CandidateStats> {
    let mut stats: Vec<&CandidateStats> = stats_by_candidate
        .values()
        .filter(|stats| stats.trials == 0)
        .collect();
    stats.sort_by_key(|stats| stats.candidate.order);
    stats
}

fn compare_stats(left: &CandidateStats, right: &CandidateStats) -> Ordering {
    let left_failed = left.failure_count() > 0 || left.passed_cycles < left.requested_cycles;
    let right_failed = right.failure_count() > 0 || right.passed_cycles < right.requested_cycles;
    left_failed
        .cmp(&right_failed)
        .then_with(|| {
            right
                .pass_ratio()
                .partial_cmp(&left.pass_ratio())
                .unwrap_or(Ordering::Equal)
        })
        .then_with(|| {
            left.unexpected_disconnects
                .cmp(&right.unexpected_disconnects)
        })
        .then_with(|| left.errors.cmp(&right.errors))
        .then_with(|| left.failed_trials.cmp(&right.failed_trials))
        .then_with(|| right.passed_cycles.cmp(&left.passed_cycles))
        .then_with(|| left.wake_p95_ms().cmp(&right.wake_p95_ms()))
        .then_with(|| left.connect_p95_ms().cmp(&right.connect_p95_ms()))
        .then_with(|| left.candidate.order.cmp(&right.candidate.order))
}

fn write_outputs(
    output_dir: &PathBuf,
    args: &OvernightConfig,
    candidates: &[Candidate],
    stats_by_candidate: &BTreeMap<String, CandidateStats>,
    best: Option<&str>,
    phase: &str,
) -> Result<()> {
    let best_stats = best.and_then(|name| stats_by_candidate.get(name));
    let summary = json!({
        "phase": phase,
        "generatedAtMs": now_ms(),
        "args": {
            "name": args.name,
            "durationHours": args.duration_hours,
            "matrixHours": args.matrix_hours,
            "confirmHours": args.confirm_hours,
            "trialCycles": args.trial_cycles,
            "wakeSeconds": args.wake_seconds,
            "cycleSeconds": args.cycle_seconds,
            "minBattery": args.min_battery,
            "wakeDeadline": args.wake_deadline,
            "sleepDeadline": args.sleep_deadline,
            "failureRecoveryDelay": args.failure_recovery_delay,
        },
        "candidates": candidates.iter().map(|candidate| json!({
            "name": candidate.name,
            "connProfile": candidate.conn_profile,
            "centralProfile": {
                "name": candidate.central_profile.name,
                "scanTimeout": candidate.central_profile.scan_timeout,
                "connectTimeout": candidate.central_profile.connect_timeout,
                "connectAttempts": candidate.central_profile.connect_attempts,
                "retryDelay": candidate.central_profile.retry_delay,
                "disconnectDeadline": candidate.central_profile.disconnect_deadline,
                "requireService": candidate.central_profile.require_service,
            },
        })).collect::<Vec<_>>(),
        "best": best_stats.map(CandidateStats::to_json),
        "testedStats": sorted_tested(stats_by_candidate).iter().map(|stats| stats.to_json()).collect::<Vec<_>>(),
        "untestedStats": sorted_untested(stats_by_candidate).iter().map(|stats| stats.to_json()).collect::<Vec<_>>(),
        "stats": stats_by_candidate.values().map(CandidateStats::to_json).collect::<Vec<_>>(),
    });
    std::fs::write(
        output_dir.join("summary.json"),
        serde_json::to_string_pretty(&summary)
            .map_err(|err| RigError::new("overnight", err.to_string()))?
            + "\n",
    )
    .map_err(|err| RigError::new("overnight", err.to_string()))?;
    write_report(output_dir, best_stats, stats_by_candidate)?;
    Ok(())
}

fn write_report(
    output_dir: &PathBuf,
    best: Option<&CandidateStats>,
    stats_by_candidate: &BTreeMap<String, CandidateStats>,
) -> Result<()> {
    let mut lines = vec![
        "# Rust Debug Overnight Report".to_string(),
        String::new(),
        format!("- Log: `{}`", output_dir.join("overnight.log").display()),
        format!(
            "- Summary JSON: `{}`",
            output_dir.join("summary.json").display()
        ),
        String::new(),
    ];
    if let Some(best) = best {
        lines.extend([
            "## Selected Candidate".to_string(),
            String::new(),
            format!("- Candidate: `{}`", best.candidate.name),
            format!("- Connection profile: `{}`", best.candidate.conn_profile),
            format!(
                "- Central profile: `{}`",
                best.candidate.central_profile.name
            ),
            format!("- Passed cycles: `{}`", best.passed_cycles),
            format!("- Pass ratio: `{:.2}`", best.pass_ratio()),
            format!("- Failed trials: `{}`", best.failed_trials),
            format!(
                "- Unexpected disconnects: `{}`",
                best.unexpected_disconnects
            ),
            format!(
                "- Primary failure stage: `{}`",
                null_text(best.primary_failure_stage())
            ),
            format!(
                "- Wake p95 ms: `{}`",
                if best.wake_latencies_ms.is_empty() {
                    "n/a".to_string()
                } else {
                    best.wake_p95_ms().to_string()
                }
            ),
            format!(
                "- Connect p95 ms: `{}`",
                if best.connect_ms.is_empty() {
                    "n/a".to_string()
                } else {
                    best.connect_p95_ms().to_string()
                }
            ),
            String::new(),
        ]);
    } else {
        lines.extend(["No candidate completed a trial.".to_string(), String::new()]);
    }

    lines.extend([
        "## Ranked Tested Candidates".to_string(),
        String::new(),
        "| Candidate | Trials | Pass ratio | Passed / Requested | Failed trials | Errors | Unexpected disconnects | Failure stage | Wake p95 | Connect p95 | RSSI avg (min..max) |".to_string(),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |".to_string(),
    ]);
    let tested = sorted_tested(stats_by_candidate);
    if tested.is_empty() {
        lines.push("| n/a | 0 | 0.00 | 0 / 0 | 0 | 0 | 0 | n/a | n/a | n/a | n/a |".to_string());
    }
    for stats in tested {
        lines.push(format!(
            "| `{}` | {} | {:.2} | {} / {} | {} | {} | {} | {} | {} | {} | {} |",
            stats.candidate.name,
            stats.trials,
            stats.pass_ratio(),
            stats.passed_cycles,
            stats.requested_cycles,
            stats.failed_trials,
            stats.errors,
            stats.unexpected_disconnects,
            null_text(stats.primary_failure_stage()),
            if stats.wake_latencies_ms.is_empty() {
                "n/a".to_string()
            } else {
                stats.wake_p95_ms().to_string()
            },
            if stats.connect_ms.is_empty() {
                "n/a".to_string()
            } else {
                stats.connect_p95_ms().to_string()
            },
            format_rssi(stats),
        ));
    }
    let untested = sorted_untested(stats_by_candidate);
    if !untested.is_empty() {
        lines.extend([
            String::new(),
            "## Untested Candidates".to_string(),
            String::new(),
            "| Candidate | Connection profile | Central profile |".to_string(),
            "| --- | --- | --- |".to_string(),
        ]);
        for stats in untested {
            lines.push(format!(
                "| `{}` | `{}` | `{}` |",
                stats.candidate.name,
                stats.candidate.conn_profile,
                stats.candidate.central_profile.name
            ));
        }
    }
    std::fs::write(output_dir.join("report.md"), lines.join("\n"))
        .map_err(|err| RigError::new("overnight", err.to_string()))?;
    Ok(())
}

fn emitter_with_file(file: Arc<Mutex<File>>) -> EventEmitter {
    let mut events = EventEmitter::stdout();
    events.add_sink(move |line| {
        if let Ok(mut file) = file.lock() {
            let _ = writeln!(file, "{line}");
            let _ = file.flush();
        }
    });
    events
}

fn append_u128(values: &mut Vec<u128>, raw: Option<&String>) {
    if let Some(value) = raw.and_then(|value| value.parse().ok()) {
        values.push(value);
    }
}

fn append_i32(values: &mut Vec<i32>, raw: Option<&String>) {
    if let Some(value) = raw.and_then(|value| value.parse().ok()) {
        values.push(value);
    }
}

fn normalize_failure_stage(stage: &str, message: &str) -> String {
    let mut raw_stage = stage.trim().to_lowercase();
    if raw_stage.starts_with("cycle ") && raw_stage.contains(": ") {
        raw_stage = raw_stage
            .split_once(": ")
            .map(|(_, suffix)| suffix.to_string())
            .unwrap_or(raw_stage);
    }
    let raw_message = message.trim().to_lowercase();
    if raw_stage.contains("active") || raw_message.contains("active battery") {
        "active".to_string()
    } else if raw_stage.contains("wake") {
        "wake".to_string()
    } else if raw_stage.contains("sleep") || raw_message.contains("redcon 4") {
        "sleep".to_string()
    } else if raw_stage.contains("battery") {
        "battery".to_string()
    } else if raw_stage.contains("discover") || raw_message.contains("advertisement") {
        "discover".to_string()
    } else if raw_stage.contains("connect")
        || raw_stage.contains("services")
        || raw_message.contains("failed to discover services")
        || raw_message.contains("timeout")
    {
        "connect".to_string()
    } else if raw_stage.contains("disconnect") || raw_message.contains("unexpected disconnect") {
        "disconnect".to_string()
    } else if raw_stage.is_empty() {
        "unknown".to_string()
    } else {
        raw_stage
    }
}

fn percentile(values: &[u128], pct: u32, default: u128) -> u128 {
    if values.is_empty() {
        return default;
    }
    let mut ordered = values.to_vec();
    ordered.sort_unstable();
    let index = ((pct as f64 / 100.0) * (ordered.len().saturating_sub(1)) as f64).round() as usize;
    ordered[index.min(ordered.len() - 1)]
}

fn merge_counts(target: &mut BTreeMap<String, u32>, source: BTreeMap<String, u32>) {
    for (key, value) in source {
        *target.entry(key).or_default() += value;
    }
}

fn rssi_avg(values: &[i32]) -> Option<f64> {
    if values.is_empty() {
        None
    } else {
        Some(values.iter().map(|value| *value as f64).sum::<f64>() / values.len() as f64)
    }
}

fn format_rssi(stats: &CandidateStats) -> String {
    match (
        rssi_avg(&stats.rssi_values),
        stats.rssi_values.iter().min(),
        stats.rssi_values.iter().max(),
    ) {
        (Some(avg), Some(min), Some(max)) => format!("{avg:.1} ({min}..{max})"),
        _ => "n/a".to_string(),
    }
}

fn null_if_empty(value: String) -> serde_json::Value {
    if value.is_empty() {
        serde_json::Value::Null
    } else {
        serde_json::Value::String(value)
    }
}

fn null_text(value: String) -> String {
    if value.is_empty() {
        "n/a".to_string()
    } else {
        value
    }
}

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

fn default_output_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("target")
        .join("rust-debug-overnight-results")
        .join(now_ms().to_string())
}
