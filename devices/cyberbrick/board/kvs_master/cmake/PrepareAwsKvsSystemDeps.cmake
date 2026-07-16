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

if(APPLE)
  # Homebrew kegs are not on the default compiler search paths, so both the
  # libraries and their headers must be staged into the dependency prefix the
  # SDK build resolves against (zlib and curl come from the macOS SDK).
  execute_process(
    COMMAND brew --prefix
    RESULT_VARIABLE brew_result
    OUTPUT_VARIABLE brew_prefix
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
  )
  if(NOT brew_result EQUAL 0 OR NOT EXISTS "${brew_prefix}")
    message(FATAL_ERROR "Homebrew is required to stage KVS SDK dependencies on macOS")
  endif()

  foreach(formula IN ITEMS openssl@3 libwebsockets srtp libusrsctp log4cplus)
    set(keg "${brew_prefix}/opt/${formula}")
    if(NOT EXISTS "${keg}/lib")
      message(FATAL_ERROR
        "Homebrew formula '${formula}' is not installed. Run: brew install ${formula}"
      )
    endif()

    file(GLOB keg_libraries "${keg}/lib/*.dylib" "${keg}/lib/*.a")
    foreach(library_path IN LISTS keg_libraries)
      get_filename_component(library_name "${library_path}" NAME)
      file(
        CREATE_LINK
          "${library_path}"
          "${TXING_KVS_SYSTEM_DEPS_DIR}/lib/${library_name}"
        SYMBOLIC
      )
      file(
        CREATE_LINK
          "${library_path}"
          "${TXING_KVS_SYSTEM_DEPS_DIR}/${library_name}"
        SYMBOLIC
      )
    endforeach()

    file(GLOB keg_headers "${keg}/include/*")
    foreach(header_path IN LISTS keg_headers)
      get_filename_component(header_name "${header_path}" NAME)
      file(
        CREATE_LINK
          "${header_path}"
          "${TXING_KVS_SYSTEM_DEPS_DIR}/include/${header_name}"
        SYMBOLIC
      )
    endforeach()
  endforeach()

  return()
endif()

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
