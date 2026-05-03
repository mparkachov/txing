cmake_minimum_required(VERSION 3.20)

project(txing_weather_matter_watch VERSION 0.6.0 LANGUAGES CXX)

add_executable(weather-matter-watch src/main.cpp)
target_compile_features(weather-matter-watch PRIVATE cxx_std_20)

include(CTest)
if(BUILD_TESTING)
  add_test(
    NAME weather_matter_watch_parse_sample
    COMMAND weather-matter-watch --parse-sample "Data = 2163"
  )
  set_tests_properties(
    weather_matter_watch_parse_sample
    PROPERTIES PASS_REGULAR_EXPRESSION "\"value\":2163"
  )
endif()
