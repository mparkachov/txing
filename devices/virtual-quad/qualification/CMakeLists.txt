cmake_minimum_required(VERSION 3.21)
project(txing_virtual_quad_qualification LANGUAGES CXX)

set(TXING_KVS_HEADLESS ON)
set(TXING_KVS_GRPC_BRIDGE OFF)
set(TXING_KVS_PATCH_WSS_WRITE ON)
set(BUILD_TESTING OFF)
add_subdirectory(../../common/board/kvs_master kvs-master EXCLUDE_FROM_ALL)

find_package(PkgConfig REQUIRED)
pkg_check_modules(GST REQUIRED IMPORTED_TARGET gstreamer-app-1.0)
add_executable(virtual-quad-media media.cpp camera.cpp)
target_link_libraries(virtual-quad-media PRIVATE txing_board_kvs_master_lib PkgConfig::GST)
target_compile_options(virtual-quad-media PRIVATE -Wall -Wextra -Wpedantic)

add_executable(virtual-quad-camera-test camera_test.cpp camera.cpp)
target_compile_features(virtual-quad-camera-test PRIVATE cxx_std_17)
target_compile_options(virtual-quad-camera-test PRIVATE -Wall -Wextra -Wpedantic)
