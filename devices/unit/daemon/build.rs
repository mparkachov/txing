use std::env;
use std::path::PathBuf;

fn main() {
    println!("cargo:rerun-if-env-changed=TXING_DAEMON_BUILD_VERSION");
    let version = env::var("TXING_DAEMON_BUILD_VERSION")
        .unwrap_or_else(|_| env!("CARGO_PKG_VERSION").to_string());
    println!("cargo:rustc-env=TXING_DAEMON_BUILD_VERSION={version}");

    println!("cargo:rerun-if-changed=../proto/txing/unit/board_video/v1/board_video.proto");
    println!("cargo:rerun-if-changed=../proto/txing/unit/hardware/v1/unit_hardware.proto");
    let protoc = protoc_bin_vendored::protoc_bin_path().expect("find vendored protoc");
    unsafe {
        env::set_var("PROTOC", protoc);
    }
    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .compile_protos(
            &[
                PathBuf::from("../proto/txing/unit/board_video/v1/board_video.proto"),
                PathBuf::from("../proto/txing/unit/hardware/v1/unit_hardware.proto"),
            ],
            &[PathBuf::from("../proto")],
        )
        .expect("compile unit daemon protobuf");
}
