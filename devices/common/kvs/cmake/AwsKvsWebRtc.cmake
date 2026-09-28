include_guard(GLOBAL)
include(ExternalProject)

set(
  TXING_AWS_KVS_WEBRTC_SDK_GIT_REPOSITORY
  "https://github.com/awslabs/amazon-kinesis-video-streams-webrtc-sdk-c.git"
  CACHE STRING
  "Git repository for the AWS KVS WebRTC C SDK fetched during native KVS builds"
)
file(STRINGS "${CMAKE_CURRENT_LIST_DIR}/../sdk.commit" TXING_KVS_SDK_COMMIT LIMIT_COUNT 1)
set(
  TXING_AWS_KVS_WEBRTC_SDK_GIT_TAG
  "${TXING_KVS_SDK_COMMIT}"
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


function(txing_link_kvs_sdk target)
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
    GIT_PROGRESS FALSE
    UPDATE_DISCONNECTED TRUE
    GIT_REMOTE_UPDATE_STRATEGY CHECKOUT
    SOURCE_DIR "${TXING_AWS_KVS_WEBRTC_SDK_SOURCE_DIR}"
    BINARY_DIR "${TXING_AWS_KVS_WEBRTC_SDK_BUILD_DIR}"
    INSTALL_DIR "${TXING_AWS_KVS_WEBRTC_SDK_INSTALL_DIR}"
    CONFIGURE_COMMAND
      "${CMAKE_COMMAND}" -E rm -rf "${TXING_AWS_KVS_WEBRTC_SDK_SYSTEM_DEPS_DIR}"
      COMMAND "${CMAKE_COMMAND}"
        "-DTXING_KVS_SYSTEM_DEPS_DIR=${TXING_AWS_KVS_WEBRTC_SDK_SYSTEM_DEPS_DIR}"
        "-DTXING_KVS_C_COMPILER=${CMAKE_C_COMPILER}"
        -P "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/PrepareAwsKvsSystemDeps.cmake"
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

  target_include_directories(
    ${target}
    PRIVATE
      "${TXING_AWS_KVS_WEBRTC_SDK_INSTALL_DIR}/include"
  )
  target_link_libraries(
    ${target}
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
  add_dependencies(${target} txing_aws_kvs_webrtc_sdk)
  if(TXING_KVS_CAP_LIBRARY)
    target_link_libraries(${target} PRIVATE "${TXING_KVS_CAP_LIBRARY}")
  endif()
endfunction()
