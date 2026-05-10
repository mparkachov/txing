use anyhow::Result;
use clap::Parser;
use txing_sparkplug_manager::log_filter::install_greengrass_debug_log_filter;
use txing_sparkplug_manager::manager::{device_session_spec, node_client_id, node_session_spec};
use txing_sparkplug_manager::runtime::{RuntimeConfig, run_runtime};

#[derive(Debug, Parser)]
#[command(name = "txing-sparkplug-manager")]
#[command(about = "Rig-wide txing Sparkplug manager")]
struct Args {
    #[arg(long, env = "TXING_RIG_ID")]
    rig_id: String,
    #[arg(long, env = "TXING_TOWN_ID")]
    town_id: String,
    #[arg(long, env = "AWS_IOT_ENDPOINT", default_value = "")]
    iot_endpoint: String,
    #[arg(long, env = "AWS_REGION", default_value = "")]
    aws_region: String,
    #[arg(long, default_value_t = 30)]
    inventory_interval_seconds: u64,
    #[arg(long, default_value_t = 60_000)]
    command_deadline_ms: u64,
    #[arg(long)]
    dry_run: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    let node = node_session_spec(
        &args.town_id,
        &args.rig_id,
        &node_client_id(&args.rig_id),
        0,
        now_ms(),
    )?;
    if args.dry_run {
        let example_device =
            device_session_spec(&args.town_id, &args.rig_id, "example-device", now_ms())?;
        println!("manager=dev.txing.rig.SparkplugManager");
        println!("rigId={}", args.rig_id);
        println!("townId={}", args.town_id);
        println!("awsRegion={}", args.aws_region);
        println!("iotEndpoint={}", args.iot_endpoint);
        println!(
            "inventoryIntervalSeconds={}",
            args.inventory_interval_seconds
        );
        println!("commandDeadlineMs={}", args.command_deadline_ms);
        println!("nodeClientId={}", node.client_id);
        println!("nodeWillTopic={}", node.will.topic);
        println!("deviceClientId={}", example_device.client_id);
        println!("deviceWillTopic={}", example_device.will.topic);
        return Ok(());
    }

    install_greengrass_debug_log_filter();
    run_runtime(RuntimeConfig {
        rig_id: args.rig_id,
        town_id: args.town_id,
        iot_endpoint: args.iot_endpoint,
        aws_region: args.aws_region,
        inventory_interval_seconds: args.inventory_interval_seconds,
        command_deadline_ms: args.command_deadline_ms,
    })
    .await
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("system time is after unix epoch")
        .as_millis() as u64
}
