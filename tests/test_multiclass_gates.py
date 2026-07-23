#!/usr/bin/env python3
"""
Multiclassing Phase 2 — per-class level gates.

The failure mode this suite exists to prevent: before Phase 2, every class-feature
gate read the single `char_level` field, which multiclassing conflates with the
TOTAL character level. A Fighter 5 / Monk 5 has total level 10, so a `char_level >= N`
gate would silently hand that character BOTH classes' level-6..10 features (e.g. the
Fighter would "know" War Magic at total-10 even though it is a Fighter-7 feature).

Phase 2 rewrote those gates to `classLevel(<thatclass>) >= N`. These tests build real
multiclass agents and assert that each class's features are gated on THAT class's
level — not the sum — via the Python-bound eligibility predicates:

  - can_use_war_magic  → Eldritch Knight (Fighter) L7+
  - can_deflect_attacks → Monk L3+
  - can_uncanny_dodge   → Rogue L5+

Run standalone (asserts raise → non-zero exit) or via tests/run_all_tests.py.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

CC = rpg.CharacterClass


def _add(engine, bm, name, col, row, hp=40):
    return add_agent_to_battle(engine, bm, create_test_agent(name, col, row), hp=hp)


def _set_classes(engine, bm, idx, primary, primary_level, extra=None, fighter_subclass=None):
    """Configure a placed agent's class_levels AFTER placement (apply_agent_configs,
    called inside add_agent_to_battle, rebuilds agents from config and would wipe an
    earlier set_agent_stats — so class levels are set here, once every agent exists)."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(primary, primary_level)          # single-class reset (clears the array first)
    if extra is not None:
        s.add_class_level(extra[0], extra[1])          # additive multiclass entry point
    if fighter_subclass is not None:
        s.fighter_subclass = fighter_subclass
    s.hp_max = 40
    s.hp_cur = 40
    engine.set_agent_stats(bm, idx, s)
    return s


# ── Data model: accessors read per-class, char_level mirrors the sum ──────────────
def test_accessors_split_total_from_class_level():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _add(engine, bm, "Fighter/Monk", 5, 5)
    _set_classes(engine, bm, a, CC.Fighter, 5, extra=(CC.Monk, 5))
    s = engine.get_agent_stats(bm, a)

    assert s.class_level(CC.Fighter) == 5, f"Fighter level should be 5, got {s.class_level(CC.Fighter)}"
    assert s.class_level(CC.Monk) == 5, f"Monk level should be 5, got {s.class_level(CC.Monk)}"
    assert s.class_level(CC.Rogue) == 0, "no Rogue levels"
    assert s.total_level() == 10, f"total level should be 10, got {s.total_level()}"
    assert s.char_level == 10, f"char_level mirror should be the sum (10), got {s.char_level}"
    assert s.has_class(CC.Fighter) and s.has_class(CC.Monk), "has both classes"
    assert not s.has_class(CC.Rogue), "has no Rogue levels"
    print("✅ test_accessors_split_total_from_class_level passed")


# ── The centerpiece: a Fighter 5 / Monk 5 gets NEITHER class's higher-level feature ──
def test_no_capstone_leak_from_total_level():
    bm = setup_battle_map(); engine = setup_combat_engine()
    # Fighter 5 / Monk 5 (total 10), Eldritch Knight on the Fighter side.
    mc = _add(engine, bm, "EK-Fighter/Monk", 5, 5)
    _set_classes(engine, bm, mc, CC.Fighter, 5, extra=(CC.Monk, 5),
                 fighter_subclass=rpg.FighterSubclass.EldritchKnight)

    # War Magic is an Eldritch Knight FIGHTER-7 feature. Fighter level here is 5, so it
    # must be unavailable — even though the TOTAL level (10) clears 7. This is exactly the
    # bug Phase 2 fixes: a `char_level >= 7` gate would wrongly grant it.
    assert not engine.can_use_war_magic(bm, mc), \
        "Fighter 5 / Monk 5 must NOT have EK War Magic (a Fighter-7 feature) at total level 10"

    # Meanwhile Deflect Attacks is a MONK-3 feature and the Monk level is 5, so it IS available.
    assert engine.can_deflect_attacks(bm, mc), \
        "Fighter 5 / Monk 5 SHOULD have Monk-3 Deflect Attacks (Monk level 5 >= 3)"
    print("✅ test_no_capstone_leak_from_total_level passed")


# ── The gate DOES fire once the relevant class reaches the threshold ──────────────
def test_single_class_fighter_reaches_war_magic():
    bm = setup_battle_map(); engine = setup_combat_engine()
    f7 = _add(engine, bm, "EK-Fighter7", 5, 5)
    _set_classes(engine, bm, f7, CC.Fighter, 7,
                 fighter_subclass=rpg.FighterSubclass.EldritchKnight)
    assert engine.can_use_war_magic(bm, f7), \
        "a single-class Eldritch Knight Fighter 7 SHOULD have War Magic"
    print("✅ test_single_class_fighter_reaches_war_magic passed")


# ── A class feature is gated on THAT class's level, not total level ───────────────
def test_monk_feature_absent_without_monk_levels():
    bm = setup_battle_map(); engine = setup_combat_engine()
    # Pure Fighter 10 — total level 10, but zero Monk levels → no Deflect Attacks.
    f10 = _add(engine, bm, "Fighter10", 5, 5)
    _set_classes(engine, bm, f10, CC.Fighter, 10)
    assert not engine.can_deflect_attacks(bm, f10), \
        "a Fighter 10 with no Monk levels must NOT have Monk Deflect Attacks"

    # Rogue 5 / Wizard 5 → Uncanny Dodge (Rogue-5) present from the 5 Rogue levels.
    rw = _add(engine, bm, "Rogue/Wizard", 6, 5)
    _set_classes(engine, bm, rw, CC.Rogue, 5, extra=(CC.Wizard, 5))
    assert engine.can_uncanny_dodge(bm, rw), \
        "Rogue 5 / Wizard 5 SHOULD have Uncanny Dodge (Rogue level 5 >= 5)"

    # ...and a Monk 10 (no Rogue levels) must NOT get Uncanny Dodge despite total level 10.
    m10 = _add(engine, bm, "Monk10", 7, 5)
    _set_classes(engine, bm, m10, CC.Monk, 10)
    assert not engine.can_uncanny_dodge(bm, m10), \
        "a Monk 10 with no Rogue levels must NOT have Rogue Uncanny Dodge"
    print("✅ test_monk_feature_absent_without_monk_levels passed")


if __name__ == "__main__":
    test_accessors_split_total_from_class_level()
    test_no_capstone_leak_from_total_level()
    test_single_class_fighter_reaches_war_magic()
    test_monk_feature_absent_without_monk_levels()
    print("\n✅ All multiclass per-class-level gate tests passed!")
