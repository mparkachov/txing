cmake_minimum_required(VERSION 3.13.1)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(txing_tbot)

set(TXING_LM20A_COMMON_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../../common/mcu/xiao_nrf54lm20a)

target_sources(app PRIVATE ${TXING_LM20A_COMMON_DIR}/src/thread_device.c)
target_include_directories(app PRIVATE ../src)
