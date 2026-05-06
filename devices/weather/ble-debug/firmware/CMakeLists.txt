cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(txing_weather_ble_debug)

target_sources(app PRIVATE
  src/main.c
  src/weather_battery.c
  src/weather_bme280.c
  src/weather_protocol.c
)
