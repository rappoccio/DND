#!/usr/bin/env python3
"""
Epic Boon tests — Phase E4 (SRD 5.2 p.88). See EPIC_BOONS_PLAN.md.

  · Boon of Fate — Improve Fate. Once per short-or-long rest (also refreshed at initiative),
      roll 2d4 and apply it as a bonus (boost=True) or penalty (boost=False) to the NEXT D20 Test
      (attack roll or saving throw), via the shared pending_roll_bonus_ primitive — the same path
      Bend Luck / Bardic Inspiration / Cutting Words use.

Scope (partial, per known_limitations.md): attack rolls + saving throws only (no ability checks),
self-primed on the holder's turn, NPC auto-use deferred.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine
from test_feats import _place, _target


# ─────────────────────────────────────────────────────────────────────────────
#  helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fate_attacker(engine, bm, idx, bonus_hit=0, feats=("Boon of Fate",)):
    """A STR-10 attacker (attack_mod stays modest so a mid-AC target gives a moderate hit rate the
    ±2d4 nudge can visibly move). bonus_hit is added straight to the to-hit modifier."""
    s = engine.get_agent_stats(bm, idx)
    s.str = 10; s.dex = 10; s.prof_bonus = 2
    s.hp_max = 80; s.hp_cur = 80
    s.is_npc = False
    for f in feats:
        s.add_feat(f)
    engine.set_agent_stats(bm, idx, s)
    w = rpg.Weapon()
    w.name = "Blade"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.proficient = True
    w.bonus_hit = bonus_hit
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = 1
    pr.die_size = 8
    w.physical_damage_types = [pr]
    engine.set_agent_weapons(bm, idx, [w])


def _reset_fate(engine, bm, idx):
    s = engine.get_agent_stats(bm, idx)
    s.boon_of_fate_used = False
    engine.set_agent_stats(bm, idx, s)


def _hit_rate(engine, bm, a, t, n, mode):
    """Fraction of `n` single attacks that land. mode ∈ {'none','boost','penalty'}; for the two
    boon modes the once-per-rest use is force-refreshed before each attack so we can sample it."""
    hits = 0
    for _ in range(n):
        if mode != "none":
            _reset_fate(engine, bm, a)
            v = engine.apply_boon_of_fate(bm, a, mode == "boost")
            assert 2 <= v <= 8, f"2d4 must be in [2,8], got {v}"
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if r.hit:
            hits += 1
    return hits / n


# ─────────────────────────────────────────────────────────────────────────────
#  gating / bookkeeping
# ─────────────────────────────────────────────────────────────────────────────

def test_boon_of_fate_returns_2d4_and_consumes_use():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Fated", 5, 5)
    _fate_attacker(engine, bm, a)

    v = engine.apply_boon_of_fate(bm, a, True)
    assert 2 <= v <= 8, f"first use should roll 2d4 (2..8), got {v}"
    assert engine.get_agent_stats(bm, a).boon_of_fate_used, "the use should now be spent"

    # Second use this rest is refused (returns 0, no further priming).
    assert engine.apply_boon_of_fate(bm, a, True) == 0, "only one use per rest"
    print("✅ test_boon_of_fate_returns_2d4_and_consumes_use passed")


def test_boon_of_fate_requires_feat():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Mundane", 5, 5)
    _fate_attacker(engine, bm, a, feats=())          # no Boon of Fate
    assert engine.apply_boon_of_fate(bm, a, True) == 0, "no feat → no effect"
    assert not engine.get_agent_stats(bm, a).boon_of_fate_used
    print("✅ test_boon_of_fate_requires_feat passed")


def test_boon_of_fate_refreshes_on_rest():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Rester", 5, 5)
    _fate_attacker(engine, bm, a)

    assert engine.apply_boon_of_fate(bm, a, True) > 0
    assert engine.get_agent_stats(bm, a).boon_of_fate_used

    engine.apply_short_rest(bm)
    assert not engine.get_agent_stats(bm, a).boon_of_fate_used, "short rest refreshes the use"
    assert engine.apply_boon_of_fate(bm, a, True) > 0, "usable again after a short rest"

    engine.apply_long_rest(bm)
    assert not engine.get_agent_stats(bm, a).boon_of_fate_used, "long rest refreshes the use"
    print("✅ test_boon_of_fate_refreshes_on_rest passed")


def test_boon_of_fate_refreshes_at_initiative():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Starter", 5, 5)
    _fate_attacker(engine, bm, a)

    assert engine.apply_boon_of_fate(bm, a, True) > 0
    assert engine.get_agent_stats(bm, a).boon_of_fate_used

    engine.roll_initiative_for(bm, a)                # a new combat rolls initiative per agent
    assert not engine.get_agent_stats(bm, a).boon_of_fate_used, "initiative refreshes the use"
    print("✅ test_boon_of_fate_refreshes_at_initiative passed")


# ─────────────────────────────────────────────────────────────────────────────
#  effect on the next D20 Test (attack roll)
# ─────────────────────────────────────────────────────────────────────────────

def test_boon_of_fate_moves_attack_hit_rate():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Fated", 5, 5)
    t = _place(engine, bm, "Mook", 6, 5)
    _fate_attacker(engine, bm, a)
    _target(engine, bm, t, hp=1_000_000, ac=12)      # moderate AC → mid hit rate

    N = 2500
    control = _hit_rate(engine, bm, a, t, N, "none")
    boosted = _hit_rate(engine, bm, a, t, N, "boost")
    penalized = _hit_rate(engine, bm, a, t, N, "penalty")

    # Guard: a pinned control rate (0 or 1) would make the comparison meaningless.
    assert 0.15 < control < 0.85, f"control hit rate {control:.2f} should be mid-band"
    assert boosted > control + 0.06, f"+2d4 should raise hits: boosted {boosted:.2f} vs control {control:.2f}"
    assert penalized < control - 0.06, f"-2d4 should lower hits: penalized {penalized:.2f} vs control {control:.2f}"
    assert boosted - penalized > 0.20, \
        f"boost vs penalty gap too small: {boosted:.2f} - {penalized:.2f}"
    print(f"✅ test_boon_of_fate_moves_attack_hit_rate passed "
          f"(penalty {penalized:.2f} < control {control:.2f} < boost {boosted:.2f})")


def main():
    print("Running Epic Boon (E4 — Boon of Fate) tests...\n")
    test_boon_of_fate_returns_2d4_and_consumes_use()
    test_boon_of_fate_requires_feat()
    test_boon_of_fate_refreshes_on_rest()
    test_boon_of_fate_refreshes_at_initiative()
    test_boon_of_fate_moves_attack_hit_rate()
    print("\n" + "=" * 60)
    print("✅ All Epic Boon (E4) tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
