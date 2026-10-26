#ifndef TXING_KVS_MASTER_SERIALIZED_DATA_CHANNEL_HPP
#define TXING_KVS_MASTER_SERIALIZED_DATA_CHANNEL_HPP

#include <mutex>
#include <utility>

namespace txing::board::kvs_master {

// One instance per peer. The pinned SDK shares mutable SCTP send metadata
// between text and binary calls, so protect the complete SDK call and binding.
// Close waits for an in-flight write; callers release this lock before joining
// the telemetry reader or closing the SDK peer. Write callbacks must not reenter.
template<class Channel>
class SerializedDataChannel final {
  public:
    bool Bind(Channel channel) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (closed_) {
            return false;
        }
        channel_ = channel;
        return true;
    }

    void Close() {
        std::lock_guard<std::mutex> lock(mutex_);
        closed_ = true;
        channel_ = Channel{};
    }

    template<class Write>
    bool Send(Channel expected, Write&& write) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (channel_ == Channel{} || channel_ != expected) {
            return false;
        }
        std::forward<Write>(write)(channel_);
        return true;
    }

  private:
    std::mutex mutex_;
    Channel channel_{};
    bool closed_ = false;
};

}  // namespace txing::board::kvs_master

#endif
