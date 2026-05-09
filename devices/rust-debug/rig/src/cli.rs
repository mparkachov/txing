use std::path::PathBuf;

use clap::{Args, Parser, Subcommand};

use crate::ble::BleCentral;
#[cfg(feature = "ble-real")]
use crate::btleplug_ble::BtleplugBleCentral;
use crate::cycle::{CycleConfig, TimeMode, run_logged_cycle_test};
use crate::error::Result;
#[cfg(not(feature = "ble-real"))]
use crate::error::RigError;
use crate::greengrass::{run_greengrass_component, run_greengrass_doctor, run_mock_component};
use crate::overnight::{Candidate, OvernightConfig, run_overnight};
use crate::sim_ble::SimBleCentral;

#[derive(Debug, Parser)]
#[command(name = "rust-debug-rig")]
#[command(about = "Rust BLE rig experiment for txing rust-debug")]
pub struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    Test(CycleArgs),
    SimTest(CycleArgs),
    Overnight(OvernightArgs),
    SimOvernight(OvernightArgs),
    Component(ComponentArgs),
    MockComponent(ComponentArgs),
    GreengrassDoctor(GreengrassDoctorArgs),
}

#[derive(Debug, Args)]
pub struct CycleArgs {
    #[arg(long, default_value_t = 1)]
    repetitions: u32,
    #[arg(long, default_value = "weather-q8zbgb")]
    name: String,
    #[arg(long, default_value_t = 30.0)]
    wake_seconds: f64,
    #[arg(long, default_value_t = 60.0)]
    cycle_seconds: f64,
    #[arg(long, default_value_t = 3)]
    min_battery: usize,
    #[arg(long, default_value_t = 10.0)]
    wake_deadline: f64,
    #[arg(long, default_value_t = 10.0)]
    sleep_deadline: f64,
    #[arg(long, default_value_t = 60.0)]
    scan_timeout: f64,
    #[arg(long, default_value_t = 30.0)]
    connect_timeout: f64,
    #[arg(long, default_value_t = 3)]
    connect_attempts: u32,
    #[arg(long, default_value_t = 2.0)]
    retry_delay: f64,
    #[arg(long, default_value_t = 5.0)]
    disconnect_deadline: f64,
    #[arg(long)]
    keep_connected_during_sleep: bool,
    #[arg(long)]
    no_require_service: bool,
    #[arg(long)]
    output_dir: Option<PathBuf>,
}

#[derive(Debug, Args)]
pub struct OvernightArgs {
    #[arg(long, default_value = "weather-q8zbgb")]
    name: String,
    #[arg(long)]
    output_dir: Option<PathBuf>,
    #[arg(long, default_value_t = 8.0)]
    duration_hours: f64,
    #[arg(long, default_value_t = 7.0)]
    matrix_hours: f64,
    #[arg(long, default_value_t = 1.0)]
    confirm_hours: f64,
    #[arg(long, default_value_t = 5)]
    trial_cycles: u32,
    #[arg(long, default_value_t = 30.0)]
    wake_seconds: f64,
    #[arg(long, default_value_t = 60.0)]
    cycle_seconds: f64,
    #[arg(long, default_value_t = 3)]
    min_battery: usize,
    #[arg(long, default_value_t = 10.0)]
    wake_deadline: f64,
    #[arg(long, default_value_t = 10.0)]
    sleep_deadline: f64,
    #[arg(long, default_value_t = 10.0)]
    failure_recovery_delay: f64,
    #[arg(long)]
    central_profiles: Option<String>,
    #[arg(long)]
    dry_run: bool,
}

#[derive(Debug, Args)]
pub struct ComponentArgs {
    #[arg(long, default_value = "rust-debug-ble-main")]
    adapter_id: String,
}

#[derive(Debug, Args)]
pub struct GreengrassDoctorArgs {
    #[arg(long)]
    no_connect: bool,
}

