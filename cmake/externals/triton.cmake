include(ExternalProject)

set(triton_PREFIX ${CMAKE_CURRENT_BINARY_DIR}/_deps/triton)
set(triton_INSTALL_DIR ${triton_PREFIX}/install)

if (WIN32)
  if (ocos_target_platform STREQUAL "AMD64")
    set(vcpkg_target_platform "x64")
  else()
    set(vcpkg_target_platform ${ocos_target_platform})
  endif()

  ExternalProject_Add(vcpkg
                      GIT_REPOSITORY https://github.com/microsoft/vcpkg.git
                      GIT_TAG 2023.06.20
                      PREFIX vcpkg
                      SOURCE_DIR ${CMAKE_CURRENT_BINARY_DIR}/_deps/vcpkg-src
                      BINARY_DIR ${CMAKE_CURRENT_BINARY_DIR}/_deps/vcpkg-build
                      CONFIGURE_COMMAND ""
                      INSTALL_COMMAND ""
                      UPDATE_COMMAND ""
                      BUILD_COMMAND "<SOURCE_DIR>/bootstrap-vcpkg.bat")

  set(VCPKG_SRC ${CMAKE_CURRENT_BINARY_DIR}/_deps/vcpkg-src)
  set(ENV{VCPKG_ROOT} ${CMAKE_CURRENT_BINARY_DIR}/_deps/vcpkg-src)

  message(STATUS "VCPKG_SRC: " ${VCPKG_SRC})
  message(STATUS "ENV{VCPKG_ROOT}: " $ENV{VCPKG_ROOT})

  add_custom_command(
    COMMAND ${VCPKG_SRC}/vcpkg integrate install
    COMMAND ${CMAKE_COMMAND} -E touch vcpkg_integrate.stamp
    OUTPUT vcpkg_integrate.stamp
    DEPENDS vcpkg
  )

  add_custom_target(vcpkg_integrate ALL DEPENDS vcpkg_integrate.stamp)
  set(VCPKG_DEPENDENCIES "vcpkg_integrate")

  function(vcpkg_install PACKAGE_NAME)
    add_custom_command(
      OUTPUT ${VCPKG_SRC}/packages/${PACKAGE_NAME}_${vcpkg_target_platform}-windows-static/BUILD_INFO
      COMMAND ${VCPKG_SRC}/vcpkg install ${PACKAGE_NAME}:${vcpkg_target_platform}-windows-static --vcpkg-root=${CMAKE_CURRENT_BINARY_DIR}/_deps/vcpkg-src
      WORKING_DIRECTORY ${VCPKG_SRC}
      DEPENDS vcpkg_integrate)

    add_custom_target(get${PACKAGE_NAME}
      ALL
      DEPENDS ${VCPKG_SRC}/packages/${PACKAGE_NAME}_${vcpkg_target_platform}-windows-static/BUILD_INFO)

    list(APPEND VCPKG_DEPENDENCIES "get${PACKAGE_NAME}")
    set(VCPKG_DEPENDENCIES ${VCPKG_DEPENDENCIES} PARENT_SCOPE)
  endfunction()

  vcpkg_install(openssl)
  vcpkg_install(openssl-windows)
  vcpkg_install(rapidjson)
  # vcpkg_install(re2)
  vcpkg_install(boost-interprocess)
  vcpkg_install(boost-stacktrace)
  vcpkg_install(pthread)
  vcpkg_install(b64)
  vcpkg_install(curl)

  add_dependencies(getb64 getpthread)
  add_dependencies(getpthread getboost-stacktrace)
  add_dependencies(getboost-stacktrace getboost-interprocess)
  #add_dependencies(getboost-interprocess getre2)
  #add_dependencies(getre2 getrapidjson)
  add_dependencies(getrapidjson getopenssl-windows)
  add_dependencies(getopenssl-windows getopenssl)

  ExternalProject_Add(triton
                      GIT_REPOSITORY https://github.com/triton-inference-server/client.git
                      GIT_TAG r23.05
                      PREFIX ${triton_PREFIX}
                      CMAKE_ARGS -DVCPKG_TARGET_TRIPLET=${vcpkg_target_platform}-windows-static 
                                 -DCMAKE_TOOLCHAIN_FILE=${VCPKG_SRC}/scripts/buildsystems/vcpkg.cmake 
                                 -DCMAKE_INSTALL_PREFIX=${triton_INSTALL_DIR}
                                 -DTRITON_ENABLE_CC_HTTP=ON 
                                 -DTRITON_ENABLE_ZLIB=OFF
                      INSTALL_COMMAND cmake -E echo "Skipping install step.")

  add_dependencies(triton ${VCPKG_DEPENDENCIES})
