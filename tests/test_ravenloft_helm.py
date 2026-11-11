#!/usr/bin/env python3
"""Ravenloft items RI4 — the Helm of Brilliance's aura and flame weapon (M4 + M5).

Diamond Light is an at-will item spell: a 30-ft Emanation that follows the wearer and deals
1d6 Radiant to each Undead that starts its turn in it, sparing every other creature (a new
`affects_creature_types` spell field). Fire Opal Flames is an at-will item spell giving the
wearer a weapon damage rider (`weapon_rider`): +1d6 Fire on every held-weapon hit, not on an
unarmed strike, until it runs out or a long rest clears it. Both round-trip through the spell
dicts; the Helm is then complete (bar its postponed light).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import json

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from helpers import (_dict_to_armor, _dict_to_spell, _dict_to_weapon, _spell_to_dict,
                     item_spell_entries)

_GUI = os.path.join(_ROOT, "gui")


def _load(fname):
    with open(os.path.join(_GUI, fname)) as f:
        return {r["name"]: r for r in json.load(f)}


ARMOR, SPELLS, WEAPONS = _load("armor.json"), _load("spells.json"), _load("weapons.json")


def _board():
    """Wearer at (5,5); an Undead foe 15 ft away, a living foe 15 ft away, an Undead foe
    ~42 ft away (outside the 30-ft aura)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    w = add_agent_to_battle(engine, bm, create_test_agent("Wearer", 5, 5), hp=60)
    near = add_agent_to_battle(engine, bm, create_test_agent("Zombie", 8, 5), hp=2000, ac=1)
    living = add_agent_to_battle(engine, bm, create_test_agent("Bandit", 5, 8), hp=200)
    far = add_agent_to_battle(engine, bm, create_test_agent("Ghoul", 11, 11), hp=200)
    for i in (near, far):
        s = engine.get_agent_stats(bm, i)
        s.is_undead = True
        engine.set_agent_stats(bm, i, s)
    bm.set_agent_faction(w, 1)
    for i in (near, living, far):
        bm.set_agent_faction(i, 2)
    armor = list(engine.get_agent_armor(bm, w))
    helm = _dict_to_armor(ARMOR["Helm of Brilliance"])
    helm.item_spells.attuned = True
    armor[0] = helm
    engine.set_agent_armor(bm, w, armor)
    engine.set_agent_spells(bm, w, item_spell_entries(engine, bm, w, SPELLS))
    return bm, engine, w, near, living, far


def _spell_idx(engine, bm, idx, name):
    return next(i for i, sp in enumerate(engine.get_agent_spells(bm, idx)) if sp.name == name)


def _cast(engine, bm, caster, name, targets=()):
    a = rpg.SpellAction()
    a.caster_idx, a.spell_idx, a.slot_level = caster, _spell_idx(engine, bm, caster, name), 0
    a.target_indices = list(targets)
    p = bm.placed_agents[caster].origin
    a.aoe_col, a.aoe_row = p.col, p.row
    return engine.execute_spell(bm, a)


def _hp(engine, bm, i):
    return engine.get_agent_stats(bm, i).hp_cur


# ── M4: Diamond Light ─────────────────────────────────────────────────────────
def test_diamond_light_hurts_only_undead():
    bm, engine, w, near, living, far = _board()
    assert _cast(engine, bm, w, "Diamond Light").valid
    hp = {i: _hp(engine, bm, i) for i in (near, living, far)}
    assert 1994 <= hp[near] < 2000, "the Undead inside takes 1d6 as the aura comes up"
    assert hp[living] == 200 and hp[far] == 200, "only Undead inside the aura"
    assert engine.get_agent_armor(bm, w)[0].item_spells.can_cast("Diamond Light"), "at will"

    for _ in range(3):
        for i in (near, living, far):
            before = _hp(engine, bm, i)
            engine.begin_turn(bm, i)
            lost = before - _hp(engine, bm, i)
            if i == near:
                assert 1 <= lost <= 6, f"1d6 Radiant at the start of its turn (lost {lost})"
            else:
                assert lost == 0, f"agent {i} lost {lost}"
            engine.end_turn(bm, i)
    print("✅ test_diamond_light_hurts_only_undead")


def test_diamond_light_follows_the_wearer():
    bm, engine, w, near, living, far = _board()
    assert _cast(engine, bm, w, "Diamond Light").valid
    engine.begin_turn(bm, w)
    bm.placed_agents[w].init_movement(60)
    before = _hp(engine, bm, far)
    assert engine.move_agent(bm, w, rpg.Cell(8, 8), rpg.MovementType.Walk)
    assert _hp(engine, bm, far) == before, "sweeping onto it does nothing: start of turn only"
    engine.end_turn(bm, w)
    engine.begin_turn(bm, far)
    assert before - _hp(engine, bm, far) >= 1, "the far ghoul is now inside the aura"
    print("✅ test_diamond_light_follows_the_wearer")


# ── M5: Fire Opal Flames ──────────────────────────────────────────────────────
def _arm(engine, bm, idx, name):
    weapons = engine.get_agent_weapons(bm, idx)
    weapons[0] = _dict_to_weapon(WEAPONS[name])
    engine.set_agent_weapons(bm, idx, weapons)


