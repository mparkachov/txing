use anyhow::Result;
use clap::Parser;
use txing_unit_daemon::{
    Cli, RuntimeConfig, init_logging, install_default_crypto_provider, prepare_cloudwatch_logging,
    run_runtime, shutdown_logging,
};

#[tokio::main]
async fn main() -> Result<()> {
    install_default_crypto_provider();
    let cli = Cli::parse();
    let config = RuntimeConfig::from_cli(cli)?;
    let cloudwatch_logging = prepare_cloudwatch_logging(&config).await?;
    let logging = init_logging(&config, cloudwatch_logging)?;
    let result = run_runtime(config).await;
    let shutdown_result = shutdown_logging(logging).await;
    result.and(shutdown_result)
}
