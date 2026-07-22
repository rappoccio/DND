#!/usr/bin/env python3
"""
Test Warlock PATRON subclass features (separate from the invocation roadmap).

Phase 1:
  - Fiend L3  Dark One's Blessing (self-kill AND ally-kill within 10 ft → temp HP)
  - Fiend L6  Dark One's Own Luck (resource grant; the actual +1d10 is an OnSaveFail reaction)
  - Celestial L14 Searing Vengeance (start-of-turn death-save spring-back)

Phase 2a:
  - Great Old One L6 Clairvoyant Combatant (bonus-action telepathic mark; WIS save vs CHA DC;
    Advantage attacking the target / Disadvantage from it; costs a use OR a Pact Magic slot)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


# ── Helpers ──────────────────────────────────────────────────────────────────

def _warlock(level, subclass, cha=10):
    """Build a Warlock Stats of a given patron. Subclass is set BEFORE
    initialize_class_resources (as the GUI does) so subclass resources are granted."""
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Warlock, level)
    s.warlock_subclass = subclass
    s.cha = cha
    s.hp_max = 30      # alive (Dark One's Blessing skips a downed warlock, hp_cur <= 0)
    s.hp_cur = 30
    s.initialize_class_resources(rpg.CharacterClass.Warlock, level)
    s.spell_slots_remaining = list(s.spell_slots_max)
    return s


def _guaranteed_blade(die_size=8):
    """A high-damage melee weapon in slot 0 for combat-path testing."""
    w = rpg.Weapon()
    w.name = "Test Blade"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = 1
    pr.die_size = die_size
    w.physical_damage_types = [pr]
    return [w, rpg.Weapon(), rpg.Weapon()]


def _cha_mod(cha):
    m = (cha - 10) // 2
    return m


def _set_hp(engine, bm, idx, hp):
    """Explicitly (re-)set an agent's HP. add_agent_to_battle re-applies configs on
    every add (destructive rebuild), wiping the stats of agents added earlier — so a
    foe's hp must be re-pinned AFTER the last add_agent_to_battle call."""
    s = rpg.Stats()
    s.hp_max = hp
    s.hp_cur = hp
    s.base_ac = 10
    engine.set_agent_stats(bm, idx, s)


# ── Fiend L3: Dark One's Blessing ─────────────────────────────────────────────

