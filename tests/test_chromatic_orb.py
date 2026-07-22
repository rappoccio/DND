#!/usr/bin/env python3
"""
Chromatic Orb — the leap mechanic (combat_spells.cpp executeSpell AttackRoll branch).

Per the spell text: on a hit it deals 3d8 of the chosen type; "If you roll the same number on two
or more of the d8s, the orb leaps to a different target of your choice within 30 feet of the target.
Make an attack roll against the new target, and make a new damage roll. The orb can't leap again
unless you cast the spell with a level 2+ spell slot."

Engine model (verified here):
  · A leap fires only on a HIT whose damage d8s contain a matching pair, to a different living
    non-ally within 30 ft of the creature being leapt from — the leap target is appended to the
    cast's target list and resolved with its OWN attack roll + damage roll (a new SpellTargetResult).
  · At base level the orb leaps at most once; a level-2+ slot lets it keep leaping (a fresh match
    each hop).
  · SpellAction.chromatic_leap_targets (the GUI picker's ordered chain) is consumed one per leap;
    when it's empty/exhausted the engine auto-picks the nearest eligible enemy (so NPC/RL/headless
    casts still leap).

Determinism: damage dice are forced to die_size=1 (every d8 reads "1" → a guaranteed matching pair,
so a leap always fires on a hit) or to a single die (num_dice=1 → no pair → never a leap). The only
randomness left is the d20 to-hit; the caster stands well away from the targets (no firing-in-melee
disadvantage), has a big attack bonus vs AC-1 targets, and each cast is retried until it lands, so
the assertions are stable.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
import helpers
from test_helpers import setup_battle_map, setup_combat_engine
from test_feats import _place, _target

FIRE = 2
_SPELLS_JSON = os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"), "spells.json")


def _chromatic(num_dice=3, die_size=1):
    """Real Chromatic Orb (native AttackRoll) with deterministic damage dice."""
    catalog = json.load(open(_SPELLS_JSON))
    d = next(s for s in catalog if s["name"] == "Chromatic Orb")
    sp = helpers._dict_to_spell(d)
    assert sp.attack_type == rpg.SpellAttack.AttackRoll, "Chromatic Orb is a ranged spell attack"
    assert sp.magic_damage_rolls, "Chromatic Orb has a magic damage roll"
    for r in sp.magic_damage_rolls:
        r.num_dice = num_dice
        r.die_size = die_size
    return sp


def _mage(engine, bm):
    """A caster parked at (2,2), away from any target cluster."""
    a = _place(engine, bm, "Mage", 2, 2)
    s = engine.get_agent_stats(bm, a)
    s.intel = 16
    s.spellcasting_ability = 3          # INT
    s.prof_bonus = 6                    # +9 to hit → only a nat-1 misses an AC-1 target
    s.spell_slots_remaining = [999] * 9
    engine.set_agent_stats(bm, a, s)
    return a


def _enemy(engine, bm, col, row, name="E"):
    e = _place(engine, bm, name, col, row)
    _target(engine, bm, e, hp=10_000, ac=1)     # huge HP (stays up), AC 1 (almost always hit)
    return e


def _cast(engine, bm, caster, primary, spell, slot_level=0, chain=None, reset=(), full_chain=False):
    """Cast Chromatic Orb at `primary`, retrying until the primary attack hits (or, when
    full_chain, until every attack in the result hits so the whole chain propagates). Resets the
    HP of `reset` agents each attempt."""
    engine.set_agent_spells(bm, caster, [spell])
    for _ in range(120):
        for t in reset:
            st = engine.get_agent_stats(bm, t)
            st.hp_cur = st.hp_max
            engine.set_agent_stats(bm, t, st)
        act = rpg.SpellAction()
        act.caster_idx = caster
        act.spell_idx = 0
        act.slot_level = slot_level
        act.target_indices = [primary]
        act.damage_type_override = FIRE
        if chain is not None:
            act.chromatic_leap_targets = chain
        res = engine.execute_spell(bm, act)
        if not res.target_results or not res.target_results[0].hit:
            continue
        if full_chain and not all(tr.hit for tr in res.target_results):
            continue
        return res
    raise AssertionError("attack(s) never landed in 120 tries")


def _hit_indices(res):
    return [tr.target_idx for tr in res.target_results]


# ─────────────────────────────────────────────────────────────────────────────
#  Binding sanity
# ─────────────────────────────────────────────────────────────────────────────

def test_leap_targets_field_binding():
    act = rpg.SpellAction()
    assert list(act.chromatic_leap_targets) == [], "defaults to empty"
    act.chromatic_leap_targets = [3, 7]
    assert list(act.chromatic_leap_targets) == [3, 7], "round-trips"
    print("✅ test_leap_targets_field_binding passed")


# ─────────────────────────────────────────────────────────────────────────────
#  The leap itself
# ─────────────────────────────────────────────────────────────────────────────

def test_matching_dice_leaps_to_nearby_enemy():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _mage(engine, bm)
    e1 = _enemy(engine, bm, 10, 8, "E1")
    e2 = _enemy(engine, bm, 11, 8, "E2")          # 5 ft from e1
    res = _cast(engine, bm, a, e1, _chromatic(), reset=(e1, e2))
    assert _hit_indices(res) == [e1, e2], f"orb should leap to the nearby enemy, got {_hit_indices(res)}"
    print("✅ test_matching_dice_leaps_to_nearby_enemy passed")


def test_no_matching_dice_no_leap():
    # A single damage die can't produce a matching pair → the orb never leaps.
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _mage(engine, bm)
    e1 = _enemy(engine, bm, 10, 8, "E1")
    e2 = _enemy(engine, bm, 11, 8, "E2")
    res = _cast(engine, bm, a, e1, _chromatic(num_dice=1), reset=(e1, e2))
    assert _hit_indices(res) == [e1], f"no match → no leap, got {_hit_indices(res)}"
    print("✅ test_no_matching_dice_no_leap passed")


def test_no_target_within_30ft_does_not_leap():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _mage(engine, bm)
    e1 = _enemy(engine, bm, 10, 8, "E1")
    far = _enemy(engine, bm, 18, 8, "Far")        # 40 ft from e1
    res = _cast(engine, bm, a, e1, _chromatic(), reset=(e1, far))
    assert _hit_indices(res) == [e1], f"no creature within 30 ft → no leap, got {_hit_indices(res)}"
    print("✅ test_no_target_within_30ft_does_not_leap passed")


def test_leap_skips_allies():
    # The auto-pick aims at a foe: an ally sits closest but must be skipped for the enemy beyond it.
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _mage(engine, bm)
    e1   = _enemy(engine, bm, 10, 8, "E1")
    ally = _enemy(engine, bm, 11, 8, "Ally")
    e2   = _enemy(engine, bm, 12, 8, "E2")
    bm.set_agent_faction(a, 1); bm.set_agent_faction(ally, 1)   # caster + ally on team 1
    bm.set_agent_faction(e1, 2); bm.set_agent_faction(e2, 2)    # foes on team 2
    res = _cast(engine, bm, a, e1, _chromatic(), reset=(e1, ally, e2))
    assert _hit_indices(res) == [e1, e2], f"leap should skip the ally for the enemy, got {_hit_indices(res)}"
    print("✅ test_leap_skips_allies passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Leap count by slot level
# ─────────────────────────────────────────────────────────────────────────────

def test_base_level_leaps_only_once():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _mage(engine, bm)
    e1 = _enemy(engine, bm, 10, 8, "E1")
    e2 = _enemy(engine, bm, 11, 8, "E2")
    e3 = _enemy(engine, bm, 12, 8, "E3")
    res = _cast(engine, bm, a, e1, _chromatic(), slot_level=0, reset=(e1, e2, e3))
    assert _hit_indices(res) == [e1, e2], f"base level leaps once only, got {_hit_indices(res)}"
    print("✅ test_base_level_leaps_only_once passed")


def test_upcast_adds_damage_dice():
    # Upcasting adds upcast_dice_bonus dice per level above base: a L9 Chromatic Orb rolls
    # 3 + 1*(9-1) = 11 d8s (which is why a high-level orb almost always finds a matching pair).
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _mage(engine, bm)
    e1 = _enemy(engine, bm, 10, 8, "E1")          # lone target → no leap to muddy the dice count
    res = _cast(engine, bm, a, e1, _chromatic(die_size=8), slot_level=9, reset=(e1,))
    n = len(res.target_results[0].dice_results)
    assert n == 11, f"L9 Chromatic Orb should roll 3 + 8 = 11 d8s, got {n}"
    print("✅ test_upcast_adds_damage_dice passed")


def test_upcast_chains_multiple_leaps():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _mage(engine, bm)
    e1 = _enemy(engine, bm, 10, 8, "E1")
    e2 = _enemy(engine, bm, 11, 8, "E2")
    e3 = _enemy(engine, bm, 12, 8, "E3")
    res = _cast(engine, bm, a, e1, _chromatic(), slot_level=2, reset=(e1, e2, e3), full_chain=True)
    assert _hit_indices(res) == [e1, e2, e3], f"level-2 slot chains every hop, got {_hit_indices(res)}"
    print("✅ test_upcast_chains_multiple_leaps passed")


# ─────────────────────────────────────────────────────────────────────────────
#  The GUI picker's chain
# ─────────────────────────────────────────────────────────────────────────────

def test_chain_picks_player_chosen_order():
    # Two equally-close enemies; the picker's chain decides which one the orb leaps to (the auto
    # rule would otherwise take the lower-indexed near_a).
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _mage(engine, bm)
    e1     = _enemy(engine, bm, 10, 8, "E1")
    near_a = _enemy(engine, bm, 11, 8, "A")       # 5 ft from e1
    near_b = _enemy(engine, bm, 10, 9, "B")       # 5 ft from e1
    res = _cast(engine, bm, a, e1, _chromatic(), chain=[near_b], reset=(e1, near_a, near_b))
    assert _hit_indices(res) == [e1, near_b], f"picker chain should win, got {_hit_indices(res)}"
    print("✅ test_chain_picks_player_chosen_order passed")


def test_invalid_chain_entry_falls_back_to_auto():
    # A chain entry out of range (>30 ft from the hop) is ignored; the engine auto-picks the
    # nearest eligible enemy instead.
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _mage(engine, bm)
    e1   = _enemy(engine, bm, 10, 8, "E1")
    near = _enemy(engine, bm, 11, 8, "Near")      # 5 ft from e1
    far  = _enemy(engine, bm, 18, 8, "Far")       # 40 ft from e1
    res = _cast(engine, bm, a, e1, _chromatic(), chain=[far], reset=(e1, near, far))
    assert _hit_indices(res) == [e1, near], f"out-of-range pick → auto-nearest, got {_hit_indices(res)}"
    print("✅ test_invalid_chain_entry_falls_back_to_auto passed")


if __name__ == "__main__":
    test_leap_targets_field_binding()
    test_matching_dice_leaps_to_nearby_enemy()
    test_no_matching_dice_no_leap()
    test_no_target_within_30ft_does_not_leap()
    test_leap_skips_allies()
    test_base_level_leaps_only_once()
    test_upcast_adds_damage_dice()
    test_upcast_chains_multiple_leaps()
    test_chain_picks_player_chosen_order()
    test_invalid_chain_entry_falls_back_to_auto()
    print("\n✅ All Chromatic Orb leap tests passed")
