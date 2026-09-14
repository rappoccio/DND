// ─────────────────────────────────────────────────────────────────────────────
//  rpg_bindings.cpp  –  pybind11 module entry point: exposes C++ RPG types to Python
//
//  Import from Python:
//      import rpg_battle_map as rpg
//
//      bm = rpg.BattleMap("map.png")
//      bm.analyze_grid()
//      bm.detect_walls()
//
//      for w in bm.walls:
//          print(w.a.col, w.a.row, "->", w.b.col, w.b.row)
//
//      cfg = rpg.AgentConfig()
//      cfg.name = "Goblin"; cfg.sprite_path = "goblin.png"
//      cfg.size = 1; cfg.start_col = 2; cfg.start_row = 3
//      bm.add_agent_config(cfg)
//      bm.apply_agent_configs()
//
//  The actual class/enum bindings are split by domain across bind_types.cpp,
//  bind_combat_attack.cpp, bind_combat_spells.cpp, bind_combat_resources.cpp,
//  bind_combat_turn.cpp, and bind_battle_map.cpp (COMBAT_REFACTOR_PLAN.md R1) —
//  see bindings_internal.hpp for their shared declarations. This file just wires
//  them together in the right order (types first, since CombatEngine/BattleMap
//  bindings reference them).
// ─────────────────────────────────────────────────────────────────────────────

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "battle_map.hpp"
#include "combat.hpp"
#include "bindings_internal.hpp"

namespace py = pybind11;
using namespace rpg;

PYBIND11_MODULE(rpg_battle_map, m)
{
    m.doc() = "RPG Battle Map – C++ analysis core (grid detection, wall detection, agents)";

    bindTypes(m);

    // ── CombatEngine ──────────────────────────────────────────────────────────
    // Split by domain across bind_combat_attack.cpp / bind_combat_spells.cpp /
    // bind_combat_resources.cpp / bind_combat_turn.cpp — see bindings_internal.hpp.
    // Each adds .def()s to this same handle.
    py::class_<CombatEngine> combat_engine_cls(m, "CombatEngine");
    combat_engine_cls
        .def(py::init<uint32_t>(), py::arg("seed") = 0,
             "Construct with a fixed seed (0 = random).");
    bindCombatAttack(combat_engine_cls);
    bindCombatSpells(combat_engine_cls);
    bindCombatResources(combat_engine_cls);
    bindCombatTurn(combat_engine_cls);

    bindBattleMap(m);
}
