cmake_minimum_required(VERSION 3.21)

project(txing_board_hardware_worker LANGUAGES CXX)

include(GNUInstallDirs)
include(CTest)

# One implementation serves every board device type; the device profile selects
# the proto package, the binary name, and the release stream the version comes
# from. Nothing below may branch on the device type beyond these derivations.
set(
  TXING_BOARD_DEVICE_TYPE
  ""
  CACHE STRING
  "Board device type this build targets (for example: unit, cyberbrick)"
)
if(TXING_BOARD_DEVICE_TYPE STREQUAL "")
  message(FATAL_ERROR
    "TXING_BOARD_DEVICE_TYPE is required; pass -DTXING_BOARD_DEVICE_TYPE=<device>."
  )
endif()

option(
  TXING_HARDWARE_WORKER_GRPC
  "Build the board hardware worker gRPC server"
  ON
)
set(
  TXING_BOARD_HARDWARE_WORKER_VERSION
  ""
  CACHE STRING
  "Release version injected at build time from release/versions/<device>"
)

set(_txing_device "${TXING_BOARD_DEVICE_TYPE}")
set(_txing_worker_core "txing_${_txing_device}_hardware_worker_core")
set(_txing_worker_bin "txing-${_txing_device}-hardware-worker")

add_library(
  ${_txing_worker_core}
  STATIC
    src/config.cpp
    src/motor.cpp
)

target_include_directories(
  ${_txing_worker_core}
  PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
)
target_compile_features(${_txing_worker_core} PUBLIC cxx_std_17)
# Binary name and socket path stay per device: both appear in the board runbook
# and in the OpenRC service files already deployed on boards.
target_compile_definitions(
  ${_txing_worker_core}
  PUBLIC
    TXING_BOARD_HARDWARE_WORKER_BINARY_NAME="${_txing_worker_bin}"
    TXING_BOARD_HARDWARE_WORKER_SOCKET_PATH="/run/${_txing_worker_bin}/${_txing_device}-hardware.sock"
)
if(NOT TXING_BOARD_HARDWARE_WORKER_VERSION STREQUAL "")
  target_compile_definitions(
    ${_txing_worker_core}
    PUBLIC
      TXING_BOARD_HARDWARE_WORKER_VERSION="${TXING_BOARD_HARDWARE_WORKER_VERSION}"
  )
endif()
target_compile_options(
  ${_txing_worker_core}
  PRIVATE
    -Wall
    -Wextra
    -Wpedantic
)

