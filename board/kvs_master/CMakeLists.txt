cmake_minimum_required(VERSION 3.21)

project(txing_board_kvs_master LANGUAGES C CXX)

include(GNUInstallDirs)
include(CTest)

set(_txing_kvs_real_sdk_default OFF)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  set(_txing_kvs_real_sdk_default ON)
endif()

option(
  TXING_KVS_REAL_SDK
  "Build txing-board-kvs-master against the AWS KVS WebRTC C SDK"
  ${_txing_kvs_real_sdk_default}
)

set(TXING_KVS_WEBRTC_SDK_DIR "" CACHE PATH "Optional local checkout of amazon-kinesis-video-streams-webrtc-sdk-c")

add_library(
  txing_board_kvs_master_lib
  STATIC
    src/aws_env.cpp
    src/config.cpp
    src/h264.cpp
    src/markers.cpp
    src/rpicam.cpp
    src/runtime.cpp
)

target_include_directories(
  txing_board_kvs_master_lib
  PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
)

target_compile_features(txing_board_kvs_master_lib PUBLIC cxx_std_17)
target_compile_options(
  txing_board_kvs_master_lib
  PRIVATE
    -Wall
    -Wextra
    -Wpedantic
)

if(TXING_KVS_REAL_SDK)
  include(FetchContent)

  if(DEFINED TXING_KVS_WEBRTC_SDK_DIR AND NOT TXING_KVS_WEBRTC_SDK_DIR STREQUAL "")
    set(KVS_WEBRTC_SDK_SOURCE_DIR "${TXING_KVS_WEBRTC_SDK_DIR}")
  else()
    FetchContent_Declare(
      kvs_webrtc_sdk
      GIT_REPOSITORY https://github.com/awslabs/amazon-kinesis-video-streams-webrtc-sdk-c.git
      GIT_TAG        v1.17.0
      GIT_SHALLOW    TRUE
    )
    FetchContent_MakeAvailable(kvs_webrtc_sdk)
    set(KVS_WEBRTC_SDK_SOURCE_DIR "${kvs_webrtc_sdk_SOURCE_DIR}")
  endif()

  set(BUILD_SAMPLE OFF CACHE BOOL "" FORCE)
  set(BUILD_TEST OFF CACHE BOOL "" FORCE)
  set(BUILD_BENCHMARK OFF CACHE BOOL "" FORCE)
  set(BUILD_STATIC_LIBS ON CACHE BOOL "" FORCE)
  set(BUILD_DEPENDENCIES ON CACHE BOOL "" FORCE)
  set(USE_OPENSSL ON CACHE BOOL "" FORCE)
  set(USE_MBEDTLS OFF CACHE BOOL "" FORCE)
  set(OPEN_SRC_INSTALL_PREFIX "${CMAKE_CURRENT_BINARY_DIR}/open-source" CACHE PATH "" FORCE)

  add_subdirectory("${KVS_WEBRTC_SDK_SOURCE_DIR}" "${CMAKE_CURRENT_BINARY_DIR}/kvs-webrtc-sdk")

  target_sources(
    txing_board_kvs_master_lib
    PRIVATE
      src/kvs_session_real.cpp
      "${KVS_WEBRTC_SDK_SOURCE_DIR}/samples/common/Common.c"
  )
  target_compile_definitions(txing_board_kvs_master_lib PRIVATE TXING_KVS_REAL_SDK=1)
  target_include_directories(
    txing_board_kvs_master_lib
    PRIVATE
      "${KVS_WEBRTC_SDK_SOURCE_DIR}"
      "${KVS_WEBRTC_SDK_SOURCE_DIR}/samples/common"
      "${KVS_WEBRTC_SDK_SOURCE_DIR}/src/include"
      "${OPEN_SRC_INSTALL_PREFIX}/include"
  )
  target_link_libraries(
    txing_board_kvs_master_lib
    PRIVATE
      kvsWebrtcClient
      kvsWebrtcSignalingClient
      kvsCommonLws
      kvspicUtils
      websockets
  )
else()
  target_sources(txing_board_kvs_master_lib PRIVATE src/kvs_session_stub.cpp)
  target_compile_definitions(txing_board_kvs_master_lib PRIVATE TXING_KVS_REAL_SDK=0)
endif()

add_executable(txing-board-kvs-master src/main.cpp)
target_link_libraries(txing-board-kvs-master PRIVATE txing_board_kvs_master_lib)

install(TARGETS txing-board-kvs-master RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")

if(BUILD_TESTING)
  add_executable(txing-board-kvs-master-tests tests/test_main.cpp)
  target_link_libraries(txing-board-kvs-master-tests PRIVATE txing_board_kvs_master_lib)
  add_test(NAME txing-board-kvs-master-tests COMMAND txing-board-kvs-master-tests)
endif()
