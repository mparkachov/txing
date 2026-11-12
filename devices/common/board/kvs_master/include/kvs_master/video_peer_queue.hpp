#ifndef TXING_KVS_MASTER_VIDEO_PEER_QUEUE_HPP
#define TXING_KVS_MASTER_VIDEO_PEER_QUEUE_HPP

#include <condition_variable>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <utility>
#include <vector>

namespace txing::board::kvs_master {

struct H264AccessUnit {
    std::vector<std::uint8_t> bytes;
    std::uint64_t presentation_ts_100ns;
    std::uint64_t duration_100ns;
    bool keyframe;
};

class VideoPeerQueue {
  public:
    using Frame = std::shared_ptr<const H264AccessUnit>;

    void Push(const Frame& frame) {
        {
            std::lock_guard lock(mutex_);
            if (closed_) return;
            if (pending_.size() == 3) {
                pending_.clear();
                awaiting_keyframe_ = true;
            }
            if (awaiting_keyframe_ && !frame->keyframe) return;
            pending_.push_back(frame);
            awaiting_keyframe_ = false;
        }
        ready_.notify_one();
    }

    Frame Take() {
        std::unique_lock lock(mutex_);
        ready_.wait(lock, [&] { return closed_ || !pending_.empty(); });
        if (closed_) return {};
        auto frame = std::move(pending_.front());
        pending_.pop_front();
        return frame;
    }

    void RequireKeyframe() {
        std::lock_guard lock(mutex_);
        pending_.clear();
        awaiting_keyframe_ = true;
    }

    void Close() {
        {
            std::lock_guard lock(mutex_);
            closed_ = true;
            pending_.clear();
        }
        ready_.notify_all();
    }

  private:
    std::mutex mutex_;
    std::condition_variable ready_;
    std::deque<Frame> pending_;
    bool awaiting_keyframe_ = true;
    bool closed_ = false;
};

}  // namespace txing::board::kvs_master

#endif
