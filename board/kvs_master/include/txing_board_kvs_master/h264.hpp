#ifndef TXING_BOARD_KVS_MASTER_H264_HPP
#define TXING_BOARD_KVS_MASTER_H264_HPP

#include <cstdint>
#include <vector>

namespace txing::board::kvs_master {

struct AccessUnit {
    std::vector<std::uint8_t> bytes;
    bool is_keyframe = false;

    bool operator==(const AccessUnit& other) const;
};

class AnnexBAccessUnitParser {
  public:
    std::vector<AccessUnit> Push(const std::uint8_t* chunk, std::size_t size);
    std::vector<AccessUnit> Finish();

  private:
    void PushNal(const std::vector<std::uint8_t>& nal, std::vector<AccessUnit>& output);
    void FlushCurrent(std::vector<AccessUnit>& output);

    std::vector<std::uint8_t> pending_;
    std::vector<std::uint8_t> current_;
    bool current_has_vcl_ = false;
    bool current_is_keyframe_ = false;
};

}  // namespace txing::board::kvs_master

#endif
