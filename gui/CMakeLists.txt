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
# Once populated, skip re-checking these deps for updates on every reconfigure. Without
# this, `cmake -S ...` re-fetches/re-checks-out pybind11 + nlohmann_json on EVERY run
# (even to the same pinned tag), and a fresh git checkout rewrites file mtimes even when
# content is unchanged — which makes the build think every header changed and forces a
# full rebuild every time, regardless of what actually changed in the project.
set(FETCHCONTENT_UPDATES_DISCONNECTED ON)
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
    bind_types.cpp
    bind_combat_attack.cpp
    bind_combat_spells.cpp
    bind_combat_resources.cpp
    bind_combat_turn.cpp
    bind_battle_map.cpp
    battle_map.cpp
    class_resources.cpp
    combat_visibility.cpp
    combat_movement.cpp
    combat_state.cpp
    combat_core.cpp
    combat_conditions.cpp
    combat_contested.cpp
    combat_riders.cpp
    combat_turn.cpp
    combat_resources.cpp
    combat_spells.cpp
    combat_attack.cpp
    combat_serialization.cpp
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

# ── Unit tests ───────────────────────────────────────────────────────────────
# Almost every suite is Python (tests/test_*.py) driving the compiled module.
#
# test_rules is the exception, and has to be: rules.hpp's free functions are not
# exposed to pybind11, so a Python test can only reach them through a CombatEngine
# — which is exactly what COMBAT_REFACTOR_PLAN.md's success criterion ("rules.hpp
# has direct unit tests that construct no CombatEngine and no BattleMap") rules
# out. It is a plain executable with no pybind11/OpenCV dependency; tests/test_rules.py
# runs it from build/ so it reports through tests/run_all_tests.py like the rest.
add_executable(test_rules test_rules.cpp)

target_include_directories(test_rules PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${nlohmann_json_SOURCE_DIR}/include
)

# ── Compiler warnings ─────────────────────────────────────────────────────────
if(MSVC)
    target_compile_options(rpg_battle_map PRIVATE /W4)
    target_compile_options(test_rules PRIVATE /W4)
else()
    target_compile_options(rpg_battle_map PRIVATE
        -Wall -Wextra -Wpedantic -Wshadow -Wconversion)
    target_compile_options(test_rules PRIVATE
        -Wall -Wextra -Wpedantic -Wshadow -Wconversion)
endif()

# ── Install: place the .so next to main.py ────────────────────────────────────
install(TARGETS rpg_battle_map
        LIBRARY DESTINATION ${CMAKE_CURRENT_SOURCE_DIR})
