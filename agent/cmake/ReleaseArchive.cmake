cmake_minimum_required(VERSION 3.24)
# libarchive ZIP local headers retain atime/ctime even with ARCHIVE_CREATE's
# MTIME set. Info-ZIP -X drops those fields and host UID/GID metadata.
file(REMOVE "${OUTPUT}")
execute_process(COMMAND "${CMAKE_COMMAND}" -E env TZ=UTC
  touch -t 202001010000 ${PATHS} COMMAND_ERROR_IS_FATAL ANY)
execute_process(COMMAND "${CMAKE_COMMAND}" -E env TZ=UTC
  zip -X -q "${OUTPUT}" ${PATHS} COMMAND_ERROR_IS_FATAL ANY)
