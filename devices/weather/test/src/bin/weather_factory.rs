use std::path::PathBuf;

use clap::{Parser, Subcommand};
use weather_device_test::error::{Result, RigError};
use weather_device_test::factory::{
    DEFAULT_FACTORY_DATA_ADDRESS, parse_address, validate_device_name, write_factory_hex,
};

#[derive(Debug, Parser)]
#[command(name = "weather-factory")]
#[command(about = "Build REDCON factory/NVE data for txing weather devices")]
struct Args {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    WriteHex {
        device_name: String,
        #[arg(long)]
        output: PathBuf,
        #[arg(long, default_value = "0x000f0000")]
        address: String,
    },
    Validate {
        device_name: String,
    },
}

fn main() {
    if let Err(err) = run() {
        eprintln!("{} {}", err.stage, err.message);
        std::process::exit(2);
    }
}

fn run() -> Result<()> {
    match Args::parse().command {
        Command::WriteHex {
            device_name,
            output,
            address,
        } => {
            let device_name = validate_device_name(&device_name)?;
            let address = if address.trim().is_empty() {
                DEFAULT_FACTORY_DATA_ADDRESS
            } else {
                parse_address(&address)?
            };
            write_factory_hex(&device_name, &output, address).map_err(|err| {
                RigError::new("factory", format!("failed to write factory HEX: {err}"))
            })?;
            println!("wrote {}", output.display());
            println!("address 0x{address:08x}");
            println!("deviceName {device_name}");
        }
        Command::Validate { device_name } => {
            println!("{}", validate_device_name(&device_name)?);
        }
    }
    Ok(())
}
