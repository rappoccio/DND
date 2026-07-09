#!/usr/bin/env python3
"""
Test the Archfey Warlock PATRON subclass (2024 D&D):

  - L3  Steps of the Fey  — "Steps of the Fey" resource (CHA-mod uses / long rest); a Bonus-Action
                            Misty Step (30 ft, no slot) with a rider: Refreshing (self temp HP) or
                            Taunting (WIS save near departure → FeyTaunt Disadvantage mark).
  - L6  Misty Escape      — the same Misty Step as a Reaction (spends the reaction, not a Bonus
                            Action); adds the Disappearing (self Invisible) and Dreadful (2d10
                            psychic near departure) rider options.
  - L10 Beguiling Defenses — immune to the Charmed condition; a once/long-rest (or Pact-slot) OnHit
                            reaction that halves the damage and reflects Psychic.
  - L14 Bewitching Magic  — a free Misty Step (no slot/use/action) after an Enchantment/Illusion cast.

These are engine-level tests (Python → rpg bindings); the GUI wiring is exercised separately.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


# ── Helpers ──────────────────────────────────────────────────────────────────

def _cha_mod(cha):
    return (cha - 10) // 2


def _archfey(engine, bm, idx, level, cha=16, wis=10):
    """Configure an already-placed agent as an Archfey Warlock of a given level. Subclass is set
    BEFORE initialize_class_resources (as the GUI does) so subclass resources are granted."""
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Warlock, level)
    s.warlock_subclass = rpg.WarlockSubclass.Archfey
    s.cha = cha
    s.wis = wis
    s.hp_max = 40
    s.hp_cur = 40
    s.base_ac = 12
    s.initialize_class_resources(rpg.CharacterClass.Warlock, level)
    s.spell_slots_remaining = list(s.spell_slots_max)
    engine.set_agent_stats(bm, idx, s)
    return s


def _archfey_pair(level, cha=16, foe_col=6, foe_row=5):
    """Warlock at (5,5) + a foe adjacent at (foe_col, foe_row). Returns (bm, engine, wl, foe)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wl = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", foe_col, foe_row))
    # Foe added last, so its stats survive add_agent_to_battle's destructive rebuild; re-pin the
    # warlock afterwards (its stats were wiped when the foe was added).
    _archfey(engine, bm, wl, level, cha=cha)
    # Low-WIS foe so it reliably fails WIS saves vs the warlock's high CHA DC.
    fs = rpg.Stats()
    fs.hp_max = 30
    fs.hp_cur = 30
    fs.base_ac = 10
    fs.wis = 1
    engine.set_agent_stats(bm, foe, fs)
    return bm, engine, wl, foe


# ── L3: Steps of the Fey resource grant + gating ──────────────────────────────

def test_steps_of_the_fey_resource_grant():
    """Steps of the Fey is granted at Archfey L3 (not L2), with max(1, CHA mod) uses."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wl = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))

    s2 = _archfey(engine, bm, wl, 2, cha=16)
    assert s2.get_resource("Steps of the Fey") is None, "no Steps of the Fey before L3"

    s3 = _archfey(engine, bm, wl, 3, cha=16)  # +3
    r = s3.get_resource("Steps of the Fey")
    assert r is not None and r.current == 3, f"expected 3 uses at CHA 16, got {r and r.current}"

    s_lowcha = _archfey(engine, bm, wl, 3, cha=8)  # -1 → min 1
    r2 = s_lowcha.get_resource("Steps of the Fey")
    assert r2 is not None and r2.current == 1, "min 1 use even with a negative CHA mod"
    print("✅ test_steps_of_the_fey_resource_grant passed")


def test_steps_of_the_fey_requires_archfey_l3():
    """A non-Archfey warlock never gets the Steps of the Fey resource."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wl = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Warlock, 5)
    s.warlock_subclass = rpg.WarlockSubclass.Fiend
    s.cha = 16
    s.initialize_class_resources(rpg.CharacterClass.Warlock, 5)
    engine.set_agent_stats(bm, wl, s)
    assert s.get_resource("Steps of the Fey") is None, "only Archfey gets Steps of the Fey"
    print("✅ test_steps_of_the_fey_requires_archfey_l3 passed")


# ── L3: Steps of the Fey teleport + costs ─────────────────────────────────────

