#!/usr/bin/env python3
"""
Bard — Bardic Inspiration: simplest d20-Test cases.

Covers the two foundational pieces of the Bardic Inspiration mechanic:
  * Part 1 — the flat `modifier` argument on roll / roll_advantage / roll_disadvantage.
  * Part 2 — grant_bardic_die / use_bardic_die folding a rolled die into the
    NEXT d20 Test (additive, unlike Portent which replaces the d20), then clearing.

Determinism: rolls are random, so equality checks use TWIN engines seeded
identically (CombatEngine(42)). The same sequence of calls consumes the same RNG
stream, so a "+v" engine differs from a control engine by exactly the bonus.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (
    setup_battle_map, setup_combat_engine, create_test_agent,
    add_agent_to_battle, create_melee_weapon,
)


def _bard(engine, bm, idx, level, cha=16, prof=2, subclass=None, dex=10):
    """Configure agent idx as a Bard of the given level/college and re-read its stats."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Bard, level)
    s.cha = cha
    s.dex = dex
    s.prof_bonus = prof
    if subclass is not None:
        s.bard_subclass = subclass  # set BEFORE init so college level-gates apply
    s.initialize_class_resources(rpg.CharacterClass.Bard, level)
    s.restore_spell_slots()
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


# ── Phase 1: chassis ─────────────────────────────────────────────────────────

def test_bard_chassis_spellcasting_and_saves():
    """L2 Bard: CHA caster, can cast, DEX + CHA saving-throw proficiencies."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 5))

    s = _bard(engine, bm, idx, 2)
    assert s.spellcasting_ability == 5, f"expected CHA (5), got {s.spellcasting_ability}"
    assert s.can_cast_spell is True
    assert s.save_prof_dex is True, "Bard should have DEX save proficiency"
    assert s.save_prof_cha is True, "Bard should have CHA save proficiency"
    print("✅ test_bard_chassis_spellcasting_and_saves passed")


def test_bardic_inspiration_uses_scale_with_cha():
    """Bardic Inspiration uses = max(1, CHA mod), restored on a long rest."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 5))

    s = _bard(engine, bm, idx, 1, cha=16)  # +3
    bi = s.resources["Bardic Inspiration"]
    assert bi.max == 3 and bi.current == 3, f"expected 3 uses at CHA 16, got {bi.current}/{bi.max}"
    assert bi.long_rest_regen == 3, "should fully regain on a long rest"

    s = _bard(engine, bm, idx, 1, cha=8)   # -1 → floored to 1
    bi = s.resources["Bardic Inspiration"]
    assert bi.max == 1, f"expected floor of 1 use at CHA 8, got {bi.max}"
    print("✅ test_bardic_inspiration_uses_scale_with_cha passed")


def test_bardic_die_size_scales_by_level():
    """Granted die size: d6 (L1) → d8 (L5) → d10 (L10) → d12 (L15)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 5))

    for level, expected in [(1, 6), (4, 6), (5, 8), (9, 8), (10, 10), (14, 10), (15, 12), (20, 12)]:
        s = _bard(engine, bm, idx, level)
        assert s.bardic_inspiration_die_size == expected, \
            f"L{level}: expected d{expected}, got d{s.bardic_inspiration_die_size}"
    print("✅ test_bardic_die_size_scales_by_level passed")


def test_font_of_inspiration_short_rest_regen_at_l5():
    """Font of Inspiration (L5): Bardic Inspiration also regains on a short rest."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 5))

    s4 = _bard(engine, bm, idx, 4)
    assert s4.resources["Bardic Inspiration"].short_rest_regen == 0, \
        "pre-L5 Bardic Inspiration should not regain on a short rest"
    s5 = _bard(engine, bm, idx, 5)
    assert s5.resources["Bardic Inspiration"].short_rest_regen == s5.resources["Bardic Inspiration"].max, \
        "L5 Font of Inspiration should regain full uses on a short rest"
    print("✅ test_font_of_inspiration_short_rest_regen_at_l5 passed")


