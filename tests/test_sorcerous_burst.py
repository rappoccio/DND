#!/usr/bin/env python3
"""
Tests for Sorcerous Burst's bonus d8s (2024 PHB / SRD 5.2): every 8 rolled on a d8 for the
spell adds another d8, and the bonus dice per cast are capped at the caster's spellcasting
ability modifier. A bonus die that lands on 8 adds another, still within the cap.

Implemented in CombatEngine::sorcerousBurstBonusDice, called from executeSpell's AttackRoll hit
branch (and the Potent Cantrip miss branch).
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_cantrip_scaling import _setup, _cast, _load_spell


def _casts(intel, level=1, n=400):
    """Yield the foe's TargetResult for `n` hitting Sorcerous Burst casts."""
    # One engine for the whole run: a fresh engine per cast reuses the fixed seed and rolls
    # the same faces every time.
    bm, engine, me, foe = _setup({rpg.CharacterClass.Sorcerer: level})
    s = engine.get_agent_stats(bm, me)
    s.intel = intel
    engine.set_agent_stats(bm, me, s)
    yield from _hits(engine, bm, me, foe, "Sorcerous Burst", n)


def _hits(engine, bm, me, foe, name, n):
    got = 0
    sp = _load_spell(name)
    while got < n:
        f = engine.get_agent_stats(bm, foe)
        f.hp_cur = f.hp_max
        engine.set_agent_stats(bm, foe, f)
        tr = _cast(engine, bm, me, sp, [foe]).target_results[0]
        if tr.hit:
            got += 1
            yield tr


def _expected_extra(base_dice, bonus, cap):
    """Bonus dice the rules allow given the base faces and the bonus faces actually rolled."""
    pending = sum(1 for d in base_dice if d == 8)
    used = 0
    for d in bonus:
        if pending == 0 or used == cap:
            break
        pending -= 1
        used += 1
        if d == 8:
            pending += 1
    return used


def test_bonus_dice_within_cap():
    """INT 16 (mod +3): bonus dice follow the 8s, never exceed 3, and do occur."""
    bonus_casts = 0
    for tr in _casts(16):
        dice = list(tr.dice_results)
        base_n = 2 if tr.critical else 1
        base, bonus = dice[:base_n], dice[base_n:]
        assert len(bonus) <= 3, f"cap is 3, got {len(bonus)} bonus dice: {dice}"
        assert all(1 <= d <= 8 for d in dice), dice
        assert len(bonus) == _expected_extra(base, bonus, 3), f"wrong bonus-die count: {dice}"
        assert tr.total_damage == sum(dice), f"damage {tr.total_damage} != sum {dice}"
        if bonus:
            bonus_casts += 1
    assert bonus_casts > 0, "400 hits and no 8 ever added a die"
    print(f"✅ test_bonus_dice_within_cap passed ({bonus_casts} casts with bonus dice)")


def test_zero_mod_no_bonus_dice():
    """INT 10 (mod +0): no bonus dice even on an 8."""
    for tr in _casts(10, n=200):
        base_n = 2 if tr.critical else 1
        assert len(tr.dice_results) == base_n, f"mod 0 should add no dice: {list(tr.dice_results)}"
    print("✅ test_zero_mod_no_bonus_dice passed")


def test_scaled_cantrip_bonus_per_die():
    """Level 5 (2d8): an 8 on either base die adds one; the cap still totals the mod."""
    seen_two = False
    for tr in _casts(16, level=5):
        dice = list(tr.dice_results)
        base_n = 4 if tr.critical else 2
        base, bonus = dice[:base_n], dice[base_n:]
        assert len(bonus) == _expected_extra(base, bonus, 3), f"wrong bonus-die count: {dice}"
        if len(bonus) >= 2:
            seen_two = True
    assert seen_two, "400 level-5 hits and never two bonus dice"
    print("✅ test_scaled_cantrip_bonus_per_die passed")


def test_fire_bolt_no_bonus_dice():
    """Only Sorcerous Burst adds dice: Fire Bolt keeps its die count on a 10."""
    bm, engine, me, foe = _setup({rpg.CharacterClass.Wizard: 1})
    for tr in _hits(engine, bm, me, foe, "Fire Bolt", 200):
        assert len(tr.dice_results) == (2 if tr.critical else 1), list(tr.dice_results)
    print("✅ test_fire_bolt_no_bonus_dice passed")


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
