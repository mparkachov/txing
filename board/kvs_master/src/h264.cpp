#include "txing_board_kvs_master/h264.hpp"

#include <optional>

namespace txing::board::kvs_master {
namespace {

using StartCode = std::pair<std::size_t, std::size_t>;

std::optional<StartCode> FindStartCode(const std::vector<std::uint8_t>& data, std::size_t from) {
    if (data.size() < 4 || from >= data.size() - 3) {
        return std::nullopt;
    }

    for (std::size_t index = from; index + 3 < data.size(); ++index) {
        if (data[index] == 0x00 && data[index + 1] == 0x00) {
            if (data[index + 2] == 0x01) {
                return StartCode(index, 3);
            }
            if (index + 3 < data.size() && data[index + 2] == 0x00 && data[index + 3] == 0x01) {
                return StartCode(index, 4);
            }
        }
    }
    return std::nullopt;
}

std::optional<std::vector<std::uint8_t>> TakeTrailingNal(std::vector<std::uint8_t>& pending) {
    const auto start = FindStartCode(pending, 0);
    if (!start || start->first != 0 || pending.size() <= start->second) {
        pending.clear();
        return std::nullopt;
    }

    auto trailing = std::move(pending);
    pending.clear();
    return trailing;
}

std::vector<std::vector<std::uint8_t>> ExtractCompleteNals(std::vector<std::uint8_t>& pending) {
    if (pending.empty()) {
        return {};
    }

    const auto first_start = FindStartCode(pending, 0);
    if (!first_start) {
        if (pending.size() > 4) {
            pending.erase(pending.begin(), pending.end() - 4);
        }
        return {};
    }

    if (first_start->first > 0) {
        pending.erase(pending.begin(), pending.begin() + static_cast<std::ptrdiff_t>(first_start->first));
    }

    std::vector<StartCode> starts;
    std::size_t index = 0;
    while (const auto start = FindStartCode(pending, index)) {
        starts.push_back(*start);
        index = start->first + start->second;
    }

    if (starts.size() < 2) {
        return {};
    }

    std::vector<std::vector<std::uint8_t>> nals;
    nals.reserve(starts.size() - 1);
    for (std::size_t i = 0; i + 1 < starts.size(); ++i) {
        const auto start = starts[i].first;
        const auto end = starts[i + 1].first;
        nals.emplace_back(pending.begin() + static_cast<std::ptrdiff_t>(start), pending.begin() + static_cast<std::ptrdiff_t>(end));
    }

    const auto tail_start = starts.back().first;
    pending.erase(pending.begin(), pending.begin() + static_cast<std::ptrdiff_t>(tail_start));
    return nals;
}

const std::uint8_t* NalPayload(const std::vector<std::uint8_t>& nal, std::size_t& payload_size) {
    const auto start = FindStartCode(nal, 0);
    if (!start || nal.size() <= start->second) {
        payload_size = 0;
        return nullptr;
    }
    payload_size = nal.size() - start->second;
    return nal.data() + static_cast<std::ptrdiff_t>(start->second);
}

std::vector<std::uint8_t> RemoveEmulationPreventionBytes(const std::uint8_t* payload, std::size_t size) {
    std::vector<std::uint8_t> rbsp;
    rbsp.reserve(size);
    std::uint8_t zero_run = 0;
    for (std::size_t index = 0; index < size; ++index) {
        const auto byte = payload[index];
        if (zero_run >= 2 && byte == 0x03) {
            zero_run = 0;
            continue;
        }
        rbsp.push_back(byte);
        if (byte == 0x00) {
            zero_run = static_cast<std::uint8_t>(zero_run + 1);
        } else {
            zero_run = 0;
        }
    }
    return rbsp;
}

class BitReader {
  public:
    explicit BitReader(const std::vector<std::uint8_t>& bytes) : bytes_(bytes) {}

    std::optional<std::uint8_t> ReadBit() {
        if (bit_offset_ / 8 >= bytes_.size()) {
            return std::nullopt;
        }

        const auto byte = bytes_[bit_offset_ / 8];
        const auto shift = 7U - static_cast<unsigned>(bit_offset_ % 8);
        ++bit_offset_;
        return static_cast<std::uint8_t>((byte >> shift) & 0x01U);
    }

