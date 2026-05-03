from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rig.connectivity_protocol import (
    CONTROL_UNAVAILABLE,
    PRESENCE_OFFLINE,
    PRESENCE_ONLINE,
    SLEEP_MODEL_MATTER_ICD,
    TRANSPORT_MATTER,
    ConnectivityState,
    WeatherMeasurements,
    build_state_topic,
)
from rig.local_pubsub import GreengrassLocalPubSub, LocalPubSub
from rig.sparkplug import utc_timestamp_ms

LOGGER = logging.getLogger("weather_rig.matter_watch")
DEFAULT_ADAPTER_ID = "weather-matter-watch"
DEFAULT_WATCH_BINARY = "weather-matter-watch"


@dataclass(slots=True, frozen=True)
class WeatherMatterWatchConfig:
    thing_name: str
    matter_node_id: str
    watch_binary: str = DEFAULT_WATCH_BINARY
    chip_tool: str = "chip-tool"
    chip_tool_storage_dir: str = ""
    adapter_id: str = DEFAULT_ADAPTER_ID
    sample_interval_seconds: float = 30.0
    temperature_endpoint: int = 1
    humidity_endpoint: int = 2
    pressure_endpoint: int = 3
    power_endpoint: int = 0


def _optional_number(payload: dict[str, Any], name: str) -> float | None:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _optional_int(payload: dict[str, Any], name: str) -> int | None:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def state_from_watcher_payload(
    payload: dict[str, Any],
    *,
    config: WeatherMatterWatchConfig,
    seq: int,
) -> ConnectivityState:
    online = payload.get("status") == "online"
    weather = (
        WeatherMeasurements(
            measured_temperature=_optional_number(payload, "measuredTemperature"),
            measured_pressure=_optional_number(payload, "measuredPressure"),
            measured_humidity=_optional_number(payload, "measuredHumidity"),
        )
        if online
        else None
    )
    return ConnectivityState(
        adapter_id=config.adapter_id,
        thing_name=config.thing_name,
        transport=TRANSPORT_MATTER,
        native_identity={
            "matterNodeId": config.matter_node_id,
            "endpoints": {
                "temperature": config.temperature_endpoint,
                "humidity": config.humidity_endpoint,
                "pressure": config.pressure_endpoint,
                "power": config.power_endpoint,
            },
        },
        presence=PRESENCE_ONLINE if online else PRESENCE_OFFLINE,
        control_availability=CONTROL_UNAVAILABLE,
        power=None,
        sleep_model=SLEEP_MODEL_MATTER_ICD,
        battery_mv=_optional_int(payload, "batteryMv") if online else None,
        observed_at_ms=_optional_int(payload, "observedAtMs") or utc_timestamp_ms(),
        seq=seq,
        weather=weather,
    )


def _watch_binary_path(raw_path: str) -> str:
    candidate = Path(raw_path)
    if candidate.is_file():
        return str(candidate)
    return raw_path


def _build_watcher_argv(config: WeatherMatterWatchConfig) -> list[str]:
    argv = [
        _watch_binary_path(config.watch_binary),
        "--chip-tool",
        config.chip_tool,
        "--node-id",
        config.matter_node_id,
        "--interval",
        str(config.sample_interval_seconds),
        "--temperature-endpoint",
        str(config.temperature_endpoint),
        "--humidity-endpoint",
        str(config.humidity_endpoint),
        "--pressure-endpoint",
        str(config.pressure_endpoint),
        "--power-endpoint",
        str(config.power_endpoint),
    ]
    if config.chip_tool_storage_dir:
        argv.extend(["--storage-directory", config.chip_tool_storage_dir])
    return argv


async def publish_watcher_line(
    line: str,
    *,
    config: WeatherMatterWatchConfig,
    bus: LocalPubSub,
    seq: int,
) -> None:
    payload = json.loads(line)
    if not isinstance(payload, dict):
        raise ValueError("weather matter watcher output must be a JSON object")
    state = state_from_watcher_payload(payload, config=config, seq=seq)
    await bus.publish(build_state_topic(config.thing_name), state.to_json())


