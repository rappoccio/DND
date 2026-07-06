#!/usr/bin/env python3
"""Golden-file regression test for the Bucket A + Bucket B NPC multiattack recipes.

Each of the 17 "Bucket A" monsters plus the 2 "Bucket B" monsters (Pit Fiend,
Chimera — whose recipes reference a 4th weapon slot) is loaded straight from the
authoritative bestiary (DND2024_MonsterStats.json) WITH its authored `multiattack`
recipe,
placed on the NEUTRAL team (faction 0 → allied with no one, so every creature is
a mutual enemy) next to a neutral NPC "Test Dummy" that is itself an automated
NPC, and driven through one automated turn under a FIXED RNG seed. The full
combat log of every monster's turn is concatenated and compared byte-for-byte
against a committed golden file (test_multiattack_recipes.golden.txt).

Because the monster starts adjacent to the dummy there is no movement, no
opportunity attacks and no reaction windows — the turn resolves cleanly and the
log is fully determined by the seed. Any change to recipe firing, weapon
composition, per-swing damage or on-hit riders shows up as a diff.

Regenerate the golden after an INTENTIONAL change (inspect the diff first!):
    python test_multiattack_recipes.py --update
"""

import sys, os, difflib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, create_test_agent,
                          add_agent_to_battle, STATS_PATH)
from agent_loader import dict_to_stats
from helpers import _weapons_from_list

# Deterministic: same seed every run ⇒ identical dice ⇒ identical log.
SEED = 1234567

GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "test_multiattack_recipes.golden.txt")

# The 17 Bucket A monsters, in a fixed order (mirrors MULTIATTACK_RECIPES_PLAN.md
# / tools/author_bucket_a.py). Each must carry a `multiattack` recipe in the JSON.
BUCKET_A = [
    "Brown Bear", "Bone Devil", "Otyugh", "Xorn", "Wyvern", "Grick", "Ettercap",
    "Ettin", "Giant Crocodile", "Tyrannosaurus Rex", "Unicorn", "Purple Worm",
    "Bearded Devil", "Balor", "Giant Scorpion", "Cloaker", "Tarrasque",
]

# Bucket B: recipes that reference a 4th weapon (index 3), only expressible once the
# record is in flat-list weapon form (tools/author_bucket_b.py). Regenerate the golden
# AFTER running that script, or these two fall back to legacy num_attacks free-combo.
BUCKET_B = [
    "Pit Fiend", "Chimera",
]

MONSTERS = BUCKET_A + BUCKET_B

with open(STATS_PATH) as _f:
    BESTIARY = json.load(_f)


def _build_scene(name):
    """A neutral 1v1: `name` (from the bestiary) adjacent to a neutral NPC dummy."""
    rec = BESTIARY[name]
    bm = setup_battle_map()
    engine = rpg.CombatEngine(SEED)
    logger = rpg.MessageLogger()
    engine.set_logger(logger)

    mon = add_agent_to_battle(engine, bm, create_test_agent(name, 5, 5))
    dummy = add_agent_to_battle(engine, bm, create_test_agent("Test Dummy", 6, 5))

    # Configure AFTER both adds: add_agent_to_battle runs apply_agent_configs, which
    # is destructive to weapons/faction (it only restores prior stats+conditions).
    ms = dict_to_stats(rec["stats"])
    ms.is_npc = True
    engine.set_agent_stats(bm, mon, ms)
    engine.set_agent_weapons(bm, mon, _weapons_from_list(rec["weapons"]))

    # A durable, easy-to-hit neutral NPC so every swing lands and the target never
    # drops (a dropped target would truncate the multiattack) — but is still a real
    # NPC on the neutral team, as requested.
    ds = engine.get_agent_stats(bm, dummy)
    ds.hp_max = 100000
    ds.hp_cur = 100000
    ds.base_ac = 10
    ds.num_attacks = 0
    ds.is_npc = True
    engine.set_agent_stats(bm, dummy, ds)

    for idx in (mon, dummy):
        bm.set_agent_faction(idx, 0)          # neutral: allied with no one → mutual enemies
        bm.set_agent_npc_automated(idx, True)
        bm.set_agent_npc_automation_strategy(idx, rpg.NpcAutomationStrategy.Simple)
    return bm, engine, logger, mon


def _run_monster_log(name):
    bm, engine, logger, mon = _build_scene(name)
    logger.flush()                            # discard placement/setup noise
    engine.begin_turn(bm, mon)
    status = engine.run_npc_turn(bm, mon)
    lines = [ln.rstrip() for ln in logger.flush()]
    st = BESTIARY[name]["stats"]
    header = (f"===== {name}  num_attacks={st['num_attacks']}  "
              f"recipe={st.get('multiattack')}  status={status} =====")
    return [header] + lines


def build_output():
    out = []
    for name in MONSTERS:
        out.extend(_run_monster_log(name))
        out.append("")
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
        print(f"✅ test_multiattack_recipes: all {len(MONSTERS)} Bucket A+B "
              f"recipe logs match the golden file")
        return 0

    # Mismatch: dump the actual output next to the golden and show a unified diff.
    actual_path = GOLDEN_PATH + ".actual"
    with open(actual_path, "w") as f:
        f.write(actual)
    diff = difflib.unified_diff(expected.splitlines(keepends=True),
                                actual.splitlines(keepends=True),
                                fromfile="golden", tofile="actual")
    sys.stdout.writelines(diff)
    print(f"\n❌ test_multiattack_recipes: output differs from golden.\n"
          f"   Wrote actual output to {actual_path}\n"
          f"   If this change is intentional, re-bootstrap with --update.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
