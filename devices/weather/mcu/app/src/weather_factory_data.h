#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace txing::weather
{
constexpr std::uint32_t kFactoryMagic = 0x31575854; // "TXW1" little-endian
constexpr std::uint8_t kFactoryVersion = 1;
constexpr std::size_t kThingNameCapacity = 26;

struct FactoryData
{
	std::array<char, kThingNameCapacity + 1> thing_name{};
};

bool ReadFactoryData(FactoryData &factory);
} // namespace txing::weather
