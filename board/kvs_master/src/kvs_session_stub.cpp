#include "txing_board_kvs_master/kvs_session.hpp"

#include "txing_board_kvs_master/markers.hpp"

#include <memory>
#include <stdexcept>

namespace txing::board::kvs_master {
namespace {

class StubKvsSession final : public KvsSession {
  public:
    void Start() override {
        started_ = true;
        EmitMarker("TXING_KVS_READY", {});
    }

    void PushH264AccessUnit(
        const std::uint8_t* data,
        std::size_t len,
        std::uint64_t /*presentation_ts_100ns*/,
        std::uint64_t /*duration_100ns*/,
        bool /*is_keyframe*/
    ) override {
        if (!started_ || data == nullptr || len == 0) {
            throw std::runtime_error("stub KVS session is not ready");
        }
    }

    void Stop() noexcept override {
        started_ = false;
    }

    std::optional<std::string> TakeFatalError() override {
        return std::nullopt;
    }

  private:
    bool started_ = false;
};

}  // namespace

std::unique_ptr<KvsSession> CreateKvsSession(const RuntimeConfig&, const AwsCredentials&) {
    return std::make_unique<StubKvsSession>();
}

}  // namespace txing::board::kvs_master
