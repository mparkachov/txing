#include "txing_board_kvs_master/markers.hpp"

#include <iostream>

namespace txing::board::kvs_master {

std::string SanitizeMarkerValue(std::string_view value) {
    std::string sanitized;
    sanitized.reserve(value.size());
    for (char character : value) {
        switch (character) {
            case '\n':
            case '\r':
            case '\t':
                sanitized.push_back(' ');
                break;
            default:
                sanitized.push_back(character);
                break;
        }
    }
    return sanitized;
}

std::string FormatMarkerLine(std::string_view prefix, std::initializer_list<MarkerField> fields) {
    std::string line(prefix);
    for (const auto& field : fields) {
        line.push_back(' ');
        line.append(field.first);
        line.push_back('=');
        line.append(SanitizeMarkerValue(field.second));
    }
    return line;
}

void EmitMarker(std::string_view prefix, std::initializer_list<MarkerField> fields) {
    std::cout << FormatMarkerLine(prefix, fields) << '\n';
    std::cout.flush();
}

}  // namespace txing::board::kvs_master
