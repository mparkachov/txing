#[cfg(unix)]
use std::fs::File;
use std::io;
#[cfg(unix)]
use std::io::{BufRead, BufReader, Write};
#[cfg(unix)]
use std::os::fd::FromRawFd;
#[cfg(unix)]
use std::thread;

const KEEP_GG_SDK_DEBUG_LOGS_ENV: &str = "TXING_KEEP_GG_SDK_DEBUG_LOGS";

pub fn install_greengrass_debug_log_filter() {
    if keep_debug_logs_enabled() {
        return;
    }
    if let Err(err) = install_output_line_filters() {
        eprintln!("warning: failed to install Greengrass SDK debug log filter: {err}");
    }
}

fn keep_debug_logs_enabled() -> bool {
    std::env::var(KEEP_GG_SDK_DEBUG_LOGS_ENV)
        .ok()
        .is_some_and(|value| matches!(value.as_str(), "1" | "true" | "TRUE" | "yes" | "on"))
}

#[cfg(unix)]
fn install_output_line_filters() -> io::Result<()> {
    install_fd_line_filter(libc::STDOUT_FILENO)?;
    install_fd_line_filter(libc::STDERR_FILENO)?;
    Ok(())
}

#[cfg(unix)]
fn install_fd_line_filter(target_fd: libc::c_int) -> io::Result<()> {
    let mut pipe_fds = [0; 2];
    if unsafe { libc::pipe(pipe_fds.as_mut_ptr()) } != 0 {
        return Err(io::Error::last_os_error());
    }

    let read_fd = pipe_fds[0];
    let write_fd = pipe_fds[1];
    let original_fd = unsafe { libc::dup(target_fd) };
    if original_fd < 0 {
        close_fd(read_fd);
        close_fd(write_fd);
        return Err(io::Error::last_os_error());
    }
    if unsafe { libc::dup2(write_fd, target_fd) } < 0 {
        close_fd(read_fd);
        close_fd(write_fd);
        close_fd(original_fd);
        return Err(io::Error::last_os_error());
    }
    close_fd(write_fd);

    thread::spawn(move || {
        let file = unsafe { File::from_raw_fd(read_fd) };
        let mut reader = BufReader::new(file);
        let mut output = unsafe { File::from_raw_fd(original_fd) };
        let mut line = Vec::new();

        loop {
            line.clear();
            match reader.read_until(b'\n', &mut line) {
                Ok(0) => break,
                Ok(_) => {
                    if should_emit_log_line(&line) {
                        let _ = output.write_all(&line);
                        let _ = output.flush();
                    }
                }
                Err(_) => break,
            }
        }
    });

    Ok(())
}

#[cfg(not(unix))]
fn install_output_line_filters() -> io::Result<()> {
    Ok(())
}

#[cfg(unix)]
fn close_fd(fd: libc::c_int) {
    unsafe {
        libc::close(fd);
    }
}

fn should_emit_log_line(line: &[u8]) -> bool {
    !line.starts_with(b"D[")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn filters_c_style_debug_lines_only() {
        assert!(!should_emit_log_line(
            b"D[gg-sdk] socket_epoll.c:69: noise\n"
        ));
        assert!(should_emit_log_line(b"I[gg-sdk] client.c:225: useful\n"));
        assert!(should_emit_log_line(
            b"W[core-bus] client_common.c:137: warning\n"
        ));
        assert!(should_emit_log_line(b"warning: BLE publish failed\n"));
    }
}