def test_bard_subclass_roundtrip():
    """bard_subclass survives the get/set Stats round-trip."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 5))

    s = engine.get_agent_stats(bm, idx)
    s.bard_subclass = rpg.BardCollege.Lore
    engine.set_agent_stats(bm, idx, s)
    assert engine.get_agent_stats(bm, idx).bard_subclass == rpg.BardCollege.Lore
    print("✅ test_bard_subclass_roundtrip passed")


def test_bard_subclass_save_load_roundtrip():
    """Phase 4: a saved Bard's college + chassis restore via restore_class_resources."""
    from agent_loader import restore_class_resources

    # The dict mirrors what main.py writes to the agents JSON for a L5 Lore Bard.
    saved = {
        "agent_class": "Bard",
        "agent_char_level": 5,
        "agent_bard_subclass": "Lore",
    }
    s = rpg.Stats()
    s.cha = 16
    restore_class_resources(s, saved, rpg)

    assert s.character_class == rpg.CharacterClass.Bard
    assert s.bard_subclass == rpg.BardCollege.Lore, f"got {s.bard_subclass}"
    assert "Bardic Inspiration" in s.resources, "chassis resource should be restored"
    assert s.bardic_inspiration_die_size == 8, "L5 Bard grants a d8"
    print("✅ test_bard_subclass_save_load_roundtrip passed")


# ── Phase 2: Font of Inspiration (L5) ────────────────────────────────────────

def test_font_of_inspiration_slot_regain():
    """L5+ Bard expends a spell slot to regain one Bardic Inspiration use."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 5))
    _bard(engine, bm, idx, 5, cha=16)  # 3 BI uses, full table-A slots

    # Expend one use so there's something to regain.
    assert engine.spend_resource(bm, idx, "Bardic Inspiration", 1)
    before = engine.get_agent_stats(bm, idx)
    bi_before = before.resources["Bardic Inspiration"].current
    slot1_before = before.spell_slots_remaining[0]

    new_count = engine.bard_regain_inspiration_from_slot(bm, idx, 1)
    after = engine.get_agent_stats(bm, idx)
    assert new_count == bi_before + 1, f"expected {bi_before}+1, got {new_count}"
    assert after.resources["Bardic Inspiration"].current == bi_before + 1
    assert after.spell_slots_remaining[0] == slot1_before - 1, "a level-1 slot should be spent"
    print("✅ test_font_of_inspiration_slot_regain passed")


def test_font_of_inspiration_rejects_pre_l5_and_when_full():
    """Pre-L5 and at-max both return -1 and leave the spell slot untouched."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 5))

    # L4: feature not online yet.
    _bard(engine, bm, idx, 4)
    slot1 = engine.get_agent_stats(bm, idx).spell_slots_remaining[0]
    assert engine.bard_regain_inspiration_from_slot(bm, idx, 1) == -1
    assert engine.get_agent_stats(bm, idx).spell_slots_remaining[0] == slot1, "slot must not be spent"

    # L5 but Bardic Inspiration already full: don't waste a slot.
    _bard(engine, bm, idx, 5)
    slot1 = engine.get_agent_stats(bm, idx).spell_slots_remaining[0]
    assert engine.bard_regain_inspiration_from_slot(bm, idx, 1) == -1
    assert engine.get_agent_stats(bm, idx).spell_slots_remaining[0] == slot1, "slot must not be spent when full"
    print("✅ test_font_of_inspiration_rejects_pre_l5_and_when_full passed")


# ── Phase 2: Superior Inspiration (L18) ──────────────────────────────────────

