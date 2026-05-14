use anyhow::Result;
use clap::Parser;
use txing_unit_daemon::{Cli, RuntimeConfig, run_runtime};

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    let config = RuntimeConfig::try_from(cli)?;
    run_runtime(config).await
}
