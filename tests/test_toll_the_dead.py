#!/usr/bin/env python3
"""
Tests for Toll the Dead (WIS save cantrip): 1d8 Necrotic on a failed save, 1d12 instead
when the target is missing any Hit Points, nothing on a success. Scales one die at
character levels 5, 11 and 17. The d12 swap and the no-damage save live in
executeSpell's Save branch; the spell itself is the `gui/spells.json` entry.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_cantrip_scaling import _setup, _cast, _load_spell, _wiz


def _toll(levels, wounded=False, foe_wis=1, caster_prof=30):
    bm, engine, me, foe = _setup(levels)
    s = engine.get_agent_stats(bm, foe)
    s.wis = foe_wis
    if wounded:
        s.hp_cur = s.hp_max - 1
    engine.set_agent_stats(bm, foe, s)
    if caster_prof != 30:
        c = engine.get_agent_stats(bm, me)
        c.prof_bonus = caster_prof
        c.intel = 1
        engine.set_agent_stats(bm, me, c)
    res = _cast(engine, bm, me, _load_spell("Toll the Dead"), [foe])
    trs = [tr for tr in res.target_results if tr.target_idx == foe]
    assert trs, "the foe should be a target"
    return trs[0]


def test_unhurt_target_takes_d8s():
    faces = []
    for _ in range(60):
        tr = _toll(_wiz(1))
        assert not tr.saved and len(tr.dice_results) == 1
        faces += list(tr.dice_results)
    assert max(faces) <= 8, f"an unhurt target takes d8s, got {max(faces)}"
    print("✅ test_unhurt_target_takes_d8s passed")


def test_wounded_target_takes_d12s():
    faces = []
    for _ in range(60):
        tr = _toll(_wiz(1), wounded=True)
        assert not tr.saved and len(tr.dice_results) == 1
        faces += list(tr.dice_results)
    assert max(faces) <= 12 and max(faces) > 8, f"a wounded target takes d12s, got max {max(faces)}"
    print("✅ test_wounded_target_takes_d12s passed")


def test_scales_with_level():
    for level, dice in ((1, 1), (5, 2), (11, 3), (17, 4)):
        tr = _toll(_wiz(level), wounded=True)
        assert len(tr.dice_results) == dice, \
            f"level {level}: want {dice} dice, got {len(tr.dice_results)}"
    print("✅ test_scales_with_level passed")


def test_successful_save_takes_nothing():
    for _ in range(10):
        tr = _toll(_wiz(1), wounded=True, foe_wis=30, caster_prof=0)
        assert tr.saved, "WIS 30 beats a DC-3 caster"
        assert tr.total_damage == 0, f"a save negates Toll the Dead, got {tr.total_damage}"
    print("✅ test_successful_save_takes_nothing passed")


if __name__ == "__main__":
    tests = [test_unhurt_target_takes_d8s, test_wounded_target_takes_d12s,
             test_scales_with_level, test_successful_save_takes_nothing]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
