if(DEFINED ENV{POWER_BOARD_ROOT})
	set(BOARD_ROOT "$ENV{POWER_BOARD_ROOT}")
endif()

cmake_minimum_required(VERSION 3.13.1)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(txing_power)

target_sources(app PRIVATE ../src/main.c)

set(POWER_ADV_INTERVAL "0x0800" CACHE STRING "BLE advertising interval in 0.625 ms units")
set(POWER_ADV_TX_POWER_DBM "4" CACHE STRING "BLE advertising TX power in dBm")
set(POWER_ADV_CONNECTABLE "1" CACHE STRING "Enable connectable advertising")
set(POWER_ADV_SCANNABLE "1" CACHE STRING "Enable scannable advertising")
set(POWER_ADV_INCLUDE_UUID "1" CACHE STRING "Include weather service UUID in scan response")
set(POWER_GATT "1" CACHE STRING "Enable weather GATT wake and battery debug service")

target_compile_definitions(app PRIVATE
	POWER_ADV_INTERVAL=${POWER_ADV_INTERVAL}
	POWER_ADV_TX_POWER_DBM=${POWER_ADV_TX_POWER_DBM}
	POWER_ADV_CONNECTABLE=${POWER_ADV_CONNECTABLE}
	POWER_ADV_SCANNABLE=${POWER_ADV_SCANNABLE}
	POWER_ADV_INCLUDE_UUID=${POWER_ADV_INCLUDE_UUID}
	POWER_GATT=${POWER_GATT}
)
