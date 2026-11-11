#!/usr/bin/env python3
"""Ravenloft items RI5 — M8 new spell records (plans/RAVENLOFT_ITEMS_PLAN.md).

Disruption (Saint Markovia's Thighbone, 1/day, DC 15): a Fiend or Undead within reach makes a
WIS save; a failure takes 25 Radiant, a success takes nothing and is Frightened (new spell field
`no_damage_on_save`, new condition flag `applies_on_save_success`); anyone else is no target.
Hold Vampires (Holy Symbol of Ravenkind, 1 charge, DC 15): vampires within 30 ft save or are
Paralyzed; other Undead are untouched. Crusader's Mantle (Yarik's Shortsword, 1/day): a 30-ft
concentration aura in which the caster and allies deal +1d4 Radiant on weapon hits.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import json

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from helpers import _dict_to_item, _dict_to_spell, _dict_to_weapon, item_spell_entries

_GUI = os.path.join(_ROOT, "gui")


def _load(fname):
    with open(os.path.join(_GUI, fname)) as f:
        return {r["name"]: r for r in json.load(f)}


SPELLS, WEAPONS, ITEMS = _load("spells.json"), _load("weapons.json"), _load("items.json")


def _board(*others):
    """Holder at (5,5), faction 1; each (name, col, row, wis, kwargs) in `others` added."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    h = add_agent_to_battle(engine, bm, create_test_agent("Holder", 5, 5), hp=60)
    idx = []
    for name, col, row, wis, faction, flags in others:
        i = add_agent_to_battle(engine, bm, create_test_agent(name, col, row), wis=wis, hp=500, ac=1)
        s = engine.get_agent_stats(bm, i)
        for k, v in flags.items():
            setattr(s, k, v)
        engine.set_agent_stats(bm, i, s)
        idx.append(i)
    # Factions last: adding an agent rebuilds the board.
    bm.set_agent_faction(h, 1)
    for i, (_, _, _, _, faction, _) in zip(idx, others):
        bm.set_agent_faction(i, faction)
    return bm, engine, h, idx


def _wield(engine, bm, idx, name, slot=0):
    w = _dict_to_weapon(WEAPONS[name])
    w.item_spells.attuned = True
    weapons = engine.get_agent_weapons(bm, idx)
    weapons[slot] = w
    engine.set_agent_weapons(bm, idx, weapons)


def _grant(engine, bm, idx):
    engine.set_agent_spells(bm, idx, item_spell_entries(engine, bm, idx, SPELLS))


def _cast(engine, bm, caster, name, targets=()):
    spells = engine.get_agent_spells(bm, caster)
    a = rpg.SpellAction()
    a.caster_idx = caster
    a.spell_idx = next(i for i, sp in enumerate(spells) if sp.name == name)
    a.slot_level = 0
    a.target_indices = list(targets)
    p = bm.placed_agents[caster].origin
    a.aoe_col, a.aoe_row = p.col, p.row
    engine.begin_turn(bm, caster)
    return engine.execute_spell(bm, a)


def _hp(engine, bm, i):
    return engine.get_agent_stats(bm, i).hp_cur


# ── Disruption ────────────────────────────────────────────────────────────────
def test_disruption_failed_save_takes_25():
    bm, engine, h, (zombie,) = _board(("Zombie", 6, 5, 1, 2, {"is_undead": True}))
    _wield(engine, bm, h, "Saint Markovia's Thighbone")
    _grant(engine, bm, h)
    res = _cast(engine, bm, h, "Disruption", [zombie])
    assert res.valid
    tr = {t.target_idx: t for t in res.target_results}[zombie]
    assert tr.save_dc == 15 and not tr.saved
    assert _hp(engine, bm, zombie) == 475, "25 Radiant, no dice"
    assert not engine.get_agent_conditions(bm, zombie).frightened
    uses = engine.get_agent_weapons(bm, h)[0].item_spells.uses_remaining
    assert uses == {"Disruption": 0}, "1/day"
    assert not any(engine.get_agent_spells(bm, h)[i].name == "Disruption"
                   for i in engine.available_castable_spells(bm, h))
    print("✅ test_disruption_failed_save_takes_25")


def test_disruption_success_frightens_without_damage():
    bm, engine, h, (fiend,) = _board(("Imp", 6, 5, 30, 2, {"is_fiend": True}))
    s = engine.get_agent_stats(bm, fiend)
    s.save_prof_wis, s.prof_bonus = True, 9       # +19: always saves vs DC 15
    engine.set_agent_stats(bm, fiend, s)
    _wield(engine, bm, h, "Saint Markovia's Thighbone")
    _grant(engine, bm, h)
    res = _cast(engine, bm, h, "Disruption", [fiend])
    tr = {t.target_idx: t for t in res.target_results}[fiend]
    assert tr.saved
    assert _hp(engine, bm, fiend) == 500, "nothing on a success, not half"
    assert engine.get_agent_conditions(bm, fiend).frightened, "Frightened on a success"
    print("✅ test_disruption_success_frightens_without_damage")


