cmake_minimum_required(VERSION 3.21)

project(txing_board_kvs_master LANGUAGES C CXX)

include(GNUInstallDirs)
include(CTest)
include(ExternalProject)

# One implementation serves every board device type over one device-independent
# protocol package. The device profile selects only the binary name, the
# hardware socket path, and the release stream the version comes from. Nothing
# below may branch on the device type beyond these derivations.
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

set(_txing_device "${TXING_BOARD_DEVICE_TYPE}")
set(_txing_kvs_lib "txing_${_txing_device}_kvs_master_lib")
set(_txing_kvs_bin "txing-${_txing_device}-kvs-master")

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

set(
  TXING_AWS_KVS_WEBRTC_SDK_GIT_REPOSITORY
  "https://github.com/awslabs/amazon-kinesis-video-streams-webrtc-sdk-c.git"
  CACHE STRING
  "Git repository for the AWS KVS WebRTC C SDK fetched during native KVS builds"
)
set(
  TXING_AWS_KVS_WEBRTC_SDK_GIT_TAG
  "bb106510cf74edd2c24881c1ae94ceaa0083d15c"
  CACHE STRING
  "Pinned AWS KVS WebRTC C SDK commit"
)
set(_txing_kvs_sdk_build_root "${CMAKE_CURRENT_BINARY_DIR}/aws-kvs-webrtc-sdk")
set(
  TXING_AWS_KVS_WEBRTC_SDK_SOURCE_DIR
  "${_txing_kvs_sdk_build_root}/src"
  CACHE PATH
  "Build-local AWS KVS WebRTC C SDK source checkout"
)
set(
  TXING_AWS_KVS_WEBRTC_SDK_BUILD_DIR
  "${_txing_kvs_sdk_build_root}/build"
  CACHE PATH
  "Build-local AWS KVS WebRTC C SDK build directory"
)
set(
  TXING_AWS_KVS_WEBRTC_SDK_INSTALL_DIR
  "${_txing_kvs_sdk_build_root}/install"
  CACHE PATH
  "Build-local AWS KVS WebRTC C SDK install prefix"
)
set(
  TXING_AWS_KVS_WEBRTC_SDK_SYSTEM_DEPS_DIR
  "${_txing_kvs_sdk_build_root}/system-deps"
  CACHE PATH
  "Build-local AWS KVS WebRTC C SDK system dependency staging prefix"
)
set(
  TXING_KVS_SYSTEM_CA_CERT_PATH
  "/etc/ssl/certs/Starfield_Services_Root_Certificate_Authority_-_G2.pem"
  CACHE STRING
  "Full path to the system CA certificate used by the native signaling client for AWS TLS verification"
)
set(
  TXING_BOARD_KVS_MASTER_VERSION
  ""
  CACHE STRING
  "Release version injected at build time from release/versions/<device>"
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
# The binary name stays per device: it is the mise install name, the OpenRC
# service name, and the default KVS signaling client id.
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

  target_sources(
    ${_txing_kvs_lib}
    PRIVATE
      src/board_video_bridge_grpc.cpp
      $<TARGET_OBJECTS:txing_board_video_bridge_proto>
  )
  target_compile_definitions(${_txing_kvs_lib} PRIVATE TXING_KVS_GRPC_BRIDGE=1)
  target_include_directories(${_txing_kvs_lib} PRIVATE "${TXING_BOARD_VIDEO_PROTO_GEN_DIR}")
  target_link_libraries(${_txing_kvs_lib} PRIVATE protobuf::libprotobuf gRPC::grpc++)
  add_dependencies(${_txing_kvs_lib} txing_board_video_bridge_proto)
else()
  target_sources(${_txing_kvs_lib} PRIVATE src/board_video_bridge_stub.cpp)
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

function(txing_find_system_library output_var)
  set(options REQUIRED)
  set(oneValueArgs FRIENDLY_NAME)
  set(multiValueArgs NAMES)
  cmake_parse_arguments(TXING_FIND "${options}" "${oneValueArgs}" "${multiValueArgs}" ${ARGN})
  unset(${output_var} CACHE)

  find_library(${output_var} NAMES ${TXING_FIND_NAMES})

  if(NOT ${output_var} AND TXING_FIND_REQUIRED)
    message(FATAL_ERROR
      "Required system library '${TXING_FIND_FRIENDLY_NAME}' was not found. "
      "Install the distro development package before building ${_txing_kvs_bin}."
    )
  endif()
endfunction()

if(TXING_KVS_REAL_SDK)
  find_package(Threads REQUIRED)
  find_package(ZLIB REQUIRED)
  set(OPENSSL_USE_STATIC_LIBS FALSE)
  find_package(OpenSSL REQUIRED)

  set(TXING_KVS_WEBRTC_CLIENT_LIBRARY
      "${TXING_AWS_KVS_WEBRTC_SDK_INSTALL_DIR}/lib/libkvsWebrtcClient.a")
  set(TXING_KVS_WEBRTC_SIGNALING_CLIENT_LIBRARY
      "${TXING_AWS_KVS_WEBRTC_SDK_INSTALL_DIR}/lib/libkvsWebrtcSignalingClient.a")
  set(TXING_KVS_COMMON_LWS_LIBRARY
      "${TXING_AWS_KVS_WEBRTC_SDK_INSTALL_DIR}/lib/libkvsCommonLws.a")
  set(TXING_KVS_PIC_UTILS_LIBRARY
      "${TXING_AWS_KVS_WEBRTC_SDK_INSTALL_DIR}/lib/libkvspicUtils.a")
  set(TXING_KVS_PIC_STATE_LIBRARY
      "${TXING_AWS_KVS_WEBRTC_SDK_INSTALL_DIR}/lib/libkvspicState.a")

  set(_txing_kvs_sdk_env)
  if(APPLE)
    # CMake 4 removed compatibility with the pre-3.5 minimum versions some of
    # the SDK's bundled dependency builds still declare.
    set(_txing_kvs_sdk_env
      "${CMAKE_COMMAND}" -E env "CMAKE_POLICY_VERSION_MINIMUM=3.5"
    )
  endif()

  ExternalProject_Add(
    txing_aws_kvs_webrtc_sdk
    GIT_REPOSITORY "${TXING_AWS_KVS_WEBRTC_SDK_GIT_REPOSITORY}"
    GIT_TAG "${TXING_AWS_KVS_WEBRTC_SDK_GIT_TAG}"
    GIT_PROGRESS TRUE
    GIT_REMOTE_UPDATE_STRATEGY CHECKOUT
    SOURCE_DIR "${TXING_AWS_KVS_WEBRTC_SDK_SOURCE_DIR}"
    BINARY_DIR "${TXING_AWS_KVS_WEBRTC_SDK_BUILD_DIR}"
    INSTALL_DIR "${TXING_AWS_KVS_WEBRTC_SDK_INSTALL_DIR}"
    CONFIGURE_COMMAND
      "${CMAKE_COMMAND}" -E rm -rf "${TXING_AWS_KVS_WEBRTC_SDK_SYSTEM_DEPS_DIR}"
      COMMAND "${CMAKE_COMMAND}"
        "-DTXING_KVS_SYSTEM_DEPS_DIR=${TXING_AWS_KVS_WEBRTC_SDK_SYSTEM_DEPS_DIR}"
        "-DTXING_KVS_C_COMPILER=${CMAKE_C_COMPILER}"
        -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/PrepareAwsKvsSystemDeps.cmake"
      COMMAND ${_txing_kvs_sdk_env} "${CMAKE_COMMAND}"
        -S "<SOURCE_DIR>"
        -B "<BINARY_DIR>"
        -DCMAKE_BUILD_TYPE=Release
        "-DCMAKE_INSTALL_PREFIX=${TXING_AWS_KVS_WEBRTC_SDK_INSTALL_DIR}"
        "-DOPEN_SRC_INSTALL_PREFIX=${TXING_AWS_KVS_WEBRTC_SDK_SYSTEM_DEPS_DIR}"
        -DBUILD_DEPENDENCIES=OFF
        -DBUILD_SAMPLE=OFF
        -DBUILD_TEST=OFF
        -DBUILD_BENCHMARK=OFF
        -DBUILD_STATIC_LIBS=ON
        -DUSE_OPENSSL=ON
        -DUSE_MBEDTLS=OFF
        -DOPENSSL_USE_STATIC_LIBS=FALSE
        "-DOPENSSL_INCLUDE_DIR=${OPENSSL_INCLUDE_DIR}"
        "-DOPENSSL_SSL_LIBRARY=${OPENSSL_SSL_LIBRARY}"
        "-DOPENSSL_CRYPTO_LIBRARY=${OPENSSL_CRYPTO_LIBRARY}"
    BUILD_COMMAND ${_txing_kvs_sdk_env} "${CMAKE_COMMAND}" --build "<BINARY_DIR>" --config Release
    INSTALL_COMMAND
      "${CMAKE_COMMAND}" --install "<BINARY_DIR>" --config Release
      COMMAND "${CMAKE_COMMAND}" -E copy_directory
        "${TXING_AWS_KVS_WEBRTC_SDK_SYSTEM_DEPS_DIR}/include/com"
        "${TXING_AWS_KVS_WEBRTC_SDK_INSTALL_DIR}/include/com"
      COMMAND "${CMAKE_COMMAND}" -E copy_if_different
        "${TXING_AWS_KVS_WEBRTC_SDK_SYSTEM_DEPS_DIR}/lib/libkvsCommonLws.a"
        "${TXING_KVS_COMMON_LWS_LIBRARY}"
      COMMAND "${CMAKE_COMMAND}" -E copy_if_different
        "${TXING_AWS_KVS_WEBRTC_SDK_SYSTEM_DEPS_DIR}/lib/libkvspicUtils.a"
        "${TXING_KVS_PIC_UTILS_LIBRARY}"
      COMMAND "${CMAKE_COMMAND}" -E copy_if_different
        "${TXING_AWS_KVS_WEBRTC_SDK_SYSTEM_DEPS_DIR}/lib/libkvspicState.a"
        "${TXING_KVS_PIC_STATE_LIBRARY}"
    BUILD_BYPRODUCTS
      "${TXING_KVS_WEBRTC_CLIENT_LIBRARY}"
      "${TXING_KVS_WEBRTC_SIGNALING_CLIENT_LIBRARY}"
      "${TXING_KVS_COMMON_LWS_LIBRARY}"
      "${TXING_KVS_PIC_UTILS_LIBRARY}"
      "${TXING_KVS_PIC_STATE_LIBRARY}"
  )
  txing_find_system_library(
    TXING_KVS_WEBSOCKETS_LIBRARY
    REQUIRED
    FRIENDLY_NAME "websockets"
    NAMES websockets
  )
  txing_find_system_library(
    TXING_KVS_SRTP_LIBRARY
    REQUIRED
    FRIENDLY_NAME "srtp2"
    NAMES srtp2
  )
  txing_find_system_library(
    TXING_KVS_USRSCTP_LIBRARY
    REQUIRED
    FRIENDLY_NAME "usrsctp"
    NAMES usrsctp
  )
  find_library(TXING_KVS_CAP_LIBRARY NAMES cap)

  target_sources(
    ${_txing_kvs_lib}
    PRIVATE
      src/kvs_session_real.cpp
  )
  target_compile_definitions(
    ${_txing_kvs_lib}
    PRIVATE
      TXING_KVS_REAL_SDK=1
      TXING_KVS_SYSTEM_CA_CERT_PATH=\"${TXING_KVS_SYSTEM_CA_CERT_PATH}\"
  )
  target_include_directories(
    ${_txing_kvs_lib}
    PRIVATE
      "${TXING_AWS_KVS_WEBRTC_SDK_INSTALL_DIR}/include"
  )
  target_link_libraries(
    ${_txing_kvs_lib}
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
      ZLIB::ZLIB
      Threads::Threads
      m
      "${CMAKE_DL_LIBS}"
  )
  add_dependencies(${_txing_kvs_lib} txing_aws_kvs_webrtc_sdk)
  if(TXING_KVS_CAP_LIBRARY)
    target_link_libraries(${_txing_kvs_lib} PRIVATE "${TXING_KVS_CAP_LIBRARY}")
  endif()
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
