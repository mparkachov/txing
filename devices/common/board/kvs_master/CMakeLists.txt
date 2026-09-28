cmake_minimum_required(VERSION 3.21)

project(txing_board_kvs_master LANGUAGES C CXX)

include(GNUInstallDirs)
include(CTest)
include(ExternalProject)

# The KVS master is one board-wide artifact. Device identity, capabilities, and
# bridge socket paths are runtime configuration supplied by the service.
set(_txing_kvs_lib "txing_board_kvs_master_lib")
set(_txing_kvs_bin "txing-board-kvs-master")

if(APPLE)
  enable_language(OBJCXX)
  # Homebrew kegs are not on the default CMake search paths on macOS.
  execute_process(
    COMMAND brew --prefix
    RESULT_VARIABLE _txing_brew_result
    OUTPUT_VARIABLE TXING_KVS_HOMEBREW_PREFIX
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
  )
  if(_txing_brew_result EQUAL 0 AND EXISTS "${TXING_KVS_HOMEBREW_PREFIX}")
    list(APPEND CMAKE_PREFIX_PATH
      "${TXING_KVS_HOMEBREW_PREFIX}"
      "${TXING_KVS_HOMEBREW_PREFIX}/opt/openssl@3"
    )
  endif()
endif()

set(_txing_kvs_real_sdk_default OFF)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  set(_txing_kvs_real_sdk_default ON)
endif()

option(
  TXING_KVS_REAL_SDK
  "Build ${_txing_kvs_bin} against the AWS KVS WebRTC C SDK"
  ${_txing_kvs_real_sdk_default}
)
option(
  TXING_KVS_GRPC_BRIDGE
  "Build ${_txing_kvs_bin} with the daemon BoardVideoBridge gRPC client"
  OFF
)

include("${CMAKE_CURRENT_SOURCE_DIR}/../../kvs/cmake/AwsKvsWebRtc.cmake")

set(
  TXING_BOARD_KVS_MASTER_VERSION
  ""
  CACHE STRING
  "Release version injected at build time from release/versions/kvs-master"
)

add_library(
  ${_txing_kvs_lib}
  STATIC
    src/aws_env.cpp
    src/config.cpp
    src/markers.cpp
    src/runtime.cpp
)

target_include_directories(
  ${_txing_kvs_lib}
  PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
)

target_compile_features(${_txing_kvs_lib} PUBLIC cxx_std_17)
target_compile_definitions(
  ${_txing_kvs_lib}
  PUBLIC
    TXING_BOARD_KVS_MASTER_BINARY_NAME="${_txing_kvs_bin}"
)
if(NOT TXING_BOARD_KVS_MASTER_VERSION STREQUAL "")
  target_compile_definitions(
    ${_txing_kvs_lib}
    PUBLIC
      TXING_BOARD_KVS_MASTER_VERSION="${TXING_BOARD_KVS_MASTER_VERSION}"
  )
endif()
target_compile_options(
  ${_txing_kvs_lib}
  PRIVATE
    -Wall
    -Wextra
    -Wpedantic
)

