if(NOT DEFINED SYSTEM_DEPS_DIR)
  message(FATAL_ERROR "SYSTEM_DEPS_DIR is required")
endif()

# The shared SDK helper consumes these archives from lib. GNUInstallDirs in
# the pinned producer dependencies selects lib64 on AL2023.
foreach(archive IN ITEMS libkvsCommonLws.a libkvspicUtils.a libkvspicState.a)
  if(EXISTS "${SYSTEM_DEPS_DIR}/lib/${archive}")
    continue()
  endif()
  if(NOT EXISTS "${SYSTEM_DEPS_DIR}/lib64/${archive}")
    message(FATAL_ERROR "Built KVS support archive not found: ${archive}")
  endif()
  file(COPY_FILE "${SYSTEM_DEPS_DIR}/lib64/${archive}"
    "${SYSTEM_DEPS_DIR}/lib/${archive}" ONLY_IF_DIFFERENT)
endforeach()
