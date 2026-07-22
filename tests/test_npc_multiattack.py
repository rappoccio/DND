#!/usr/bin/env python3
"""
Test suite for NPC segmented multiattack — MULTIATTACK_PLAN.md.

An NPC can carry an ordered recipe of (weapon_slot, count) segments (Stats.multiattack), e.g. a dragon's
"one Bite + two Claws". runWeaponTurn (NPC auto-turn only) walks the recipe: it seeds the FIRST deliverable
segment, then advances through st.pending_segments, positioning for each segment's own weapon and skipping a
segment whose weapon can't be delivered (skip-unreachable policy) or whose slot is empty (empty-slot ruling).
An empty recipe ⇒ exact legacy behavior (num_attacks swings with one auto-selected weapon).

The render-attack hook fires once per SWING (before the attack resolves), so swing counts are hit-independent.
Weapons are built with 0 damage dice + a fixed bonus_damage so per-hit damage is deterministic (crit-proof:
a crit only doubles dice, of which there are none) — total HP loss decodes exactly which slots swung.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


def _automate(bm, idx, strategy=None):
    bm.set_agent_npc_automated(idx, True)
    if strategy is not None:
        bm.set_agent_npc_automation_strategy(idx, strategy)


def _hp(engine, bm, idx):
    return engine.get_agent_stats(bm, idx).hp_cur


def _fixed_weapon(name, dmg, reach_ft=5):
    """A melee weapon that ALWAYS hits (bonus_hit huge) and deals exactly `dmg` (no dice → crit-proof)."""
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = reach_ft
    w.damage_dice = 1
    w.damage_dice_count = 0
    w.damage_modifier = 0
    w.bonus_damage = dmg
    w.bonus_hit = 50
    w.range_short_feet = reach_ft
    w.range_long_feet = reach_ft
    w.normal_range_ft = reach_ft
    return w


def _set_recipe(engine, bm, idx, recipe, num_attacks=1):
    s = engine.get_agent_stats(bm, idx)
    s.num_attacks = num_attacks
    s.multiattack = recipe            # assign whole list (pybind copies on read)
    engine.set_agent_stats(bm, idx, s)


def _driver(engine, bm, npc):
    """Run one automated NPC turn, returning the list of (attacker, target) swings the hook saw."""
    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)
    assert status == rpg.FlowStatus.Completed, f"turn did not complete cleanly: {status}"
    assert not engine.pending_decision().active, "no parked reaction window expected in these headless setups"
    return calls


# ── Composition: recipe drives an ordered multi-weapon Attack, overriding num_attacks ─────────────
def test_recipe_composition():
    """multiattack=[(0,1),(1,2)] against one adjacent enemy → exactly 1 swing with slot 0 then 2 with
    slot 1 (3 total), NOT num_attacks (deliberately 5). Damage decodes the per-slot split."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Dragon", 6, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 7, 5), hp=1000)
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(foe, 2)
    # Distinct fixed damage so total HP loss uniquely decodes the composition: 1×Bite(1) + 2×Claw(10) = 21.
    engine.set_agent_weapons(bm, npc, [_fixed_weapon("Bite", 1), _fixed_weapon("Claw", 10), rpg.Weapon()])
    _set_recipe(engine, bm, npc, [(0, 1), (1, 2)], num_attacks=5)
    _automate(bm, npc)

    calls = _driver(engine, bm, npc)

    assert calls == [(npc, foe), (npc, foe), (npc, foe)], f"expected 3 swings (1+2), got {calls}"
    dmg = 1000 - _hp(engine, bm, foe)
    assert dmg == 1 * 1 + 2 * 10, f"expected 1 Bite + 2 Claws = 21 damage, got {dmg}"
    print("✅ test_recipe_composition passed")


# ── Skip-unreachable: a segment whose weapon can't reach is dropped; earlier segments still fire ────
def test_skip_unreachable_segment():
    """A short-reach segment that cannot be delivered (foe out of reach, zero movement to close) is skipped;
    the turn still runs the earlier reachable segment and ends cleanly with no crash and no repeat."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Reaver", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 7, 5), hp=1000)  # 2 cells = 10ft away
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(foe, 2)
    # slot 0 has 10ft reach (hits at range 2); slot 1 has 5ft reach (cannot). Zero movement → cannot close.
    engine.set_agent_weapons(bm, npc,
                             [_fixed_weapon("Polearm", 7, reach_ft=10), _fixed_weapon("Dagger", 3), rpg.Weapon()])
    s = engine.get_agent_stats(bm, npc); s.speed_walk = 0
    s.num_attacks = 1; s.multiattack = [(0, 1), (1, 2)]
    engine.set_agent_stats(bm, npc, s)
    _automate(bm, npc)

    calls = _driver(engine, bm, npc)

    assert calls == [(npc, foe)], f"only the reachable 10ft-reach segment should swing, got {calls}"
    dmg = 1000 - _hp(engine, bm, foe)
    assert dmg == 7, f"only the Polearm (7) landed; the Dagger segment was skipped — got {dmg}"
    print("✅ test_skip_unreachable_segment passed")


# ── Empty-slot ruling: a recipe segment referencing an empty weapon slot is silently skipped ───────
def test_empty_slot_segment_skipped():
    """multiattack=[(1,2),(0,1)] where slot 1 is EMPTY → the leading empty-slot segment is skipped and the
    turn seeds/executes slot 0 (1 swing)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Brute", 6, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 7, 5), hp=1000)
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(foe, 2)
    # slot 1 left empty — a bare rpg.Weapon() defaults name to "Unarmed", so blank the name explicitly
    # (the engine's empty-slot ruling keys off name.empty()).
    _empty = rpg.Weapon(); _empty.name = ""
    engine.set_agent_weapons(bm, npc, [_fixed_weapon("Club", 4), _empty, rpg.Weapon()])
    _set_recipe(engine, bm, npc, [(1, 2), (0, 1)], num_attacks=3)
    _automate(bm, npc)

    calls = _driver(engine, bm, npc)

    assert calls == [(npc, foe)], f"empty slot-1 segment skipped, only slot-0 swings once, got {calls}"
    assert 1000 - _hp(engine, bm, foe) == 4, "exactly one Club hit landed"
    print("✅ test_empty_slot_segment_skipped passed")


# ── Legacy: an empty recipe reproduces num_attacks behavior exactly ────────────────────────────────
def test_legacy_empty_recipe_uses_num_attacks():
    """No multiattack recipe → the turn falls back to num_attacks swings with one auto-selected weapon,
    identical to today's behavior."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Ogre", 6, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 7, 5), hp=1000)
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(foe, 2)
    engine.set_agent_weapons(bm, npc, [_fixed_weapon("Greatclub", 6), rpg.Weapon(), rpg.Weapon()])
    _set_recipe(engine, bm, npc, [], num_attacks=3)   # empty recipe
    _automate(bm, npc)

    calls = _driver(engine, bm, npc)

    assert calls == [(npc, foe)] * 3, f"empty recipe → num_attacks (3) swings, got {calls}"
    assert 1000 - _hp(engine, bm, foe) == 3 * 6, "three Greatclub hits (num_attacks path)"
    print("✅ test_legacy_empty_recipe_uses_num_attacks passed")


def run_all():
    test_recipe_composition()
    test_skip_unreachable_segment()
    test_empty_slot_segment_skipped()
    test_legacy_empty_recipe_uses_num_attacks()
    print("\nAll NPC segmented-multiattack tests passed ✅")


if __name__ == "__main__":
    run_all()