else()
  # RapidJSON 1.1.0 (released in 2016) is compatible with the triton build. Later code is not compatible without
  # patching due to the change in variable name for the include dir from RAPIDJSON_INCLUDE_DIRS to 
  # RapidJSON_INCLUDE_DIRS in the generated cmake file used by find_package:
  #   https://github.com/Tencent/rapidjson/commit/b91c515afea9f0ba6a81fc670889549d77c83db3
  # The triton code here https://github.com/triton-inference-server/common/blob/main/CMakeLists.txt is using 
  # RAPIDJSON_INCLUDE_DIRS so the build fails if a newer RapidJSON version is used. It will find the package but the
  # include path will be wrong so the build error is delayed/misleading.
  set(RapidJSON_PREFIX ${CMAKE_CURRENT_BINARY_DIR}/_deps/rapidjson)
  set(RapidJSON_INSTALL_DIR ${RapidJSON_PREFIX}/install)
  ExternalProject_Add(RapidJSON
                      PREFIX ${RapidJSON_PREFIX}
                      URL https://github.com/Tencent/rapidjson/archive/refs/tags/v1.1.0.zip
                      URL_HASH SHA1=0fe7b4f7b83df4b3d517f4a202f3a383af7a0818
                      # this didn't set anything
                      # INSTALL_DIR ${CMAKE_CURRENT_BINARY_DIR}/_deps/install
                      # INSTALL_COMMAND cmake -E echo "Skipping install step."
                      CMAKE_ARGS -DRAPIDJSON_BUILD_DOC=OFF
                                 -DRAPIDJSON_BUILD_EXAMPLES=OFF
                                 -DRAPIDJSON_BUILD_TESTS=OFF
                                 -DRAPIDJSON_HAS_STDSTRING=ON
                                 -DRAPIDJSON_USE_MEMBERSMAP=ON                                 
                                 -DCMAKE_INSTALL_PREFIX=${RapidJSON_INSTALL_DIR}
                                 )

  ExternalProject_Get_Property(RapidJSON SOURCE_DIR BINARY_DIR)
  message(STATUS "RapidJSON src=${SOURCE_DIR} binary=${BINARY_DIR}")
  # Set RapidJSON_ROOT_DIR for find_package. The required RapidJSONConfig.cmake file is generated in the binary dir
  set(RapidJSON_ROOT_DIR ${BINARY_DIR})

  # set(CURL_SOURCE_DIR ${CMAKE_CURRENT_BINARY_DIR}/_deps/CURL-src)
  # set(CURL_BINARY_DIR ${CMAKE_CURRENT_BINARY_DIR}/_deps/CURL-build)
  # set(CURL_INCLUDE_DIR ${CURL_SOURCE_DIR}/include)
  # set(CURL_LIBRARY_DIR ${CURL_BINARY_DIR}/lib)

  # ExternalProject_Add(CURL
  #                     # PREFIX curl
  #                     GIT_REPOSITORY https://github.com/curl/curl.git
  #                     GIT_TAG "curl-7_86_0"
  #                     SOURCE_DIR ${CURL_SOURCE_DIR}
  #                     BINARY_DIR ${CURL_BINARY_DIR}
  #                     INSTALL_COMMAND cmake -E echo "Skipping install step."
  #                     CMAKE_ARGS -DBUILD_TESTING=OFF
  #                                -DBUILD_CURL_EXE=OFF
  #                                -DBUILD_SHARED_LIBS=OFF
  #                                -DCURL_STATICLIB=ON
  #                                -DHTTP_ONLY=ON
  #                                -DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE})
  # OVERRIDE_FIND_PACKAGE is so that we can use find_package in our CMakeLists.txt and the triton find_package(CURL)
  # use this version
  # FetchContent_Declare(
  #     CURL
  #     GIT_REPOSITORY https://github.com/curl/curl.git
  #     GIT_TAG "curl-7_86_0"
  #     OVERRIDE_FIND_PACKAGE 
  # )

  # We have to set CMAKE_INSTALL_PREFIX so the dependencies of triton client don't attempt to install to system paths
  ExternalProject_Add(triton
                      GIT_REPOSITORY https://github.com/triton-inference-server/client.git
                      GIT_TAG r23.05
                      PREFIX ${triton_ROOT_DIR}
                      CMAKE_ARGS -DTRITON_ENABLE_CC_HTTP=ON
                                 -DTRITON_ENABLE_ZLIB=OFF
                                 -DTRITON_USE_THIRD_PARTY=OFF
                                 -DCMAKE_INSTALL_PREFIX=${triton_INSTALL_DIR}
                      INSTALL_COMMAND cmake -E echo "Skipping install step."
                      DEPENDS RapidJSON)

  add_dependencies(triton RapidJSON)
endif() #if (WIN32)

set(triton_THIRD_PARTY_DIR ${BINARY_DIR}/third-party)
