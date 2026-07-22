#!/usr/bin/env python3
"""
Weapon-list generalization — Phase 1 of MULTIATTACK_RECIPES_PLAN.md.

Weapons were a fixed 3-slot array [main_hand, off_hand, ranged], capping a monster at 3
distinct attacks. They are now a variable-length "Attack N" list (still padded to >=3 so
the PC main/off/ranged convention holds), letting a monster carry a 4th/5th distinct weapon
that a multiattack recipe can reference by index.

Covers:
  - the C++ set/get round-trip preserves >3 weapons and pads short lists to 3
  - helpers._weapons_to_list / _weapons_from_list (new flat list form) round-trip
  - back-compat: the legacy {main_hand,off_hand,ranged} dict still loads
  - trailing empties are dropped on save but interior slots keep their index
  - agent_loader loads the new list form
"""

import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from helpers import (_weapon_to_dict, _dict_to_weapon, _weapons_to_list,
                     _weapons_from_list, _weapon_slot_is_empty)


def _is_empty_slot(w):
    """A blank weapon slot: empty name or the default "Unarmed" sentinel."""
    return _weapon_slot_is_empty(w)
from agent_loader import load_agents_from_json
from test_helpers import setup_battle_map, setup_combat_engine, add_agent_to_battle, create_test_agent


def _named_weapon(name, num_dice=1, die_size=6, dtype=rpg.PhysicalDamage.Slashing):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.proficient = True
    pr = rpg.PhysicalDamageRoll(); pr.type = dtype; pr.num_dice = num_dice; pr.die_size = die_size
    w.physical_damage_types = [pr]
    return w


def test_cpp_roundtrip_more_than_three():
    """A 5-weapon list survives set→get with all 5 distinct attacks intact."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Hydra", 5, 5), hp=100)
    names = ["Bite1", "Bite2", "Bite3", "Bite4", "Tail"]
    engine.set_agent_weapons(bm, idx, [_named_weapon(n) for n in names])
    got = engine.get_agent_weapons(bm, idx)
    assert len(got) == 5, f"expected 5 weapons, got {len(got)}"
    assert [w.name for w in got] == names, [w.name for w in got]
    print("✅ test_cpp_roundtrip_more_than_three passed")


def test_cpp_pads_short_list_to_three():
    """A single-weapon list is padded to >=3 so weapons[0/1/2] stay addressable."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 6, 6), hp=10)
    engine.set_agent_weapons(bm, idx, [_named_weapon("Scimitar")])
    got = engine.get_agent_weapons(bm, idx)
    assert len(got) >= 3, f"expected padding to >=3, got {len(got)}"
    assert got[0].name == "Scimitar"
    # Padded slots are blank rpg.Weapon()s — an empty name or the "Unarmed" sentinel.
    assert _is_empty_slot(got[1]) and _is_empty_slot(got[2]), (got[1].name, got[2].name)
    print("✅ test_cpp_pads_short_list_to_three passed")


def test_weapons_to_list_drops_trailing_empties():
    """_weapons_to_list keeps interior indices but trims trailing blank slots."""
    weapons = [_named_weapon("Bite"), rpg.Weapon(), _named_weapon("Tail"),
               rpg.Weapon(), rpg.Weapon()]
    data = _weapons_to_list(weapons)
    assert len(data) == 3, f"expected trailing empties dropped -> 3, got {len(data)}"
    assert data[0]["name"] == "Bite"
    assert data[1] == {}          # interior empty preserved so 'Tail' keeps index 2
    assert data[2]["name"] == "Tail"
    print("✅ test_weapons_to_list_drops_trailing_empties passed")


def test_list_form_roundtrip():
    """A 4-attack list round-trips through _weapons_to_list -> _weapons_from_list."""
    weapons = [_named_weapon("Claw"), _named_weapon("Claw2"),
               _named_weapon("Ranged Spit"), _named_weapon("Slam")]
    weapons[2].type = rpg.WeaponType.Ranged
    restored = _weapons_from_list(_weapons_to_list(weapons))
    assert len(restored) == 4, f"expected 4 weapons, got {len(restored)}"
    assert [w.name for w in restored] == ["Claw", "Claw2", "Ranged Spit", "Slam"]
    assert restored[2].type == rpg.WeaponType.Ranged
    print("✅ test_list_form_roundtrip passed")


