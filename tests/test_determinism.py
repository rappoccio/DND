#!/usr/bin/env python3
"""Determinism harness for the CombatEngine (COMBAT_REFACTOR_PLAN.md R0).

This is the refactor's oracle. It runs one fixed, scripted encounter under a fixed
RNG seed — manual PC attacks, a PC spell cast, and automated NPC turns, across
several rounds — and dumps every engine-visible outcome (attack/spell results, the
message log, and each agent's full Stats/Conditions/position after every step) to a
byte-comparable golden file.

Per the plan's scope rule, every phase of the refactor (R1..R5) must leave this
test's output byte-identical to the committed golden. Any diff after a phase billed
as a "pure mechanical move" means the move was not, in fact, behavior-preserving —
investigate before proceeding to the next phase.

The scene deliberately drives four different subsystems in one script: manual melee
attacks (combat_attack.cpp / execute_action), a spell cast (combat_spells.cpp /
execute_spell), automated NPC turns that move and swing (combat_turn.cpp,
combat_movement.cpp, combat_riders.cpp via run_npc_turn), and per-turn resource
bookkeeping (Agent::Stats::applyClassResources, begin_turn/end_turn). Widening this
script to cover more subsystems as the refactor proceeds is expected and welcome —
just regenerate the golden after inspecting the diff.

Regenerate the golden after an INTENTIONAL behavior change (inspect the diff first!):
    python test_determinism.py --update
"""

import sys, os, json, difflib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, create_test_agent, add_agent_to_battle
from helpers import _dict_to_spell

# Deterministic: same seed every run => identical dice => identical log.
SEED = 20260811
ROUNDS = 3

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_determinism.golden.txt")
SPELLS_PATH = os.path.join(_ROOT, "gui", "spells.json")

with open(SPELLS_PATH) as _f:
    _SPELLS_BY_NAME = {s["name"]: s for s in json.load(_f)}


def _melee_weapon(name, die_size, reach_ft=5):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = reach_ft
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = 1
    pr.die_size = die_size
    w.physical_damage_types = [pr]
    return w


def _ranged_weapon(name, die_size, normal_range_ft=80, long_range_ft=320):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Ranged
    w.normal_range_ft = normal_range_ft
    w.long_range_ft = long_range_ft
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Piercing
    pr.num_dice = 1
    pr.die_size = die_size
    w.physical_damage_types = [pr]
    return w


def _build_scene():
    """Aria (PC Fighter) + Wren (PC Wizard), faction 1, vs Skarn (melee NPC) + Vex
    (ranged NPC), faction 2, automated with the Simple/PreferRange strategies."""
    bm = setup_battle_map()
    engine = rpg.CombatEngine(SEED)
    logger = rpg.MessageLogger()
    engine.set_logger(logger)

    aria = add_agent_to_battle(engine, bm, create_test_agent("Aria", 3, 3))
    wren = add_agent_to_battle(engine, bm, create_test_agent("Wren", 2, 3))
    skarn = add_agent_to_battle(engine, bm, create_test_agent("Skarn", 8, 3))
    vex = add_agent_to_battle(engine, bm, create_test_agent("Vex", 9, 6))

    # Configure AFTER all adds: apply_agent_configs (inside add_agent_to_battle) only
    # restores prior stats+conditions, not weapons/spells (test_multiattack_recipes.py
    # convention).
    a = engine.get_agent_stats(bm, aria)
    a.str, a.dex, a.con, a.intel, a.wis, a.cha = 16, 14, 14, 10, 10, 10
    a.hp_max = a.hp_cur = 44
    a.base_ac = 18
    a.is_npc = False
    a.set_class_level(rpg.CharacterClass.Fighter, 5)
    a.initialize_class_resources(rpg.CharacterClass.Fighter, 5)
    engine.set_agent_stats(bm, aria, a)

    w = engine.get_agent_stats(bm, wren)
    w.str, w.dex, w.con, w.intel, w.wis, w.cha = 8, 14, 12, 16, 12, 10
    w.hp_max = w.hp_cur = 27
    w.base_ac = 12
    w.is_npc = False
    w.set_class_level(rpg.CharacterClass.Wizard, 5)
    w.initialize_class_resources(rpg.CharacterClass.Wizard, 5)
    engine.set_agent_stats(bm, wren, w)

    sk = engine.get_agent_stats(bm, skarn)
    sk.str, sk.dex, sk.con, sk.intel, sk.wis, sk.cha = 18, 12, 16, 8, 10, 8
    sk.hp_max = sk.hp_cur = 60
    sk.base_ac = 15
    sk.is_npc = True
    sk.num_attacks = 2
    engine.set_agent_stats(bm, skarn, sk)

    vx = engine.get_agent_stats(bm, vex)
    vx.str, vx.dex, vx.con, vx.intel, vx.wis, vx.cha = 10, 16, 12, 8, 12, 8
    vx.hp_max = vx.hp_cur = 40
    vx.base_ac = 13
    vx.is_npc = True
    vx.num_attacks = 1
    engine.set_agent_stats(bm, vex, vx)

    engine.set_agent_weapons(bm, aria, [_melee_weapon("Longsword", 8), rpg.Weapon(), rpg.Weapon()])
    engine.set_agent_weapons(bm, skarn, [_melee_weapon("Greataxe", 12), rpg.Weapon(), rpg.Weapon()])
    engine.set_agent_weapons(bm, vex, [_ranged_weapon("Shortbow", 6), rpg.Weapon(), rpg.Weapon()])
    engine.set_agent_spells(bm, wren, [_dict_to_spell(_SPELLS_BY_NAME["Fire Bolt"])])

    for idx in (aria, wren):
        bm.set_agent_faction(idx, 1)
    for idx in (skarn, vex):
        bm.set_agent_faction(idx, 2)
        bm.set_agent_npc_automated(idx, True)
    bm.set_agent_npc_automation_strategy(skarn, rpg.NpcAutomationStrategy.Simple)
    bm.set_agent_npc_automation_strategy(vex, rpg.NpcAutomationStrategy.PreferRange)

    logger.flush()  # discard placement/setup noise
    return bm, engine, logger, {"Aria": aria, "Wren": wren, "Skarn": skarn, "Vex": vex}


