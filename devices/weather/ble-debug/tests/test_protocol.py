from __future__ import annotations

import struct
import unittest

from weather_ble_debug.protocol import (
    MEASUREMENT_STRUCT,
    PROTOCOL_VERSION,
    REDCON_ACTIVE,
    REDCON_IDLE,
    STATE_FLAG_ACTIVE,
    STATE_FLAG_BME280_VALID,
    WEATHER_COMMAND_UUID,
    encode_command,
    encode_measurement_for_test,
    encode_state_for_test,
    parse_measurement,
    parse_state,
)


class WeatherBleProtocolTests(unittest.TestCase):
    def test_command_normalizes_redcon_one_and_two_to_active(self) -> None:
        self.assertEqual(encode_command(1), struct.pack("<BB", PROTOCOL_VERSION, REDCON_ACTIVE))
        self.assertEqual(encode_command(2), struct.pack("<BB", PROTOCOL_VERSION, REDCON_ACTIVE))
        self.assertEqual(encode_command(3), struct.pack("<BB", PROTOCOL_VERSION, REDCON_ACTIVE))
        self.assertEqual(encode_command(4), struct.pack("<BB", PROTOCOL_VERSION, REDCON_IDLE))

    def test_parse_state(self) -> None:
        payload = bytes([PROTOCOL_VERSION, 3, STATE_FLAG_ACTIVE | STATE_FLAG_BME280_VALID, 0xB8, 0x0B])
        state = parse_state(payload)

        self.assertEqual(state.redcon, 3)
        self.assertTrue(state.active)
        self.assertTrue(state.bme280_valid)
        self.assertEqual(state.battery_mv, 3000)

    def test_parse_measurement(self) -> None:
        payload = MEASUREMENT_STRUCT.pack(PROTOCOL_VERSION, 2163, 100800, 4450, 3010)
        measurement = parse_measurement(payload)

        self.assertEqual(measurement.temperature_c, 21.63)
        self.assertEqual(measurement.pressure_kpa, 100.8)
        self.assertEqual(measurement.humidity_percent, 44.5)
        self.assertEqual(measurement.battery_mv, 3010)

    def test_test_encoders_round_trip(self) -> None:
        state = parse_state(encode_state_for_test(redcon=3, bme280_valid=True, battery_mv=3300))
        measurement = parse_measurement(
            encode_measurement_for_test(
                temperature_c=19.25,
                pressure_kpa=99.4,
                humidity_percent=50.5,
                battery_mv=3300,
            )
        )

        self.assertTrue(state.active)
        self.assertTrue(state.bme280_valid)
        self.assertEqual(measurement.temperature_c, 19.25)
        self.assertTrue(WEATHER_COMMAND_UUID.endswith("f100"))


if __name__ == "__main__":
    unittest.main()

