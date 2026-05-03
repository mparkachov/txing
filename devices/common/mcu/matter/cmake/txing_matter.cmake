#
# Copyright (c) 2026 txing contributors
#
# SPDX-License-Identifier: Apache-2.0
#

include(${ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR}/config/nrfconnect/app/enable-gnu-std.cmake)
include(${ZEPHYR_NRF_MODULE_DIR}/samples/matter/common/cmake/source_common.cmake)
include(${ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR}/src/app/chip_data_model.cmake)

set(TXING_MATTER_DIR ${CMAKE_CURRENT_LIST_DIR}/..)

function(txing_matter_configure_app)
  cmake_parse_arguments(ARG "" "ZAP_FILE;IDL_FILE;ZAP_GENERATED_DIR" "APP_SOURCES" ${ARGN})
  if(NOT ARG_ZAP_FILE)
    message(FATAL_ERROR "txing_matter_configure_app requires ZAP_FILE")
  endif()
  if(NOT ARG_APP_SOURCES)
    message(FATAL_ERROR "txing_matter_configure_app requires APP_SOURCES")
  endif()
  if(NOT ARG_ZAP_GENERATED_DIR)
    cmake_path(GET ARG_ZAP_FILE PARENT_PATH source_zap_parent_dir)
    set(ARG_ZAP_GENERATED_DIR ${source_zap_parent_dir}/zap-generated)
  endif()
  if(NOT EXISTS ${ARG_ZAP_GENERATED_DIR})
    message(FATAL_ERROR "txing_matter_configure_app requires ZAP_GENERATED_DIR with pregenerated ZAP C++ files: ${ARG_ZAP_GENERATED_DIR}")
  endif()

  cmake_path(GET ARG_ZAP_FILE PARENT_PATH ZAP_PARENT_DIR)
  set(generated_zap_parent_dir ${CMAKE_CURRENT_BINARY_DIR}/txing-zap)
  set(generated_zap_dir ${generated_zap_parent_dir}/zap-generated)
  file(MAKE_DIRECTORY ${generated_zap_parent_dir})
  file(COPY ${ARG_ZAP_GENERATED_DIR} DESTINATION ${generated_zap_parent_dir})

  if(ARG_IDL_FILE)
    set(idl_args IDL ${ARG_IDL_FILE})
  endif()

  target_include_directories(app PRIVATE
    ${TXING_MATTER_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${ZAP_PARENT_DIR}
    ${generated_zap_parent_dir}
    ${generated_zap_dir}
  )

  target_include_directories(matter-data-model PUBLIC
    ${ZAP_PARENT_DIR}
    ${generated_zap_parent_dir}
    ${generated_zap_dir}
  )

  target_sources(app PRIVATE
    ${TXING_MATTER_DIR}/src/standard_clusters.cpp
    ${TXING_MATTER_DIR}/src/txing_matter_app.cpp
    ${ARG_APP_SOURCES}
  )

  chip_configure_data_model(matter-data-model
    BYPASS_IDL
    GEN_DIR ${generated_zap_dir}
    ZAP_FILE ${ARG_ZAP_FILE}
    ${idl_args}
    ZCL_PATH ${ZEPHYR_CONNECTEDHOMEIP_MODULE_DIR}/src/app/zap-templates/zcl/zcl.json
  )
endfunction()