if(TXING_HARDWARE_WORKER_GRPC)
  find_package(Protobuf CONFIG QUIET)
  if(NOT Protobuf_FOUND)
    find_package(Protobuf REQUIRED)
  endif()
  find_package(gRPC CONFIG REQUIRED)
  find_program(GRPC_CPP_PLUGIN_EXECUTABLE grpc_cpp_plugin REQUIRED)

  get_filename_component(
    TXING_BOARD_HARDWARE_PROTO_ROOT
    "${CMAKE_CURRENT_SOURCE_DIR}/../../../${_txing_device}/proto"
    ABSOLUTE
  )
  set(
    TXING_BOARD_HARDWARE_PROTO_RELATIVE
    "txing/${_txing_device}/hardware/v1/${_txing_device}_hardware.proto"
  )
  set(
    TXING_BOARD_HARDWARE_PROTO
    "${TXING_BOARD_HARDWARE_PROTO_ROOT}/${TXING_BOARD_HARDWARE_PROTO_RELATIVE}"
  )
  if(NOT EXISTS "${TXING_BOARD_HARDWARE_PROTO}")
    message(FATAL_ERROR
      "BoardHardware proto not found at '${TXING_BOARD_HARDWARE_PROTO}'. "
      "The repository checkout must include devices/${_txing_device}/proto."
    )
  endif()
  set(TXING_BOARD_HARDWARE_PROTO_GEN_DIR
      "${CMAKE_CURRENT_BINARY_DIR}/generated")
  set(_txing_proto_stem
      "${TXING_BOARD_HARDWARE_PROTO_GEN_DIR}/txing/${_txing_device}/hardware/v1/${_txing_device}_hardware")
  set(TXING_BOARD_HARDWARE_PROTO_SRCS
      "${_txing_proto_stem}.pb.cc"
      "${_txing_proto_stem}.grpc.pb.cc")
  set(TXING_BOARD_HARDWARE_PROTO_HDRS
      "${_txing_proto_stem}.pb.h"
      "${_txing_proto_stem}.grpc.pb.h")

  # The generated header path and the C++ namespace both carry the device's
  # proto package, so the shared sources reach them through this generated
  # binding header rather than naming either directly.
  configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/include/hardware_worker/proto_binding.hpp.in"
    "${TXING_BOARD_HARDWARE_PROTO_GEN_DIR}/hardware_worker/proto_binding.hpp"
    @ONLY
  )

  add_custom_command(
    OUTPUT ${TXING_BOARD_HARDWARE_PROTO_SRCS} ${TXING_BOARD_HARDWARE_PROTO_HDRS}
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${TXING_BOARD_HARDWARE_PROTO_GEN_DIR}"
    COMMAND protobuf::protoc
      "--proto_path=${TXING_BOARD_HARDWARE_PROTO_ROOT}"
      "--cpp_out=${TXING_BOARD_HARDWARE_PROTO_GEN_DIR}"
      "--grpc_out=${TXING_BOARD_HARDWARE_PROTO_GEN_DIR}"
      "--plugin=protoc-gen-grpc=${GRPC_CPP_PLUGIN_EXECUTABLE}"
      "${TXING_BOARD_HARDWARE_PROTO_RELATIVE}"
    DEPENDS "${TXING_BOARD_HARDWARE_PROTO}"
    WORKING_DIRECTORY "${TXING_BOARD_HARDWARE_PROTO_ROOT}"
    VERBATIM
  )

  add_library(txing_board_hardware_proto OBJECT ${TXING_BOARD_HARDWARE_PROTO_SRCS})
  target_include_directories(txing_board_hardware_proto PUBLIC "${TXING_BOARD_HARDWARE_PROTO_GEN_DIR}")
  target_link_libraries(txing_board_hardware_proto PUBLIC protobuf::libprotobuf gRPC::grpc++)
  target_compile_features(txing_board_hardware_proto PUBLIC cxx_std_17)

  add_executable(${_txing_worker_bin} src/main.cpp $<TARGET_OBJECTS:txing_board_hardware_proto>)
  target_include_directories(${_txing_worker_bin} PRIVATE "${TXING_BOARD_HARDWARE_PROTO_GEN_DIR}")
  target_link_libraries(
    ${_txing_worker_bin}
    PRIVATE
      ${_txing_worker_core}
      protobuf::libprotobuf
      gRPC::grpc++
  )
  add_dependencies(${_txing_worker_bin} txing_board_hardware_proto)
  install(TARGETS ${_txing_worker_bin} RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
endif()

if(BUILD_TESTING)
  add_executable(${_txing_worker_bin}-tests tests/test_main.cpp)
  target_link_libraries(${_txing_worker_bin}-tests PRIVATE ${_txing_worker_core})
  add_test(NAME ${_txing_worker_bin}-tests COMMAND ${_txing_worker_bin}-tests)

  if(TXING_HARDWARE_WORKER_GRPC)
    add_dependencies(${_txing_worker_bin}-tests ${_txing_worker_bin})
    add_test(
      NAME ${_txing_worker_bin}-version
      COMMAND $<TARGET_FILE:${_txing_worker_bin}> --version
    )
    set_tests_properties(
      ${_txing_worker_bin}-version
      PROPERTIES
        PASS_REGULAR_EXPRESSION "^${_txing_worker_bin} [0-9]+\\.[0-9]+\\.[0-9]+"
    )
  endif()
endif()