def test_legacy_dict_form_still_loads():
    """Back-compat: the old {main_hand,off_hand,ranged} dict deserializes and pads to 3."""
    legacy = {
        "main_hand": _weapon_to_dict(_named_weapon("Battleaxe")),
        "off_hand": "",
        "ranged": _weapon_to_dict(_named_weapon("Hurl Flame")),
    }
    restored = _weapons_from_list(legacy)
    assert len(restored) == 3
    assert restored[0].name == "Battleaxe"
    assert _is_empty_slot(restored[1]), restored[1].name
    assert restored[2].name == "Hurl Flame"
    print("✅ test_legacy_dict_form_still_loads passed")


def test_from_list_pads_to_three():
    """A 1-entry list deserializes to 3 padded rpg.Weapon."""
    restored = _weapons_from_list([_weapon_to_dict(_named_weapon("Dagger"))])
    assert len(restored) == 3
    assert restored[0].name == "Dagger"
    print("✅ test_from_list_pads_to_three passed")


def test_agent_loader_reads_list_form():
    """agent_loader.load_agents_from_json accepts the new flat list 'weapons' field,
    including a 4th attack that a fixed 3-slot loader could not hold."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    agents_json = {
        "agents": [{
            "name": "PitFiend", "sprite_path": "", "size": 1, "col": 5, "row": 5,
            "stats": {"str": 26, "hp_max": 300, "hp_cur": 300, "ac": 19},
            "weapons": [
                _weapon_to_dict(_named_weapon("Bite", 2, 8, rpg.PhysicalDamage.Piercing)),
                _weapon_to_dict(_named_weapon("Devilish Claw", 2, 8)),
                {},
                _weapon_to_dict(_named_weapon("Fiery Mace", 2, 6, rpg.PhysicalDamage.Bludgeoning)),
            ],
        }]
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(agents_json, f)
        path = f.name
    try:
        assert load_agents_from_json(path, bm, engine, sprites_dir=""), "agent load failed"
        got = engine.get_agent_weapons(bm, 0)
        assert len(got) >= 4, f"4th attack dropped — only {len(got)} slots"
        assert got[0].name == "Bite"
        assert got[1].name == "Devilish Claw"
        assert _is_empty_slot(got[2]), got[2].name   # interior empty preserved
        assert got[3].name == "Fiery Mace"
        print("✅ test_agent_loader_reads_list_form passed")
    finally:
        os.unlink(path)


def test_agent_loader_reads_legacy_dict():
    """agent_loader still loads the legacy 3-slot dict save."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    agents_json = {
        "agents": [{
            "name": "Wolf", "sprite_path": "", "size": 1, "col": 4, "row": 4,
            "stats": {"str": 14, "hp_max": 20, "hp_cur": 20, "ac": 13},
            "weapons": {"main_hand": _weapon_to_dict(_named_weapon("Bite")),
                        "off_hand": "", "ranged": ""},
        }]
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(agents_json, f)
        path = f.name
    try:
        assert load_agents_from_json(path, bm, engine, sprites_dir=""), "agent load failed"
        got = engine.get_agent_weapons(bm, 0)
        assert got[0].name == "Bite"
        print("✅ test_agent_loader_reads_legacy_dict passed")
    finally:
        os.unlink(path)


def main():
    print("Running weapon-list generalization tests...\n")
    test_cpp_roundtrip_more_than_three()
    test_cpp_pads_short_list_to_three()
    test_weapons_to_list_drops_trailing_empties()
    test_list_form_roundtrip()
    test_legacy_dict_form_still_loads()
    test_from_list_pads_to_three()
    test_agent_loader_reads_list_form()
    test_agent_loader_reads_legacy_dict()
    print("\n" + "=" * 60)
    print("✅ All weapon-list generalization tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
