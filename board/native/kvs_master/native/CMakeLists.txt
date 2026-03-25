cmake_minimum_required(VERSION 3.21)

project(txing_kvs_shim LANGUAGES C)

option(TXING_KVS_REAL_SDK "Build the real KVS shim against the AWS WebRTC C SDK" OFF)

include(GNUInstallDirs)

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

  add_subdirectory("${KVS_WEBRTC_SDK_SOURCE_DIR}" "${CMAKE_CURRENT_BINARY_DIR}/kvs-webrtc-sdk")

  add_library(
    txing_kvs_shim
    SHARED
    txing_kvs_shim.c
    "${KVS_WEBRTC_SDK_SOURCE_DIR}/samples/common/Common.c"
  )
  target_include_directories(
    txing_kvs_shim
    PRIVATE
      "${KVS_WEBRTC_SDK_SOURCE_DIR}"
      "${KVS_WEBRTC_SDK_SOURCE_DIR}/samples/common"
      "${KVS_WEBRTC_SDK_SOURCE_DIR}/src/include"
      "${OPEN_SRC_INSTALL_PREFIX}/include"
  )
  target_link_libraries(
    txing_kvs_shim
    PRIVATE
      kvsWebrtcClient
      kvsWebrtcSignalingClient
      kvsCommonLws
      kvspicUtils
      websockets
  )
else()
  add_library(txing_kvs_shim SHARED txing_kvs_shim_stub.c)
endif()

target_include_directories(txing_kvs_shim PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
set_target_properties(txing_kvs_shim PROPERTIES OUTPUT_NAME txing_kvs_shim)

install(
  TARGETS txing_kvs_shim
  LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
  ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
  RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
)
