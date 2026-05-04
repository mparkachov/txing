#
# Copyright (c) 2026 txing contributors
#
# SPDX-License-Identifier: Apache-2.0
#

cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})

project(txing-weather-ble-connected-idle)

set(TXING_WEATHER_FACTORY_DATA_ADDR "0x000f0000" CACHE STRING "Address of txing weather factory data")

target_sources(app PRIVATE
  src/main.cpp
  src/weather_ble_protocol.cpp
  src/weather_factory_data.cpp
  src/weather_device.cpp
)

target_compile_options(app PRIVATE $<$<COMPILE_LANGUAGE:CXX>:-std=gnu++20>)
target_compile_definitions(app PRIVATE
  TXING_WEATHER_FACTORY_DATA_ADDR=${TXING_WEATHER_FACTORY_DATA_ADDR}
)
