use anyhow::Result;
use clap::Parser;
use txing_ble_connectivity::ble_protocol::ADAPTER_ID;
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
    #[arg(long, default_value_t = 0)]
    max_connections: usize,
    #[arg(long)]
    no_ble: bool,
    #[arg(long, env = "TXING_RIG_LOCAL_PUBSUB_SOCKET", default_value = "")]
    local_ipc_socket: String,
    #[arg(long)]
    dry_run: bool,
    #[arg(long)]
    debug: bool,
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
        max_connections: args.max_connections,
        no_ble: args.no_ble,
        local_ipc_socket: args.local_ipc_socket,
        debug: args.debug || env_flag("TXING_RIG_BLE_DEBUG"),
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
        println!("maxConnections={}", config.max_connections);
        println!("noBle={}", config.no_ble);
        println!("localIpcSocket={}", config.local_ipc_socket);
        println!("debug={}", config.debug);
        return Ok(());
    }

    run_component_runtime(config).await
}

fn env_flag(name: &str) -> bool {
    std::env::var(name).ok().is_some_and(|value| {
        matches!(
            value.as_str(),
            "1" | "true" | "TRUE" | "yes" | "YES" | "on" | "ON"
        )
    })
}
