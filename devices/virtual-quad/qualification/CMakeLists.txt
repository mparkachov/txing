cmake_minimum_required(VERSION 3.21)
project(txing_virtual_quad_qualification LANGUAGES CXX)

set(TXING_KVS_HEADLESS ON)
set(TXING_KVS_GRPC_BRIDGE OFF)
set(BUILD_TESTING OFF)
add_subdirectory(../../common/board/kvs_master kvs-master EXCLUDE_FROM_ALL)

find_package(PkgConfig REQUIRED)
pkg_check_modules(GST REQUIRED IMPORTED_TARGET gstreamer-app-1.0)
add_executable(virtual-quad-media media.cpp)
target_link_libraries(virtual-quad-media PRIVATE txing_board_kvs_master_lib PkgConfig::GST)
target_compile_options(virtual-quad-media PRIVATE -Wall -Wextra -Wpedantic)
