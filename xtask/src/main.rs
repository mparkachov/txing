use std::env;
use std::fs;
use std::path::Path;
use std::process::{Command, ExitCode};

const BIN_NAME: &str = "txing";
const UF2_BASE: &str = "0x27000";
const UF2_FAMILY: &str = "0xADA52840";
const TARGET_TRIPLE: &str = "thumbv7em-none-eabihf";
const UF2_MOUNT_DIR: &str = "/Volumes/XIAO-SENSE";

fn main() -> ExitCode {
    let mut args = env::args().skip(1);
    let cmd = args.next().unwrap_or_else(|| "uf2".to_string());

    let workspace_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("xtask should live under workspace root");

    match cmd.as_str() {
        "build" => to_exit_code(run_build(workspace_root)),
        "bin" => to_exit_code(run_bin(workspace_root)),
        "uf2" => to_exit_code(run_uf2(workspace_root)),
        "flash" => to_exit_code(run_flash(workspace_root)),
        _ => {
            eprintln!("unknown command: {cmd}");
            eprintln!("usage: cargo fw [build|bin|uf2|flash]");
            ExitCode::from(2)
        }
    }
}

fn to_exit_code(ok: bool) -> ExitCode {
    if ok {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    }
}

fn run_build(workspace_root: &Path) -> bool {
    run(
        workspace_root,
        "cargo",
        ["build", "--release"].as_slice(),
    )
}

fn run_bin(workspace_root: &Path) -> bool {
    if !run_build(workspace_root) {
        return false;
    }

    let artifacts_dir = workspace_root.join("target").join(TARGET_TRIPLE).join("release");
    if let Err(err) = fs::create_dir_all(&artifacts_dir) {
        eprintln!("failed to create artifacts directory: {err}");
        return false;
    }
    let bin_path = artifacts_dir.join(format!("{BIN_NAME}.bin"));

    run(
        workspace_root,
        "cargo",
        [
            "objcopy",
            "--release",
            "--",
            "-O",
            "binary",
            &bin_path.display().to_string(),
        ]
        .as_slice(),
    )
}

fn run_uf2(workspace_root: &Path) -> bool {
    if !run_bin(workspace_root) {
        return false;
    }

    let artifacts_dir = workspace_root.join("target").join(TARGET_TRIPLE).join("release");
    let bin_path = artifacts_dir.join(format!("{BIN_NAME}.bin"));
    let uf2_path = artifacts_dir.join(format!("{BIN_NAME}.uf2"));

    run(
        workspace_root,
        "uf2conv",
        [
            &bin_path.display().to_string(),
            "--base",
            UF2_BASE,
            "--family",
            UF2_FAMILY,
            "--output",
            &uf2_path.display().to_string(),
        ]
        .as_slice(),
    )
}

fn run_flash(workspace_root: &Path) -> bool {
    if !run_uf2(workspace_root) {
        return false;
    }

    let artifacts_dir = workspace_root.join("target").join(TARGET_TRIPLE).join("release");
    let uf2_path = artifacts_dir.join(format!("{BIN_NAME}.uf2"));
    let mount_dir = Path::new(UF2_MOUNT_DIR);
    let destination = mount_dir.join(format!("{BIN_NAME}.uf2"));

    if !mount_dir.exists() {
        eprintln!("mount point not found: {}", mount_dir.display());
        return false;
    }

    println!("> cp {} {}", uf2_path.display(), destination.display());
    match fs::copy(&uf2_path, &destination) {
        Ok(_) => true,
        Err(err) => {
            eprintln!("failed to copy UF2: {err}");
            false
        }
    }
}

fn run(workspace_root: &Path, program: &str, args: &[&str]) -> bool {
    println!("> {} {}", program, args.join(" "));
    match Command::new(program)
        .args(args)
        .current_dir(workspace_root)
        .status()
    {
        Ok(status) if status.success() => true,
        Ok(_) => false,
        Err(err) => {
            eprintln!("failed to run {program}: {err}");
            false
        }
    }
}