if(TXING_KVS_GRPC_BRIDGE)
  # Both Homebrew and Alpine gRPC export protobuf config targets. Resolving
  # protobuf in module mode first creates a partial duplicate target set.
  find_package(Protobuf CONFIG REQUIRED)
  find_package(gRPC CONFIG REQUIRED)
  find_program(GRPC_CPP_PLUGIN_EXECUTABLE grpc_cpp_plugin REQUIRED)

  get_filename_component(
    TXING_BOARD_VIDEO_PROTO_ROOT
    "${CMAKE_CURRENT_SOURCE_DIR}/../proto"
    ABSOLUTE
  )
  set(
    TXING_BOARD_VIDEO_PROTO_RELATIVE
    "txing/board/board_video/v1/board_video.proto"
  )
  set(
    TXING_BOARD_MAVLINK_BRIDGE_PROTO_RELATIVE
    "txing/board/mavlink_bridge/v1/mavlink_bridge.proto"
  )
  set(
    TXING_BOARD_VIDEO_PROTO
    "${TXING_BOARD_VIDEO_PROTO_ROOT}/${TXING_BOARD_VIDEO_PROTO_RELATIVE}"
  )
  if(NOT EXISTS "${TXING_BOARD_VIDEO_PROTO}")
    message(FATAL_ERROR
      "BoardVideoBridge proto not found at '${TXING_BOARD_VIDEO_PROTO}'. "
      "The repository checkout must include devices/common/board/proto."
    )
  endif()
  set(TXING_BOARD_VIDEO_PROTO_GEN_DIR
      "${CMAKE_CURRENT_BINARY_DIR}/generated")
  set(TXING_BOARD_VIDEO_PROTO_SRCS
      "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}/txing/board/board_video/v1/board_video.pb.cc"
      "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}/txing/board/board_video/v1/board_video.grpc.pb.cc")
  set(TXING_BOARD_VIDEO_PROTO_HDRS
      "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}/txing/board/board_video/v1/board_video.pb.h"
      "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}/txing/board/board_video/v1/board_video.grpc.pb.h")

  add_custom_command(
    OUTPUT ${TXING_BOARD_VIDEO_PROTO_SRCS} ${TXING_BOARD_VIDEO_PROTO_HDRS}
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}"
    COMMAND protobuf::protoc
      "--proto_path=${TXING_BOARD_VIDEO_PROTO_ROOT}"
      "--cpp_out=${TXING_BOARD_VIDEO_PROTO_GEN_DIR}"
      "--grpc_out=${TXING_BOARD_VIDEO_PROTO_GEN_DIR}"
      "--plugin=protoc-gen-grpc=${GRPC_CPP_PLUGIN_EXECUTABLE}"
      "${TXING_BOARD_VIDEO_PROTO_RELATIVE}"
    DEPENDS "${TXING_BOARD_VIDEO_PROTO}"
    WORKING_DIRECTORY "${TXING_BOARD_VIDEO_PROTO_ROOT}"
    VERBATIM
  )
  add_library(txing_board_video_bridge_proto OBJECT ${TXING_BOARD_VIDEO_PROTO_SRCS})
  target_include_directories(txing_board_video_bridge_proto PUBLIC "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}")
  target_link_libraries(txing_board_video_bridge_proto PUBLIC protobuf::libprotobuf gRPC::grpc++)
  target_compile_features(txing_board_video_bridge_proto PUBLIC cxx_std_17)

  set(
    TXING_BOARD_MAVLINK_BRIDGE_PROTO
    "${TXING_BOARD_VIDEO_PROTO_ROOT}/${TXING_BOARD_MAVLINK_BRIDGE_PROTO_RELATIVE}"
  )
  if(NOT EXISTS "${TXING_BOARD_MAVLINK_BRIDGE_PROTO}")
    message(FATAL_ERROR
      "BoardMavlinkBridge proto not found at '${TXING_BOARD_MAVLINK_BRIDGE_PROTO}'. "
      "The repository checkout must include devices/common/board/proto."
    )
  endif()
  set(TXING_BOARD_MAVLINK_BRIDGE_PROTO_SRCS
      "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}/txing/board/mavlink_bridge/v1/mavlink_bridge.pb.cc"
      "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}/txing/board/mavlink_bridge/v1/mavlink_bridge.grpc.pb.cc")
  set(TXING_BOARD_MAVLINK_BRIDGE_PROTO_HDRS
      "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}/txing/board/mavlink_bridge/v1/mavlink_bridge.pb.h"
      "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}/txing/board/mavlink_bridge/v1/mavlink_bridge.grpc.pb.h")
  add_custom_command(
    OUTPUT ${TXING_BOARD_MAVLINK_BRIDGE_PROTO_SRCS} ${TXING_BOARD_MAVLINK_BRIDGE_PROTO_HDRS}
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}"
    COMMAND protobuf::protoc
      "--proto_path=${TXING_BOARD_VIDEO_PROTO_ROOT}"
      "--cpp_out=${TXING_BOARD_VIDEO_PROTO_GEN_DIR}"
      "--grpc_out=${TXING_BOARD_VIDEO_PROTO_GEN_DIR}"
      "--plugin=protoc-gen-grpc=${GRPC_CPP_PLUGIN_EXECUTABLE}"
      "${TXING_BOARD_MAVLINK_BRIDGE_PROTO_RELATIVE}"
    DEPENDS "${TXING_BOARD_MAVLINK_BRIDGE_PROTO}"
    WORKING_DIRECTORY "${TXING_BOARD_VIDEO_PROTO_ROOT}"
    VERBATIM
  )
  add_library(txing_board_mavlink_bridge_proto OBJECT ${TXING_BOARD_MAVLINK_BRIDGE_PROTO_SRCS})
  target_include_directories(txing_board_mavlink_bridge_proto PUBLIC "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}")
  target_link_libraries(txing_board_mavlink_bridge_proto PUBLIC protobuf::libprotobuf gRPC::grpc++)
  target_compile_features(txing_board_mavlink_bridge_proto PUBLIC cxx_std_17)

  target_sources(
    ${_txing_kvs_lib}
    PRIVATE
      src/board_video_bridge_grpc.cpp
      src/board_mavlink_bridge_grpc.cpp
      $<TARGET_OBJECTS:txing_board_video_bridge_proto>
      $<TARGET_OBJECTS:txing_board_mavlink_bridge_proto>
  )
  target_compile_definitions(${_txing_kvs_lib} PRIVATE TXING_KVS_GRPC_BRIDGE=1)
  target_include_directories(${_txing_kvs_lib} PRIVATE "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}")
  target_link_libraries(${_txing_kvs_lib} PRIVATE protobuf::libprotobuf gRPC::grpc++)
  add_dependencies(${_txing_kvs_lib} txing_board_video_bridge_proto txing_board_mavlink_bridge_proto)
