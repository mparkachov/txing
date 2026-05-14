use anyhow::Result;
use clap::Parser;
use txing_unit_daemon::{Cli, RuntimeConfig, install_default_crypto_provider, run_runtime};

#[tokio::main]
async fn main() -> Result<()> {
    install_default_crypto_provider();
    let cli = Cli::parse();
    let config = RuntimeConfig::from_cli(cli)?;
    run_runtime(config).await
}
