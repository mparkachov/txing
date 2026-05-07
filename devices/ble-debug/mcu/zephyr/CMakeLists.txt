if(DEFINED ENV{BLE_DEBUG_BOARD_ROOT})
	set(BOARD_ROOT "$ENV{BLE_DEBUG_BOARD_ROOT}")
endif()

cmake_minimum_required(VERSION 3.13.1)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(txing_ble_debug)

target_sources(app PRIVATE ../src/main.c)

set(BLE_DEBUG_ADV_INTERVAL "0x4000" CACHE STRING "BLE advertising interval in 0.625 ms units")
set(BLE_DEBUG_ADV_TX_POWER_DBM "-46" CACHE STRING "BLE advertising TX power in dBm")
set(BLE_DEBUG_ADV_CONNECTABLE "0" CACHE STRING "Enable connectable advertising")
set(BLE_DEBUG_ADV_SCANNABLE "0" CACHE STRING "Enable scannable advertising")
set(BLE_DEBUG_ADV_INCLUDE_UUID "0" CACHE STRING "Include weather service UUID in scan response")
set(BLE_DEBUG_GATT "0" CACHE STRING "Enable weather GATT wake and battery debug service")

target_compile_definitions(app PRIVATE
	BLE_DEBUG_ADV_INTERVAL=${BLE_DEBUG_ADV_INTERVAL}
	BLE_DEBUG_ADV_TX_POWER_DBM=${BLE_DEBUG_ADV_TX_POWER_DBM}
	BLE_DEBUG_ADV_CONNECTABLE=${BLE_DEBUG_ADV_CONNECTABLE}
	BLE_DEBUG_ADV_SCANNABLE=${BLE_DEBUG_ADV_SCANNABLE}
	BLE_DEBUG_ADV_INCLUDE_UUID=${BLE_DEBUG_ADV_INCLUDE_UUID}
	BLE_DEBUG_GATT=${BLE_DEBUG_GATT}
)