else()
  target_sources(${_txing_kvs_lib} PRIVATE src/board_video_bridge_stub.cpp src/board_mavlink_bridge_stub.cpp)
  target_compile_definitions(${_txing_kvs_lib} PRIVATE TXING_KVS_GRPC_BRIDGE=0)
endif()

find_package(PkgConfig QUIET)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  if(NOT PKG_CONFIG_FOUND)
    message(FATAL_ERROR "pkg-config is required to build ${_txing_kvs_bin} on Linux")
  endif()
  pkg_check_modules(LIBCAMERA QUIET libcamera)
  if(NOT LIBCAMERA_FOUND)
    message(FATAL_ERROR "libcamera development files are required on Linux; install libcamera-dev")
  endif()
endif()

if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  target_sources(${_txing_kvs_lib} PRIVATE src/video_capturer_libcamera.cpp)
  target_include_directories(${_txing_kvs_lib} PRIVATE ${LIBCAMERA_INCLUDE_DIRS})
  target_compile_options(${_txing_kvs_lib} PRIVATE ${LIBCAMERA_CFLAGS_OTHER})
  target_link_libraries(${_txing_kvs_lib} PRIVATE ${LIBCAMERA_LIBRARIES})
  target_compile_definitions(${_txing_kvs_lib} PRIVATE TXING_KVS_HAS_LIBCAMERA=1)
elseif(APPLE)
  target_sources(${_txing_kvs_lib} PRIVATE src/video_capturer_avfoundation.mm)
  set_source_files_properties(
    src/video_capturer_avfoundation.mm
    PROPERTIES COMPILE_OPTIONS "-fobjc-arc"
  )
  set_target_properties(
    ${_txing_kvs_lib}
    PROPERTIES
      OBJCXX_STANDARD 17
      OBJCXX_STANDARD_REQUIRED ON
  )
  target_compile_definitions(${_txing_kvs_lib} PRIVATE TXING_KVS_HAS_LIBCAMERA=0)
  target_link_libraries(
    ${_txing_kvs_lib}
    PRIVATE
      "-framework AVFoundation"
      "-framework CoreMedia"
      "-framework CoreVideo"
      "-framework VideoToolbox"
      "-framework Foundation"
  )
else()
  target_sources(${_txing_kvs_lib} PRIVATE src/video_capturer_stub.cpp)
  target_compile_definitions(${_txing_kvs_lib} PRIVATE TXING_KVS_HAS_LIBCAMERA=0)
endif()

if(TXING_KVS_REAL_SDK)
  txing_link_kvs_sdk(${_txing_kvs_lib})
  target_sources(${_txing_kvs_lib} PRIVATE src/kvs_session_real.cpp)
  target_compile_definitions(${_txing_kvs_lib} PRIVATE TXING_KVS_REAL_SDK=1
    TXING_KVS_SYSTEM_CA_CERT_PATH=\"${TXING_KVS_SYSTEM_CA_CERT_PATH}\")
else()
  target_sources(${_txing_kvs_lib} PRIVATE src/kvs_session_stub.cpp)
  target_compile_definitions(${_txing_kvs_lib} PRIVATE TXING_KVS_REAL_SDK=0)
endif()

add_executable(${_txing_kvs_bin} src/main.cpp)
target_link_libraries(${_txing_kvs_bin} PRIVATE ${_txing_kvs_lib})

install(TARGETS ${_txing_kvs_bin} RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")

if(BUILD_TESTING)
  add_executable(${_txing_kvs_bin}-tests tests/test_main.cpp)
  target_link_libraries(${_txing_kvs_bin}-tests PRIVATE ${_txing_kvs_lib})
  add_test(NAME ${_txing_kvs_bin}-tests COMMAND ${_txing_kvs_bin}-tests)
endif()
