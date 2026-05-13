use anyhow::Result;
use clap::Parser;
use txing_aws_connectivity::retained::ADAPTER_ID;
use txing_aws_connectivity::runtime::{RuntimeConfig, run_component_runtime};

#[derive(Debug, Parser)]
#[command(version, about)]
struct Args {
    #[arg(long, env = "TXING_AWS_CONNECTIVITY_ADAPTER_ID", default_value = ADAPTER_ID)]
    adapter_id: String,

    #[arg(long, env = "AWS_IOT_ENDPOINT", default_value = "")]
    iot_endpoint: String,

    #[arg(long, env = "AWS_REGION", default_value = "")]
    aws_region: String,

    #[arg(long, env = "TXING_AWS_CONNECTIVITY_CLIENT_ID", default_value = "")]
    client_id: String,

    #[arg(long, env = "TXING_RIG_LOCAL_PUBSUB_SOCKET", default_value = "")]
    local_ipc_socket: String,

    #[arg(long = "include-capability")]
    include_capabilities: Vec<String>,

    #[arg(long, default_value_t = 10_000)]
    heartbeat_interval_ms: u64,

    #[arg(long, default_value_t = 10_000)]
    state_report_interval_ms: u64,

    #[arg(long, default_value_t = 60)]
    keep_alive_seconds: u16,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    run_component_runtime(RuntimeConfig {
        adapter_id: args.adapter_id,
        iot_endpoint: args.iot_endpoint,
        aws_region: args.aws_region,
        client_id: args.client_id,
        heartbeat_interval_ms: args.heartbeat_interval_ms,
        state_report_interval_ms: args.state_report_interval_ms,
        keep_alive_seconds: args.keep_alive_seconds,
        local_ipc_socket: args.local_ipc_socket,
        include_capabilities: args.include_capabilities,
    })
    .await
}