def _hits(engine, bm, a, t, n=30):
    out = []
    for _ in range(n):
        engine.begin_turn(bm, a)
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if r.hit:
            out.append(r)
    assert out
    return out


def test_fire_opal_flames_adds_fire_to_weapon_hits():
    bm, engine, w, near, _, _ = _board()
    _arm(engine, bm, w, "Longsword")
    bm.set_agent_position(near, rpg.Cell(6, 5))
    for r in _hits(engine, bm, w, near, n=5):
        assert rpg.MagicDamage.Fire not in list(r.magic_damage_types), "no flames yet"

    assert _cast(engine, bm, w, "Fire Opal Flames", [w]).valid
    s = engine.get_agent_stats(bm, w)
    assert (s.weapon_rider_dice, s.weapon_rider_die_size) == (1, 6)
    assert s.weapon_rider_damage_type == int(rpg.MagicDamage.Fire) and s.weapon_rider_turns > 50

    # A held weapon: +1d6 Fire on every hit.
    for r in _hits(engine, bm, w, near):
        assert rpg.MagicDamage.Fire in list(r.magic_damage_types)
        rider = [d for name, d in r.damage_breakdown if name == "weapon rider"]
        assert rider and 1 <= rider[0] <= (12 if r.critical else 6), rider
    print("✅ test_fire_opal_flames_adds_fire_to_weapon_hits")


def test_flames_skip_unarmed_and_end_on_long_rest():
    bm, engine, w, near, _, _ = _board()
    bm.set_agent_position(near, rpg.Cell(6, 5))
    assert _cast(engine, bm, w, "Fire Opal Flames", [w]).valid
    weapons = engine.get_agent_weapons(bm, w)
    weapons[0] = rpg.Weapon()                 # the default "Unarmed" strike
    engine.set_agent_weapons(bm, w, weapons)
    for r in _hits(engine, bm, w, near, n=20):
        assert not [d for name, d in r.damage_breakdown if name == "weapon rider"]

    engine.apply_long_rest(bm)
    s = engine.get_agent_stats(bm, w)
    assert s.weapon_rider_dice == 0 and s.weapon_rider_turns == 0
    print("✅ test_flames_skip_unarmed_and_end_on_long_rest")


def test_rider_counts_down():
    bm, engine, w, _, _, _ = _board()
    rec = dict(SPELLS["Fire Opal Flames"], duration=2)
    sp = _dict_to_spell(rec)
    engine.set_agent_spells(bm, w, [sp])
    a = rpg.SpellAction()
    a.caster_idx, a.spell_idx, a.slot_level, a.target_indices = w, 0, 0, [w]
    assert engine.execute_spell(bm, a).valid
    engine.begin_turn(bm, w)
    assert engine.get_agent_stats(bm, w).weapon_rider_turns == 1
    engine.begin_turn(bm, w)
    s = engine.get_agent_stats(bm, w)
    assert s.weapon_rider_turns == 0 and s.weapon_rider_dice == 0
    print("✅ test_rider_counts_down")


# ── Round trip ────────────────────────────────────────────────────────────────
def test_new_spell_fields_round_trip():
    dl = _dict_to_spell(SPELLS["Diamond Light"])
    assert dl.affects_creature_mask == int(rpg.CreatureType.Undead)
    assert dl.moves_with_caster and not dl.effects_on_enter and not dl.requires_concentration
    d = _spell_to_dict(dl)
    assert d["affects_creature_types"] == ["Undead"]
    assert _dict_to_spell(d).affects_creature_mask == int(rpg.CreatureType.Undead)

    fl = _dict_to_spell(SPELLS["Fire Opal Flames"])
    d = _spell_to_dict(fl)
    assert d["weapon_rider"] == {"type": "Fire", "num_dice": 1, "die_size": 6}
    assert _dict_to_spell(d).weapon_rider.num_dice == 1

    plain = _spell_to_dict(_dict_to_spell(SPELLS["Fireball"]))
    assert "affects_creature_types" not in plain and "weapon_rider" not in plain
    print("✅ test_new_spell_fields_round_trip")


def test_vampire_is_a_type_bit():
    bm, engine, w, near, _, _ = _board()
    s = engine.get_agent_stats(bm, near)
    s.is_vampire = True
    engine.set_agent_stats(bm, near, s)
    rec = dict(SPELLS["Diamond Light"], affects_creature_types=["Vampire"])
    sp = _dict_to_spell(rec)
    assert sp.affects_creature_mask == int(rpg.CreatureType.Vampire)
    print("✅ test_vampire_is_a_type_bit")


if __name__ == "__main__":
    test_diamond_light_hurts_only_undead()
    test_diamond_light_follows_the_wearer()
    test_fire_opal_flames_adds_fire_to_weapon_hits()
    test_flames_skip_unarmed_and_end_on_long_rest()
    test_rider_counts_down()
    test_new_spell_fields_round_trip()
    test_vampire_is_a_type_bit()
    print("\nAll Ravenloft items RI4 tests passed!")
