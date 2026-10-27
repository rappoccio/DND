#!/usr/bin/env python3
"""
Tests for two melee cantrips, both loaded straight from `gui/spells.json`:

Blade Ward (abjuration cantrip, Concentration up to 1 minute):
  - Whenever a creature makes an attack roll against the warded creature, the attacker
    subtracts 1d4 from the roll. A `blade_warded` Stats flag set by the "BladeWarded"
    condition, read by rollToHit (weapon attacks) and rollSpellAttack; torn down when
    concentration drops.

Booming Blade (evocation cantrip):
  - A melee weapon attack against a creature within 5 ft, run through the real weapon-attack
    pipeline. On a hit the target is sheathed until the start of the caster's next turn; if it
    willingly moves it takes 1d8 Thunder and the spell ends.
  - Scaling by character level: +1d8 Thunder on the hit at 5 (move damage 2d8), 2d8/3d8 at 11,
    3d8/4d8 at 17.
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


def _load_spell(name):
    with open(os.path.join(_GUI_DIR, "spells.json")) as f:
        data = json.load(f)
    for entry in data:
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
    s.dex = 10
    s.base_ac = 10
    engine.set_agent_stats(bm, idx, s)
    return idx


def _caster(engine, bm, idx, level=1, hit_bonus=50):
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    s.spellcasting_ability = 3   # INT
    s.intel = 16
    s.prof_bonus = 2
    s.set_class_level(rpg.CharacterClass.Wizard, level)
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, _three([_mk_weapon("Rapier", attack_bonus=hit_bonus)]))


def _cast(engine, bm, caster, sp, targets):
    engine.set_agent_spells(bm, caster, [sp])
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.target_indices = list(targets)
    return engine.execute_spell(bm, action)


def _sheaths(engine, idx):
    return [c for c in engine.active_agent_conditions
            if c.agent_idx == idx and c.condition_name == "BoomingBlade"]


def _hp(engine, bm, idx):
    return engine.get_agent_stats(bm, idx).hp_cur


def _walk(engine, bm, idx, col, row):
    engine.begin_turn(bm, idx)
    bm.placed_agents[idx].init_movement(30)
    assert engine.move_agent(bm, idx, rpg.Cell(col, row), rpg.MovementType.Walk), "setup: move failed"


# ─────────────────────────────────────────────────────────────────────────────
#  Blade Ward
# ─────────────────────────────────────────────────────────────────────────────

def test_blade_ward_json():
    sp = _load_spell("Blade Ward")
    assert sp.level == 0
    assert sp.requires_concentration
    assert [c.condition_name for c in sp.conditions] == ["BladeWarded"]
    print("✅ test_blade_ward_json passed")


def test_blade_ward_sets_flag_and_concentration_clears_it():
    bm, engine = setup_battle_map(), setup_combat_engine()
    me = _place(engine, bm, "Wizard", 5, 5, 1)
    _caster(engine, bm, me)
    _cast(engine, bm, me, _load_spell("Blade Ward"), [me])
    assert engine.get_agent_stats(bm, me).blade_warded, "caster should be warded"
    assert engine.get_agent_conditions(bm, me).concentrating, "Blade Ward is concentration"

    engine.drop_concentration(bm, me)
    assert not engine.get_agent_stats(bm, me).blade_warded, "ward must end with concentration"
    print("✅ test_blade_ward_sets_flag_and_concentration_clears_it passed")


def test_roll_to_hit_subtracts_1d4():
    engine = setup_combat_engine()
    atk = rpg.Stats()
    w = _mk_weapon("Axe", attack_bonus=0)
    for _ in range(40):
        r = engine.roll_to_hit(w, atk, 10)
        assert r.total_roll - r.d20 - r.attack_mod == 0, "unwarded: no extra term"
    seen = set()
    for _ in range(80):
        r = engine.roll_to_hit(w, atk, 10, target_blade_warded=True)
        d = r.total_roll - r.d20 - r.attack_mod
        assert -4 <= d <= -1, f"Blade Ward should subtract 1..4, got {d}"
        seen.add(d)
    assert len(seen) > 1, "the d4 should be rolled fresh each attack"
    print("✅ test_roll_to_hit_subtracts_1d4 passed")


def test_weapon_attack_against_warded_creature():
    bm, engine = setup_battle_map(), setup_combat_engine()
    me = _place(engine, bm, "Wizard", 5, 5, 1)
    foe = _place(engine, bm, "Orc", 6, 5, 2)
    _caster(engine, bm, me)
    _caster(engine, bm, foe, hit_bonus=0)
    _cast(engine, bm, me, _load_spell("Blade Ward"), [me])

    for _ in range(20):
        # A hit can break concentration (and with it the ward) — re-cast when that happens.
        if not engine.get_agent_stats(bm, me).blade_warded:
            _cast(engine, bm, me, _load_spell("Blade Ward"), [me])
        a = rpg.Attack()
        a.attacker_idx = foe
        a.target_idx = me
        a.weapon_idx = 0
        r = engine.execute_action(bm, a)
        assert r.valid
        d = r.total_roll - r.d20 - r.attack_mod
        assert -4 <= d <= -1, f"attack vs warded creature should lose 1..4, got {d}"
        s = engine.get_agent_stats(bm, me)
        s.hp_cur = s.hp_max
        engine.set_agent_stats(bm, me, s)
    print("✅ test_weapon_attack_against_warded_creature passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Booming Blade
# ─────────────────────────────────────────────────────────────────────────────

def _booming_setup(level):
    bm, engine = setup_battle_map(), setup_combat_engine()
    me = _place(engine, bm, "Bladesinger", 5, 5, 1)
    foe = _place(engine, bm, "Orc", 6, 5, 2)
    _caster(engine, bm, me, level=level)
    return bm, engine, me, foe


def _cast_until_hit(level):
    """Cast Booming Blade (to-hit +50, so only a natural 1 misses) until it lands."""
    for _ in range(10):
        bm, engine, me, foe = _booming_setup(level)
        res = _cast(engine, bm, me, _load_spell("Booming Blade"), [foe])
        tr = res.target_results[0]
        if tr.hit:
            return bm, engine, me, foe, tr
        assert not _sheaths(engine, foe), "a miss must not sheathe the target"
    raise AssertionError("Booming Blade never hit")


def test_booming_blade_hit_sheathes_without_thunder_at_level_1():
    bm, engine, me, foe, tr = _cast_until_hit(1)
    dealt = 500 - _hp(engine, bm, foe)
    assert dealt == tr.total_damage
    assert 1 <= dealt <= 16, f"level 1: weapon damage only (1d8, crit 2d8), got {dealt}"
    sh = _sheaths(engine, foe)
    assert len(sh) == 1 and sh[0].delay_dice == 1 and sh[0].delay_die_size == 8
    assert "sheathed" in tr.log_message
    print("✅ test_booming_blade_hit_sheathes_without_thunder_at_level_1 passed")


def test_moving_detonates_and_ends_spell():
    bm, engine, me, foe, _ = _cast_until_hit(1)
    before = _hp(engine, bm, foe)
    _walk(engine, bm, foe, 8, 5)
    boom = before - _hp(engine, bm, foe)
    assert 1 <= boom <= 8, f"moving should deal 1d8 Thunder, got {boom}"
    assert not _sheaths(engine, foe), "the spell ends after it detonates"

    before = _hp(engine, bm, foe)
    _walk(engine, bm, foe, 9, 5)
    assert _hp(engine, bm, foe) == before, "a second move deals nothing"
    print("✅ test_moving_detonates_and_ends_spell passed")


def test_level_5_scaling():
    bm, engine, me, foe, tr = _cast_until_hit(5)
    assert "Thunder" in tr.log_message, "level 5: the hit adds 1d8 Thunder"
    assert len(tr.dice_results) in (1, 2), "1d8 Thunder on the hit (2d8 on a crit)"
    sh = _sheaths(engine, foe)
    assert len(sh) == 1 and sh[0].delay_dice == 2, "level 5: moving deals 2d8"
    before = _hp(engine, bm, foe)
    _walk(engine, bm, foe, 8, 5)
    boom = before - _hp(engine, bm, foe)
    assert 2 <= boom <= 16, f"moving should deal 2d8 Thunder, got {boom}"
    print("✅ test_level_5_scaling passed")


def test_level_11_and_17_scaling():
    for level, on_hit, on_move in ((11, 2, 3), (17, 3, 4)):
        bm, engine, me, foe, tr = _cast_until_hit(level)
        n = len(tr.dice_results)
        assert n in (on_hit, 2 * on_hit), f"level {level}: {on_hit}d8 on the hit, got {n} dice"
        assert _sheaths(engine, foe)[0].delay_dice == on_move, f"level {level}: {on_move}d8 on move"
    print("✅ test_level_11_and_17_scaling passed")


def test_sheath_expires_at_casters_next_turn():
    bm, engine, me, foe, _ = _cast_until_hit(1)
    engine.tick_agent_conditions_for_caster(bm, me)
    assert not _sheaths(engine, foe), "the sheath lasts until the start of the caster's next turn"
    before = _hp(engine, bm, foe)
    _walk(engine, bm, foe, 8, 5)
    assert _hp(engine, bm, foe) == before, "moving after expiry deals nothing"
    print("✅ test_sheath_expires_at_casters_next_turn passed")


def test_miss_does_not_sheathe():
    bm, engine = setup_battle_map(), setup_combat_engine()
    me = _place(engine, bm, "Bladesinger", 5, 5, 1)
    foe = _place(engine, bm, "Orc", 6, 5, 2)
    _caster(engine, bm, me, hit_bonus=-60)     # only a natural 20 hits
    for _ in range(5):
        tr = _cast(engine, bm, me, _load_spell("Booming Blade"), [foe]).target_results[0]
        if not tr.hit:
            assert not _sheaths(engine, foe)
            assert _hp(engine, bm, foe) == 500
            assert tr.log_message.startswith("miss")
            print("✅ test_miss_does_not_sheathe passed")
            return
    raise AssertionError("expected at least one miss")


def test_out_of_reach_fails():
    bm, engine = setup_battle_map(), setup_combat_engine()
    me = _place(engine, bm, "Bladesinger", 5, 5, 1)
    foe = _place(engine, bm, "Orc", 7, 5, 2)       # 10 ft away
    _caster(engine, bm, me)
    tr = _cast(engine, bm, me, _load_spell("Booming Blade"), [foe]).target_results[0]
    assert not tr.hit and not _sheaths(engine, foe)
    assert _hp(engine, bm, foe) == 500
    print("✅ test_out_of_reach_fails passed")


if __name__ == "__main__":
    test_blade_ward_json()
    test_blade_ward_sets_flag_and_concentration_clears_it()
    test_roll_to_hit_subtracts_1d4()
    test_weapon_attack_against_warded_creature()
    test_booming_blade_hit_sheathes_without_thunder_at_level_1()
    test_moving_detonates_and_ends_spell()
    test_level_5_scaling()
    test_level_11_and_17_scaling()
    test_sheath_expires_at_casters_next_turn()
    test_miss_does_not_sheathe()
    test_out_of_reach_fails()
    print("\nAll Blade Ward / Booming Blade tests passed.")
