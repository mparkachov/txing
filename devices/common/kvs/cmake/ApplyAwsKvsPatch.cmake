find_package(Git REQUIRED)

execute_process(
  COMMAND "${GIT_EXECUTABLE}" apply --reverse --check "${TXING_KVS_PATCH}"
  WORKING_DIRECTORY "${TXING_KVS_SOURCE_DIR}"
  RESULT_VARIABLE already_applied
  OUTPUT_QUIET
  ERROR_QUIET
)
if(NOT already_applied EQUAL 0)
  execute_process(
    COMMAND "${GIT_EXECUTABLE}" apply "${TXING_KVS_PATCH}"
    WORKING_DIRECTORY "${TXING_KVS_SOURCE_DIR}"
    COMMAND_ERROR_IS_FATAL ANY
  )
endif()
