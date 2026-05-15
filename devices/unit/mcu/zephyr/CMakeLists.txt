cmake_minimum_required(VERSION 3.13.1)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(txing_unit)

set(TXING_XIAO_NRF54L15_DIR ${CMAKE_CURRENT_LIST_DIR}/../../../common/mcu/xiao_nrf54l15)

target_include_directories(app PRIVATE ${TXING_XIAO_NRF54L15_DIR}/include)
target_sources(app PRIVATE
  ../src/main.c
  ${TXING_XIAO_NRF54L15_DIR}/src/redcon.c
)
