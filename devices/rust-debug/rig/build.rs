use std::env;
use std::fs;
use std::path::PathBuf;

fn main() {
    println!("cargo:rerun-if-env-changed=RUST_DEBUG_RIG_TEST_REPETITIONS");
    println!("cargo:rerun-if-env-changed=RUST_DEBUG_RIG_TEST_ARGS");

    let repetitions = env::var("RUST_DEBUG_RIG_TEST_REPETITIONS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(1);

    let mut generated = String::new();
    for index in 1..=repetitions {
        let test_name = format!("physical_ble_redcon_{index:03}");
        let test_name_literal = format!("{test_name:?}");
        generated.push_str(&format!(
            r#"
#[tokio::test]
#[ignore = "requires a physical BLE device and host Bluetooth access"]
async fn {test_name}() {{
    run_physical_ble_cycle({test_name_literal}, {index}).await;
}}
"#
        ));
    }

    let out_dir = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR is set by Cargo"));
    fs::write(out_dir.join("physical_ble_tests.rs"), generated)
        .expect("failed to write generated physical BLE tests");
}
