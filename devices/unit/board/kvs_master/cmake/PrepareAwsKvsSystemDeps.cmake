if(NOT DEFINED TXING_KVS_SYSTEM_DEPS_DIR)
  message(FATAL_ERROR "TXING_KVS_SYSTEM_DEPS_DIR is required")
endif()

if(NOT DEFINED TXING_KVS_C_COMPILER)
  message(FATAL_ERROR "TXING_KVS_C_COMPILER is required")
endif()

file(MAKE_DIRECTORY
  "${TXING_KVS_SYSTEM_DEPS_DIR}/include"
  "${TXING_KVS_SYSTEM_DEPS_DIR}/lib"
)

foreach(library IN ITEMS srtp2 usrsctp log4cplus curl websockets z ssl crypto)
  execute_process(
    COMMAND "${TXING_KVS_C_COMPILER}" "-print-file-name=lib${library}.so"
    RESULT_VARIABLE result
    OUTPUT_VARIABLE library_path
    OUTPUT_STRIP_TRAILING_WHITESPACE
  )
  if(NOT result EQUAL 0 OR
      library_path STREQUAL "" OR
      library_path STREQUAL "lib${library}.so" OR
      NOT EXISTS "${library_path}")
    message(FATAL_ERROR "System lib${library}.so not found")
  endif()

  file(
    CREATE_LINK
      "${library_path}"
      "${TXING_KVS_SYSTEM_DEPS_DIR}/lib/lib${library}.so"
    SYMBOLIC
  )
  file(
    CREATE_LINK
      "${library_path}"
      "${TXING_KVS_SYSTEM_DEPS_DIR}/lib${library}.so"
    SYMBOLIC
  )
endforeach()
