#ifndef TXING_BOARD_KVS_MASTER_MARKERS_HPP
#define TXING_BOARD_KVS_MASTER_MARKERS_HPP

#include <initializer_list>
#include <string>
#include <string_view>
#include <utility>

namespace txing::board::kvs_master {

using MarkerField = std::pair<std::string, std::string>;

std::string SanitizeMarkerValue(std::string_view value);
std::string FormatMarkerLine(std::string_view prefix, std::initializer_list<MarkerField> fields);
void EmitMarker(std::string_view prefix, std::initializer_list<MarkerField> fields);

}  // namespace txing::board::kvs_master

#endif