def test_steps_of_the_fey_teleports_and_spends():
    """A plain Steps of the Fey (effect 0) teleports the warlock, spends a use + the bonus action."""
    bm, engine, wl, foe = _archfey_pair(3, cha=16)
    engine.begin_turn(bm, wl)
    before = engine.get_agent_stats(bm, wl).get_resource("Steps of the Fey").current
    assert engine.has_bonus_action(bm, wl)

    assert engine.steps_of_the_fey(bm, wl, 5, 7, 0), "teleport within 30 ft should succeed"
    ag = bm.placed_agents[wl].origin
    assert (ag.col, ag.row) == (5, 7), f"warlock should be at (5,7), got ({ag.col},{ag.row})"
    after = engine.get_agent_stats(bm, wl).get_resource("Steps of the Fey").current
    assert after == before - 1, "one Steps of the Fey use spent"
    assert not engine.has_bonus_action(bm, wl), "the bonus action should be spent"
    print("✅ test_steps_of_the_fey_teleports_and_spends passed")


def test_steps_of_the_fey_range_gate():
    """A destination beyond 30 ft is refused (no use spent, no teleport)."""
    bm, engine, wl, foe = _archfey_pair(3, cha=16)
    engine.begin_turn(bm, wl)
    before = engine.get_agent_stats(bm, wl).get_resource("Steps of the Fey").current
    assert not engine.steps_of_the_fey(bm, wl, 5, 11, 0), "6 cells (30 ft) is fine but 11 is > 30 ft"
    ag = bm.placed_agents[wl].origin
    assert (ag.col, ag.row) == (5, 5), "warlock should not have moved"
    after = engine.get_agent_stats(bm, wl).get_resource("Steps of the Fey").current
    assert after == before, "no use spent on a refused teleport"
    print("✅ test_steps_of_the_fey_range_gate passed")


def test_refreshing_step_grants_temp_hp():
    """Refreshing Step (effect 1) grants the warlock 1d10 temporary HP."""
    bm, engine, wl, foe = _archfey_pair(3, cha=16)
    engine.begin_turn(bm, wl)
    assert engine.get_agent_stats(bm, wl).temp_hp == 0
    assert engine.steps_of_the_fey(bm, wl, 5, 7, 1)
    thp = engine.get_agent_stats(bm, wl).temp_hp
    assert 1 <= thp <= 10, f"Refreshing Step should grant 1d10 temp HP, got {thp}"
    print("✅ test_refreshing_step_grants_temp_hp passed")


def test_taunting_step_marks_nearby_foe():
    """Taunting Step (effect 2): a foe near the departure square that fails its WIS save gets the
    directed 'FeyTaunt' mark."""
    bm, engine, wl, foe = _archfey_pair(3, cha=20)  # DC 8 + PB(2) + 5 = 15 vs foe WIS -5 → always fails
    engine.begin_turn(bm, wl)
    assert engine.steps_of_the_fey(bm, wl, 5, 7, 2)
    marks = [c for c in engine.active_agent_conditions
             if c.condition_name == "FeyTaunt" and c.agent_idx == foe and c.caster_idx == wl]
    assert len(marks) == 1, f"expected one FeyTaunt mark on the foe, got {len(marks)}"
    print("✅ test_taunting_step_marks_nearby_foe passed")


# ── L6: Disappearing / Dreadful step + Misty Escape ───────────────────────────

def test_disappearing_step_l6_only():
    """Disappearing Step (effect 3) sets Invisible, and is refused below L6."""
    bm, engine, wl, foe = _archfey_pair(3, cha=16)
    engine.begin_turn(bm, wl)
    assert not engine.steps_of_the_fey(bm, wl, 5, 7, 3), "Disappearing Step needs L6"
    assert not engine.get_agent_conditions(bm, wl).invisible

    bm, engine, wl, foe = _archfey_pair(6, cha=16)
    engine.begin_turn(bm, wl)
    assert engine.steps_of_the_fey(bm, wl, 5, 7, 3), "Disappearing Step works at L6"
    assert engine.get_agent_conditions(bm, wl).invisible, "warlock should be Invisible"
    print("✅ test_disappearing_step_l6_only passed")


def test_dreadful_step_deals_psychic():
    """Dreadful Step (effect 4) deals 2d10 psychic to a foe near the departure that fails its save."""
    bm, engine, wl, foe = _archfey_pair(6, cha=20)  # high DC vs foe WIS -5 → always fails
    engine.begin_turn(bm, wl)
    hp_before = engine.get_agent_stats(bm, foe).hp_cur
    assert engine.steps_of_the_fey(bm, wl, 5, 7, 4)
    hp_after = engine.get_agent_stats(bm, foe).hp_cur
    assert hp_before - hp_after >= 2, f"Dreadful Step should deal 2d10 psychic, dealt {hp_before - hp_after}"
    print("✅ test_dreadful_step_deals_psychic passed")


