use clap::Parser;

fn main() {
    let cli = txing_board_kvs_master::cli::Cli::parse();
    if let Err(err) = txing_board_kvs_master::run(cli.into()) {
        txing_board_kvs_master::emit_marker("TXING_KVS_ERROR", &[("detail", &err.to_string())]);
        std::process::exit(1);
    }
}
