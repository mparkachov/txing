foreach(required IN ITEMS SDK_SOURCE_DIR PATCH_FILE EXPECTED_REVISION)
  if(NOT DEFINED ${required})
    message(FATAL_ERROR "${required} is required")
  endif()
endforeach()

execute_process(COMMAND git -C "${SDK_SOURCE_DIR}" rev-parse HEAD
  OUTPUT_VARIABLE revision OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
if(NOT revision STREQUAL EXPECTED_REVISION)
  message(FATAL_ERROR "KVS event-loop fix requires the pinned SDK revision")
endif()

execute_process(COMMAND git -C "${SDK_SOURCE_DIR}" apply --check "${PATCH_FILE}"
  RESULT_VARIABLE applicable OUTPUT_QUIET ERROR_QUIET)
if(applicable EQUAL 0)
  execute_process(COMMAND git -C "${SDK_SOURCE_DIR}" apply "${PATCH_FILE}"
    COMMAND_ERROR_IS_FATAL ANY)
  message(STATUS "Applied KVS signaling event-loop fix")
else()
  execute_process(COMMAND git -C "${SDK_SOURCE_DIR}" apply --reverse --check "${PATCH_FILE}"
    RESULT_VARIABLE applied OUTPUT_QUIET ERROR_QUIET)
  if(NOT applied EQUAL 0)
    message(FATAL_ERROR "KVS event-loop fix does not match the SDK source; inspect the checkout")
  endif()
endif()
