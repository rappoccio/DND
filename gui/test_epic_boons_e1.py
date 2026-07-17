#!/usr/bin/env python3
"""
Epic Boon tests — Phase E1 (SRD 5.2 p.88). See EPIC_BOONS_PLAN.md.

  · Boon of Truesight            — Truesight 60 ft (pierces the Invisible condition to 60 ft;
                                   folded in via Stats.effectiveTruesightRange(), queried like
                                   Skulker so it round-trips without serializing raw sense ranges).
  · Boon of Irresistible Offense
      – Overcome Defenses        — the holder's B/P/S damage ignores Resistance (0.5 → 1.0);
                                   Immunity (0.0) and Vulnerability (2.0) are untouched.
      – Overwhelming Strike      — on a natural 20, extra damage equal to the FULL boosted
                                   ability score (STR or DEX per irresistible_offense_ability).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine
from test_feats import _place, _target
from test_general_feats_g5 import _flat_slashing, _make_invisible


# ─────────────────────────────────────────────────────────────────────────────
#  Boon of Truesight — Truesight 60 ft
# ─────────────────────────────────────────────────────────────────────────────

def test_boon_of_truesight_pierces_invisible_to_60ft():
    bm = setup_battle_map(); engine = setup_combat_engine()
    viewer = _place(engine, bm, "Seer", 5, 5)
    hidden = _place(engine, bm, "Wraith", 17, 5)      # 12 cells = 60 ft
    _make_invisible(engine, bm, hidden)

    assert not engine.can_perceive_target(bm, viewer, hidden), \
        "without the boon, an Invisible creature at 60 ft can't be perceived"
    s = engine.get_agent_stats(bm, viewer); s.feats = ["Boon of Truesight"]
    engine.set_agent_stats(bm, viewer, s)
    assert engine.can_perceive_target(bm, viewer, hidden), \
        "Boon of Truesight (60 ft) pierces Invisible at 60 ft"
    print("✅ test_boon_of_truesight_pierces_invisible_to_60ft passed")


def test_boon_of_truesight_limited_to_60ft():
    bm = setup_battle_map(); engine = setup_combat_engine()
    viewer = _place(engine, bm, "Seer", 5, 5)
    hidden = _place(engine, bm, "Wraith", 18, 5)      # 13 cells = 65 ft, beyond 60 ft
    _make_invisible(engine, bm, hidden)
    s = engine.get_agent_stats(bm, viewer); s.feats = ["Boon of Truesight"]
    engine.set_agent_stats(bm, viewer, s)
    assert not engine.can_perceive_target(bm, viewer, hidden), \
        "Boon of Truesight does not reach beyond 60 ft"
    print("✅ test_boon_of_truesight_limited_to_60ft passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Boon of Irresistible Offense — Overcome Defenses (ignore B/P/S Resistance)
# ─────────────────────────────────────────────────────────────────────────────

def _slashing_attacker(engine, bm, idx, feats, strv=10):
    s = engine.get_agent_stats(bm, idx)
    s.str = strv; s.dex = 10; s.prof_bonus = 2
    s.hp_max = 80; s.hp_cur = 80
    s.feats = list(feats)
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [_flat_slashing(total=20), _flat_slashing(total=20),
                                       _flat_slashing(total=20)])


def _noncrit_hit_damage(engine, bm, a, t, tries=200):
    """Land a normal (non-critical) hit and return its total damage, so an incidental
    natural 20 (which would add Overwhelming Strike) never contaminates the measurement."""
    for _ in range(tries):
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if r.hit and not r.critical:
            return r.total_damage
    raise AssertionError("never landed a non-critical hit")


def _resistant_target(engine, bm, t, mult):
    _target(engine, bm, t, hp=1_000_000, ac=10)
    s = engine.get_agent_stats(bm, t)
    for ti in (0, 1, 2):                      # Bludgeoning / Piercing / Slashing
        s.set_physical_damage_multiplier(ti, mult)
    engine.set_agent_stats(bm, t, s)


def test_overcome_defenses_ignores_resistance():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Champion", 5, 5)
    t = _place(engine, bm, "Ghost", 6, 5)
    _resistant_target(engine, bm, t, 0.5)     # Resistance to B/P/S

    _slashing_attacker(engine, bm, a, feats=[])
    assert _noncrit_hit_damage(engine, bm, a, t) == 10, \
        "control: 20 Slashing vs Resistance (0.5) = 10"
    _slashing_attacker(engine, bm, a, feats=["Boon of Irresistible Offense"])
    assert _noncrit_hit_damage(engine, bm, a, t) == 20, \
        "Overcome Defenses lifts B/P/S Resistance → full 20"
    print("✅ test_overcome_defenses_ignores_resistance passed")


def test_overcome_defenses_keeps_immunity():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Champion", 5, 5)
    t = _place(engine, bm, "Golem", 6, 5)
    _resistant_target(engine, bm, t, 0.0)     # Immunity to B/P/S
    _slashing_attacker(engine, bm, a, feats=["Boon of Irresistible Offense"])
    assert _noncrit_hit_damage(engine, bm, a, t) == 0, \
        "Overcome Defenses lifts Resistance only — Immunity (0.0) still zeroes the damage"
    print("✅ test_overcome_defenses_keeps_immunity passed")


def test_overcome_defenses_keeps_vulnerability():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Champion", 5, 5)
    t = _place(engine, bm, "Husk", 6, 5)
    _resistant_target(engine, bm, t, 2.0)     # Vulnerability to B/P/S
    _slashing_attacker(engine, bm, a, feats=["Boon of Irresistible Offense"])
    assert _noncrit_hit_damage(engine, bm, a, t) == 40, \
        "Overcome Defenses leaves Vulnerability (2.0) intact → 40"
    print("✅ test_overcome_defenses_keeps_vulnerability passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Boon of Irresistible Offense — Overwhelming Strike (nat-20 → +ability score)
# ─────────────────────────────────────────────────────────────────────────────

def _nat20_hit(engine, bm, a, t, tries=4000):
    """Loop attacks until a natural 20 lands; return (total_damage, breakdown-dict)."""
    for _ in range(tries):
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if r.d20 == 20:
            return r.total_damage, dict(r.damage_breakdown)
    raise AssertionError("never rolled a natural 20")


def test_overwhelming_strike_adds_full_str_on_nat20():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Slayer", 5, 5)
    t = _place(engine, bm, "Dummy", 6, 5)
    _target(engine, bm, t, hp=1_000_000, ac=10)       # no resistance → multiplier 1.0

    # STR 20 (+5 mod). Flat weapon: 20 dice of d1 = 20 Slashing; crit doubles the dice → 40,
    # + STR mod 5 = 45 base. Overwhelming Strike then adds the full STR score (20) → 65.
    _slashing_attacker(engine, bm, a, feats=[], strv=20)
    base, base_bd = _nat20_hit(engine, bm, a, t)
    assert base == 45, f"control nat-20: 40 (crit dice) + 5 (STR mod) = 45, got {base}"
    assert "Overwhelming Strike" not in base_bd, "no boon → no Overwhelming Strike line"

    _slashing_attacker(engine, bm, a, feats=["Boon of Irresistible Offense"], strv=20)
    s = engine.get_agent_stats(bm, a); s.irresistible_offense_ability = 0   # STR
    engine.set_agent_stats(bm, a, s)
    boon, boon_bd = _nat20_hit(engine, bm, a, t)
    assert boon_bd.get("Overwhelming Strike") == 20, \
        f"Overwhelming Strike adds the full STR score (20), got {boon_bd.get('Overwhelming Strike')}"
    assert boon == 65, f"nat-20 with boon: 45 base + 20 (STR score) = 65, got {boon}"
    print("✅ test_overwhelming_strike_adds_full_str_on_nat20 passed")


def test_overwhelming_strike_reads_chosen_ability():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Duelist", 5, 5)
    t = _place(engine, bm, "Dummy", 6, 5)
    _target(engine, bm, t, hp=1_000_000, ac=10)

    _slashing_attacker(engine, bm, a, feats=["Boon of Irresistible Offense"], strv=10)
    s = engine.get_agent_stats(bm, a)
    s.dex = 24                                        # a distinctive DEX score
    s.irresistible_offense_ability = 1                # read DEX, not STR
    engine.set_agent_stats(bm, a, s)
    _boon, bd = _nat20_hit(engine, bm, a, t)
    assert bd.get("Overwhelming Strike") == 24, \
        f"with ability=DEX, Overwhelming Strike adds the DEX score (24), got {bd.get('Overwhelming Strike')}"
    print("✅ test_overwhelming_strike_reads_chosen_ability passed")


def test_irresistible_offense_ability_round_trips():
    """The chosen ability persists on Stats (serialized in the save's stats block)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Slayer", 5, 5)
    s = engine.get_agent_stats(bm, a)
    s.irresistible_offense_ability = 1
    engine.set_agent_stats(bm, a, s)
    assert engine.get_agent_stats(bm, a).irresistible_offense_ability == 1, \
        "irresistible_offense_ability round-trips through the engine"
    print("✅ test_irresistible_offense_ability_round_trips passed")


def main():
    print("Running Epic Boon (E1 — Truesight + Irresistible Offense) tests...\n")
    test_boon_of_truesight_pierces_invisible_to_60ft()
    test_boon_of_truesight_limited_to_60ft()
    test_overcome_defenses_ignores_resistance()
    test_overcome_defenses_keeps_immunity()
    test_overcome_defenses_keeps_vulnerability()
    test_overwhelming_strike_adds_full_str_on_nat20()
    test_overwhelming_strike_reads_chosen_ability()
    test_irresistible_offense_ability_round_trips()
    print("\n" + "=" * 60)
    print("✅ All Epic Boon (E1) tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