def test_dark_ones_blessing_self_kill():
    """A Fiend L3+ Warlock that drops an enemy to 0 HP gains max(1, CHA mod + level) temp HP."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wl = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5), hp=1)
    s = _warlock(3, rpg.WarlockSubclass.Fiend, cha=16)  # +3
    engine.set_agent_stats(bm, wl, s)
    engine.set_agent_weapons(bm, wl, _guaranteed_blade())
    assert engine.get_agent_stats(bm, wl).temp_hp == 0
    engine.begin_turn(bm, wl)
    res = engine.execute_action(bm, rpg.Attack(wl, foe, 0))
    assert res.hit
    assert engine.get_agent_stats(bm, foe).hp_cur <= 0, "foe should be dropped"
    expected = max(1, _cha_mod(16) + 3)  # 3 + 3 = 6
    assert engine.get_agent_stats(bm, wl).temp_hp == expected, \
        f"Dark One's Blessing: expected {expected} temp HP, got {engine.get_agent_stats(bm, wl).temp_hp}"
    print("✅ test_dark_ones_blessing_self_kill passed")


def test_dark_ones_blessing_requires_fiend_l3():
    """A non-Fiend (or sub-L3) Warlock gains NO temp HP when it drops an enemy."""
    # Celestial L3 — wrong patron.
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wl = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5), hp=1)
    engine.set_agent_stats(bm, wl, _warlock(3, rpg.WarlockSubclass.Celestial, cha=16))
    engine.set_agent_weapons(bm, wl, _guaranteed_blade())
    engine.begin_turn(bm, wl)
    engine.execute_action(bm, rpg.Attack(wl, foe, 0))
    assert engine.get_agent_stats(bm, wl).temp_hp == 0, "non-Fiend should not get Dark One's Blessing"

    # Fiend L2 — too low.
    bm2 = setup_battle_map()
    engine2 = setup_combat_engine()
    wl2 = add_agent_to_battle(engine2, bm2, create_test_agent("Warlock", 5, 5))
    foe2 = add_agent_to_battle(engine2, bm2, create_test_agent("Foe", 6, 5), hp=1)
    engine2.set_agent_stats(bm2, wl2, _warlock(2, rpg.WarlockSubclass.Fiend, cha=16))
    engine2.set_agent_weapons(bm2, wl2, _guaranteed_blade())
    engine2.begin_turn(bm2, wl2)
    engine2.execute_action(bm2, rpg.Attack(wl2, foe2, 0))
    assert engine2.get_agent_stats(bm2, wl2).temp_hp == 0, "Fiend L2 is below the L3 feature"
    print("✅ test_dark_ones_blessing_requires_fiend_l3 passed")


def test_dark_ones_blessing_ally_kill_within_10ft():
    """When an ALLY drops an enemy within 10 ft of a Fiend L3+ Warlock, the Warlock still gets
    the temp HP; an identical kill more than 10 ft away grants nothing."""
    # Within 10 ft: warlock(5,5) — enemy(6,5) [5 ft] — ally(7,5) makes the kill.
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wl = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5), hp=1)
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 7, 5))
    bm.set_agent_faction(wl, 1)
    bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(foe, 2)
    engine.set_agent_stats(bm, wl, _warlock(3, rpg.WarlockSubclass.Fiend, cha=16))
    _set_hp(engine, bm, foe, 1)  # re-pin: the ally add wiped the foe's hp=1
    engine.set_agent_weapons(bm, ally, _guaranteed_blade())
    engine.begin_turn(bm, ally)
    engine.execute_action(bm, rpg.Attack(ally, foe, 0))
    assert engine.get_agent_stats(bm, foe).hp_cur <= 0, "ally should drop the foe"
    expected = max(1, _cha_mod(16) + 3)
    assert engine.get_agent_stats(bm, wl).temp_hp == expected, \
        f"ally-kill within 10 ft should grant {expected} temp HP, got {engine.get_agent_stats(bm, wl).temp_hp}"

    # Beyond 10 ft: warlock(5,5) — enemy(10,5) [25 ft] — ally(11,5). No temp HP.
    bm2 = setup_battle_map()
    engine2 = setup_combat_engine()
    wl2 = add_agent_to_battle(engine2, bm2, create_test_agent("Warlock", 5, 5))
    foe2 = add_agent_to_battle(engine2, bm2, create_test_agent("Foe", 10, 5), hp=1)
    ally2 = add_agent_to_battle(engine2, bm2, create_test_agent("Ally", 11, 5))
    bm2.set_agent_faction(wl2, 1)
    bm2.set_agent_faction(ally2, 1)
    bm2.set_agent_faction(foe2, 2)
    engine2.set_agent_stats(bm2, wl2, _warlock(3, rpg.WarlockSubclass.Fiend, cha=16))
    _set_hp(engine2, bm2, foe2, 1)  # re-pin: the ally add wiped the foe's hp=1
    engine2.set_agent_weapons(bm2, ally2, _guaranteed_blade())
    engine2.begin_turn(bm2, ally2)
    engine2.execute_action(bm2, rpg.Attack(ally2, foe2, 0))
    assert engine2.get_agent_stats(bm2, foe2).hp_cur <= 0, "ally should drop the far foe"
    assert engine2.get_agent_stats(bm2, wl2).temp_hp == 0, \
        "an ally-kill beyond 10 ft must grant no Dark One's Blessing"
    print("✅ test_dark_ones_blessing_ally_kill_within_10ft passed")


# ── Fiend L6: Dark One's Own Luck ─────────────────────────────────────────────

def test_dark_ones_own_luck_resource_grant():
    """Fiend L6 grants the 'Dark One's Own Luck' resource = max(1, CHA mod) uses; absent at L5."""
    s = _warlock(6, rpg.WarlockSubclass.Fiend, cha=18)  # +4
    luck = s.get_resource("Dark One's Own Luck")
    assert luck is not None, "Fiend L6 should grant Dark One's Own Luck"
    assert luck.max == max(1, _cha_mod(18)), f"expected {max(1, _cha_mod(18))} uses, got {luck.max}"
    assert luck.current == luck.max, "should start fully available"

    # Floor of 1 with a low CHA.
    s_low = _warlock(6, rpg.WarlockSubclass.Fiend, cha=8)  # -1 → floor 1
    assert s_low.get_resource("Dark One's Own Luck").max == 1, "uses floor at 1"

    # Not present at L5.
    s5 = _warlock(5, rpg.WarlockSubclass.Fiend, cha=18)
    assert s5.get_resource("Dark One's Own Luck") is None, "Dark One's Own Luck is L6, not L5"

    # Not present for a different patron.
    s_other = _warlock(6, rpg.WarlockSubclass.GreatOldOne, cha=18)
    assert s_other.get_resource("Dark One's Own Luck") is None, "only the Fiend gets Dark One's Own Luck"
    print("✅ test_dark_ones_own_luck_resource_grant passed")


