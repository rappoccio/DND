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


# ── Phase 3: College of Glamour — Mantle of Inspiration ──────────────────────

def test_mantle_grants_double_die_thp():
    """Mantle grants each recipient temp HP = 2× the rolled Bardic Inspiration die, spending a use.

    Twin seeded engines: the internal die roll consumes the same draw as the control's roll(8).
    """
    bm_c = setup_battle_map()
    ctrl = setup_combat_engine()
    bidx_c = add_agent_to_battle(ctrl, bm_c, create_test_agent("GlamourBard", 5, 5))
    _bard(ctrl, bm_c, bidx_c, 5, cha=16, subclass=rpg.BardCollege.Glamour)  # d8 at L5
    die_val = ctrl.roll(8)   # mirrors the internal Mantle roll

    bm_t = setup_battle_map()
    test = setup_combat_engine()
    bidx = add_agent_to_battle(test, bm_t, create_test_agent("GlamourBard", 5, 5))
    a1 = add_agent_to_battle(test, bm_t, create_test_agent("Ally1", 6, 6))
    a2 = add_agent_to_battle(test, bm_t, create_test_agent("Ally2", 7, 7))
    _bard(test, bm_t, bidx, 5, cha=16, subclass=rpg.BardCollege.Glamour)  # 3 uses, d8
    before = test.get_agent_stats(bm_t, bidx).resources["Bardic Inspiration"].current

    thp = test.apply_mantle_of_inspiration(bm_t, bidx, [a1, a2])
    assert thp == 2 * die_val, f"expected {2*die_val} temp HP, got {thp}"
    assert test.get_agent_stats(bm_t, a1).temp_hp == thp, "ally 1 should get the temp HP"
    assert test.get_agent_stats(bm_t, a2).temp_hp == thp, "ally 2 should get the temp HP"
    after = test.get_agent_stats(bm_t, bidx).resources["Bardic Inspiration"].current
    assert after == before - 1, "Mantle should spend one Bardic Inspiration use"
    print("✅ test_mantle_grants_double_die_thp passed")


def test_mantle_caps_at_cha_mod_and_skips_self():
    """Mantle affects at most CHA-mod creatures and never the bard itself (2024 'other creatures')."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    bidx = add_agent_to_battle(engine, bm, create_test_agent("GlamourBard", 5, 5))
    allies = [add_agent_to_battle(engine, bm, create_test_agent(f"Ally{i}", 6 + i, 6))
              for i in range(4)]
    _bard(engine, bm, bidx, 5, cha=14, subclass=rpg.BardCollege.Glamour)  # CHA +2 → cap 2

    # Pass the bard plus all four allies; only the first two valid allies should be bolstered.
    thp = engine.apply_mantle_of_inspiration(bm, bidx, [bidx] + allies)
    assert thp > 0
    assert engine.get_agent_stats(bm, bidx).temp_hp == 0, "the bard must not bolster itself"
    bolstered = [a for a in allies if engine.get_agent_stats(bm, a).temp_hp == thp]
    assert len(bolstered) == 2, f"CHA +2 should cap recipients at 2, got {len(bolstered)}"
    print("✅ test_mantle_caps_at_cha_mod_and_skips_self passed")


def test_mantle_requires_glamour_l3_and_a_use():
    """Mantle is rejected for non-Glamour bards, pre-L3, and when no Bardic Inspiration remains."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    bidx = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 6))

    _bard(engine, bm, bidx, 5, subclass=rpg.BardCollege.Lore)
    assert engine.apply_mantle_of_inspiration(bm, bidx, [ally]) == 0, "Lore bard cannot use Mantle"

    _bard(engine, bm, bidx, 2, subclass=rpg.BardCollege.Glamour)
    assert engine.apply_mantle_of_inspiration(bm, bidx, [ally]) == 0, "pre-L3 Glamour bard cannot use Mantle"

    _bard(engine, bm, bidx, 5, cha=16, subclass=rpg.BardCollege.Glamour)  # 3 uses
    engine.spend_resource(bm, bidx, "Bardic Inspiration", 3)              # drain them
    assert engine.apply_mantle_of_inspiration(bm, bidx, [ally]) == 0, "no use left → no Mantle"
    print("✅ test_mantle_requires_glamour_l3_and_a_use passed")