async def run_weather_matter_watch(
    *,
    config: WeatherMatterWatchConfig,
    bus: LocalPubSub,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    if not config.thing_name:
        LOGGER.info("Weather Matter watch is idle because WEATHER_THING_NAME is not configured")
        await _wait_forever(shutdown_event)
        return
    if not config.matter_node_id:
        LOGGER.info("Weather Matter watch is idle because WEATHER_MATTER_NODE_ID is not configured")
        await _wait_forever(shutdown_event)
        return

    argv = _build_watcher_argv(config)
    LOGGER.info("Starting weather Matter watcher argv=%s", argv)
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_task = asyncio.create_task(_log_stderr(process))
    seq = 0
    try:
        assert process.stdout is not None
        while shutdown_event is None or not shutdown_event.is_set():
            raw_line = await process.stdout.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            seq += 1
            try:
                await publish_watcher_line(line, config=config, bus=bus, seq=seq)
            except Exception:
                LOGGER.exception("Ignoring invalid weather Matter watcher output line=%r", line)
    finally:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()
        stderr_task.cancel()
        await asyncio.gather(stderr_task, return_exceptions=True)


async def _log_stderr(process: asyncio.subprocess.Process) -> None:
    assert process.stderr is not None
    while True:
        raw_line = await process.stderr.readline()
        if not raw_line:
            return
        LOGGER.warning("weather-matter-watch: %s", raw_line.decode("utf-8", errors="replace").rstrip())


async def _wait_forever(shutdown_event: asyncio.Event | None) -> None:
    if shutdown_event is None:
        await asyncio.Future()
    else:
        await shutdown_event.wait()


def _env_text(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    return int(value, 0)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="weather-rig-matter-watch",
        description="Observe a commissioned Matter weather node and publish local txing connectivity state.",
    )
    parser.add_argument("--thing-name", default=_env_text("WEATHER_THING_NAME", _env_text("THING_NAME")))
    parser.add_argument("--matter-node-id", default=_env_text("WEATHER_MATTER_NODE_ID"))
    parser.add_argument("--watch-binary", default=_env_text("WEATHER_MATTER_WATCH_BINARY", DEFAULT_WATCH_BINARY))
    parser.add_argument("--chip-tool", default=_env_text("WEATHER_CHIP_TOOL", "chip-tool"))
    parser.add_argument("--chip-tool-storage-dir", default=_env_text("WEATHER_CHIP_TOOL_STORAGE_DIR"))
    parser.add_argument("--adapter-id", default=_env_text("WEATHER_ADAPTER_ID", DEFAULT_ADAPTER_ID))
    parser.add_argument("--sample-interval", type=float, default=float(_env_text("WEATHER_SAMPLE_INTERVAL_SECONDS", "30")))
    parser.add_argument("--temperature-endpoint", type=int, default=_env_int("WEATHER_TEMPERATURE_ENDPOINT", 1))
    parser.add_argument("--humidity-endpoint", type=int, default=_env_int("WEATHER_HUMIDITY_ENDPOINT", 2))
    parser.add_argument("--pressure-endpoint", type=int, default=_env_int("WEATHER_PRESSURE_ENDPOINT", 3))
    parser.add_argument("--power-endpoint", type=int, default=_env_int("WEATHER_POWER_ENDPOINT", 0))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def _runner() -> None:
        loop = asyncio.get_running_loop()
        shutdown_event = asyncio.Event()

        def _request_shutdown() -> None:
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _request_shutdown)
            except NotImplementedError:
                break

        bus = GreengrassLocalPubSub()
        try:
            await run_weather_matter_watch(
                config=WeatherMatterWatchConfig(
                    thing_name=args.thing_name,
                    matter_node_id=args.matter_node_id,
                    watch_binary=args.watch_binary,
                    chip_tool=args.chip_tool,
                    chip_tool_storage_dir=args.chip_tool_storage_dir,
                    adapter_id=args.adapter_id,
                    sample_interval_seconds=args.sample_interval,
                    temperature_endpoint=args.temperature_endpoint,
                    humidity_endpoint=args.humidity_endpoint,
                    pressure_endpoint=args.pressure_endpoint,
                    power_endpoint=args.power_endpoint,
                ),
                bus=bus,
                shutdown_event=shutdown_event,
            )
        finally:
            bus.close()

    asyncio.run(_runner())


if __name__ == "__main__":
    main()
