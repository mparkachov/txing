if(DEFINED ENV{POWER_BOARD_ROOT})
	set(BOARD_ROOT "$ENV{POWER_BOARD_ROOT}")
endif()

cmake_minimum_required(VERSION 3.13.1)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(txing_power)

target_sources(app PRIVATE ../src/main.c)
