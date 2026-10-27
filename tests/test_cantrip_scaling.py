#!/usr/bin/env python3
"""
Tests for cantrip damage scaling by character level (2024 PHB / SRD 5.2): a damaging cantrip
gets one more damage die at total character levels 5, 11 and 17.

Opt-in per spell through the `cantrip_dice_per_tier` field in `gui/spells.json`, applied in
executeSpell next to the upcast block. Monster level-0 pseudo-spells (breath weapons, auras)
leave it at 0 and must not scale. True Strike scales by hand: +1d6/2d6/3d6 Radiant on the hit.

Spells are loaded straight from `gui/spells.json` via the real `helpers._dict_to_spell`.
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
import helpers
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from test_feats import _mk_weapon, _three

_GUI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")

SCALING = ["Acid Splash", "Chill Touch", "Fire Bolt", "Poison Spray", "Produce Flame",
           "Ray of Frost", "Sacred Flame", "Shocking Grasp", "Sorcerous Burst", "Starry Wisp",
           "Vicious Mockery", "Mind Sliver"]


def _spell_dicts():
    with open(os.path.join(_GUI_DIR, "spells.json")) as f:
        return json.load(f)


def _load_spell(name):
    for entry in _spell_dicts():
        if entry.get("name") == name:
            return helpers._dict_to_spell(entry)
    raise AssertionError(f"{name} not found in spells.json")


def _place(engine, bm, name, col, row, faction):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    bm.set_agent_faction(idx, faction)
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = 500
    s.hp_cur = 500
    s.str = 10
    s.dex = 1          # always fails a DEX save against the DC-40 caster
    s.base_ac = 10
    engine.set_agent_stats(bm, idx, s)
    return idx


def _caster(engine, bm, idx, levels):
    """levels: {CharacterClass: n}. Spell attack +40 and save DC 48, so attacks hit
    (bar a natural 1) and saves fail."""
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    s.spellcasting_ability = 3   # INT
    s.intel = 30
    s.prof_bonus = 30
    for cls, n in levels.items():
        s.add_class_level(cls, n)
    engine.set_agent_stats(bm, idx, s)


def _cast(engine, bm, caster, sp, targets, aoe=None):
    engine.set_agent_spells(bm, caster, [sp])
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = 0
    action.target_indices = list(targets)
    if aoe is not None:
        action.aoe_col, action.aoe_row = aoe
    return engine.execute_spell(bm, action)


def _setup(levels):
    bm, engine = setup_battle_map(), setup_combat_engine()
    me = _place(engine, bm, "Wizard", 5, 5, 1)
    foe = _place(engine, bm, "Orc", 6, 5, 2)
    _caster(engine, bm, me, levels)
    return bm, engine, me, foe


def _wiz(n):
    return {rpg.CharacterClass.Wizard: n}


def _hit_result(levels, name, aoe=False):
    """Cast until the foe takes a (non-natural-1) hit; return its TargetResult."""
    for _ in range(20):
        bm, engine, me, foe = _setup(levels)
        res = _cast(engine, bm, me, _load_spell(name), [] if aoe else [foe],
                    aoe=(6, 5) if aoe else None)
        trs = [tr for tr in res.target_results if tr.target_idx == foe]
        assert trs, f"{name}: the foe should be a target"
        if trs[0].total_damage > 0:
            return trs[0]
    raise AssertionError(f"{name}: no damaging cast in 20 tries")


# ─────────────────────────────────────────────────────────────────────────────

def test_json_opt_in():
    by_name = {d["name"]: d for d in _spell_dicts()}
    for n in SCALING:
        assert by_name[n].get("cantrip_dice_per_tier") == 1, f"{n} should scale"
        assert _load_spell(n).cantrip_dice_per_tier == 1, f"{n}: loader drops the field"
    for d in _spell_dicts():
        if d.get("level") == 0 and d["name"] not in SCALING:
            assert d.get("cantrip_dice_per_tier", 0) == 0, f"{d['name']} must not scale"
    assert by_name["Mind Sliver"]["upcast_dice_bonus"] == 0
    print("✅ test_json_opt_in passed")


def test_attack_cantrip_scales():
    """Fire Bolt: 1/2/3/4 d10 at levels 1/5/11/17 (doubled on a crit)."""
    for level, dice in ((1, 1), (5, 2), (11, 3), (17, 4)):
        tr = _hit_result(_wiz(level), "Fire Bolt")
        n = len(tr.dice_results)
        want = 2 * dice if tr.critical else dice
        assert n == want, f"Fire Bolt at level {level}: want {want} dice, got {n}"
    print("✅ test_attack_cantrip_scales passed")


def test_save_cantrip_scales():
    """Sacred Flame: 1/2/3/4 d8 on a failed save."""
    for level, dice in ((1, 1), (5, 2), (11, 3), (17, 4)):
        tr = _hit_result(_wiz(level), "Sacred Flame")
        assert len(tr.dice_results) == dice, \
            f"Sacred Flame at level {level}: want {dice} dice, got {len(tr.dice_results)}"
        assert dice <= tr.total_damage <= 8 * dice
    print("✅ test_save_cantrip_scales passed")


def test_acid_splash_scales():
    for level, dice in ((1, 1), (5, 2), (11, 3), (17, 4)):
        tr = _hit_result(_wiz(level), "Acid Splash", aoe=True)
        assert len(tr.dice_results) == dice, \
            f"Acid Splash at level {level}: want {dice} dice, got {len(tr.dice_results)}"
        assert dice <= tr.total_damage <= 6 * dice
    print("✅ test_acid_splash_scales passed")


def test_monster_level0_does_not_scale():
    """A breath weapon stored as a level-0 spell keeps its dice for a level-17 caster."""
    base = _load_spell("BreathFireConeLow")
    want = sum(r.num_dice for r in base.magic_damage_rolls)
    bm, engine = setup_battle_map(), setup_combat_engine()
    me = _place(engine, bm, "Dragon", 5, 5, 1)
    foe = _place(engine, bm, "Orc", 6, 5, 2)
    _caster(engine, bm, me, _wiz(17))
    res = _cast(engine, bm, me, base, [], aoe=(6, 5))
    trs = [tr for tr in res.target_results if tr.target_idx == foe]
    assert trs, "the foe should be in the cone"
    assert len(trs[0].dice_results) == want, \
        f"breath should roll {want} dice, got {len(trs[0].dice_results)}"
    print("✅ test_monster_level0_does_not_scale passed")


def test_multiclass_uses_total_level():
    """Wizard 3 / Cleric 2 is character level 5: tier 1."""
    tr = _hit_result({rpg.CharacterClass.Wizard: 3, rpg.CharacterClass.Cleric: 2}, "Sacred Flame")
    assert len(tr.dice_results) == 2, f"multiclass level 5: want 2 dice, got {len(tr.dice_results)}"
    print("✅ test_multiclass_uses_total_level passed")


def test_classless_npc_stays_tier0():
    """A stat-block caster with no class levels does not scale."""
    tr = _hit_result({}, "Sacred Flame")
    assert len(tr.dice_results) == 1
    print("✅ test_classless_npc_stays_tier0 passed")


def test_true_strike_radiant():
    """True Strike: weapon die + 0/1/2/3 d6 Radiant at levels 1/5/11/17 (doubled on a crit)."""
    for level, extra in ((1, 0), (5, 1), (11, 2), (17, 3)):
        for _ in range(20):
            bm, engine, me, foe = _setup(_wiz(level))
            engine.set_agent_weapons(bm, me, _three([_mk_weapon("Rapier")]))
            tr = _cast(engine, bm, me, _load_spell("True Strike"), [foe]).target_results[0]
            if tr.hit:
                break
        else:
            raise AssertionError("True Strike never hit")
        mult = 2 if tr.critical else 1
        want = mult * (1 + extra)     # _mk_weapon is 1d8
        assert len(tr.dice_results) == want, \
            f"True Strike at level {level}: want {want} dice, got {len(tr.dice_results)}"
    print("✅ test_true_strike_radiant passed")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