# ── College of Glamour: Mantle of Majesty (Bard L6) ──────────────────────────

def _command_spell():
    """A minimal Command spell (Save vs WIS, no damage), matching spells.json's entry."""
    s = rpg.Spell()
    s.name        = "Command"
    s.type        = rpg.SpellType.Harm
    s.geometry    = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.Save
    s.save_ability = rpg.SaveAbility.Wisdom
    s.range       = 60
    s.level       = 1
    return s


def _glamour6(engine, bm, bidx, level=6, cha=16):
    """Configure a Glamour Bard of `level` with Command prepared, as a player (not NPC)."""
    s = _bard(engine, bm, bidx, level, cha=cha, prof=3, subclass=rpg.BardCollege.Glamour)
    s.is_npc = False
    engine.set_agent_stats(bm, bidx, s)
    engine.set_agent_spells(bm, bidx, [_command_spell()])
    return engine.get_agent_stats(bm, bidx)


def _charm(engine, bm, target, by):
    """Mark `target` as Charmed by agent `by` (the auto-fail precondition)."""
    c = engine.get_agent_conditions(bm, target)
    c.charmed = True
    c.charmed_by = by
    engine.set_agent_conditions(bm, target, c)


def _cast_command(engine, bm, bard, target, word, free_cast=True, slot_level=0):
    act = rpg.SpellAction()
    act.caster_idx     = bard
    act.spell_idx      = 0
    act.target_indices = [target]
    act.command_word   = word
    act.free_cast      = free_cast
    act.slot_level     = slot_level
    return engine.execute_spell(bm, act)


def test_mantle_majesty_seeded_only_at_glamour_l6():
    """The 'Mantle of Majesty' resource (1 use) exists only for a College of Glamour Bard L6+."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    bidx = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 5))

    _bard(engine, bm, bidx, 5, subclass=rpg.BardCollege.Glamour)
    assert "Mantle of Majesty" not in engine.get_agent_stats(bm, bidx).resources, "no resource pre-L6"

    _bard(engine, bm, bidx, 6, subclass=rpg.BardCollege.Valor)
    assert "Mantle of Majesty" not in engine.get_agent_stats(bm, bidx).resources, "Valor has no Majesty"

    _bard(engine, bm, bidx, 6, subclass=rpg.BardCollege.Glamour)
    maj = engine.get_agent_stats(bm, bidx).resources.get("Mantle of Majesty")
    assert maj is not None and maj.current == 1 and maj.max == 1, "Glamour L6 → 1 use"
    print("✅ test_mantle_majesty_seeded_only_at_glamour_l6 passed")


def test_activate_mantle_of_majesty_opens_window():
    """Activation spends the use, sets a 10-round window, and concentrates on 'Mantle of Majesty'."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    bidx = add_agent_to_battle(engine, bm, create_test_agent("GlamourBard", 5, 5))
    _glamour6(engine, bm, bidx)

    assert engine.activate_mantle_of_majesty(bm, bidx) is True
    s = engine.get_agent_stats(bm, bidx)
    assert s.mantle_majesty_turns == 10, f"window should be 10 rounds, got {s.mantle_majesty_turns}"
    assert s.resources["Mantle of Majesty"].current == 0, "activation spends the use"
    c = engine.get_agent_conditions(bm, bidx)
    assert c.concentrating and c.concentrating_on == "Mantle of Majesty", "window IS concentration"

    # No use left → a second activation fails (the window may still be re-cast through, but the
    # resource is gone).
    assert engine.activate_mantle_of_majesty(bm, bidx) is False
    print("✅ test_activate_mantle_of_majesty_opens_window passed")


