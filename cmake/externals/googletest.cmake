FetchContent_Declare(
  googletest
  GIT_REPOSITORY https://github.com/google/googletest.git
  GIT_TAG        release-1.11.0
)

set(BUILD_GMOCK ON CACHE BOOL "Builds the googlemock subproject" FORCE)
FetchContent_MakeAvailable(googletest)
set_target_properties(gmock PROPERTIES FOLDER "externals/gtest")
set_target_properties(gmock_main PROPERTIES FOLDER "externals/gtest")
set_target_properties(gtest PROPERTIES FOLDER "externals/gtest")
set_target_properties(gtest_main PROPERTIES FOLDER "externals/gtest")
