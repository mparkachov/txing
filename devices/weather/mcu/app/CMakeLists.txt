#
# Copyright (c) 2026 txing contributors
#
# SPDX-License-Identifier: Apache-2.0
#

cmake_minimum_required(VERSION 3.20.0)

set(TXING_MATTER_ROOT ${CMAKE_CURRENT_LIST_DIR}/../../../common/mcu/matter)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})

project(txing-weather-matter)

include(${TXING_MATTER_ROOT}/cmake/txing_matter.cmake)

txing_matter_configure_app(
  ZAP_FILE ${CMAKE_CURRENT_LIST_DIR}/src/default_zap/weather-station.zap
  IDL_FILE ${CMAKE_CURRENT_LIST_DIR}/src/default_zap/weather-station.matter
  ZAP_GENERATED_DIR ${ZEPHYR_NRF_MODULE_DIR}/applications/matter_weather_station/src/default_zap/zap-generated
  APP_SOURCES
    src/main.cpp
    src/weather_device.cpp
)
