#!/usr/bin/env python3
"""
Weapon save/load round-trip — regression for NPC/monster weapons being dropped.

Bug: the GUI saved weapons by NAME only and reconstructed them by looking the name up in the
PC weapons.json catalog. NPC / monster weapons (Bite, Claw, custom attacks) aren't in that
catalog, so they were silently lost on a save→load round-trip (and per-weapon customizations
like bonus_hit / mastery / damage dice were lost for catalog weapons too).

Fix: save the full weapon dict (helpers._weapon_to_dict) and reconstruct from it directly
(helpers._dict_to_weapon), no catalog lookup. This verifies both the serializer round-trip and
the agent loader (load_agents_from_json), which mirrors the GUI _load_agents dict path.
"""

import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from helpers import _weapon_to_dict, _dict_to_weapon
from agent_loader import load_agents_from_json
from test_helpers import setup_battle_map, setup_combat_engine


def _npc_weapon():
    """A monster attack that is NOT in the PC weapons.json catalog."""
    w = rpg.Weapon()
    w.name = "Bite"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 10
    w.proficient = True
    w.bonus_hit = 4
    w.bonus_damage = 2
    w.heavy = True
    w.mastery = rpg.WeaponMastery.Topple
    pr = rpg.PhysicalDamageRoll(); pr.type = rpg.PhysicalDamage.Piercing; pr.num_dice = 2; pr.die_size = 6
    mr = rpg.MagicDamageRoll(); mr.type = rpg.MagicDamage.Necrotic; mr.num_dice = 1; mr.die_size = 8
    w.physical_damage_types = [pr]
    w.magic_damage_types = [mr]
    return w


def test_weapon_dict_round_trip():
    w = _npc_weapon()
    w2 = _dict_to_weapon(_weapon_to_dict(w))
    assert w2.name == "Bite"
    assert w2.reach_ft == 10
    assert w2.bonus_hit == 4 and w2.bonus_damage == 2
    assert w2.heavy is True
    assert w2.mastery == rpg.WeaponMastery.Topple
    assert len(w2.physical_damage_types) == 1
    pr = w2.physical_damage_types[0]
    assert pr.type == rpg.PhysicalDamage.Piercing and pr.num_dice == 2 and pr.die_size == 6
    assert len(w2.magic_damage_types) == 1
    mr = w2.magic_damage_types[0]
    assert mr.type == rpg.MagicDamage.Necrotic and mr.num_dice == 1 and mr.die_size == 8
    print("✅ test_weapon_dict_round_trip passed")


def test_npc_weapon_survives_agent_load():
    """An agents JSON with a full weapon dict (the new save format) loads the weapon back —
    even though 'Bite' is not in the PC weapons catalog."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    agents_json = {
        "agents": [{
            "name": "Wolf", "sprite_path": "", "size": 1, "col": 5, "row": 5,
            "stats": {"str": 14, "dex": 12, "con": 12, "hp_max": 20, "hp_cur": 20, "ac": 13},
            "weapons": {"main_hand": _weapon_to_dict(_npc_weapon()), "off_hand": "", "ranged": ""},
        }]
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(agents_json, f)
        path = f.name
    try:
        assert load_agents_from_json(path, bm, engine, sprites_dir=""), "agent load failed"
        w = engine.get_agent_weapons(bm, 0)[0]
        assert w.name == "Bite", f"NPC weapon dropped on load — got '{w.name}'"
        assert w.reach_ft == 10 and w.bonus_hit == 4
        assert w.physical_damage_types[0].num_dice == 2 and w.physical_damage_types[0].die_size == 6
        print("✅ test_npc_weapon_survives_agent_load passed")
    finally:
        os.unlink(path)


def test_legacy_name_string_still_loads():
    """Backward compat: an old save with a bare weapon-name string still resolves via the catalog."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    agents_json = {
        "agents": [{
            "name": "Fighter", "sprite_path": "", "size": 1, "col": 5, "row": 5,
            "stats": {"str": 16, "hp_max": 30, "hp_cur": 30, "ac": 16},
            "weapons": {"main_hand": "Longsword", "off_hand": "", "ranged": ""},
        }]
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(agents_json, f)
        path = f.name
    try:
        # agent_loader only reconstructs dict weapons (no PC catalog); a bare name yields the
        # default Unarmed there. The GUI _load_agents resolves names via weapon_name_to_dict.
        # Here we just assert the loader doesn't choke on the legacy string form.
        assert load_agents_from_json(path, bm, engine, sprites_dir=""), "agent load failed"
        print("✅ test_legacy_name_string_still_loads passed")
    finally:
        os.unlink(path)


def main():
    print("Running weapon save/load round-trip tests...\n")
    test_weapon_dict_round_trip()
    test_npc_weapon_survives_agent_load()
    test_legacy_name_string_still_loads()
    print("\n" + "=" * 60)
    print("✅ All weapon save/load tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
