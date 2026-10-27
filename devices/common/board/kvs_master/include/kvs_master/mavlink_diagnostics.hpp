#ifndef TXING_KVS_MASTER_MAVLINK_DIAGNOSTICS_HPP
#define TXING_KVS_MASTER_MAVLINK_DIAGNOSTICS_HPP

#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <exception>
#include <sstream>
#include <string>

namespace txing::board::kvs_master {

enum class MavlinkOperation { callback, control, uplink, telemetry, reply, sdk, count };

// Independent atomics keep an unfinished call observable without acquiring any
// callback, bridge, SDK or send lock. Snapshots are approximate across fields.
// This type deliberately accepts no payload, credentials or remote identity.
class MavlinkDiagnostics final {
    struct Counters {
        std::atomic<std::uint64_t> started{0}, finished{0}, failed{0};
        std::atomic<std::uint64_t> last_start_ms{0}, last_ms{0}, max_ms{0};
    };

  public:
    static std::uint64_t NowMs() noexcept {
        return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
    }

    class Scope final {
      public:
        explicit Scope(Counters& counters) noexcept
            : counters_(counters), start_ms_(NowMs()), exceptions_(std::uncaught_exceptions()) {
            counters_.last_start_ms.store(start_ms_);
            ++counters_.started;
        }
        Scope(const Scope&) = delete;
        Scope& operator=(const Scope&) = delete;
        void Fail() noexcept { failed_ = true; }
        ~Scope() {
            const auto elapsed = NowMs() - start_ms_;
            counters_.last_ms.store(elapsed);
            auto maximum = counters_.max_ms.load();
            while (maximum < elapsed && !counters_.max_ms.compare_exchange_weak(maximum, elapsed)) {}
            if (failed_ || std::uncaught_exceptions() > exceptions_) ++counters_.failed;
            ++counters_.finished;
        }

      private:
        Counters& counters_;
        std::uint64_t start_ms_;
        int exceptions_;
        bool failed_ = false;
    };

    Scope Track(MavlinkOperation operation) noexcept {
        return Scope(counters_[static_cast<std::size_t>(operation)]);
    }

    void SdkStatus(std::uint32_t status) noexcept { last_sdk_status_.store(status); }

    std::string Line(bool final) const {
        static constexpr const char* names[] = {"callback", "control", "uplink", "telemetry", "reply", "sdk"};
        const auto now = NowMs();
        const auto unix_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        std::ostringstream out;
        out << "TXING_MAVLINK_DIAGNOSTICS instance=" << instance_
            << " final=" << (final ? 1 : 0) << " steadyMs=" << now
            << " unixMs=" << unix_ms
            << " lastSdkStatus=" << last_sdk_status_.load();
        for (std::size_t i = 0; i < counters_.size(); ++i) {
            const auto& counter = counters_[i];
            // Read finished first so a concurrent completion cannot make the
            // sampled finished count exceed the sampled started count.
            const auto finished = counter.finished.load();
            const auto started = counter.started.load();
            const auto begin = counter.last_start_ms.load();
            out << ' ' << names[i] << "Started=" << started
                << ' ' << names[i] << "Finished=" << finished
                << ' ' << names[i] << "Failed=" << counter.failed.load()
                << ' ' << names[i] << "Pending=" << (started - finished)
                << ' ' << names[i] << "PendingMs=" << (started != finished && now >= begin ? now - begin : 0)
                << ' ' << names[i] << "LastMs=" << counter.last_ms.load()
                << ' ' << names[i] << "MaxMs=" << counter.max_ms.load();
        }
        return out.str();
    }

  private:
    static std::uint64_t NextInstance() noexcept {
        static std::atomic<std::uint64_t> next{0};
        return ++next;
    }
    const std::uint64_t instance_ = NextInstance();
    std::array<Counters, static_cast<std::size_t>(MavlinkOperation::count)> counters_;
    std::atomic<std::uint32_t> last_sdk_status_{0};
};

}  // namespace txing::board::kvs_master

#endif
