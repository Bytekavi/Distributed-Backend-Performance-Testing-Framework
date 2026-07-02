cmake_minimum_required(VERSION 3.20)
project(distributed_load_generator VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(loadgen src/main.cpp)
target_compile_options(loadgen PRIVATE -Wall -Wextra -Wpedantic)
target_link_libraries(loadgen PRIVATE pthread)

install(TARGETS loadgen RUNTIME DESTINATION bin)

