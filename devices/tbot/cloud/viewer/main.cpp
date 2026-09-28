#include "viewer.hpp"
#include <cerrno>
#include <csignal>
#include <fcntl.h>
#include <poll.h>
#include <thread>
#include <unistd.h>

namespace {
constexpr std::size_t MaxPacket = 65536;
std::atomic<bool> stopped{false};
void Signal(int) { stopped = true; }
bool ReadBytes(void *dst, std::size_t size) {
  auto *p = static_cast<unsigned char *>(dst);
  while (size) {
    pollfd fd{STDIN_FILENO, POLLIN, 0};
    int ready = poll(&fd, 1, 250);
    if (stopped)
      return false;
    if (ready < 0) {
      if (errno == EINTR)
        continue;
      return false;
    }
    if (ready == 0)
      continue;
    ssize_t count = read(STDIN_FILENO, p, size);
    if (count <= 0)
      return false;
    p += count;
    size -= static_cast<std::size_t>(count);
  }
  return true;
}
bool Read(char &kind, std::string &body) {
  unsigned char header[5];
  if (!ReadBytes(header, sizeof(header)))
    return false;
  kind = static_cast<char>(header[0]);
  std::size_t size = (std::size_t(header[1]) << 24) |
                     (std::size_t(header[2]) << 16) |
                     (std::size_t(header[3]) << 8) | header[4];
  if (size > MaxPacket)
    return false;
  body.resize(size);
  return ReadBytes(body.data(), size);
}
std::vector<std::string> Split(const std::string &input) {
  std::vector<std::string> fields;
  std::size_t start = 0;
  for (;;) {
    auto end = input.find('\0', start);
    fields.push_back(
        input.substr(start, end == std::string::npos ? end : end - start));
    if (end == std::string::npos)
      break;
    start = end + 1;
  }
  return fields;
}
class Output {
  std::mutex mutex_;
  std::condition_variable cv_;
  std::deque<std::string> queue_;
  std::thread thread_;

public:
  Output() {
    fcntl(STDOUT_FILENO, F_SETFL, fcntl(STDOUT_FILENO, F_GETFL) | O_NONBLOCK);
    thread_ = std::thread([this] { Run(); });
  }
  ~Output() {
    stopped = true;
    cv_.notify_all();
    thread_.join();
  }
  void Send(char kind, const std::string &body) {
    if (body.size() > MaxPacket) {
      stopped = true;
      return;
    }
    std::string packet(5, '\0');
    packet[0] = kind;
    for (int i = 0; i < 4; i++)
      packet[1 + i] = static_cast<char>(body.size() >> (24 - 8 * i));
    packet += body;
    std::lock_guard<std::mutex> lock(mutex_);
    if (queue_.size() >= 64) {
      stopped = true;
      return;
    }
    queue_.push_back(std::move(packet));
    cv_.notify_one();
  }

private:
  void Run() {
    for (;;) {
      std::string packet;
      {
        std::unique_lock<std::mutex> lock(mutex_);
        cv_.wait_for(lock, std::chrono::milliseconds(100),
                     [this] { return stopped || !queue_.empty(); });
        if (queue_.empty()) {
          if (stopped)
            return;
          continue;
        }
        packet = std::move(queue_.front());
        queue_.pop_front();
      }
      std::size_t offset = 0;
      auto deadline =
          std::chrono::steady_clock::now() + std::chrono::seconds(2);
      while (offset < packet.size()) {
        ssize_t count = write(STDOUT_FILENO, packet.data() + offset,
                              packet.size() - offset);
        if (count > 0) {
          offset += static_cast<std::size_t>(count);
          continue;
        }
        if (count < 0 && (errno == EINTR || errno == EAGAIN)) {
          if (std::chrono::steady_clock::now() >= deadline) {
            stopped = true;
            return;
          }
          pollfd fd{STDOUT_FILENO, POLLOUT, 0};
          poll(&fd, 1, 50);
          continue;
        }
        stopped = true;
        return;
      }
    }
  }
};
} // namespace
int main(int argc, char **argv) {
  if (argc != 6 || (std::strcmp(argv[1], "mavlink") != 0 &&
                    std::strcmp(argv[1], "video") != 0))
    return 2;
  std::signal(SIGTERM, Signal);
  std::signal(SIGINT, Signal);
  std::signal(SIGPIPE, SIG_IGN);
  // SDK logging uses the process logger; only sanitized IPC errors are
  // observable.
  SET_LOGGER_LOG_LEVEL(LOG_LEVEL_SILENT);
  Output output;
  bool initialized = false;
  try {
    txing::Credentials credentials;
    char kind;
    std::string body;
    if (!Read(kind, body) || kind != 'C')
      throw std::runtime_error("initial task credentials missing");
    credentials.Update(Split(body));
    std::fill(body.begin(), body.end(), 0);
    txing::Check(initKvsWebRtc(), "initialize WebRTC");
    initialized = true;
    txing::Viewer viewer(
        std::strcmp(argv[1], "video") == 0,
        [&output](char k, const std::string &p) { output.Send(k, p); });
    std::mutex requestsMutex;
    std::deque<std::pair<char, std::string>> requests;
    // Credential refresh never touches a healthy peer. Uplink hooks are
    // executed on the worker's main thread, separate from credential and
    // receive callbacks.
    std::thread input([&] {
      try {
        char type;
        std::string data;
        while (Read(type, data)) {
          if (type == 'C') {
            credentials.Update(Split(data));
            std::fill(data.begin(), data.end(), 0);
          } else if (type == 'B' || type == 'J') {
            std::lock_guard<std::mutex> lock(requestsMutex);
            if (requests.size() >= 16)
              throw std::runtime_error("viewer send queue full");
            requests.emplace_back(type, std::move(data));
          } else
            break;
        }
      } catch (...) {
        output.Send('E', "invalid viewer IPC request");
      }
      stopped = true;
    });
    try {
      viewer.Signaling(argv[2], argv[3], argv[4], argv[5], &credentials);
      if (!stopped) {
        viewer.Peer(viewer.Configuration());
        viewer.SendOffer(viewer.Offer());
      }
      while (!stopped && !viewer.Closed()) {
        std::deque<std::pair<char, std::string>> batch;
        {
          std::lock_guard<std::mutex> lock(requestsMutex);
          batch.swap(requests);
        }
        for (const auto &request : batch)
          viewer.Send(request.first == 'B', request.second);
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
      }
    } catch (const std::exception &err) {
      output.Send('E', err.what());
    }
    stopped = true;
    input.join();
    viewer.Stop();
  } catch (const std::exception &err) {
    output.Send('E', err.what());
  }
  if (initialized)
    deinitKvsWebRtc();
  return 0;
}