# ── Celestial L14: Searing Vengeance ──────────────────────────────────────────

def test_searing_vengeance_resource_grant():
    """Searing Vengeance resource is granted at Celestial L14, not L13."""
    s14 = _warlock(14, rpg.WarlockSubclass.Celestial, cha=16)
    assert s14.get_resource("Searing Vengeance") is not None, "Celestial L14 should grant Searing Vengeance"
    s13 = _warlock(13, rpg.WarlockSubclass.Celestial, cha=16)
    assert s13.get_resource("Searing Vengeance") is None, "Searing Vengeance is L14, not L13"
    s_other = _warlock(14, rpg.WarlockSubclass.Fiend, cha=16)
    assert s_other.get_resource("Searing Vengeance") is None, "only the Celestial gets Searing Vengeance"
    print("✅ test_searing_vengeance_resource_grant passed")


def test_searing_vengeance_springs_back():
    """A downed Celestial L14 Warlock springs back to half HP at the start of its turn instead of
    rolling a death save — once per long rest; a second turn falls through to the normal death save."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wl = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 8, 5), hp=40)
    bm.set_agent_faction(wl, 1)
    bm.set_agent_faction(foe, 2)
    s = _warlock(14, rpg.WarlockSubclass.Celestial, cha=16)
    s.hp_max = 20
    s.hp_cur = 0
    engine.set_agent_stats(bm, wl, s)
    c = engine.get_agent_conditions(bm, wl)
    c.unconscious = True
    engine.set_agent_conditions(bm, wl, c)

    # Start of turn: spring back instead of a death save.
    engine.begin_turn(bm, wl)
    out = engine.get_agent_stats(bm, wl)
    assert out.hp_cur == 10, f"Searing Vengeance should restore hp_max/2 = 10, got {out.hp_cur}"
    assert not engine.get_agent_conditions(bm, wl).unconscious, "should be conscious again"
    assert engine.get_agent_stats(bm, wl).get_resource("Searing Vengeance").current == 0, \
        "Searing Vengeance should be spent"

    # Second time it cannot fire (resource gone): a fresh downing rolls a normal death save instead.
    s2 = engine.get_agent_stats(bm, wl)
    s2.hp_cur = 0
    engine.set_agent_stats(bm, wl, s2)
    c2 = engine.get_agent_conditions(bm, wl)
    c2.unconscious = True
    c2.death_save_failures = 0
    c2.death_save_successes = 0
    engine.set_agent_conditions(bm, wl, c2)
    engine.begin_turn(bm, wl)
    out2 = engine.get_agent_stats(bm, wl)
    assert out2.hp_cur <= 0, "without the resource the Warlock stays down (rolls a death save, not a spring-back)"
    print("✅ test_searing_vengeance_springs_back passed")


# ── Great Old One L6: Clairvoyant Combatant ───────────────────────────────────

def test_clairvoyant_combatant_resource_grant():
    """The 'Clairvoyant Combatant' use is granted at GOO L6, not L5 / other patrons."""
    s6 = _warlock(6, rpg.WarlockSubclass.GreatOldOne, cha=16)
    assert s6.get_resource("Clairvoyant Combatant") is not None, "GOO L6 should grant the use"
    s5 = _warlock(5, rpg.WarlockSubclass.GreatOldOne, cha=16)
    assert s5.get_resource("Clairvoyant Combatant") is None, "Clairvoyant Combatant is L6, not L5"
    s_other = _warlock(6, rpg.WarlockSubclass.Fiend, cha=16)
    assert s_other.get_resource("Clairvoyant Combatant") is None, "only GOO gets Clairvoyant Combatant"
    print("✅ test_clairvoyant_combatant_resource_grant passed")


def test_clairvoyant_combatant_gating():
    """Activation is refused for the wrong patron and below L6. (The 60-ft range gate is the
    standard shared range check; the 12x12 test map maxes out at 55 ft, so it can't be exercised here.)"""
    # Wrong patron.
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wl = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5))
    engine.set_agent_stats(bm, wl, _warlock(6, rpg.WarlockSubclass.Fiend, cha=18))
    engine.begin_turn(bm, wl)
    assert not engine.activate_clairvoyant_combatant(bm, wl, foe), "non-GOO must not activate"

    # GOO L5 — too low.
    bm2 = setup_battle_map()
    engine2 = setup_combat_engine()
    wl2 = add_agent_to_battle(engine2, bm2, create_test_agent("Warlock", 5, 5))
    foe2 = add_agent_to_battle(engine2, bm2, create_test_agent("Foe", 6, 5))
    engine2.set_agent_stats(bm2, wl2, _warlock(5, rpg.WarlockSubclass.GreatOldOne, cha=18))
    engine2.begin_turn(bm2, wl2)
    assert not engine2.activate_clairvoyant_combatant(bm2, wl2, foe2), "GOO L5 is below the L6 feature"
    print("✅ test_clairvoyant_combatant_gating passed")