def test_superior_inspiration_tops_to_two_at_l18():
    """At combat start a L18 Bard regains Bardic Inspiration up to 2 if it has fewer."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 5))
    _bard(engine, bm, idx, 18, cha=20)  # 5 BI uses

    cur = engine.get_agent_stats(bm, idx).resources["Bardic Inspiration"].current
    engine.spend_resource(bm, idx, "Bardic Inspiration", cur - 1)  # leave exactly 1
    assert engine.get_agent_stats(bm, idx).resources["Bardic Inspiration"].current == 1

    engine.apply_superior_inspiration(bm)
    assert engine.get_agent_stats(bm, idx).resources["Bardic Inspiration"].current == 2, \
        "Superior Inspiration should top up to 2"
    print("✅ test_superior_inspiration_tops_to_two_at_l18 passed")


def test_superior_inspiration_noop_before_l18():
    """A L17 Bard is unaffected by Superior Inspiration."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 5))
    _bard(engine, bm, idx, 17, cha=20)

    cur = engine.get_agent_stats(bm, idx).resources["Bardic Inspiration"].current
    engine.spend_resource(bm, idx, "Bardic Inspiration", cur - 1)  # leave 1
    engine.apply_superior_inspiration(bm)
    assert engine.get_agent_stats(bm, idx).resources["Bardic Inspiration"].current == 1, \
        "pre-L18 Bard should not regain"
    print("✅ test_superior_inspiration_noop_before_l18 passed")


# ── Part 1: flat modifier on the roll API ────────────────────────────────────

def test_roll_flat_modifier():
    """roll(20, m) == roll(20) + m on identically seeded engines."""
    base  = rpg.CombatEngine(42).roll(20)
    plus7 = rpg.CombatEngine(42).roll(20, 7)
    assert plus7 == base + 7, f"expected {base}+7, got {plus7}"
    print("✅ test_roll_flat_modifier passed")


def test_roll_advantage_modifier():
    """The modifier is added once, AFTER advantage selection (not inside max)."""
    base  = rpg.CombatEngine(42).roll_advantage(20)
    plus5 = rpg.CombatEngine(42).roll_advantage(20, 5)
    assert plus5 == base + 5, f"expected {base}+5, got {plus5}"
    print("✅ test_roll_advantage_modifier passed")


def test_roll_disadvantage_modifier():
    """The modifier is added once, AFTER disadvantage selection (not inside min)."""
    base  = rpg.CombatEngine(42).roll_disadvantage(20)
    plus5 = rpg.CombatEngine(42).roll_disadvantage(20, 5)
    assert plus5 == base + 5, f"expected {base}+5, got {plus5}"
    print("✅ test_roll_disadvantage_modifier passed")


# ── Part 2: grant / use the held die ─────────────────────────────────────────

def test_grant_sets_held_die():
    """grant_bardic_die stores the die SIZE on the recipient's Stats."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Ally", 5, 5))

    assert engine.grant_bardic_die(bm, idx, 8) is True
    stats = engine.get_agent_stats(bm, idx)
    assert stats.bardic_inspiration_die == 8, \
        f"expected held d8, got d{stats.bardic_inspiration_die}"
    print("✅ test_grant_sets_held_die passed")


def test_grant_overwrites_existing_die():
    """RAW: only one Bardic Inspiration die at a time — a new grant overwrites."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Ally", 5, 5))

    engine.grant_bardic_die(bm, idx, 6)
    engine.grant_bardic_die(bm, idx, 10)
    stats = engine.get_agent_stats(bm, idx)
    assert stats.bardic_inspiration_die == 10, \
        f"expected overwrite to d10, got d{stats.bardic_inspiration_die}"
    print("✅ test_grant_overwrites_existing_die passed")


def test_use_returns_value_and_clears_die():
    """use_bardic_die rolls 1..d, returns it, and clears the held die."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Ally", 5, 5))

    engine.grant_bardic_die(bm, idx, 8)
    v = engine.use_bardic_die(bm, idx)
    assert 1 <= v <= 8, f"rolled value {v} out of range 1..8"
    stats = engine.get_agent_stats(bm, idx)
    assert stats.bardic_inspiration_die == 0, "die should be consumed after use"
    print("✅ test_use_returns_value_and_clears_die passed")


def test_use_with_no_die_is_noop():
    """Spending with no held die returns 0 and leaves the (empty) state alone."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Ally", 5, 5))

    v = engine.use_bardic_die(bm, idx)
    assert v == 0, f"expected 0 with no die held, got {v}"
    print("✅ test_use_with_no_die_is_noop passed")


# ── Part 2: the rolled die folds into the next d20 Test, once ────────────────

