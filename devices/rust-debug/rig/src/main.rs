#[tokio::main]
async fn main() {
    if let Err(err) = rust_debug_rig::cli::run().await {
        eprintln!("{} {}", err.stage, err.message);
        std::process::exit(2);
    }
}