def test_disruption_ignores_the_living():
    bm, engine, h, (bandit,) = _board(("Bandit", 6, 5, 1, 2, {}))
    _wield(engine, bm, h, "Saint Markovia's Thighbone")
    _grant(engine, bm, h)
    res = _cast(engine, bm, h, "Disruption", [bandit])
    assert _hp(engine, bm, bandit) == 500
    assert not engine.get_agent_conditions(bm, bandit).frightened
    assert not [t for t in res.target_results if t.target_idx == bandit]
    print("✅ test_disruption_ignores_the_living")


# ── Hold Vampires ─────────────────────────────────────────────────────────────
def test_hold_vampires_paralyzes_only_vampires():
    bm, engine, h, (vamp, zombie, far_vamp) = _board(
        ("Spawn", 7, 5, 1, 2, {"is_undead": True, "is_vampire": True}),
        ("Zombie", 5, 7, 1, 2, {"is_undead": True}),
        ("Strahd", 11, 11, 1, 2, {"is_undead": True, "is_vampire": True}))
    sym = _dict_to_item(ITEMS["Holy Symbol of Ravenkind"])
    sym.item_spells.attuned = True
    engine.set_agent_items(bm, h, [sym])
    _grant(engine, bm, h)
    res = _cast(engine, bm, h, "Hold Vampires")
    assert res.valid
    by = {t.target_idx: t for t in res.target_results}
    assert set(by) == {vamp}, f"only the vampire within 30 ft ({set(by)})"
    assert by[vamp].save_dc == 15
    assert engine.get_agent_conditions(bm, vamp).paralyzed
    assert not engine.get_agent_conditions(bm, zombie).paralyzed
    assert not engine.get_agent_conditions(bm, far_vamp).paralyzed
    assert engine.get_agent_items(bm, h)[0].item_spells.charges == 9
    print("✅ test_hold_vampires_paralyzes_only_vampires")


# ── Crusader's Mantle ─────────────────────────────────────────────────────────
def _aura_riders(engine, bm, attacker, target, n=20):
    out = []
    for _ in range(n):
        engine.begin_turn(bm, attacker)
        r = engine.execute_action(bm, rpg.Attack(attacker, target, 0))
        if r.hit:
            out.append([d for name, d in r.damage_breakdown if name == "aura rider"])
    assert out
    return out


def test_crusaders_mantle_aura():
    bm, engine, h, (ally, far_ally, foe, foe2) = _board(
        ("Ally", 7, 5, 10, 1, {}), ("FarAlly", 11, 11, 10, 1, {}),
        ("Foe", 8, 5, 10, 2, {}), ("Foe2", 11, 10, 10, 2, {}))
    _wield(engine, bm, h, "Yarik's Shortsword")
    for i in (ally, far_ally):
        _wield(engine, bm, i, "Longsword")
    _grant(engine, bm, h)
    assert _cast(engine, bm, h, "Crusader's Mantle").valid
    c = engine.get_agent_conditions(bm, h)
    assert c.concentrating and c.concentrating_on == "Crusader's Mantle"
    assert engine.get_agent_weapons(bm, h)[0].item_spells.uses_remaining == \
        {"Crusader's Mantle": 0}
    assert engine.get_agent_stats(bm, h).weapon_rider_dice == 0, "an aura, not a personal rider"

    for riders in _aura_riders(engine, bm, ally, foe):
        assert len(riders) == 1 and 1 <= riders[0] <= 8, riders
    for riders in _aura_riders(engine, bm, far_ally, foe2):
        assert riders == [], "outside the 30-ft aura"
    print("✅ test_crusaders_mantle_aura")


def test_new_flags_parse():
    d = _dict_to_spell(SPELLS["Disruption"])
    assert d.no_damage_on_save and d.conditions[0].applies_on_save_success
    assert d.affects_creature_mask == int(rpg.CreatureType.Fiend) | int(rpg.CreatureType.Undead)
    assert not _dict_to_spell(SPELLS["Hold Person"]).conditions[0].applies_on_save_success
    from helpers import spell_classes
    assert spell_classes("Crusader's Mantle") == {"Paladin"}
    print("✅ test_new_flags_parse")


if __name__ == "__main__":
    test_disruption_failed_save_takes_25()
    test_disruption_success_frightens_without_damage()
    test_disruption_ignores_the_living()
    test_hold_vampires_paralyzes_only_vampires()
    test_crusaders_mantle_aura()
    test_new_flags_parse()
    print("\nAll Ravenloft items RI5 tests passed!")