def test_bonus_folds_into_next_roll_once():
    """The spent die adds to exactly the NEXT roll, then clears.

    Twin engines share the RNG stream: use_bardic_die's internal d8 roll consumes
    the same draw as the control's explicit roll(8), keeping the d20s aligned.
    """
    # Control — same draw order, no bonus.
    bm_c = setup_battle_map()
    ctrl = setup_combat_engine()
    add_agent_to_battle(ctrl, bm_c, create_test_agent("Ally", 5, 5))
    die_val = ctrl.roll(8)    # mirrors use_bardic_die's internal roll
    r1_base = ctrl.roll(20)   # first d20 after
    r2_base = ctrl.roll(20)   # second d20 after

    # Test — grant + use, then two d20s.
    bm_t = setup_battle_map()
    test = setup_combat_engine()
    idx = add_agent_to_battle(test, bm_t, create_test_agent("Ally", 5, 5))
    test.grant_bardic_die(bm_t, idx, 8)
    v = test.use_bardic_die(bm_t, idx)
    assert v == die_val, f"internal die roll diverged: {v} != {die_val}"

    r1 = test.roll(20)
    r2 = test.roll(20)
    assert r1 == r1_base + v, f"bonus not applied to next roll: {r1} != {r1_base}+{v}"
    assert r2 == r2_base,     f"bonus not cleared after one roll: {r2} != {r2_base}"
    print("✅ test_bonus_folds_into_next_roll_once passed")


def test_bonus_applies_to_attack_total_not_d20():
    """roll_to_hit adds the bonus to total_roll but leaves the natural d20 (crit) alone."""
    weapon = create_melee_weapon()
    attacker = rpg.Stats()
    attacker.str = 14  # +2

    # Control — same draw order, no bonus.
    bm_c = setup_battle_map()
    ctrl = setup_combat_engine()
    add_agent_to_battle(ctrl, bm_c, create_test_agent("Ally", 5, 5))
    die_val = ctrl.roll(8)
    r_base = ctrl.roll_to_hit(weapon, attacker, 10)

    # Test — grant + use, then attack.
    bm_t = setup_battle_map()
    test = setup_combat_engine()
    idx = add_agent_to_battle(test, bm_t, create_test_agent("Ally", 5, 5))
    test.grant_bardic_die(bm_t, idx, 8)
    v = test.use_bardic_die(bm_t, idx)
    r = test.roll_to_hit(weapon, attacker, 10)

    assert v == die_val, f"internal die roll diverged: {v} != {die_val}"
    assert r.d20 == r_base.d20, f"natural d20 must be unchanged: {r.d20} != {r_base.d20}"
    assert r.total_roll == r_base.total_roll + v, \
        f"bonus not in attack total: {r.total_roll} != {r_base.total_roll}+{v}"
    print("✅ test_bonus_applies_to_attack_total_not_d20 passed")


# ── Phase 3: College subclasses (combat-core slice) ──────────────────────────

def test_dance_unarmored_defense():
    """College of Dance (L3+): AC = 10 + DEX + CHA while unarmored; not before L3."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("DanceBard", 5, 5))

    _bard(engine, bm, idx, 3, cha=14, dex=16, subclass=rpg.BardCollege.Dance)
    ac = engine.calculate_ac(bm, idx)
    assert ac == 10 + 3 + 2, f"Dance UD should be 15 (10+DEX+CHA), got {ac}"

    # Pre-L3: no Unarmored Defense → standard 10 + DEX (CHA not counted).
    _bard(engine, bm, idx, 2, cha=14, dex=16, subclass=rpg.BardCollege.Dance)
    ac2 = engine.calculate_ac(bm, idx)
    assert ac2 == 10 + 3, f"pre-L3 Dance bard should be 13 (no UD), got {ac2}"
    print("✅ test_dance_unarmored_defense passed")


def test_valor_extra_attack_at_l6():
    """College of Valor grants Extra Attack at L6 (num_attacks == 2); others don't."""
    for level, subclass, expected in [
        (5, rpg.BardCollege.Valor, 1),
        (6, rpg.BardCollege.Valor, 2),
        (6, rpg.BardCollege.Lore, 1),
    ]:
        bm = setup_battle_map()
        engine = setup_combat_engine()
        idx = add_agent_to_battle(engine, bm, create_test_agent("ValorBard", 5, 5))
        s = _bard(engine, bm, idx, level, subclass=subclass)
        assert s.num_attacks == expected, \
            f"L{level} {subclass}: expected {expected} attacks, got {s.num_attacks}"
    print("✅ test_valor_extra_attack_at_l6 passed")


