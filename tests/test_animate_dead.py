#!/usr/bin/env python3
"""
Test Divine Intervention — Phase D3 (Animate Dead / Planar Binding).

D3 wires two GUI-resolved control spells and the two flags that route their targeting:

  - Animate Dead (animates_dead): targets a CORPSE (conditions.dead) via the shared
    corpse-pick and raises a Skeleton/Zombie servant from it (GUI spawn_agent). It must be
    distinct from revives_dead (Raise Dead brings the ORIGINAL creature back; Animate Dead
    consumes the corpse into an undead) so the corpse-pick can tell them apart.
  - Planar Binding (binds_creature): a Charisma-save single-target that, on a failed save,
    transfers the target to the caster's team (GUI control transfer).

The engine does nothing with either flag (both spells resolve entirely GUI-side, exactly like
the D2 corpse-pick), so coverage here is the serializer round-trips and the spells.json wiring
— the same shape as test_raise_dead.py. The click / spawn / save flows are exercised manually.

See DIVINE_INTERVENTION_SPEC.md §7 (D3) and DIVINE_INTERVENTION_PLAN.md Phase D3.
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
import helpers

_GUI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")


def _load_spell(name):
    """Build an rpg.Spell straight from spells.json via the real _dict_to_spell path, so the
    test also covers the JSON fields and the animates_dead / binds_creature deserializers."""
    with open(os.path.join(_GUI_DIR, "spells.json")) as f:
        data = json.load(f)
    for entry in data:
        if entry.get("name") == name:
            return helpers._dict_to_spell(entry), entry
    raise AssertionError(f"{name} not found in spells.json")


def test_animate_dead_flag_round_trips():
    """animates_dead survives JSON load and a dict round-trip, and is NOT revives_dead."""
    sp, _ = _load_spell("Animate Dead")
    assert getattr(sp, "animates_dead", False), "Animate Dead should load with animates_dead=True"
    assert not getattr(sp, "revives_dead", False), \
        "Animate Dead must NOT be revives_dead — it raises an undead, it doesn't revive the corpse"
    again = helpers._dict_to_spell(helpers._spell_to_dict(sp))
    assert again.animates_dead, "animates_dead should survive a serializer round-trip"
    assert not again.revives_dead, "revives_dead should stay False across the round-trip"
    print("✅ test_animate_dead_flag_round_trips passed")


def test_planar_binding_flag_round_trips():
    """binds_creature survives JSON load and a dict round-trip."""
    sp, _ = _load_spell("Planar Binding")
    assert getattr(sp, "binds_creature", False), "Planar Binding should load with binds_creature=True"
    again = helpers._dict_to_spell(helpers._spell_to_dict(sp))
    assert again.binds_creature, "binds_creature should survive a serializer round-trip"
    print("✅ test_planar_binding_flag_round_trips passed")


def test_revive_spells_do_not_animate():
    """The D2 revive spells carry revives_dead but never animates_dead — the corpse-pick must
    route them to the revive path, not the raise-an-undead path."""
    for name in ("Raise Dead", "Revivify"):
        sp, _ = _load_spell(name)
        assert getattr(sp, "revives_dead", False), f"{name} should stay revives_dead=True"
        assert not getattr(sp, "animates_dead", False), \
            f"{name} must NOT be animates_dead"
    print("✅ test_revive_spells_do_not_animate passed")


def test_json_wiring():
    """Animate Dead and Planar Binding are wired with the expected targeting fields."""
    _, ad = _load_spell("Animate Dead")
    assert ad.get("animates_dead") is True, "Animate Dead JSON needs animates_dead: true"
    assert ad["geometry"] == "Single", "Animate Dead picks one corpse (Single geometry)"
    assert ad["attack_type"] == "Automatic", "Animate Dead is not a save/attack roll"
    assert ad["level"] == 3, "Animate Dead is a 3rd-level spell"

    _, pb = _load_spell("Planar Binding")
    assert pb.get("binds_creature") is True, "Planar Binding JSON needs binds_creature: true"
    assert pb["geometry"] == "Single", "Planar Binding targets one creature"
    assert pb["attack_type"] == "Save", "Planar Binding is a saving-throw spell"
    assert pb["save_ability"] == "SaveCha", "Planar Binding forces a Charisma save"
    assert pb["level"] == 5, "Planar Binding is a 5th-level spell"
    print("✅ test_json_wiring passed")


def test_undead_stat_blocks_present():
    """The undead Animate Dead can raise (Skeleton / Zombie) exist in the bestiary, so the
    GUI spawn path has a stat block to load."""
    with open(os.path.join(_GUI_DIR, "DND2024_MonsterStats.json")) as f:
        mobs = json.load(f)
    names = set()

    def _walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("name"), str):
                names.add(o["name"])
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    _walk(mobs)
    for undead in ("Skeleton", "Zombie"):
        assert undead in names, f"Animate Dead needs a '{undead}' bestiary stat block"
    print("✅ test_undead_stat_blocks_present passed")


def run_all():
    test_animate_dead_flag_round_trips()
    test_planar_binding_flag_round_trips()
    test_revive_spells_do_not_animate()
    test_json_wiring()
    test_undead_stat_blocks_present()
    print("\n✅ All Animate Dead / Planar Binding (D3) tests passed")


if __name__ == "__main__":
    run_all()
