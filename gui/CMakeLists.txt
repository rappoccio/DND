cmake_minimum_required(VERSION 3.25)
project(rpg_battle_map LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ── Dependencies ──────────────────────────────────────────────────────────────
find_package(OpenCV 4 REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter Development)

# pybind11 – fetched automatically so no manual install is needed
include(FetchContent)
FetchContent_Declare(
    pybind11
    GIT_REPOSITORY https://github.com/pybind/pybind11.git
    GIT_TAG        v2.13.1
    GIT_SHALLOW    TRUE
)
FetchContent_Declare(
    nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG        v3.11.3
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(pybind11 nlohmann_json)

# ── Python extension module ───────────────────────────────────────────────────
pybind11_add_module(rpg_battle_map
    rpg_bindings.cpp
    battle_map.cpp
    combat.cpp
    combat_visibility.cpp
    combat_movement.cpp
    combat_state.cpp
    combat_core.cpp
    combat_conditions.cpp
    combat_riders.cpp
    combat_turn.cpp
    combat_resources.cpp
    combat_spells.cpp
    combat_attack.cpp
    map_configs.cpp
    spell.cpp
)

target_include_directories(rpg_battle_map PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${OpenCV_INCLUDE_DIRS}
    ${nlohmann_json_SOURCE_DIR}/include
)

target_link_libraries(rpg_battle_map PRIVATE
    ${OpenCV_LIBS}
)

# ── Unit tests (Python) ──────────────────────────────────────────────────────
# Tests are written in Python; see test_*.py scripts

# ── Compiler warnings ─────────────────────────────────────────────────────────
if(MSVC)
    target_compile_options(rpg_battle_map PRIVATE /W4)
else()
    target_compile_options(rpg_battle_map PRIVATE
        -Wall -Wextra -Wpedantic -Wshadow -Wconversion)
endif()

# ── Install: place the .so next to main.py ────────────────────────────────────
install(TARGETS rpg_battle_map
        LIBRARY DESTINATION ${CMAKE_CURRENT_SOURCE_DIR})
