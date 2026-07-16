cmake_minimum_required(VERSION 3.21)

project(txing_cyberbrick_hardware_worker LANGUAGES CXX)

include(GNUInstallDirs)
include(CTest)

option(
  TXING_HARDWARE_WORKER_GRPC
  "Build txing-cyberbrick-hardware-worker gRPC server"
  ON
)

add_library(
  txing_cyberbrick_hardware_worker_core
  STATIC
    src/config.cpp
    src/motor.cpp
)

target_include_directories(
  txing_cyberbrick_hardware_worker_core
  PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/include"
)
target_compile_features(txing_cyberbrick_hardware_worker_core PUBLIC cxx_std_17)
target_compile_options(
  txing_cyberbrick_hardware_worker_core
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
    TXING_CYBERBRICK_HARDWARE_PROTO_ROOT
    "${CMAKE_CURRENT_SOURCE_DIR}/../../proto"
    ABSOLUTE
  )
  set(
    TXING_CYBERBRICK_HARDWARE_PROTO_RELATIVE
    "txing/cyberbrick/hardware/v1/cyberbrick_hardware.proto"
  )
  set(
    TXING_CYBERBRICK_HARDWARE_PROTO
    "${TXING_CYBERBRICK_HARDWARE_PROTO_ROOT}/${TXING_CYBERBRICK_HARDWARE_PROTO_RELATIVE}"
  )
  if(NOT EXISTS "${TXING_CYBERBRICK_HARDWARE_PROTO}")
    message(FATAL_ERROR
      "CyberbrickHardware proto not found at '${TXING_CYBERBRICK_HARDWARE_PROTO}'. "
      "The repository checkout must include devices/cyberbrick/proto."
    )
  endif()
  set(TXING_CYBERBRICK_HARDWARE_PROTO_GEN_DIR
      "${CMAKE_CURRENT_BINARY_DIR}/generated")
  set(TXING_CYBERBRICK_HARDWARE_PROTO_SRCS
      "${TXING_CYBERBRICK_HARDWARE_PROTO_GEN_DIR}/txing/cyberbrick/hardware/v1/cyberbrick_hardware.pb.cc"
      "${TXING_CYBERBRICK_HARDWARE_PROTO_GEN_DIR}/txing/cyberbrick/hardware/v1/cyberbrick_hardware.grpc.pb.cc")
  set(TXING_CYBERBRICK_HARDWARE_PROTO_HDRS
      "${TXING_CYBERBRICK_HARDWARE_PROTO_GEN_DIR}/txing/cyberbrick/hardware/v1/cyberbrick_hardware.pb.h"
      "${TXING_CYBERBRICK_HARDWARE_PROTO_GEN_DIR}/txing/cyberbrick/hardware/v1/cyberbrick_hardware.grpc.pb.h")

  add_custom_command(
    OUTPUT ${TXING_CYBERBRICK_HARDWARE_PROTO_SRCS} ${TXING_CYBERBRICK_HARDWARE_PROTO_HDRS}
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${TXING_CYBERBRICK_HARDWARE_PROTO_GEN_DIR}"
    COMMAND protobuf::protoc
      "--proto_path=${TXING_CYBERBRICK_HARDWARE_PROTO_ROOT}"
      "--cpp_out=${TXING_CYBERBRICK_HARDWARE_PROTO_GEN_DIR}"
      "--grpc_out=${TXING_CYBERBRICK_HARDWARE_PROTO_GEN_DIR}"
      "--plugin=protoc-gen-grpc=${GRPC_CPP_PLUGIN_EXECUTABLE}"
      "${TXING_CYBERBRICK_HARDWARE_PROTO_RELATIVE}"
    DEPENDS "${TXING_CYBERBRICK_HARDWARE_PROTO}"
    WORKING_DIRECTORY "${TXING_CYBERBRICK_HARDWARE_PROTO_ROOT}"
    VERBATIM
  )

  add_library(txing_cyberbrick_hardware_proto OBJECT ${TXING_CYBERBRICK_HARDWARE_PROTO_SRCS})
  target_include_directories(txing_cyberbrick_hardware_proto PUBLIC "${TXING_CYBERBRICK_HARDWARE_PROTO_GEN_DIR}")
  target_link_libraries(txing_cyberbrick_hardware_proto PUBLIC protobuf::libprotobuf gRPC::grpc++)
  target_compile_features(txing_cyberbrick_hardware_proto PUBLIC cxx_std_17)

  add_executable(txing-cyberbrick-hardware-worker src/main.cpp $<TARGET_OBJECTS:txing_cyberbrick_hardware_proto>)
  target_include_directories(txing-cyberbrick-hardware-worker PRIVATE "${TXING_CYBERBRICK_HARDWARE_PROTO_GEN_DIR}")
  target_link_libraries(
    txing-cyberbrick-hardware-worker
    PRIVATE
      txing_cyberbrick_hardware_worker_core
      protobuf::libprotobuf
      gRPC::grpc++
  )
  add_dependencies(txing-cyberbrick-hardware-worker txing_cyberbrick_hardware_proto)
  install(TARGETS txing-cyberbrick-hardware-worker RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
endif()

if(BUILD_TESTING)
  add_executable(txing-cyberbrick-hardware-worker-tests tests/test_main.cpp)
  target_link_libraries(txing-cyberbrick-hardware-worker-tests PRIVATE txing_cyberbrick_hardware_worker_core)
  add_test(NAME txing-cyberbrick-hardware-worker-tests COMMAND txing-cyberbrick-hardware-worker-tests)

  if(TXING_HARDWARE_WORKER_GRPC)
    add_dependencies(txing-cyberbrick-hardware-worker-tests txing-cyberbrick-hardware-worker)
    add_test(
      NAME txing-cyberbrick-hardware-worker-version
      COMMAND $<TARGET_FILE:txing-cyberbrick-hardware-worker> --version
    )
    set_tests_properties(
      txing-cyberbrick-hardware-worker-version
      PROPERTIES
        PASS_REGULAR_EXPRESSION "^txing-cyberbrick-hardware-worker [0-9]+\\.[0-9]+\\.[0-9]+"
    )
  endif()
endif()
