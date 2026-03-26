#ifndef TXING_BOARD_KVS_MASTER_RPICAM_HPP
#define TXING_BOARD_KVS_MASTER_RPICAM_HPP

#include "txing_board_kvs_master/config.hpp"

#include <optional>
#include <string>
#include <vector>

namespace txing::board::kvs_master {

std::vector<std::string> BuildRpicamArguments(const CameraConfig& config);

class RpicamProcess {
  public:
    RpicamProcess() = default;
    RpicamProcess(const RpicamProcess&) = delete;
    RpicamProcess& operator=(const RpicamProcess&) = delete;
    RpicamProcess(RpicamProcess&& other) noexcept;
    RpicamProcess& operator=(RpicamProcess&& other) noexcept;
    ~RpicamProcess();

    static RpicamProcess Spawn(const CameraConfig& config);

    int stdout_fd() const;
    std::optional<int> TryWait();
    void Terminate();

  private:
    explicit RpicamProcess(int stdout_fd, int pid) noexcept;
    void CloseStdout() noexcept;
    int WaitPid(int options);

    int stdout_fd_ = -1;
    int pid_ = -1;
};

}  // namespace txing::board::kvs_master

#endif