def test_activate_rejected_for_non_glamour_or_pre_l6():
    bm = setup_battle_map(); engine = setup_combat_engine()
    bidx = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 5))

    _bard(engine, bm, bidx, 6, subclass=rpg.BardCollege.Valor)
    assert engine.activate_mantle_of_majesty(bm, bidx) is False, "Valor cannot use Majesty"

    _bard(engine, bm, bidx, 5, subclass=rpg.BardCollege.Glamour)
    assert engine.activate_mantle_of_majesty(bm, bidx) is False, "pre-L6 Glamour cannot use Majesty"
    print("✅ test_activate_rejected_for_non_glamour_or_pre_l6 passed")


def test_free_command_cast_skips_slot():
    """free_cast=True must not expend a spell slot; a normal cast does."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    bidx = add_agent_to_battle(engine, bm, create_test_agent("GlamourBard", 5, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 6, 5))
    _glamour6(engine, bm, bidx)

    before = list(engine.get_agent_stats(bm, bidx).spell_slots_remaining)
    _cast_command(engine, bm, bidx, enemy, 3, free_cast=True)
    after_free = list(engine.get_agent_stats(bm, bidx).spell_slots_remaining)
    assert after_free == before, "free cast must not consume a slot"

    _cast_command(engine, bm, bidx, enemy, 3, free_cast=False, slot_level=1)
    after_paid = list(engine.get_agent_stats(bm, bidx).spell_slots_remaining)
    assert after_paid[0] == before[0] - 1, "a paid cast consumes a level-1 slot"
    print("✅ test_free_command_cast_skips_slot passed")


def test_restore_mantle_of_majesty_from_slot():
    """Restore requires a level 3+ slot, refills the use, and rejects when already full."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    bidx = add_agent_to_battle(engine, bm, create_test_agent("GlamourBard", 5, 5))
    _glamour6(engine, bm, bidx)

    engine.spend_resource(bm, bidx, "Mantle of Majesty", 1)
    assert engine.get_agent_stats(bm, bidx).resources["Mantle of Majesty"].current == 0

    assert engine.bard_restore_mantle_of_majesty_from_slot(bm, bidx, 2) == -1, "needs a L3+ slot"
    assert engine.get_agent_stats(bm, bidx).resources["Mantle of Majesty"].current == 0

    slots_before = list(engine.get_agent_stats(bm, bidx).spell_slots_remaining)
    assert engine.bard_restore_mantle_of_majesty_from_slot(bm, bidx, 3) == 1, "L3 slot refills the use"
    s = engine.get_agent_stats(bm, bidx)
    assert s.resources["Mantle of Majesty"].current == 1
    assert s.spell_slots_remaining[2] == slots_before[2] - 1, "a L3 slot was spent"

    assert engine.bard_restore_mantle_of_majesty_from_slot(bm, bidx, 3) == -1, "already full → no-op"
    print("✅ test_restore_mantle_of_majesty_from_slot passed")


