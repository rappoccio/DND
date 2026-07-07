#!/usr/bin/env python3
"""
Test suite for the restorative spells Remove Curse and Greater Restoration.

Remove Curse strips every curse-tracked condition (the Vistani Curse of Vulnerability /
Weakness / Affliction) from the target. Greater Restoration does that AND ends Charmed /
Petrified, reduces Exhaustion by one level, and restores any reduction to the HP maximum.

Both are wired two ways and both are exercised here:
  · directly via the engine helpers  engine.cure_curses / engine.greater_restoration
  · end-to-end through execute_spell, keyed on the spell name (like Command)

Ending a curse deliberately still fires its Vistani "kickback" on the original caster
(the curse rebounds when the victim is freed) — see test_vistani.py for that mechanism.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


# ── curse authoring (mirrors the Vistani spells.json records) ────────────────

def _make_curse_spell(curse_kind, condition_name="Cursed", kickback_dice=3, die=6):
    sp = rpg.Spell()
    sp.name        = "TestCurse"
    sp.type        = rpg.SpellType.Harm
    sp.geometry    = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range       = 30
    sp.duration    = 100
    sp.level       = 0
    sp.num_targets = 1
    sp.requires_los = False
    sp.requires_concentration = False
    c = rpg.AttackCondition()
    c.condition_name       = condition_name
    c.requires_save        = False
    c.curse_kind           = curse_kind
    c.kickback_dice        = kickback_dice
    c.kickback_die_size    = die
    c.kickback_damage_type = rpg.MagicDamage.Psychic
    sp.conditions = [c]
    return sp


def _cast_curse(engine, bm, caster, target, curse_kind, curse_choice, condition_name="Cursed"):
    sp = _make_curse_spell(curse_kind, condition_name)
    engine.set_agent_spells(bm, caster, [sp])
    act = rpg.SpellAction()
    act.caster_idx     = caster
    act.spell_idx      = 0
    act.target_indices = [target]
    act.curse_choice   = curse_choice
    engine.execute_spell(bm, act)


def _make_restore_spell(name, spell_type):
    sp = rpg.Spell()
    sp.name        = name
    sp.type        = spell_type
    sp.geometry    = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range       = 60   # touch in RAW; widened here so the 10-ft test spacing never range-gates
    sp.duration    = 1
    sp.level       = 5
    sp.num_targets = 1
    sp.requires_los = False
    sp.requires_concentration = False
    return sp


def _cast_restore(engine, bm, caster, target, name, spell_type):
    sp = _make_restore_spell(name, spell_type)
    engine.set_agent_spells(bm, caster, [sp])
    act = rpg.SpellAction()
    act.caster_idx     = caster
    act.spell_idx      = 0
    act.target_indices = [target]
    engine.execute_spell(bm, act)


def _setup_pair(caster_hp=100):
    """A caster (cleric) and a victim, both healthy. Returns (engine, bm, caster, victim)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Cleric", 2, 5))
    victim = add_agent_to_battle(engine, bm, create_test_agent("Victim", 4, 5))
    s = engine.get_agent_stats(bm, caster)
    s.hp_max = caster_hp
    s.hp_cur = caster_hp
    engine.set_agent_stats(bm, caster, s)
    return engine, bm, caster, victim


# ─────────────────────────────────────────────────────────────────────────────
#  Remove Curse
# ─────────────────────────────────────────────────────────────────────────────

def test_cure_curses_removes_weakness_curse():
    """cure_curses lifts a Curse of Weakness: the 'Cursed' condition is gone and the save
    Disadvantage it imposed is lifted."""
    engine, bm, caster, victim = _setup_pair()
    WIS = int(rpg.SaveAbility.SaveWis)
    _cast_curse(engine, bm, caster, victim, curse_kind=2, curse_choice=WIS)
    assert engine.curse_save_disadvantage(bm, victim, rpg.SaveAbility.SaveWis)

    removed = engine.cure_curses(bm, victim)

    assert removed == 1, f"exactly one curse should be cleared, got {removed}"
    assert not engine.curse_save_disadvantage(bm, victim, rpg.SaveAbility.SaveWis), \
        "Disadvantage must lift once the curse is removed"
    assert not [c for c in engine.active_agent_conditions
                if c.agent_idx == victim and c.condition_name == "Cursed"], \
        "the 'Cursed' tracking entry must be gone"
    print("✅ test_cure_curses_removes_weakness_curse passed")


