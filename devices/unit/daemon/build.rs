use std::env;

fn main() {
    println!("cargo:rerun-if-env-changed=TXING_DAEMON_BUILD_VERSION");
    let version = env::var("TXING_DAEMON_BUILD_VERSION")
        .unwrap_or_else(|_| env!("CARGO_PKG_VERSION").to_string());
    println!("cargo:rustc-env=TXING_DAEMON_BUILD_VERSION={version}");
}
