use std::path::PathBuf;

use anyhow::Result;
use clap::Parser;
use txing_rig_local_pubsub::run_broker_until_shutdown;

#[derive(Debug, Parser)]
#[command(name = "txing-rig-local-pubsub")]
#[command(about = "Unix-socket local pub/sub broker for txing rig components")]
struct Args {
    #[arg(long, env = "TXING_RIG_LOCAL_PUBSUB_SOCKET")]
    socket: PathBuf,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    run_broker_until_shutdown(args.socket, async {
        let _ = tokio::signal::ctrl_c().await;
    })
    .await
}
