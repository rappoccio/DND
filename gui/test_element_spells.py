#!/usr/bin/env python3
"""
Cast-time element choice — Chromatic Orb & Sorcerous Burst (G5b picker, second consumer).

These two spells don't have a fixed damage type in spells.json (the stored type is a placeholder);
the caster picks one element per cast. The GUI opens the reusable ElementPickerDialog and stores the
choice on SpellAction.damage_type_override; executeSpell rewrites every magic-damage roll's type to
that MagicDamage_t for THAT cast only (no persistent mutation of the stored spell — design choice (a)).

Verified here:
  · the chosen type is what actually lands (resistance to the chosen type halves it; resistance to a
    DIFFERENT type does not),
  · the override genuinely overrides the stored placeholder type (resisting the stored type no longer
    matters once a different element is chosen),
  · the override is per-cast — the agent's stored spell keeps its placeholder type afterward,
  · Sorcerous Burst's Psychic option (which Chromatic Orb lacks) works,
  · the SpellAction field round-trips.

To isolate the rewrite from to-hit randomness, the loaded spells are made Automatic (the override is
independent of the attack roll) and their damage is normalized to a flat 10 (num_dice=0, bonus=10).

MagicDamage_t indices: Acid=0, Cold=1, Fire=2, Force=3, Lightning=4, Necrotic=5, Poison=6,
Psychic=7, Radiant=8, Thunder=9.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
import helpers
from test_helpers import setup_battle_map, setup_combat_engine
from test_feats import _place, _target

ACID, COLD, FIRE, LIGHTNING, POISON, PSYCHIC, THUNDER = 0, 1, 2, 4, 6, 7, 9
_SPELLS_JSON = os.path.join(os.path.dirname(__file__), "spells.json")


def _load_spell(name, flat=10):
    """Load a real spell from spells.json, made deterministic: Automatic (always resolves) and a
    flat `flat` damage (no dice) while KEEPING its stored placeholder damage type."""
    catalog = json.load(open(_SPELLS_JSON))
    d = next(s for s in catalog if s["name"] == name)
    sp = helpers._dict_to_spell(d)
    sp.attack_type = rpg.SpellAttack.Automatic
    assert sp.magic_damage_rolls, f"{name} should have a magic damage roll"
    for r in sp.magic_damage_rolls:
        r.num_dice = 0
        r.die_size = 6
        r.bonus = flat
    return sp


def _caster(engine, bm, idx):
    s = engine.get_agent_stats(bm, idx)
    s.intel = 16
    s.spellcasting_ability = 3
    s.prof_bonus = 3
    s.spell_slots_remaining = [9, 9, 9, 9, 9, 0, 0, 0, 0]
    engine.set_agent_stats(bm, idx, s)


def _set_mult(engine, bm, idx, type_idx, mult):
    s = engine.get_agent_stats(bm, idx)
    arr = list(s.magic_damage_multipliers)
    arr[type_idx] = mult
    s.magic_damage_multipliers = arr
    engine.set_agent_stats(bm, idx, s)


def _cast(engine, bm, caster, tgt, spell, override=-1):
    engine.set_agent_spells(bm, caster, [spell])
    act = rpg.SpellAction()
    act.caster_idx = caster
    act.spell_idx = 0
    act.target_indices = [tgt]
    act.damage_type_override = override
    res = engine.execute_spell(bm, act)
    return res.target_results[0].total_damage


# ─────────────────────────────────────────────────────────────────────────────
#  Binding sanity
# ─────────────────────────────────────────────────────────────────────────────

def test_override_field_binding():
    act = rpg.SpellAction()
    assert act.damage_type_override == -1, "defaults to -1 (no override)"
    act.damage_type_override = FIRE
    assert act.damage_type_override == FIRE, "round-trips"
    print("✅ test_override_field_binding passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Chromatic Orb
# ─────────────────────────────────────────────────────────────────────────────

def test_chromatic_orb_lands_as_chosen_type():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Sorcerer", 5, 5); _caster(engine, bm, a)
    t = _place(engine, bm, "Tgt", 6, 5); _target(engine, bm, t, hp=10_000)
    spell = _load_spell("Chromatic Orb")

    _set_mult(engine, bm, t, FIRE, 0.5)                  # resists the CHOSEN element
    assert _cast(engine, bm, a, t, spell, override=FIRE) == 5, "Fire-chosen + Fire-resistant → halved"

    _set_mult(engine, bm, t, FIRE, 1.0)                  # clear
    _set_mult(engine, bm, t, COLD, 0.5)                  # resists a DIFFERENT element
    assert _cast(engine, bm, a, t, spell, override=FIRE) == 10, "Fire-chosen vs Cold resistance → full"
    print("✅ test_chromatic_orb_lands_as_chosen_type passed")


def test_chromatic_orb_override_replaces_stored_type():
    # The stored placeholder type is Thunder. Choosing Fire must make Thunder resistance irrelevant,
    # and NOT choosing (override=-1) must fall back to the stored Thunder type.
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Sorcerer", 5, 5); _caster(engine, bm, a)
    t = _place(engine, bm, "Tgt", 6, 5); _target(engine, bm, t, hp=10_000)
    spell = _load_spell("Chromatic Orb")
    assert spell.magic_damage_rolls[0].type == rpg.MagicDamage.Thunder, "stored placeholder is Thunder"

    _set_mult(engine, bm, t, THUNDER, 0.5)               # resists the STORED type
    assert _cast(engine, bm, a, t, spell, override=-1) == 5, "no choice → stored Thunder is resisted"
    assert _cast(engine, bm, a, t, spell, override=FIRE) == 10, "Fire-chosen → Thunder resistance no longer applies"
    print("✅ test_chromatic_orb_override_replaces_stored_type passed")


def test_override_is_per_cast_only():
    # The agent's stored spell must keep its placeholder type after a cast (no persistent mutation).
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Sorcerer", 5, 5); _caster(engine, bm, a)
    t = _place(engine, bm, "Tgt", 6, 5); _target(engine, bm, t, hp=10_000)
    spell = _load_spell("Chromatic Orb")
    _cast(engine, bm, a, t, spell, override=FIRE)
    stored = engine.get_agent_spells(bm, a)[0]
    assert stored.magic_damage_rolls[0].type == rpg.MagicDamage.Thunder, "stored spell unchanged after the cast"
    print("✅ test_override_is_per_cast_only passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Sorcerous Burst
# ─────────────────────────────────────────────────────────────────────────────

def test_sorcerous_burst_lands_as_chosen_type():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Sorcerer", 5, 5); _caster(engine, bm, a)
    t = _place(engine, bm, "Tgt", 6, 5); _target(engine, bm, t, hp=10_000)
    spell = _load_spell("Sorcerous Burst")

    _set_mult(engine, bm, t, PSYCHIC, 0.5)               # Psychic is a Sorcerous-Burst-only option
    assert _cast(engine, bm, a, t, spell, override=PSYCHIC) == 5, "Psychic-chosen + Psychic-resistant → halved"

    _set_mult(engine, bm, t, PSYCHIC, 1.0)
    _set_mult(engine, bm, t, ACID, 0.5)
    assert _cast(engine, bm, a, t, spell, override=PSYCHIC) == 10, "Psychic-chosen vs Acid resistance → full"
    print("✅ test_sorcerous_burst_lands_as_chosen_type passed")


def main():
    print("Running cast-time element choice tests (Chromatic Orb / Sorcerous Burst)...\n")
    test_override_field_binding()
    test_chromatic_orb_lands_as_chosen_type()
    test_chromatic_orb_override_replaces_stored_type()
    test_override_is_per_cast_only()
    test_sorcerous_burst_lands_as_chosen_type()
    print("\n" + "=" * 60)
    print("✅ All cast-time element choice tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