def test_cutting_words_subtracts_from_next_roll():
    """College of Lore Cutting Words subtracts the rolled die from the next D20 Test.

    Twin seeded engines: cutting_words' internal die roll consumes the same draw as the
    control's explicit roll, keeping the subsequent d20 aligned.
    """
    bm_c = setup_battle_map()
    ctrl = setup_combat_engine()
    idx_c = add_agent_to_battle(ctrl, bm_c, create_test_agent("LoreBard", 5, 5))
    _bard(ctrl, bm_c, idx_c, 5, subclass=rpg.BardCollege.Lore)  # d8 at L5
    die_val = ctrl.roll(8)        # mirrors the internal Cutting Words roll
    enemy_base = ctrl.roll(20)    # the target's roll, unmodified

    bm_t = setup_battle_map()
    test = setup_combat_engine()
    idx_t = add_agent_to_battle(test, bm_t, create_test_agent("LoreBard", 5, 5))
    _bard(test, bm_t, idx_t, 5, subclass=rpg.BardCollege.Lore)
    before = test.get_agent_stats(bm_t, idx_t).resources["Bardic Inspiration"].current

    v = test.bard_cutting_words(bm_t, idx_t)
    assert v == die_val, f"internal die roll diverged: {v} != {die_val}"
    after = test.get_agent_stats(bm_t, idx_t).resources["Bardic Inspiration"].current
    assert after == before - 1, "Cutting Words should spend one Bardic Inspiration use"

    enemy_roll = test.roll(20)
    assert enemy_roll == enemy_base - v, f"expected {enemy_base}-{v}, got {enemy_roll}"
    print("✅ test_cutting_words_subtracts_from_next_roll passed")


def test_cutting_words_requires_lore_and_a_use():
    """Cutting Words is rejected for non-Lore bards and when no use remains."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 5))

    _bard(engine, bm, idx, 5, subclass=rpg.BardCollege.Valor)
    assert engine.bard_cutting_words(bm, idx) == 0, "Valor bard cannot use Cutting Words"

    _bard(engine, bm, idx, 5, cha=16, subclass=rpg.BardCollege.Lore)  # 3 uses
    engine.spend_resource(bm, idx, "Bardic Inspiration", 3)           # drain them
    assert engine.bard_cutting_words(bm, idx) == 0, "no use left → no Cutting Words"
    print("✅ test_cutting_words_requires_lore_and_a_use passed")


if __name__ == "__main__":
    tests = [
        test_bard_chassis_spellcasting_and_saves,
        test_bardic_inspiration_uses_scale_with_cha,
        test_bardic_die_size_scales_by_level,
        test_font_of_inspiration_short_rest_regen_at_l5,
        test_bard_subclass_roundtrip,
        test_bard_subclass_save_load_roundtrip,
        test_font_of_inspiration_slot_regain,
        test_font_of_inspiration_rejects_pre_l5_and_when_full,
        test_superior_inspiration_tops_to_two_at_l18,
        test_superior_inspiration_noop_before_l18,
        test_dance_unarmored_defense,
        test_valor_extra_attack_at_l6,
        test_cutting_words_subtracts_from_next_roll,
        test_cutting_words_requires_lore_and_a_use,
        test_roll_flat_modifier,
        test_roll_advantage_modifier,
        test_roll_disadvantage_modifier,
        test_grant_sets_held_die,
        test_grant_overwrites_existing_die,
        test_use_returns_value_and_clears_die,
        test_use_with_no_die_is_noop,
        test_bonus_folds_into_next_roll_once,
        test_bonus_applies_to_attack_total_not_d20,
    ]

    print("Running Bard Bardic Inspiration Tests...")
    print("=" * 60)

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
