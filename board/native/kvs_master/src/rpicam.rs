use anyhow::{Context, Result, anyhow};
#[cfg(unix)]
use nix::sys::signal::{Signal, kill};
#[cfg(unix)]
use nix::unistd::Pid;
use std::path::PathBuf;
use std::process::{Child, ChildStdout, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

#[derive(Debug, Clone)]
pub struct CameraConfig {
    pub path: PathBuf,
    pub camera: u32,
    pub width: u32,
    pub height: u32,
    pub framerate: u32,
    pub bitrate: u32,
    pub intra: u32,
}

pub fn build_command_arguments(config: &CameraConfig) -> Vec<String> {
    vec![
        "-n".to_string(),
        "-t".to_string(),
        "0".to_string(),
        "--inline".to_string(),
        "--camera".to_string(),
        config.camera.to_string(),
        "--width".to_string(),
        config.width.to_string(),
        "--height".to_string(),
        config.height.to_string(),
        "--framerate".to_string(),
        config.framerate.to_string(),
        "--bitrate".to_string(),
        config.bitrate.to_string(),
        "--intra".to_string(),
        config.intra.to_string(),
        "-o".to_string(),
        "-".to_string(),
    ]
}

pub fn spawn(config: &CameraConfig) -> Result<Child> {
    let mut command = Command::new(&config.path);
    command
        .args(build_command_arguments(config))
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }

    command
        .spawn()
        .with_context(|| format!("failed to start {}", config.path.display()))
}

pub fn terminate(child: &mut Child) -> Result<()> {
    if child.try_wait()?.is_some() {
        return Ok(());
    }

    #[cfg(unix)]
    {
        let child_id = child.id();
        let pid = Pid::from_raw(
            i32::try_from(child_id)
                .map_err(|_| anyhow!("child pid {child_id} does not fit in i32"))?,
        );
        kill(pid, Signal::SIGTERM).context("failed to send SIGTERM to rpicam-vid")?;
    }

    #[cfg(not(unix))]
    {
        child.kill().context("failed to stop rpicam-vid")?;
    }

    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if child.try_wait()?.is_some() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(100));
    }

    child.kill().context("failed to force-stop rpicam-vid")?;
    let _ = child.wait();
    Ok(())
}

pub fn take_stdout(child: &mut Child) -> Result<ChildStdout> {
    child
        .stdout
        .take()
        .context("rpicam-vid stdout pipe was not available")
}

#[cfg(test)]
mod tests {
    use super::{CameraConfig, build_command_arguments};
    use std::path::PathBuf;

    #[test]
    fn builds_expected_rpicam_arguments() {
        let arguments = build_command_arguments(&CameraConfig {
            path: PathBuf::from("/usr/bin/rpicam-vid"),
            camera: 1,
            width: 1920,
            height: 1080,
            framerate: 30,
            bitrate: 8_000_000,
            intra: 30,
        });

        assert_eq!(
            arguments,
            vec![
                "-n",
                "-t",
                "0",
                "--inline",
                "--camera",
                "1",
                "--width",
                "1920",
                "--height",
                "1080",
                "--framerate",
                "30",
                "--bitrate",
                "8000000",
                "--intra",
                "30",
                "-o",
                "-",
            ]
        );
    }
}
