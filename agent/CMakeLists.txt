cmake_minimum_required(VERSION 3.24)
project(txing_agent VERSION 0.1.0 LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
include(CTest)
include(FetchContent)
set(AGENT_BUILD_TESTING "${BUILD_TESTING}")
set(BUILD_TESTING OFF CACHE BOOL "Dependency tests" FORCE)
set(BUILD_ONLY "iot;iot-data" CACHE STRING "AWS clients")
set(ENABLE_TESTING OFF CACHE BOOL "AWS tests")
set(AUTORUN_UNIT_TESTS OFF CACHE BOOL "AWS tests")
set(BUILD_SHARED_LIBS OFF CACHE BOOL "Static AWS SDK")
set(MINIMIZE_SIZE ON CACHE BOOL "Minimize AWS SDK")
set(ENABLE_UNITY_BUILD ON CACHE BOOL "AWS unity builds")
set(AWS_USE_CRYPTO_SHARED_LIBS ON CACHE BOOL "Use the same system crypto as KVS")
set(S2N_USE_CRYPTO_SHARED_LIBS ON CACHE BOOL "Use system crypto for s2n")
# aws-c-io otherwise prefers an installed s2n package over the pinned CRT
# submodule. That package can use a different crypto ABI (Homebrew uses AWS-LC).
set(CMAKE_DISABLE_FIND_PACKAGE_s2n ON)
# Pin both the release and its immutable commit, including recursive CRT pins.
FetchContent_Declare(aws_sdk
  GIT_REPOSITORY https://github.com/aws/aws-sdk-cpp.git
  GIT_TAG 1.11.913
  GIT_SHALLOW TRUE
  GIT_SUBMODULES_RECURSE TRUE)
FetchContent_MakeAvailable(aws_sdk)
set(BUILD_TESTING "${AGENT_BUILD_TESTING}" CACHE BOOL "Agent tests" FORCE)
execute_process(COMMAND git -C "${aws_sdk_SOURCE_DIR}" rev-parse HEAD
  OUTPUT_VARIABLE aws_sdk_revision OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
if(NOT aws_sdk_revision STREQUAL "269ff2277f247d78526414b5052729844532362e")
  message(FATAL_ERROR "AWS SDK source does not match the pinned commit")
endif()
find_package(Threads REQUIRED)
add_library(agent_core src/core.cpp src/aws.cpp src/credentials.cpp src/kvs.cpp src/peer.cpp)
target_include_directories(agent_core PUBLIC include)
target_link_libraries(agent_core PUBLIC aws-cpp-sdk-core aws-cpp-sdk-iot aws-cpp-sdk-iot-data Threads::Threads)
include(../devices/common/kvs/cmake/AwsKvsWebRtc.cmake)
txing_link_kvs_sdk(agent_core)
# Keep the shared SDK pin/build resources intact; apply this agent build's
# cross-thread signaling fix explicitly to its private dependency checkout.
# CMake 3.27+ uses a separate patch step for UPDATE_DISCONNECTED builds.
# Depending on the normal patch step would force an update/rebuild every time.
set(agent_kvs_patch_step patch)
if(CMAKE_VERSION VERSION_GREATER_EQUAL 3.27)
  set(agent_kvs_patch_step patch_disconnected)
endif()
ExternalProject_Add_Step(txing_aws_kvs_webrtc_sdk agent_event_loop_fix
  COMMAND "${CMAKE_COMMAND}"
    "-DSDK_SOURCE_DIR=${TXING_AWS_KVS_WEBRTC_SDK_SOURCE_DIR}"
    "-DPATCH_FILE=${CMAKE_CURRENT_SOURCE_DIR}/cmake/kvs-lws-event-loop.patch"
    "-DEXPECTED_REVISION=${TXING_AWS_KVS_WEBRTC_SDK_GIT_TAG}"
    -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ApplyKvsEventLoopFix.cmake"
  DEPENDEES "${agent_kvs_patch_step}"
  DEPENDERS configure
  DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ApplyKvsEventLoopFix.cmake"
          "${CMAKE_CURRENT_SOURCE_DIR}/cmake/kvs-lws-event-loop.patch")
target_include_directories(agent_core PUBLIC "${TXING_AWS_KVS_WEBRTC_SDK_INSTALL_DIR}/include")
target_compile_options(agent_core PRIVATE -Wall -Wextra -Wpedantic)
add_executable(txing-agent src/main.cpp)
target_link_libraries(txing-agent PRIVATE agent_core)
if(BUILD_TESTING)
  add_executable(agent-tests tests/runtime_test.cpp tests/peer_test.cpp)
  target_link_libraries(agent-tests PRIVATE agent_core)
  add_test(NAME agent-runtime COMMAND agent-tests)
  set_tests_properties(agent-runtime PROPERTIES TIMEOUT 45)
  # Requires an operator-selected active Thing; default tests never call AWS.
  add_executable(agent-live-tests tests/live_test.cpp)
  target_link_libraries(agent-live-tests PRIVATE agent_core)
endif()
