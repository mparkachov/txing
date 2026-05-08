use std::collections::BTreeSet;
use std::env;
use std::fs;
use std::path::PathBuf;

fn main() {
    println!("cargo:rerun-if-env-changed=RUST_DEBUG_RIG_TEST_REPETITIONS");
    println!("cargo:rerun-if-env-changed=RUST_DEBUG_RIG_TEST_PROFILES");
    println!("cargo:rerun-if-env-changed=RUST_DEBUG_RIG_TEST_ARGS");

    let repetitions = env::var("RUST_DEBUG_RIG_TEST_REPETITIONS")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(1);
    let profiles = physical_test_profiles();

    let mut generated = String::new();
    for profile in profiles {
        let suite = sanitize_identifier(&profile);
        for index in 1..=repetitions {
            let test_name = format!("physical_ble_{suite}_{index:03}");
            let test_name_literal = format!("{test_name:?}");
            let profile_literal = format!("{profile:?}");
            generated.push_str(&format!(
                r#"
#[tokio::test]
#[ignore = "requires a physical BLE device and host Bluetooth access"]
async fn {test_name}() {{
    run_physical_ble_cycle({test_name_literal}, {profile_literal}, {index}).await;
}}
"#
            ));
        }
    }

    let out_dir = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR is set by Cargo"));
    fs::write(out_dir.join("physical_ble_tests.rs"), generated)
        .expect("failed to write generated physical BLE tests");
}

fn physical_test_profiles() -> Vec<String> {
    let explicit = env::var("RUST_DEBUG_RIG_TEST_PROFILES")
        .ok()
        .filter(|value| !value.trim().is_empty());
    let raw = explicit.unwrap_or_else(|| {
        profiles_from_args(&env::var("RUST_DEBUG_RIG_TEST_ARGS").unwrap_or_default())
    });
    let mut seen = BTreeSet::new();
    let mut profiles = Vec::new();
    for profile in raw
        .split(',')
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        if seen.insert(profile.to_string()) {
            profiles.push(profile.to_string());
        }
    }
    if profiles.is_empty() {
        profiles.push("fast-50-0-20".to_string());
    }
    profiles
}

fn profiles_from_args(args: &str) -> String {
    let mut profiles = Vec::new();
    let mut tokens = args.split_whitespace();
    while let Some(token) = tokens.next() {
        if let Some(value) = token.strip_prefix("--conn-profile=") {
            profiles.push(value.to_string());
        } else if token == "--conn-profile" {
            if let Some(value) = tokens.next() {
                profiles.push(value.to_string());
            }
        }
    }
    profiles.join(",")
}

fn sanitize_identifier(value: &str) -> String {
    let mut out = String::new();
    for ch in value.chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
        } else {
            out.push('_');
        }
    }
    while out.contains("__") {
        out = out.replace("__", "_");
    }
    let out = out.trim_matches('_').to_string();
    if out.is_empty() {
        "profile".to_string()
    } else {
        out
    }
}
