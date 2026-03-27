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
option(
  TXING_KVS_USE_SYSTEM_DEPENDENCIES
  "Build the AWS KVS WebRTC SDK against distro-provided dependencies instead of the vendored third-party build"
  OFF
)

set(
  _txing_kvs_default_sdk_source_dir
  "${CMAKE_CURRENT_SOURCE_DIR}/../aws-kvs-webrtc-sdk"
)
set(
  _txing_kvs_default_sdk_install_dir
  "${_txing_kvs_default_sdk_source_dir}/install"
)

set(
  TXING_KVS_WEBRTC_SDK_DIR
  "${_txing_kvs_default_sdk_source_dir}"
  CACHE PATH
  "Local checkout of amazon-kinesis-video-streams-webrtc-sdk-c"
)
set(
  TXING_KVS_WEBRTC_SDK_INSTALL_DIR
  "${_txing_kvs_default_sdk_install_dir}"
  CACHE PATH
  "Install prefix of the locally built amazon-kinesis-video-streams-webrtc-sdk-c"
)

add_library(
  txing_board_kvs_master_lib
  STATIC
    src/aws_env.cpp
    src/config.cpp
    src/markers.cpp
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

find_package(PkgConfig QUIET)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  if(NOT PKG_CONFIG_FOUND)
    message(FATAL_ERROR "pkg-config is required to build txing-board-kvs-master on Linux")
  endif()
  pkg_check_modules(LIBCAMERA QUIET libcamera)
  if(NOT LIBCAMERA_FOUND)
    message(FATAL_ERROR "libcamera development files are required on Linux; install libcamera-dev")
  endif()
endif()

if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  target_sources(txing_board_kvs_master_lib PRIVATE src/video_capturer_libcamera.cpp)
  target_include_directories(txing_board_kvs_master_lib PRIVATE ${LIBCAMERA_INCLUDE_DIRS})
  target_compile_options(txing_board_kvs_master_lib PRIVATE ${LIBCAMERA_CFLAGS_OTHER})
  target_link_libraries(txing_board_kvs_master_lib PRIVATE ${LIBCAMERA_LIBRARIES})
  target_compile_definitions(txing_board_kvs_master_lib PRIVATE TXING_KVS_HAS_LIBCAMERA=1)
else()
  target_sources(txing_board_kvs_master_lib PRIVATE src/video_capturer_stub.cpp)
  target_compile_definitions(txing_board_kvs_master_lib PRIVATE TXING_KVS_HAS_LIBCAMERA=0)
endif()

function(txing_find_local_or_system_library output_var)
  set(options REQUIRED)
  set(oneValueArgs FRIENDLY_NAME)
  set(multiValueArgs NAMES)
  cmake_parse_arguments(TXING_FIND "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})

  find_library(
    ${output_var}
    NAMES ${TXING_FIND_NAMES}
    PATHS
      "${TXING_KVS_WEBRTC_SDK_INSTALL_DIR}/lib"
      "${TXING_KVS_WEBRTC_SDK_INSTALL_DIR}/lib64"
    NO_DEFAULT_PATH
  )

  if(NOT ${output_var})
    find_library(${output_var} NAMES ${TXING_FIND_NAMES})
  endif()

  if(NOT ${output_var} AND TXING_FIND_REQUIRED)
    message(FATAL_ERROR
      "Required library '${TXING_FIND_FRIENDLY_NAME}' was not found. "
      "Build the local AWS SDK install first with `just build-aws-sdk`."
    )
  endif()
endfunction()

if(TXING_KVS_REAL_SDK)
  if(NOT EXISTS "${TXING_KVS_WEBRTC_SDK_INSTALL_DIR}/include/com/amazonaws/kinesis/video/webrtcclient/Include.h")
    message(FATAL_ERROR
      "AWS KVS WebRTC SDK install not found at '${TXING_KVS_WEBRTC_SDK_INSTALL_DIR}'. "
      "Run `just build-aws-sdk` from the board directory first."
    )
  endif()

  if(TXING_KVS_USE_SYSTEM_DEPENDENCIES AND CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(WARNING
      "TXING_KVS_USE_SYSTEM_DEPENDENCIES=ON assumes the separately built local AWS SDK install "
      "was configured with BUILD_DEPENDENCIES=OFF. Debian Trixie ships newer OpenSSL and libsrtp2 "
      "packages than AWS's documented system dependency window, so this mode remains an explicit override."
    )
  endif()

  find_package(Threads REQUIRED)
  find_package(ZLIB QUIET)
  set(OPENSSL_USE_STATIC_LIBS FALSE)
  find_package(OpenSSL REQUIRED)

  txing_find_local_or_system_library(
    TXING_KVS_WEBRTC_CLIENT_LIBRARY
    REQUIRED
    FRIENDLY_NAME "kvsWebrtcClient"
    NAMES kvsWebrtcClient libkvsWebrtcClient.a
  )
  txing_find_local_or_system_library(
    TXING_KVS_WEBRTC_SIGNALING_CLIENT_LIBRARY
    REQUIRED
    FRIENDLY_NAME "kvsWebrtcSignalingClient"
    NAMES kvsWebrtcSignalingClient libkvsWebrtcSignalingClient.a
  )
  txing_find_local_or_system_library(
    TXING_KVS_COMMON_LWS_LIBRARY
    REQUIRED
    FRIENDLY_NAME "kvsCommonLws"
    NAMES kvsCommonLws libkvsCommonLws.a
  )
  txing_find_local_or_system_library(
    TXING_KVS_PIC_UTILS_LIBRARY
    REQUIRED
    FRIENDLY_NAME "kvspicUtils"
    NAMES kvspicUtils libkvspicUtils.a
  )
  txing_find_local_or_system_library(
    TXING_KVS_PIC_STATE_LIBRARY
    REQUIRED
    FRIENDLY_NAME "kvspicState"
    NAMES kvspicState libkvspicState.a
  )
  txing_find_local_or_system_library(
    TXING_KVS_WEBSOCKETS_LIBRARY
    REQUIRED
    FRIENDLY_NAME "websockets"
    NAMES websockets libwebsockets.a
  )
  txing_find_local_or_system_library(
    TXING_KVS_SRTP_LIBRARY
    REQUIRED
    FRIENDLY_NAME "srtp2"
    NAMES srtp2 libsrtp2.a
  )
  txing_find_local_or_system_library(
    TXING_KVS_USRSCTP_LIBRARY
    REQUIRED
    FRIENDLY_NAME "usrsctp"
    NAMES usrsctp libusrsctp.a
  )
  find_library(TXING_KVS_CAP_LIBRARY NAMES cap)

  target_sources(
    txing_board_kvs_master_lib
    PRIVATE
      src/kvs_session_real.cpp
  )
  target_compile_definitions(txing_board_kvs_master_lib PRIVATE TXING_KVS_REAL_SDK=1)
  target_include_directories(
    txing_board_kvs_master_lib
    PRIVATE
      "${TXING_KVS_WEBRTC_SDK_INSTALL_DIR}/include"
  )
  target_link_libraries(
    txing_board_kvs_master_lib
    PRIVATE
      "${TXING_KVS_WEBRTC_CLIENT_LIBRARY}"
      "${TXING_KVS_WEBRTC_SIGNALING_CLIENT_LIBRARY}"
      "${TXING_KVS_COMMON_LWS_LIBRARY}"
      "${TXING_KVS_PIC_UTILS_LIBRARY}"
      "${TXING_KVS_PIC_STATE_LIBRARY}"
      "${TXING_KVS_WEBSOCKETS_LIBRARY}"
      "${TXING_KVS_SRTP_LIBRARY}"
      "${TXING_KVS_USRSCTP_LIBRARY}"
      OpenSSL::SSL
      OpenSSL::Crypto
      Threads::Threads
      m
      "${CMAKE_DL_LIBS}"
  )
  if(ZLIB_FOUND)
    target_link_libraries(txing_board_kvs_master_lib PRIVATE ZLIB::ZLIB)
  endif()
  if(TXING_KVS_CAP_LIBRARY)
    target_link_libraries(txing_board_kvs_master_lib PRIVATE "${TXING_KVS_CAP_LIBRARY}")
  endif()
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