def test_cure_curses_restores_vulnerability_multiplier():
    """cure_curses on a Curse of Vulnerability restores the target's damage multiplier."""
    engine, bm, caster, victim = _setup_pair()
    FIRE = 2  # Acid=0, Cold=1, Fire=2, …
    _cast_curse(engine, bm, caster, victim, curse_kind=1, curse_choice=FIRE)
    assert list(engine.get_agent_stats(bm, victim).magic_damage_multipliers)[FIRE] == 2.0

    engine.cure_curses(bm, victim)

    restored = list(engine.get_agent_stats(bm, victim).magic_damage_multipliers)[FIRE]
    assert restored == 1.0, f"multiplier must restore to 1.0 after Remove Curse, got {restored}"
    print("✅ test_cure_curses_restores_vulnerability_multiplier passed")


def test_cure_curses_removes_affliction_and_clears_flag():
    """cure_curses on a Curse of Affliction removes the tracked entry AND clears the Blinded flag."""
    engine, bm, caster, victim = _setup_pair()
    _cast_curse(engine, bm, caster, victim, curse_kind=3, curse_choice=0, condition_name="Blinded")
    assert engine.get_agent_conditions(bm, victim).blinded, "affliction should have Blinded the target"

    engine.cure_curses(bm, victim)

    assert not engine.get_agent_conditions(bm, victim).blinded, "Blinded flag must be cleared"
    assert not [c for c in engine.active_agent_conditions if c.agent_idx == victim], \
        "no curse tracking entries should remain"
    print("✅ test_cure_curses_removes_affliction_and_clears_flag passed")


def test_cure_curses_fires_kickback_on_caster():
    """Freeing the victim still rebounds the Vistani kickback onto the curse's caster."""
    engine, bm, caster, victim = _setup_pair()
    _cast_curse(engine, bm, caster, victim, curse_kind=2, curse_choice=int(rpg.SaveAbility.SaveWis))
    before = engine.get_agent_stats(bm, caster).hp_cur

    engine.cure_curses(bm, victim)

    dealt = before - engine.get_agent_stats(bm, caster).hp_cur
    assert 3 <= dealt <= 18, f"ending the curse should rebound 3d6 on the caster, got {dealt}"
    print("✅ test_cure_curses_fires_kickback_on_caster passed")


def test_cure_curses_no_op_when_uncursed():
    """cure_curses on a creature with no curse removes nothing and returns 0."""
    engine, bm, caster, victim = _setup_pair()
    assert engine.cure_curses(bm, victim) == 0
    print("✅ test_cure_curses_no_op_when_uncursed passed")