def _dump_state(engine, bm, agents, out, label):
    out.append(f"--- state: {label} ---")
    for name, idx in agents.items():
        p = bm.placed_agents[idx]
        stats = engine.get_agent_stats(bm, idx)
        conds = engine.get_agent_conditions(bm, idx)
        resources = ", ".join(f"{k}={v!r}" for k, v in sorted(stats.resources.items()))
        out.append(f"  {name}: pos=({p.origin.col},{p.origin.row}) {stats!r} {conds!r} "
                   f"resources=[{resources}]")


def build_output():
    bm, engine, logger, agents = _build_scene()
    out = []
    _dump_state(engine, bm, agents, out, "initial")

    for rnd in range(1, ROUNDS + 1):
        out.append(f"===== ROUND {rnd} =====")

        # Aria: a manual melee attack on Skarn.
        engine.begin_turn(bm, agents["Aria"])
        r = engine.execute_action(bm, rpg.Attack(agents["Aria"], agents["Skarn"], 0))
        out.append(f"Aria attacks Skarn: {r!r}")
        engine.end_turn(bm, agents["Aria"])
        _dump_state(engine, bm, agents, out, f"round {rnd} after Aria")

        # Wren: cast Fire Bolt at Vex.
        engine.begin_turn(bm, agents["Wren"])
        act = rpg.SpellAction()
        act.caster_idx = agents["Wren"]
        act.spell_idx = 0
        act.target_indices = [agents["Vex"]]
        sr = engine.execute_spell(bm, act)
        targets = ", ".join(repr(t) for t in sr.target_results)
        out.append(f"Wren casts Fire Bolt at Vex: {sr!r} targets=[{targets}]")
        engine.end_turn(bm, agents["Wren"])
        _dump_state(engine, bm, agents, out, f"round {rnd} after Wren")

        # Skarn and Vex: automated NPC turns.
        for name in ("Skarn", "Vex"):
            idx = agents[name]
            engine.begin_turn(bm, idx)
            status = engine.run_npc_turn(bm, idx)
            lines = [ln.rstrip() for ln in logger.flush()]
            out.append(f"{name} npc turn: status={status}")
            out.extend(f"  log: {ln}" for ln in lines)
            engine.end_turn(bm, idx)
        _dump_state(engine, bm, agents, out, f"round {rnd} after NPC turns")

    return "\n".join(out).rstrip() + "\n"


def main():
    update = "--update" in sys.argv
    actual = build_output()

    if update:
        with open(GOLDEN_PATH, "w") as f:
            f.write(actual)
        print(f"✅ wrote golden: {GOLDEN_PATH} ({actual.count(chr(10))} lines)")
        return 0

    if not os.path.exists(GOLDEN_PATH):
        print(f"❌ no golden file yet: {GOLDEN_PATH}\n"
              f"   Build the engine, then bootstrap it once with:\n"
              f"       python {os.path.basename(__file__)} --update\n"
              f"   Inspect the output, then commit the golden.")
        return 1

    with open(GOLDEN_PATH) as f:
        expected = f.read()

    if actual == expected:
        print(f"✅ test_determinism: {ROUNDS}-round scripted encounter matches the golden file")
        return 0

    actual_path = GOLDEN_PATH + ".actual"
    with open(actual_path, "w") as f:
        f.write(actual)
    diff = difflib.unified_diff(expected.splitlines(keepends=True),
                                actual.splitlines(keepends=True),
                                fromfile="golden", tofile="actual")
    sys.stdout.writelines(diff)
    print(f"\n❌ test_determinism: output differs from golden.\n"
          f"   Wrote actual output to {actual_path}\n"
          f"   If this change is intentional, re-bootstrap with --update.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
