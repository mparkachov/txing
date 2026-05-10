use anyhow::Result;
use clap::Parser;
use txing_ble_connectivity::ble_protocol::ADAPTER_ID;
use txing_ble_connectivity::log_filter::install_greengrass_debug_log_filter;
use txing_ble_connectivity::runtime::{RuntimeConfig, run_component_runtime};

#[derive(Debug, Parser)]
#[command(name = "txing-ble-connectivity")]
#[command(about = "Rig-wide txing BLE connectivity adapter")]
struct Args {
    #[arg(long, env = "TXING_BLE_ADAPTER_ID", default_value = ADAPTER_ID)]
    adapter_id: String,
    #[arg(long, default_value_t = 500)]
    scan_interval_ms: u64,
    #[arg(long, default_value_t = 20_000)]
    presence_timeout_ms: u64,
    #[arg(long, default_value_t = 2_000)]
    reconnect_delay_ms: u64,
    #[arg(long, default_value_t = 8_000)]
    connect_timeout_ms: u64,
    #[arg(long, default_value_t = 8_000)]
    command_timeout_ms: u64,
    #[arg(long, default_value_t = 10_000)]
    heartbeat_interval_ms: u64,
    #[arg(long, default_value_t = 30_000)]
    state_report_interval_ms: u64,
    #[arg(long, default_value_t = 0)]
    max_connections: usize,
    #[arg(long)]
    no_ble: bool,
    #[arg(long)]
    dry_run: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    let config = RuntimeConfig {
        adapter_id: args.adapter_id,
        scan_interval_ms: args.scan_interval_ms,
        presence_timeout_ms: args.presence_timeout_ms,
        reconnect_delay_ms: args.reconnect_delay_ms,
        connect_timeout_ms: args.connect_timeout_ms,
        command_timeout_ms: args.command_timeout_ms,
        heartbeat_interval_ms: args.heartbeat_interval_ms,
        state_report_interval_ms: args.state_report_interval_ms,
        max_connections: args.max_connections,
        no_ble: args.no_ble,
    };

    if args.dry_run {
        println!("component=dev.txing.rig.BleConnectivity");
        println!("adapterId={}", config.adapter_id);
        println!("scanIntervalMs={}", config.scan_interval_ms);
        println!("presenceTimeoutMs={}", config.presence_timeout_ms);
        println!("reconnectDelayMs={}", config.reconnect_delay_ms);
        println!("connectTimeoutMs={}", config.connect_timeout_ms);
        println!("commandTimeoutMs={}", config.command_timeout_ms);
        println!("heartbeatIntervalMs={}", config.heartbeat_interval_ms);
        println!("stateReportIntervalMs={}", config.state_report_interval_ms);
        println!("maxConnections={}", config.max_connections);
        println!("noBle={}", config.no_ble);
        return Ok(());
    }

    install_greengrass_debug_log_filter();
    run_component_runtime(config).await
}
