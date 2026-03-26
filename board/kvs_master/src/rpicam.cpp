#include "txing_board_kvs_master/rpicam.hpp"

#include <array>
#include <chrono>
#include <csignal>
#include <cstring>
#include <stdexcept>
#include <thread>
#include <unistd.h>
#include <sys/wait.h>

namespace txing::board::kvs_master {

std::vector<std::string> BuildRpicamArguments(const CameraConfig& config) {
    return {
        "-n",
        "-t",
        "0",
        "--inline",
        "--camera",
        std::to_string(config.camera),
        "--width",
        std::to_string(config.width),
        "--height",
        std::to_string(config.height),
        "--framerate",
        std::to_string(config.framerate),
        "--bitrate",
        std::to_string(config.bitrate),
        "--intra",
        std::to_string(config.intra),
        "-o",
        "-",
    };
}

RpicamProcess::RpicamProcess(int stdout_fd, int pid) noexcept : stdout_fd_(stdout_fd), pid_(pid) {}

RpicamProcess::RpicamProcess(RpicamProcess&& other) noexcept : stdout_fd_(other.stdout_fd_), pid_(other.pid_) {
    other.stdout_fd_ = -1;
    other.pid_ = -1;
}

RpicamProcess& RpicamProcess::operator=(RpicamProcess&& other) noexcept {
    if (this == &other) {
        return *this;
    }
    CloseStdout();
    stdout_fd_ = other.stdout_fd_;
    pid_ = other.pid_;
    other.stdout_fd_ = -1;
    other.pid_ = -1;
    return *this;
}

RpicamProcess::~RpicamProcess() {
    CloseStdout();
}

RpicamProcess RpicamProcess::Spawn(const CameraConfig& config) {
    std::array<int, 2> pipe_fds = {-1, -1};
    if (pipe(pipe_fds.data()) != 0) {
        throw std::runtime_error("failed to create pipe for rpicam-vid stdout");
    }

    const auto arguments = BuildRpicamArguments(config);
    std::vector<char*> argv;
    argv.reserve(arguments.size() + 2);
    argv.push_back(const_cast<char*>(config.path.c_str()));
    for (const auto& argument : arguments) {
        argv.push_back(const_cast<char*>(argument.c_str()));
    }
    argv.push_back(nullptr);

    const auto pid = fork();
    if (pid < 0) {
        close(pipe_fds[0]);
        close(pipe_fds[1]);
        throw std::runtime_error("failed to fork rpicam-vid");
    }

    if (pid == 0) {
        close(pipe_fds[0]);
        if (setpgid(0, 0) != 0) {
            _exit(127);
        }
        if (dup2(pipe_fds[1], STDOUT_FILENO) < 0) {
            _exit(127);
        }
        close(pipe_fds[1]);
        execv(config.path.c_str(), argv.data());
        _exit(127);
    }

    close(pipe_fds[1]);
    return RpicamProcess(pipe_fds[0], pid);
}

int RpicamProcess::stdout_fd() const {
    return stdout_fd_;
}

std::optional<int> RpicamProcess::TryWait() {
    if (pid_ <= 0) {
        return 0;
    }

    const auto result = WaitPid(WNOHANG);
    if (result == 0) {
        return std::nullopt;
    }
    return result;
}

void RpicamProcess::Terminate() {
    if (pid_ <= 0) {
        return;
    }

    const auto existing_status = WaitPid(WNOHANG);
    if (existing_status != 0) {
        return;
    }

    if (kill(-pid_, SIGTERM) != 0 && errno != ESRCH) {
        throw std::runtime_error("failed to send SIGTERM to rpicam-vid");
    }

    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (std::chrono::steady_clock::now() < deadline) {
        const auto result = WaitPid(WNOHANG);
        if (result != 0) {
            return;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    if (kill(-pid_, SIGKILL) != 0 && errno != ESRCH) {
        throw std::runtime_error("failed to force-stop rpicam-vid");
    }
    WaitPid(0);
}

void RpicamProcess::CloseStdout() noexcept {
    if (stdout_fd_ >= 0) {
        close(stdout_fd_);
        stdout_fd_ = -1;
    }
}

int RpicamProcess::WaitPid(int options) {
    if (pid_ <= 0) {
        return 0;
    }

    int status = 0;
    const auto wait_result = waitpid(pid_, &status, options);
    if (wait_result == 0) {
        return 0;
    }
    if (wait_result < 0) {
        if (errno == EINTR) {
            return 0;
        }
        if (errno == ECHILD) {
            pid_ = -1;
            CloseStdout();
            return 0;
        }
        throw std::runtime_error("waitpid failed for rpicam-vid");
    }

    pid_ = -1;
    CloseStdout();
    if (WIFEXITED(status)) {
        return WEXITSTATUS(status);
    }
    if (WIFSIGNALED(status)) {
        return 128 + WTERMSIG(status);
    }
    return status;
}

}  // namespace txing::board::kvs_master