def test_command_auto_fails_for_creature_charmed_by_bard():
    """During the window, a creature Charmed by THIS bard auto-fails its save vs Command."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    bidx = add_agent_to_battle(engine, bm, create_test_agent("GlamourBard", 5, 5))
    enemy = add_agent_to_battle(engine, bm, create_test_agent("Thug", 6, 5))
    _glamour6(engine, bm, bidx)
    # Make a normal save trivially succeed (huge WIS) so only the auto-fail can make it land.
    es = engine.get_agent_stats(bm, enemy); es.wis = 40; engine.set_agent_stats(bm, enemy, es)

    engine.activate_mantle_of_majesty(bm, bidx)

    # Not charmed → high WIS saves → Halt does NOT land.
    res = _cast_command(engine, bm, bidx, enemy, 3)
    assert res.target_results[0].saved is True, "uncharmed high-WIS target should save"
    assert engine.get_agent_conditions(bm, enemy).incapacitated is False

    # Charmed by the bard → auto-fail regardless of the roll → Halt lands.
    _charm(engine, bm, enemy, bidx)
    res = _cast_command(engine, bm, bidx, enemy, 3)
    assert res.target_results[0].saved is False, "Charmed-by-bard target auto-fails"
    assert engine.get_agent_conditions(bm, enemy).incapacitated is True, "Halt should incapacitate"
    print("✅ test_command_auto_fails_for_creature_charmed_by_bard passed")


def test_command_word_effects_on_failed_save():
    """Each Command word maps onto its mechanic on a failed save (failure forced via auto-fail)."""
    # word, checker(conditions) for direct-flag words
    flag_cases = [
        (0, lambda c: c.disarmed),       # Drop
        (2, lambda c: c.prone),          # Grovel
        (3, lambda c: c.incapacitated),  # Halt
    ]
    for word, ok in flag_cases:
        bm = setup_battle_map(); engine = setup_combat_engine()
        bidx = add_agent_to_battle(engine, bm, create_test_agent("GlamourBard", 5, 5))
        enemy = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5))
        _glamour6(engine, bm, bidx)
        engine.activate_mantle_of_majesty(bm, bidx)
        _charm(engine, bm, enemy, bidx)              # force the save to auto-fail
        _cast_command(engine, bm, bidx, enemy, word)
        assert ok(engine.get_agent_conditions(bm, enemy)), f"word {word} effect missing"

    # Flee / Approach create a 1-turn movement-restriction condition keyed to the bard.
    for word, name in [(1, "CommandFlee"), (4, "CommandApproach")]:
        bm = setup_battle_map(); engine = setup_combat_engine()
        bidx = add_agent_to_battle(engine, bm, create_test_agent("GlamourBard", 5, 5))
        enemy = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5))
        _glamour6(engine, bm, bidx)
        engine.activate_mantle_of_majesty(bm, bidx)
        _charm(engine, bm, enemy, bidx)
        _cast_command(engine, bm, bidx, enemy, word)
        match = [c for c in engine.active_agent_conditions
                 if c.agent_idx == enemy and c.condition_name == name and c.caster_idx == bidx]
        assert match, f"word {word} should create a {name} condition"
    print("✅ test_command_word_effects_on_failed_save passed")


def test_mantle_window_ends_on_drop_concentration():
    """Dropping concentration ends the unearthly-appearance window immediately."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    bidx = add_agent_to_battle(engine, bm, create_test_agent("GlamourBard", 5, 5))
    _glamour6(engine, bm, bidx)
    engine.activate_mantle_of_majesty(bm, bidx)
    assert engine.get_agent_stats(bm, bidx).mantle_majesty_turns == 10

    engine.drop_concentration(bm, bidx)
    s = engine.get_agent_stats(bm, bidx)
    assert s.mantle_majesty_turns == 0, "dropping concentration ends the window"
    c = engine.get_agent_conditions(bm, bidx)
    assert not c.concentrating, "concentration cleared"
    print("✅ test_mantle_window_ends_on_drop_concentration passed")


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
        test_mantle_grants_double_die_thp,
        test_mantle_caps_at_cha_mod_and_skips_self,
        test_mantle_requires_glamour_l3_and_a_use,
        test_mantle_majesty_seeded_only_at_glamour_l6,
        test_activate_mantle_of_majesty_opens_window,
        test_activate_rejected_for_non_glamour_or_pre_l6,
        test_free_command_cast_skips_slot,
        test_restore_mantle_of_majesty_from_slot,
        test_command_auto_fails_for_creature_charmed_by_bard,
        test_command_word_effects_on_failed_save,
        test_mantle_window_ends_on_drop_concentration,
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
