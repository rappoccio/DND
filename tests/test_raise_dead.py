#!/usr/bin/env python3
"""
Test Divine Intervention — Phase D2 (Raise Dead / the shared corpse revive path).

D2 wires the revive-a-corpse spells and the flag that drives the GUI corpse-pick mode
(select a conditions.dead body — invisible to the normal target click). Engine coverage
here; the corpse-pick click flow (_corpse_at / _resolve_corpse_spell) is exercised manually.

  - revives_dead round-trips through the spell serializers (JSON → rpg.Spell → dict → rpg.Spell).
  - Raise Dead on a true-dead corpse clears conditions.dead and restores the creature to life
    (>=1 HP), routing through the same heal choke point as every other Heal spell.
  - Revivify shares the identical path (it, too, could not revive a corpse before D2).
  - A revives_dead heal on a LIVE creature is an ordinary heal (no dead flag to clear, no crash).

See DIVINE_INTERVENTION_SPEC.md §7 (D2) and §10.5.
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
import helpers
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)

TEAM = 1
_GUI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")


def _load_spell(name):
    """Build an rpg.Spell straight from spells.json via the real _dict_to_spell path, so the
    test also covers the JSON fields and the revives_dead deserializer."""
    with open(os.path.join(_GUI_DIR, "spells.json")) as f:
        data = json.load(f)
    for entry in data:
        if entry.get("name") == name:
            return helpers._dict_to_spell(entry)
    raise AssertionError(f"{name} not found in spells.json")


def _place(engine, bm, name, col, row, faction=TEAM):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    bm.set_agent_faction(idx, faction)
    return idx


def _make_caster(engine, bm, idx, spell):
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_spells(bm, idx, [spell])


def _kill(engine, bm, idx):
    """Reduce to a true-dead corpse: down it, then set conditions.dead (as §10 does)."""
    engine.damage_agent(bm, idx, 999)
    engine.apply_unconscious(bm, idx)
    cond = engine.get_agent_conditions(bm, idx)
    cond.dead = True
    engine.set_agent_conditions(bm, idx, cond)


def _cast(engine, bm, caster, target, slot_level):
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = slot_level
    action.target_indices = [target]
    engine.execute_spell(bm, action)


def test_revives_dead_flag_round_trips():
    """revives_dead survives JSON load and a dict round-trip on both revive spells."""
    for name in ("Raise Dead", "Revivify"):
        sp = _load_spell(name)
        assert getattr(sp, "revives_dead", False), f"{name} should load with revives_dead=True"
        again = helpers._dict_to_spell(helpers._spell_to_dict(sp))
        assert again.revives_dead, f"{name}.revives_dead should survive a serializer round-trip"
    print("✅ test_revives_dead_flag_round_trips passed")


def test_raise_dead_revives_corpse():
    """Raise Dead on a corpse clears conditions.dead and brings it back at >=1 HP."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    ally   = _place(engine, bm, "Fighter", 6, 5)   # adjacent (within the 5 ft touch range)
    _make_caster(engine, bm, caster, _load_spell("Raise Dead"))

    _kill(engine, bm, ally)
    assert engine.get_agent_conditions(bm, ally).dead, "the ally should be a true-dead corpse first"

    _cast(engine, bm, caster, ally, slot_level=5)

    cond = engine.get_agent_conditions(bm, ally)
    s = engine.get_agent_stats(bm, ally)
    assert not cond.dead, "Raise Dead must clear the dead condition"
    assert not cond.unconscious, "the revived creature should regain consciousness"
    assert s.hp_cur >= 1, f"the revived creature should have >=1 HP, got {s.hp_cur}"
    print("✅ test_raise_dead_revives_corpse passed")


def test_revivify_shares_the_path():
    """Revivify (level 3) revives a corpse through the same choke point as Raise Dead."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    ally   = _place(engine, bm, "Rogue", 6, 5)
    _make_caster(engine, bm, caster, _load_spell("Revivify"))

    _kill(engine, bm, ally)
    _cast(engine, bm, caster, ally, slot_level=3)

    cond = engine.get_agent_conditions(bm, ally)
    assert not cond.dead, "Revivify must clear the dead condition"
    assert engine.get_agent_stats(bm, ally).hp_cur >= 1, "Revivify must restore >=1 HP"
    print("✅ test_revivify_shares_the_path passed")


def test_revives_dead_heal_on_live_creature_is_ordinary():
    """A revives_dead heal on a wounded-but-alive creature just heals — no dead flag, no crash."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    ally   = _place(engine, bm, "Fighter", 6, 5)
    _make_caster(engine, bm, caster, _load_spell("Raise Dead"))

    s = engine.get_agent_stats(bm, ally)
    s.hp_cur = 3
    engine.set_agent_stats(bm, ally, s)

    _cast(engine, bm, caster, ally, slot_level=5)

    s = engine.get_agent_stats(bm, ally)
    assert not engine.get_agent_conditions(bm, ally).dead, "a live target never becomes dead"
    assert s.hp_cur >= 4, f"the live target should be healed above 3 HP, got {s.hp_cur}"
    print("✅ test_revives_dead_heal_on_live_creature_is_ordinary passed")


def run_all():
    test_revives_dead_flag_round_trips()
    test_raise_dead_revives_corpse()
    test_revivify_shares_the_path()
    test_revives_dead_heal_on_live_creature_is_ordinary()
    print("\n✅ All Raise Dead (D2) tests passed")


if __name__ == "__main__":
    run_all()
