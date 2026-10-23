cmake_minimum_required(VERSION 3.24)
project(txing_probe_native_dependencies LANGUAGES C CXX)
include(ExternalProject)
# AL2023 supplies SRTP, curl, zlib and snapshot-safe OpenSSL. These three
# libraries are not in its package catalog; keep exact upstream revisions.
ExternalProject_Add(websockets
  GIT_REPOSITORY https://github.com/warmcat/libwebsockets.git
  GIT_TAG ab9df9cfc39de7a49967f18387b6b76310947442
  UPDATE_DISCONNECTED TRUE
  CMAKE_ARGS -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr
    -DLWS_INSTALL_LIB_DIR:PATH=lib -DLIB_SUFFIX=64
    -DLWS_WITH_STATIC=OFF -DLWS_WITH_SHARED=ON
    -DLWS_WITHOUT_TESTAPPS=ON -DLWS_WITH_LIBUV=OFF -DLWS_WITH_LIBEVENT=OFF
    -DLWS_WITH_LIBEV=OFF -DLWS_WITHOUT_EXTENSIONS=ON
    -DOPENSSL_ROOT_DIR=/opt/snapsafe)
ExternalProject_Add(usrsctp
  GIT_REPOSITORY https://github.com/sctplab/usrsctp.git
  GIT_TAG 07f871bda23943c43c9e74cc54f25130459de830
  UPDATE_DISCONNECTED TRUE
  CMAKE_ARGS -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr
    -DCMAKE_INSTALL_LIBDIR=lib64 -Dsctp_build_shared_lib=ON
    -Dsctp_build_programs=OFF -Dsctp_werror=OFF)
ExternalProject_Add(log4cplus
  GIT_REPOSITORY https://github.com/log4cplus/log4cplus.git
  GIT_TAG b11c9480ebb060866d2e25ce7179574b3d93385e
  UPDATE_DISCONNECTED TRUE
  CMAKE_ARGS -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr
    -DCMAKE_INSTALL_LIBDIR=lib64 -DBUILD_SHARED_LIBS=ON
    -DLOG4CPLUS_BUILD_TESTING=OFF -DLOG4CPLUS_BUILD_LOGGINGSERVER=OFF)