def _goo_pair(cha=20, level=6, target_wis=1):
    """GOO L6 Warlock at (5,5) + a low-WIS foe at (6,5) so the WIS save reliably FAILS
    against the Warlock's high CHA DC. Returns (bm, engine, wl, foe)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wl = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5))
    s = _warlock(level, rpg.WarlockSubclass.GreatOldOne, cha=cha)
    engine.set_agent_stats(bm, wl, s)
    fs = engine.get_agent_stats(bm, foe)
    fs.wis = target_wis
    engine.set_agent_stats(bm, foe, fs)
    engine.begin_turn(bm, wl)
    return bm, engine, wl, foe


def _cc_condition(engine, wl, foe):
    """Return the active ClairvoyantCombatant mark on `foe` cast by `wl`, or None."""
    for cond in engine.active_agent_conditions:
        if (cond.condition_name == "ClairvoyantCombatant"
                and cond.agent_idx == foe and cond.caster_idx == wl):
            return cond
    return None


def test_clairvoyant_combatant_activation_and_mark():
    """A successful activation against a low-WIS foe (high CHA DC) spends the use, spends the bonus
    action, and — on the failed save — places the directed ClairvoyantCombatant mark on the foe."""
    bm, engine, wl, foe = _goo_pair(cha=20, level=20)  # DC 8 + 5 + 6 = 19; foe WIS 1 (-5) always fails
    uses_before = engine.get_agent_stats(bm, wl).get_resource("Clairvoyant Combatant").current
    assert engine.has_bonus_action(bm, wl), "warlock should start its turn with a bonus action"
    assert engine.activate_clairvoyant_combatant(bm, wl, foe), "activation should succeed"

    uses_after = engine.get_agent_stats(bm, wl).get_resource("Clairvoyant Combatant").current
    assert uses_after == uses_before - 1, "a use should be spent"
    assert not engine.has_bonus_action(bm, wl), "the bonus action should be spent"
    mark = _cc_condition(engine, wl, foe)
    assert mark is not None, "a failed save should place the ClairvoyantCombatant mark on the foe"
    assert mark.turns_remaining == 1, "the mark lasts until the start of the warlock's next turn"
    print("✅ test_clairvoyant_combatant_activation_and_mark passed")


def test_clairvoyant_combatant_high_save_no_mark():
    """When the target makes the save (very low DC, high WIS), the activation still consumes the
    resource but NO mark is placed."""
    # Low CHA → low DC (8 + 0 + 2 = 10 at L6); foe WIS 20 (+5) → save total >= 6, beats DC most rolls.
    # To make the pass deterministic, give the foe an enormous WIS so even a nat-1 clears the DC.
    bm = setup_battle_map()
    engine = setup_combat_engine()
    wl = add_agent_to_battle(engine, bm, create_test_agent("Warlock", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5))
    engine.set_agent_stats(bm, wl, _warlock(6, rpg.WarlockSubclass.GreatOldOne, cha=10))  # DC 8+0+2 = 10
    fs = engine.get_agent_stats(bm, foe)
    fs.wis = 40  # mod +15 → 1 + 15 = 16 >= 10 even on a nat 1
    engine.set_agent_stats(bm, foe, fs)
    engine.begin_turn(bm, wl)
    assert engine.activate_clairvoyant_combatant(bm, wl, foe), "activation succeeds (contact is made)"
    assert _cc_condition(engine, wl, foe) is None, "a successful save should place no mark"
    print("✅ test_clairvoyant_combatant_high_save_no_mark passed")


def test_clairvoyant_combatant_pact_slot_fallback():
    """When the 'Clairvoyant Combatant' use is exhausted, a second activation spends a Pact Magic
    slot (spell_slots_remaining at the pact slot level)."""
    bm, engine, wl, foe = _goo_pair(cha=20, level=20)
    # First activation spends the single use.
    assert engine.activate_clairvoyant_combatant(bm, wl, foe)
    assert engine.get_agent_stats(bm, wl).get_resource("Clairvoyant Combatant").current == 0, \
        "the only use should now be spent"

    # Refresh the bonus action (next turn would; here we just re-grant it) and re-activate: must use a slot.
    engine.begin_turn(bm, wl)
    s = engine.get_agent_stats(bm, wl)
    psl = s.pact_slot_level()
    assert psl >= 1
    slots_before = s.spell_slots_remaining[psl - 1]
    assert slots_before > 0, "warlock should have a Pact slot to spend"
    assert engine.activate_clairvoyant_combatant(bm, wl, foe), "should reuse by spending a Pact slot"
    slots_after = engine.get_agent_stats(bm, wl).spell_slots_remaining[psl - 1]
    assert slots_after == slots_before - 1, "a Pact Magic slot should be spent on the reuse"
    print("✅ test_clairvoyant_combatant_pact_slot_fallback passed")


def test_clairvoyant_combatant_blocked_when_exhausted():
    """With no use and no Pact slot remaining, activation is refused."""
    bm, engine, wl, foe = _goo_pair(cha=20, level=20)
    s = engine.get_agent_stats(bm, wl)
    # Drain the use (get_resource returns a live reference, so this mutates s in place) and all pact slots.
    s.get_resource("Clairvoyant Combatant").current = 0
    s.spell_slots_remaining = [0] * 9
    engine.set_agent_stats(bm, wl, s)
    engine.begin_turn(bm, wl)
    assert not engine.activate_clairvoyant_combatant(bm, wl, foe), \
        "no use and no Pact slot → activation must fail"
    print("✅ test_clairvoyant_combatant_blocked_when_exhausted passed")


if __name__ == '__main__':
    test_dark_ones_blessing_self_kill()
    test_dark_ones_blessing_requires_fiend_l3()
    test_dark_ones_blessing_ally_kill_within_10ft()
    test_dark_ones_own_luck_resource_grant()
    test_searing_vengeance_resource_grant()
    test_searing_vengeance_springs_back()
    test_clairvoyant_combatant_resource_grant()
    test_clairvoyant_combatant_gating()
    test_clairvoyant_combatant_activation_and_mark()
    test_clairvoyant_combatant_high_save_no_mark()
    test_clairvoyant_combatant_pact_slot_fallback()
    test_clairvoyant_combatant_blocked_when_exhausted()
    print("\n✅ All Warlock patron tests passed!")