pub async fn run() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::Test(args) => {
            run_real_cycle_command(args).await?;
        }
        Command::SimTest(args) => {
            let mut central = SimBleCentral::default();
            run_cycle_command(args, TimeMode::Virtual, &mut central).await?;
        }
        Command::Overnight(args) => {
            run_real_overnight_command(args).await?;
        }
        Command::SimOvernight(args) => {
            let config = overnight_config(args);
            let mut factory = |_candidate: &Candidate| -> Box<dyn BleCentral + Send> {
                Box::new(SimBleCentral::default())
            };
            let _ = run_overnight(config, TimeMode::Virtual, &mut factory).await?;
        }
        Command::Component(args) => {
            run_greengrass_component(&args.adapter_id)?;
        }
        Command::MockComponent(args) => {
            run_mock_component(&args.adapter_id)?;
        }
        Command::GreengrassDoctor(args) => {
            run_greengrass_doctor(args.no_connect)?;
        }
    }
    Ok(())
}

#[cfg(feature = "ble-real")]
async fn run_real_cycle_command(args: CycleArgs) -> Result<()> {
    let mut central = BtleplugBleCentral::new();
    run_cycle_command(args, TimeMode::Real, &mut central).await
}

#[cfg(not(feature = "ble-real"))]
async fn run_real_cycle_command(_args: CycleArgs) -> Result<()> {
    Err(RigError::new(
        "ble",
        "build with --features ble-real to run physical BLE cycle tests",
    ))
}

#[cfg(feature = "ble-real")]
async fn run_real_overnight_command(args: OvernightArgs) -> Result<()> {
    let config = overnight_config(args);
    let mut factory = |_candidate: &Candidate| -> Box<dyn BleCentral + Send> {
        Box::new(BtleplugBleCentral::new())
    };
    let _ = run_overnight(config, TimeMode::Real, &mut factory).await?;
    Ok(())
}

#[cfg(not(feature = "ble-real"))]
async fn run_real_overnight_command(_args: OvernightArgs) -> Result<()> {
    Err(RigError::new(
        "ble",
        "build with --features ble-real to run physical BLE overnight tests",
    ))
}

async fn run_cycle_command(
    args: CycleArgs,
    time_mode: TimeMode,
    central: &mut dyn BleCentral,
) -> Result<()> {
    let output_dir = args.output_dir.clone();
    let mut config = cycle_config(args)?;
    let run = run_logged_cycle_test(central, &mut config, time_mode, output_dir, true).await?;
    println!("log={}", run.log_path.display());
    Ok(())
}

fn cycle_config(args: CycleArgs) -> Result<CycleConfig> {
    let mut config = CycleConfig::default_for_name(args.name)?;
    config.repetitions = args.repetitions;
    config.wake_seconds = args.wake_seconds;
    config.cycle_seconds = args.cycle_seconds;
    config.min_battery = args.min_battery;
    config.wake_deadline = args.wake_deadline;
    config.sleep_deadline = args.sleep_deadline;
    config.scan_timeout = args.scan_timeout;
    config.connect_timeout = args.connect_timeout;
    config.connect_attempts = args.connect_attempts;
    config.retry_delay = args.retry_delay;
    config.disconnect_deadline = args.disconnect_deadline;
    config.keep_connected_during_sleep = args.keep_connected_during_sleep;
    config.require_service = !args.no_require_service;
    Ok(config)
}

fn overnight_config(args: OvernightArgs) -> OvernightConfig {
    OvernightConfig {
        name: args.name,
        output_dir: args.output_dir,
        duration_hours: args.duration_hours,
        matrix_hours: args.matrix_hours,
        confirm_hours: args.confirm_hours,
        trial_cycles: args.trial_cycles,
        wake_seconds: args.wake_seconds,
        cycle_seconds: args.cycle_seconds,
        min_battery: args.min_battery,
        wake_deadline: args.wake_deadline,
        sleep_deadline: args.sleep_deadline,
        failure_recovery_delay: args.failure_recovery_delay,
        central_profiles: args.central_profiles,
        dry_run: args.dry_run,
    }
}