    std::optional<std::uint32_t> ReadBits(std::size_t count) {
        std::uint32_t value = 0;
        for (std::size_t index = 0; index < count; ++index) {
            const auto bit = ReadBit();
            if (!bit) {
                return std::nullopt;
            }
            value = (value << 1U) | static_cast<std::uint32_t>(*bit);
        }
        return value;
    }

    std::optional<std::uint32_t> ReadUnsignedExpGolomb() {
        std::size_t leading_zeros = 0;
        while (true) {
            const auto bit = ReadBit();
            if (!bit) {
                return std::nullopt;
            }
            if (*bit == 1U) {
                break;
            }
            ++leading_zeros;
        }

        if (leading_zeros == 0) {
            return 0;
        }

        const auto suffix = ReadBits(leading_zeros);
        if (!suffix) {
            return std::nullopt;
        }
        return ((1U << leading_zeros) - 1U) + *suffix;
    }

  private:
    const std::vector<std::uint8_t>& bytes_;
    std::size_t bit_offset_ = 0;
};

bool FirstMbInSliceIsZero(const std::uint8_t* payload, std::size_t size) {
    if (size < 2) {
        return false;
    }
    const auto rbsp = RemoveEmulationPreventionBytes(payload + 1, size - 1);
    BitReader reader(rbsp);
    const auto first_mb = reader.ReadUnsignedExpGolomb();
    return first_mb && *first_mb == 0;
}

}  // namespace

bool AccessUnit::operator==(const AccessUnit& other) const {
    return is_keyframe == other.is_keyframe && bytes == other.bytes;
}

std::vector<AccessUnit> AnnexBAccessUnitParser::Push(const std::uint8_t* chunk, std::size_t size) {
    pending_.insert(pending_.end(), chunk, chunk + static_cast<std::ptrdiff_t>(size));

    std::vector<AccessUnit> output;
    const auto nals = ExtractCompleteNals(pending_);
    for (const auto& nal : nals) {
        PushNal(nal, output);
    }
    return output;
}

std::vector<AccessUnit> AnnexBAccessUnitParser::Finish() {
    std::vector<AccessUnit> output;
    if (const auto trailing = TakeTrailingNal(pending_)) {
        PushNal(*trailing, output);
    }
    FlushCurrent(output);
    return output;
}

void AnnexBAccessUnitParser::PushNal(const std::vector<std::uint8_t>& nal, std::vector<AccessUnit>& output) {
    std::size_t payload_size = 0;
    const auto* payload = NalPayload(nal, payload_size);
    if (payload == nullptr || payload_size == 0) {
        return;
    }

    const auto nal_type = static_cast<std::uint8_t>(payload[0] & 0x1fU);
    const bool is_vcl = nal_type >= 1 && nal_type <= 5;

    if (nal_type == 9) {
        FlushCurrent(output);
        return;
    }

    if (is_vcl && current_has_vcl_ && FirstMbInSliceIsZero(payload, payload_size)) {
        FlushCurrent(output);
    } else if (!is_vcl && current_has_vcl_ && (nal_type == 6 || nal_type == 7 || nal_type == 8)) {
        FlushCurrent(output);
    }

    current_.insert(current_.end(), nal.begin(), nal.end());
    if (is_vcl) {
        current_has_vcl_ = true;
        if (nal_type == 5) {
            current_is_keyframe_ = true;
        }
    }
}

void AnnexBAccessUnitParser::FlushCurrent(std::vector<AccessUnit>& output) {
    if (current_has_vcl_ && !current_.empty()) {
        AccessUnit access_unit;
        access_unit.bytes = std::move(current_);
        access_unit.is_keyframe = current_is_keyframe_;
        output.push_back(std::move(access_unit));
    } else {
        current_.clear();
    }

    current_has_vcl_ = false;
    current_is_keyframe_ = false;
}

}  // namespace txing::board::kvs_master
