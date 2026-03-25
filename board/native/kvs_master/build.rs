use std::env;
use std::path::PathBuf;

fn main() {
    let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    let force_stub = env::var_os("CARGO_FEATURE_FORCE_STUB_SHIM").is_some();
    let use_real_sdk = target_os == "linux" && !force_stub;

    let mut config = cmake::Config::new("native");
    let out_dir = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR must be set"));
    let open_source_dir = out_dir.join("open-source");

    config
        .define(
            "TXING_KVS_REAL_SDK",
            if use_real_sdk { "ON" } else { "OFF" },
        )
        .define(
            "OPEN_SRC_INSTALL_PREFIX",
            open_source_dir.display().to_string(),
        )
        .profile("Release");

    if let Some(path) = env::var_os("TXING_KVS_WEBRTC_SDK_DIR") {
        config.define(
            "TXING_KVS_WEBRTC_SDK_DIR",
            PathBuf::from(path).display().to_string(),
        );
    }

    let dst = config.build();
    let lib_dir = dst.join("lib");

    println!("cargo:rerun-if-env-changed=TXING_KVS_WEBRTC_SDK_DIR");
    println!("cargo:rerun-if-changed=native/CMakeLists.txt");
    println!("cargo:rerun-if-changed=native/txing_kvs_shim.h");
    println!("cargo:rerun-if-changed=native/txing_kvs_shim.c");
    println!("cargo:rerun-if-changed=native/txing_kvs_shim_stub.c");
    println!("cargo:rustc-link-search=native={}", lib_dir.display());
    println!("cargo:rustc-link-lib=dylib=txing_kvs_shim");

    if cfg!(unix) {
        println!("cargo:rustc-link-arg=-Wl,-rpath,{}", lib_dir.display());
    }
}
