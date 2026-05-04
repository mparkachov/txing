#include "weather_factory_data.h"

#include <cstddef>
#include <cstdint>

namespace txing::weather
{
namespace
{
struct StoredFactoryData
{
	std::uint32_t magic;
	std::uint8_t version;
	std::uint8_t thing_name_len;
	char thing_name[kThingNameCapacity];
	std::uint32_t crc32;
};

static_assert(sizeof(StoredFactoryData) == 36);

#ifndef TXING_WEATHER_FACTORY_DATA_ADDR
#define TXING_WEATHER_FACTORY_DATA_ADDR 0x000f0000u
#endif

const auto *const kStoredFactoryData =
	reinterpret_cast<const StoredFactoryData *>(TXING_WEATHER_FACTORY_DATA_ADDR);

std::uint32_t Crc32(const std::uint8_t *data, std::size_t size)
{
	std::uint32_t crc = 0xffffffffu;
	for (std::size_t i = 0; i < size; ++i) {
		crc ^= data[i];
		for (int bit = 0; bit < 8; ++bit) {
			const bool lsb = (crc & 1u) != 0;
			crc >>= 1u;
			if (lsb) {
				crc ^= 0xedb88320u;
			}
		}
	}
	return crc ^ 0xffffffffu;
}
} // namespace

bool ReadFactoryData(FactoryData &factory)
{
	const StoredFactoryData &stored = *kStoredFactoryData;
	if (stored.magic != kFactoryMagic || stored.version != kFactoryVersion) {
		return false;
	}
	if (stored.thing_name_len == 0 || stored.thing_name_len > kThingNameCapacity) {
		return false;
	}
	const auto *bytes = reinterpret_cast<const std::uint8_t *>(&stored);
	const std::size_t without_crc = sizeof(StoredFactoryData) - sizeof(stored.crc32);
	if (Crc32(bytes, without_crc) != stored.crc32) {
		return false;
	}
	for (std::size_t i = 0; i < stored.thing_name_len; ++i) {
		const char ch = stored.thing_name[i];
		if (ch < '!' || ch > '~') {
			return false;
		}
		factory.thing_name[i] = ch;
	}
	factory.thing_name[stored.thing_name_len] = '\0';
	return true;
}
} // namespace txing::weather