def test_misty_escape_spends_reaction_not_bonus():
    """Misty Escape (as_reaction=True) spends the reaction, leaves the bonus action, and needs L6."""
    bm, engine, wl, foe = _archfey_pair(3, cha=16)
    engine.begin_turn(bm, wl)
    assert not engine.steps_of_the_fey(bm, wl, 5, 7, 0, True), "Misty Escape needs L6"

    bm, engine, wl, foe = _archfey_pair(6, cha=16)
    engine.begin_turn(bm, wl)
    assert engine.has_bonus_action(bm, wl)
    assert not engine.get_agent_conditions(bm, wl).reaction_used
    assert engine.steps_of_the_fey(bm, wl, 5, 7, 0, True), "reaction Misty Step at L6"
    assert engine.get_agent_conditions(bm, wl).reaction_used, "the reaction should be spent"
    assert engine.has_bonus_action(bm, wl), "the bonus action should NOT be spent"
    print("✅ test_misty_escape_spends_reaction_not_bonus passed")


# ── L10: Beguiling Defenses ───────────────────────────────────────────────────

def test_beguiling_defenses_resource_grant():
    """Beguiling Defenses (1 use / long rest) is granted at L10, not L9."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wl = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    s9 = _archfey(engine, bm, wl, 9, cha=16)
    assert s9.get_resource("Beguiling Defenses") is None, "no Beguiling Defenses before L10"
    s10 = _archfey(engine, bm, wl, 10, cha=16)
    r = s10.get_resource("Beguiling Defenses")
    assert r is not None and r.current == 1, "one Beguiling Defenses use at L10"
    print("✅ test_beguiling_defenses_resource_grant passed")


def test_beguiling_defenses_charm_immunity():
    """An Archfey L10+ warlock is immune to the Charmed condition (refused in applyCharmed)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wl = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))

    # L9 control: Charmed lands.
    _archfey(engine, bm, wl, 9, cha=16)
    c = rpg.ActiveAgentCondition()
    c.agent_idx = wl
    c.condition_name = "Charmed"
    c.turns_remaining = 10
    engine.add_agent_condition(bm, c)
    assert engine.get_agent_conditions(bm, wl).charmed, "L9 warlock should be Charmable"

    # L10: Charmed is refused.
    wl2 = add_agent_to_battle(engine, bm, create_test_agent("Warlock2", 8, 8))
    _archfey(engine, bm, wl2, 10, cha=16)
    c2 = rpg.ActiveAgentCondition()
    c2.agent_idx = wl2
    c2.condition_name = "Charmed"
    c2.turns_remaining = 10
    engine.add_agent_condition(bm, c2)
    assert not engine.get_agent_conditions(bm, wl2).charmed, \
        "L10 warlock is immune to Charmed (Beguiling Defenses)"
    print("✅ test_beguiling_defenses_charm_immunity passed")


# ── L14: Bewitching Magic ─────────────────────────────────────────────────────

def test_bewitching_magic_free_misty_step():
    """Bewitching Magic (L14) teleports for free — no Steps of the Fey use spent; gated below L14."""
    bm, engine, wl, foe = _archfey_pair(10, cha=16)
    engine.begin_turn(bm, wl)
    assert not engine.bewitching_misty_step(bm, wl, 5, 7, 0), "Bewitching Magic needs L14"

    bm, engine, wl, foe = _archfey_pair(14, cha=16)
    engine.begin_turn(bm, wl)
    steps_before = engine.get_agent_stats(bm, wl).get_resource("Steps of the Fey").current
    assert engine.bewitching_misty_step(bm, wl, 5, 7, 0), "free Misty Step at L14"
    ag = bm.placed_agents[wl].origin
    assert (ag.col, ag.row) == (5, 7), "warlock should have teleported"
    steps_after = engine.get_agent_stats(bm, wl).get_resource("Steps of the Fey").current
    assert steps_after == steps_before, "Bewitching Magic spends NO Steps of the Fey use"
    assert engine.has_bonus_action(bm, wl), "Bewitching Magic spends no action either"
    print("✅ test_bewitching_magic_free_misty_step passed")


if __name__ == '__main__':
    test_steps_of_the_fey_resource_grant()
    test_steps_of_the_fey_requires_archfey_l3()
    test_steps_of_the_fey_teleports_and_spends()
    test_steps_of_the_fey_range_gate()
    test_refreshing_step_grants_temp_hp()
    test_taunting_step_marks_nearby_foe()
    test_disappearing_step_l6_only()
    test_dreadful_step_deals_psychic()
    test_misty_escape_spends_reaction_not_bonus()
    test_beguiling_defenses_resource_grant()
    test_beguiling_defenses_charm_immunity()
    test_bewitching_magic_free_misty_step()
    print("\n✅ All Archfey Warlock patron tests passed!")
