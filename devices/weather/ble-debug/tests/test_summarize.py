from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from weather_ble_debug.summarize import summarize_path


def _line(timestamp: str, event: str, **fields: object) -> str:
    pairs = " ".join(f"{key}={value}" for key, value in fields.items())
    return f"{timestamp} {event} {pairs}".rstrip()


class WeatherBleDebugSummarizeTests(unittest.TestCase):
    def test_soak_log_passes_with_one_hz_measurements(self) -> None:
        path = self._write_log(
            [
                _line("2026-05-05T10:00:00.000Z", "adv", name="weather-1", service=1),
                _line("2026-05-05T10:00:00.100Z", "connected", connectMs=90),
                _line(
                    "2026-05-05T10:00:00.200Z",
                    "services",
                    command=1,
                    state=1,
                    measurement=1,
                    servicesMs=100,
                ),
                _line("2026-05-05T10:00:00.300Z", "state", redcon=4),
                _line("2026-05-05T10:00:00.400Z", "command", redcon=3),
                _line("2026-05-05T10:00:00.500Z", "state", redcon=3),
                _line("2026-05-05T10:00:01.500Z", "measurement"),
                _line("2026-05-05T10:00:02.500Z", "measurement"),
                _line("2026-05-05T10:00:03.500Z", "measurement"),
                _line("2026-05-05T10:00:03.600Z", "wake-ok", latencyMs=3200),
                _line("2026-05-05T10:00:04.000Z", "command", redcon=4),
                _line("2026-05-05T10:00:04.100Z", "state", redcon=4),
                _line("2026-05-05T10:00:04.300Z", "sleep-ok", latencyMs=300),
                _line("2026-05-05T10:00:04.400Z", "disconnect", unexpected=0),
                _line("2026-05-05T10:00:04.500Z", "summary", command="soak"),
            ]
        )

        summary = summarize_path(path)

        self.assertFalse(summary.failed)
        self.assertEqual(summary.fields["status"], "pass")
        self.assertEqual(summary.fields["measurementCount"], 3)
        self.assertEqual(summary.fields["minIntervalMs"], 1000)
        self.assertEqual(summary.fields["maxIntervalMs"], 1000)

    def test_unexpected_disconnect_and_error_fail(self) -> None:
        path = self._write_log(
            [
                _line("2026-05-05T10:00:00.000Z", "adv", name="weather-1", service=1),
                _line(
                    "2026-05-05T10:00:00.100Z",
                    "services",
                    command=1,
                    state=1,
                    measurement=1,
                ),
                _line("2026-05-05T10:00:01.000Z", "disconnect", unexpected=1),
                _line("2026-05-05T10:00:01.100Z", "error", stage="idle", message="unexpected-disconnect"),
            ]
        )

        summary = summarize_path(path)

        self.assertTrue(summary.failed)
        self.assertIn("unexpected-disconnect", summary.fields["reason"])
        self.assertIn("cli-error", summary.fields["reason"])
        self.assertEqual(summary.fields["errorStage"], "idle")

    def test_measurement_after_sleep_fails(self) -> None:
        path = self._write_log(
            [
                _line("2026-05-05T10:00:00.000Z", "adv", name="weather-1", service=1),
                _line(
                    "2026-05-05T10:00:00.100Z",
                    "services",
                    command=1,
                    state=1,
                    measurement=1,
                ),
                _line("2026-05-05T10:00:00.200Z", "state", redcon=3),
                _line("2026-05-05T10:00:01.200Z", "measurement"),
                _line("2026-05-05T10:00:02.200Z", "state", redcon=4),
                _line("2026-05-05T10:00:03.200Z", "measurement"),
                _line("2026-05-05T10:00:03.300Z", "summary", command="soak"),
            ]
        )

        summary = summarize_path(path)

        self.assertTrue(summary.failed)
        self.assertIn("measurement-after-sleep", summary.fields["reason"])
        self.assertEqual(summary.fields["measurementsAfterSleep"], 1)

    def _write_log(self, lines: list[str]) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "weather.log"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
