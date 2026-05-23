cmake_minimum_required(VERSION 3.21)

project(txing_unit_hardware_worker LANGUAGES CXX)

include(GNUInstallDirs)
include(CTest)

option(
  TXING_HARDWARE_WORKER_GRPC
  "Build txing-unit-hardware-worker gRPC server"
  ON
)

add_library(
  txing_unit_hardware_worker_core
  STATIC
    src/config.cpp
    src/motor.cpp
)

target_include_directories(
  txing_unit_hardware_worker_core
  PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
)
target_compile_features(txing_unit_hardware_worker_core PUBLIC cxx_std_17)
target_compile_options(
  txing_unit_hardware_worker_core
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
    TXING_UNIT_HARDWARE_PROTO_ROOT
    "${CMAKE_CURRENT_SOURCE_DIR}/../../proto"
    ABSOLUTE
  )
  set(
    TXING_UNIT_HARDWARE_PROTO_RELATIVE
    "txing/unit/hardware/v1/unit_hardware.proto"
  )
  set(
    TXING_UNIT_HARDWARE_PROTO
    "${TXING_UNIT_HARDWARE_PROTO_ROOT}/${TXING_UNIT_HARDWARE_PROTO_RELATIVE}"
  )
  if(NOT EXISTS "${TXING_UNIT_HARDWARE_PROTO}")
    message(FATAL_ERROR
      "UnitHardware proto not found at '${TXING_UNIT_HARDWARE_PROTO}'. "
      "The repository checkout must include devices/unit/proto."
    )
  endif()
  set(TXING_UNIT_HARDWARE_PROTO_GEN_DIR
      "${CMAKE_CURRENT_BINARY_DIR}/generated")
  set(TXING_UNIT_HARDWARE_PROTO_SRCS
      "${TXING_UNIT_HARDWARE_PROTO_GEN_DIR}/txing/unit/hardware/v1/unit_hardware.pb.cc"
      "${TXING_UNIT_HARDWARE_PROTO_GEN_DIR}/txing/unit/hardware/v1/unit_hardware.grpc.pb.cc")
  set(TXING_UNIT_HARDWARE_PROTO_HDRS
      "${TXING_UNIT_HARDWARE_PROTO_GEN_DIR}/txing/unit/hardware/v1/unit_hardware.pb.h"
      "${TXING_UNIT_HARDWARE_PROTO_GEN_DIR}/txing/unit/hardware/v1/unit_hardware.grpc.pb.h")

  add_custom_command(
    OUTPUT ${TXING_UNIT_HARDWARE_PROTO_SRCS} ${TXING_UNIT_HARDWARE_PROTO_HDRS}
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${TXING_UNIT_HARDWARE_PROTO_GEN_DIR}"
    COMMAND protobuf::protoc
      "--proto_path=${TXING_UNIT_HARDWARE_PROTO_ROOT}"
      "--cpp_out=${TXING_UNIT_HARDWARE_PROTO_GEN_DIR}"
      "--grpc_out=${TXING_UNIT_HARDWARE_PROTO_GEN_DIR}"
      "--plugin=protoc-gen-grpc=${GRPC_CPP_PLUGIN_EXECUTABLE}"
      "${TXING_UNIT_HARDWARE_PROTO_RELATIVE}"
    DEPENDS "${TXING_UNIT_HARDWARE_PROTO}"
    WORKING_DIRECTORY "${TXING_UNIT_HARDWARE_PROTO_ROOT}"
    VERBATIM
  )

  add_library(txing_unit_hardware_proto OBJECT ${TXING_UNIT_HARDWARE_PROTO_SRCS})
  target_include_directories(txing_unit_hardware_proto PUBLIC "${TXING_UNIT_HARDWARE_PROTO_GEN_DIR}")
  target_link_libraries(txing_unit_hardware_proto PUBLIC protobuf::libprotobuf gRPC::grpc++)
  target_compile_features(txing_unit_hardware_proto PUBLIC cxx_std_17)

  add_executable(txing-unit-hardware-worker src/main.cpp $<TARGET_OBJECTS:txing_unit_hardware_proto>)
  target_include_directories(txing-unit-hardware-worker PRIVATE "${TXING_UNIT_HARDWARE_PROTO_GEN_DIR}")
  target_link_libraries(
    txing-unit-hardware-worker
    PRIVATE
      txing_unit_hardware_worker_core
      protobuf::libprotobuf
      gRPC::grpc++
  )
  add_dependencies(txing-unit-hardware-worker txing_unit_hardware_proto)
  install(TARGETS txing-unit-hardware-worker RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")

  if(BUILD_TESTING)
    add_test(
      NAME txing-unit-hardware-worker-version
      COMMAND txing-unit-hardware-worker --version
    )
    set_tests_properties(
      txing-unit-hardware-worker-version
      PROPERTIES
        PASS_REGULAR_EXPRESSION "^txing-unit-hardware-worker [0-9]+\\.[0-9]+\\.[0-9]+"
    )
  endif()
endif()

if(BUILD_TESTING)
  add_executable(txing-unit-hardware-worker-tests tests/test_main.cpp)
  target_link_libraries(txing-unit-hardware-worker-tests PRIVATE txing_unit_hardware_worker_core)
  add_test(NAME txing-unit-hardware-worker-tests COMMAND txing-unit-hardware-worker-tests)
endif()