def test_remove_curse_spell_end_to_end():
    """The Remove Curse spell (Help type) cast through execute_spell clears the curse."""
    engine, bm, caster, victim = _setup_pair()
    _cast_curse(engine, bm, caster, victim, curse_kind=1, curse_choice=2)  # Fire vulnerability
    assert list(engine.get_agent_stats(bm, victim).magic_damage_multipliers)[2] == 2.0

    _cast_restore(engine, bm, caster, victim, "Remove Curse", rpg.SpellType.Help)

    assert list(engine.get_agent_stats(bm, victim).magic_damage_multipliers)[2] == 1.0, \
        "Remove Curse should have restored the vulnerability multiplier"
    assert not [c for c in engine.active_agent_conditions if c.agent_idx == victim], \
        "no curse should remain after Remove Curse"
    print("✅ test_remove_curse_spell_end_to_end passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Greater Restoration
# ─────────────────────────────────────────────────────────────────────────────

def test_greater_restoration_reduces_exhaustion_by_one():
    engine, bm, caster, victim = _setup_pair()
    vc = engine.get_agent_conditions(bm, victim)
    vc.exhaustion_level = 3
    engine.set_agent_conditions(bm, victim, vc)

    changed = engine.greater_restoration(bm, victim)

    assert changed
    assert engine.get_agent_conditions(bm, victim).exhaustion_level == 2, \
        "Greater Restoration should remove exactly one level of Exhaustion"
    print("✅ test_greater_restoration_reduces_exhaustion_by_one passed")


def test_greater_restoration_clears_charmed():
    engine, bm, caster, victim = _setup_pair()
    vc = engine.get_agent_conditions(bm, victim)
    vc.charmed = True
    vc.charmed_by = caster
    engine.set_agent_conditions(bm, victim, vc)

    engine.greater_restoration(bm, victim)

    vc2 = engine.get_agent_conditions(bm, victim)
    assert not vc2.charmed and vc2.charmed_by == -1, "Charmed must be cleared"
    print("✅ test_greater_restoration_clears_charmed passed")


def test_greater_restoration_restores_hp_maximum():
    """A vampiric HP-max drain (available_hit_points) is restored."""
    engine, bm, caster, victim = _setup_pair()
    vs = engine.get_agent_stats(bm, victim)
    vs.hp_max = 40
    vs.available_hit_points = 15   # effective max is 40 - 15 = 25
    engine.set_agent_stats(bm, victim, vs)

    engine.greater_restoration(bm, victim)

    assert engine.get_agent_stats(bm, victim).available_hit_points == 0, \
        "HP-maximum reduction must be fully restored"
    print("✅ test_greater_restoration_restores_hp_maximum passed")


def test_greater_restoration_cures_petrified_and_restores_state():
    """Un-petrifying restores the creature's real speed and damage multipliers from the
    pre-petrify snapshot (not the flat 0-speed / 0.5× the condition imposes)."""
    engine, bm, caster, victim = _setup_pair()
    vs = engine.get_agent_stats(bm, victim)
    vs.speed_walk = 30
    vs.set_magic_damage_multiplier(1, 2.0)   # Cold: vulnerable before petrifying
    engine.set_agent_stats(bm, victim, vs)

    engine.apply_petrified(bm, victim)
    assert engine.get_agent_conditions(bm, victim).petrified
    assert engine.get_agent_stats(bm, victim).speed_walk == 0
    assert list(engine.get_agent_stats(bm, victim).magic_damage_multipliers)[1] == 0.5

    engine.greater_restoration(bm, victim)

    st = engine.get_agent_stats(bm, victim)
    assert not engine.get_agent_conditions(bm, victim).petrified, "Petrified must be cleared"
    assert st.speed_walk == 30, f"walking speed must be restored to 30, got {st.speed_walk}"
    assert list(st.magic_damage_multipliers)[1] == 2.0, \
        "the pre-petrify Cold vulnerability must be restored (not left at 0.5×)"
    print("✅ test_greater_restoration_cures_petrified_and_restores_state passed")


def test_greater_restoration_cures_curse_too():
    """Greater Restoration also strips curses (and rebounds their kickback)."""
    engine, bm, caster, victim = _setup_pair()
    _cast_curse(engine, bm, caster, victim, curse_kind=2, curse_choice=int(rpg.SaveAbility.SaveWis))
    before = engine.get_agent_stats(bm, caster).hp_cur

    engine.greater_restoration(bm, victim)

    assert not engine.curse_save_disadvantage(bm, victim, rpg.SaveAbility.SaveWis), \
        "the curse should be cleared by Greater Restoration"
    dealt = before - engine.get_agent_stats(bm, caster).hp_cur
    assert 3 <= dealt <= 18, f"the cured curse should still rebound on its caster, got {dealt}"
    print("✅ test_greater_restoration_cures_curse_too passed")


def test_greater_restoration_no_op_when_healthy():
    engine, bm, caster, victim = _setup_pair()
    assert engine.greater_restoration(bm, victim) is False, \
        "a creature with nothing to restore should report no change"
    print("✅ test_greater_restoration_no_op_when_healthy passed")


def test_greater_restoration_spell_end_to_end():
    """The Greater Restoration spell (Help type) cast through execute_spell reduces Exhaustion."""
    engine, bm, caster, victim = _setup_pair()
    vc = engine.get_agent_conditions(bm, victim)
    vc.exhaustion_level = 2
    engine.set_agent_conditions(bm, victim, vc)

    _cast_restore(engine, bm, caster, victim, "Greater Restoration", rpg.SpellType.Help)

    assert engine.get_agent_conditions(bm, victim).exhaustion_level == 1, \
        "Greater Restoration should have removed one Exhaustion level"
    print("✅ test_greater_restoration_spell_end_to_end passed")


if __name__ == "__main__":
    test_cure_curses_removes_weakness_curse()
    test_cure_curses_restores_vulnerability_multiplier()
    test_cure_curses_removes_affliction_and_clears_flag()
    test_cure_curses_fires_kickback_on_caster()
    test_cure_curses_no_op_when_uncursed()
    test_remove_curse_spell_end_to_end()
    test_greater_restoration_reduces_exhaustion_by_one()
    test_greater_restoration_clears_charmed()
    test_greater_restoration_restores_hp_maximum()
    test_greater_restoration_cures_petrified_and_restores_state()
    test_greater_restoration_cures_curse_too()
    test_greater_restoration_no_op_when_healthy()
    test_greater_restoration_spell_end_to_end()
    print("\nAll Remove Curse / Greater Restoration tests passed ✅")
