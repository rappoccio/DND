#!/usr/bin/env python3
"""
Evoker (Wizard) subclass features (2024 D&D):

  L3  Potent Cantrip      — a missed attack-roll cantrip still deals HALF its damage.
  L6  Sculpt Spells        — modeled by the persistent "safe targets" set
                             (see test_evoker_safe_targets.py).
  L10 Empowered Evocation  — add INT mod to ONE damage roll of a Wizard Evocation spell.
  L14 Overchannel          — deal maximum damage with a damaging spell of level 1-5;
                             first use per Long Rest is free, later uses inflict
                             escalating Necrotic self-damage.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_evoker(engine, bm, col, row, level, intel=18):
    idx = add_agent_to_battle(engine, bm, create_test_agent("Evoker", col, row))
    s = engine.get_agent_stats(bm, idx)
    s.character_class = rpg.CharacterClass.Wizard
    s.wizard_subclass = rpg.WizardSubclass.Evoker
    s.char_level = level
    s.intel = intel
    s.can_cast_spell = True
    s.spellcasting_ability = 3  # INT
    s.set_class_level(rpg.CharacterClass.Wizard, level)
    s.restore_spell_slots()
    s.initialize_class_resources(rpg.CharacterClass.Wizard, level)
    engine.set_agent_stats(bm, idx, s)
    return idx


def _dmg_roll(dtype, num_dice, die_size, bonus):
    r = rpg.MagicDamageRoll()
    r.type = dtype
    r.num_dice = num_dice
    r.die_size = die_size
    r.bonus = bonus
    return r


def _auto_evocation(level, rolls, school=None):
    """An auto-hitting (no save/attack) damaging Evocation spell with fixed damage rolls."""
    sp = rpg.Spell()
    sp.name = "TestBlast"
    sp.level = level
    sp.type = rpg.SpellType.Harm
    sp.school = rpg.SpellSchool.Evocation if school is None else school
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.geometry = rpg.SpellGeometry.Single
    sp.range = 120
    sp.magic_damage_rolls = rolls
    return sp


def _cast(engine, bm, caster, target, slot_level=0, overchannel=False):
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = slot_level
    action.target_indices = [target]
    action.overchannel = overchannel
    return engine.execute_spell(bm, action)


# ── Empowered Evocation (L10) ────────────────────────────────────────────────

def test_empowered_evocation_adds_int_to_one_roll():
    """L10 Evoker (INT 18, +4) adds INT mod to exactly one of two 10-damage rolls → 24, not 28."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = _make_evoker(engine, bm, 2, 2, level=10, intel=18)
    target = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 4, 2), hp=200)
    engine.set_agent_spells(bm, caster, [_auto_evocation(
        0, [_dmg_roll(rpg.MagicDamage.Fire, 0, 0, 10),
            _dmg_roll(rpg.MagicDamage.Fire, 0, 0, 10)])])
    tr = _cast(engine, bm, caster, target).target_results[0]
    assert tr.total_damage == 24, f"expected 20 base + 4 INT on one roll = 24, got {tr.total_damage}"
    print("✅ test_empowered_evocation_adds_int_to_one_roll passed")


def test_empowered_evocation_gated_below_l10():
    """An Evoker below L10 gets no Empowered Evocation bonus."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = _make_evoker(engine, bm, 2, 2, level=9, intel=18)
    target = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 4, 2), hp=200)
    engine.set_agent_spells(bm, caster, [_auto_evocation(0, [_dmg_roll(rpg.MagicDamage.Fire, 0, 0, 10)])])
    tr = _cast(engine, bm, caster, target).target_results[0]
    assert tr.total_damage == 10, f"L9 Evoker should deal 10 (no INT bonus), got {tr.total_damage}"
    print("✅ test_empowered_evocation_gated_below_l10 passed")


def test_empowered_evocation_evocation_only():
    """Empowered Evocation only applies to Evocation-school spells."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = _make_evoker(engine, bm, 2, 2, level=10, intel=18)
    target = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 4, 2), hp=200)
    necro = _auto_evocation(0, [_dmg_roll(rpg.MagicDamage.Necrotic, 0, 0, 10)],
                            school=rpg.SpellSchool.Necromancy)
    engine.set_agent_spells(bm, caster, [necro])
    tr = _cast(engine, bm, caster, target).target_results[0]
    assert tr.total_damage == 10, f"non-Evocation should get no INT bonus, got {tr.total_damage}"
    print("✅ test_empowered_evocation_evocation_only passed")


# ── Potent Cantrip (L3) ──────────────────────────────────────────────────────

def _attack_cantrip():
    sp = rpg.Spell()
    sp.name = "Fire Bolt"
    sp.level = 0
    sp.type = rpg.SpellType.Harm
    sp.school = rpg.SpellSchool.Evocation
    sp.attack_type = rpg.SpellAttack.AttackRoll
    sp.geometry = rpg.SpellGeometry.Single
    sp.range = 120
    sp.magic_damage_rolls = [_dmg_roll(rpg.MagicDamage.Fire, 0, 0, 8)]  # fixed 8 damage
    return sp


def _miss_damage_over_casts(engine, bm, caster, target, casts=20):
    """Cast a guaranteed-miss cantrip many times; return the set of damages dealt on misses."""
    misses = []
    for _ in range(casts):
        tr = _cast(engine, bm, caster, target).target_results[0]
        if not tr.hit:
            misses.append(tr.total_damage)
    return misses


def test_potent_cantrip_half_on_miss():
    """Evoker L3: a missed attack cantrip still deals half (8 → 4)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = _make_evoker(engine, bm, 2, 2, level=3, intel=10)  # +0 INT so no Empowered muddling
    # AC 99 → every non-nat-20 roll misses.
    target = add_agent_to_battle(engine, bm, create_test_agent("Wall", 4, 2), hp=500, ac=99)
    engine.set_agent_spells(bm, caster, [_attack_cantrip()])
    misses = _miss_damage_over_casts(engine, bm, caster, target)
    assert misses, "expected at least one miss against AC 99"
    assert all(d == 4 for d in misses), f"every missed cantrip should deal 4 (half of 8), got {set(misses)}"
    print("✅ test_potent_cantrip_half_on_miss passed")


def test_potent_cantrip_none_without_feature():
    """A non-Evoker deals 0 on a missed attack cantrip."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = _make_evoker(engine, bm, 2, 2, level=3, intel=10)
    s = engine.get_agent_stats(bm, caster)
    s.wizard_subclass = rpg.WizardSubclass.Abjurer  # not an Evoker
    engine.set_agent_stats(bm, caster, s)
    target = add_agent_to_battle(engine, bm, create_test_agent("Wall", 4, 2), hp=500, ac=99)
    engine.set_agent_spells(bm, caster, [_attack_cantrip()])
    misses = _miss_damage_over_casts(engine, bm, caster, target)
    assert misses, "expected at least one miss against AC 99"
    assert all(d == 0 for d in misses), f"non-Evoker miss should deal 0, got {set(misses)}"
    print("✅ test_potent_cantrip_none_without_feature passed")


# ── Overchannel (L14) ────────────────────────────────────────────────────────

def _overchannel_spell():
    # 6d6 Fire — max = 36 under Overchannel, auto-hit so no save halving.
    return _auto_evocation(3, [_dmg_roll(rpg.MagicDamage.Fire, 6, 6, 0)])


def test_overchannel_max_damage_first_use_free():
    """L14 Evoker: overchanneled 6d6 deals its max (36); first use costs no HP."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = _make_evoker(engine, bm, 2, 2, level=14, intel=10)  # INT 10 → Empowered Evocation adds 0
    target = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 4, 2), hp=500)
    engine.set_agent_spells(bm, caster, [_overchannel_spell()])
    hp_before = engine.get_agent_stats(bm, caster).hp_cur

    tr = _cast(engine, bm, caster, target, slot_level=3, overchannel=True).target_results[0]
    cs = engine.get_agent_stats(bm, caster)
    assert tr.total_damage == 36, f"6d6 overchanneled should be max 36, got {tr.total_damage}"
    assert cs.hp_cur == hp_before, f"first Overchannel use is free, but caster lost HP ({hp_before}→{cs.hp_cur})"
    assert cs.overchannel_uses == 1, f"overchannel_uses should be 1, got {cs.overchannel_uses}"
    print("✅ test_overchannel_max_damage_first_use_free passed")


def test_overchannel_second_use_self_damage():
    """Second overchannel before a rest still maxes damage but hurts the caster."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = _make_evoker(engine, bm, 2, 2, level=14, intel=10)  # INT 10 → Empowered Evocation adds 0
    target = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 4, 2), hp=500)
    engine.set_agent_spells(bm, caster, [_overchannel_spell()])

    _cast(engine, bm, caster, target, slot_level=3, overchannel=True)  # free first use
    hp_before = engine.get_agent_stats(bm, caster).hp_cur
    tr = _cast(engine, bm, caster, target, slot_level=3, overchannel=True).target_results[0]
    cs = engine.get_agent_stats(bm, caster)
    assert tr.total_damage == 36, f"second overchannel should still max at 36, got {tr.total_damage}"
    # 2nd use = 2d12 per spell level (level 3) = 6d12 Necrotic → 6..72 self-damage.
    lost = hp_before - cs.hp_cur
    assert 6 <= lost <= 72, f"second use should cost 6d12 (6-72) Necrotic, lost {lost}"
    assert cs.overchannel_uses == 2, f"overchannel_uses should be 2, got {cs.overchannel_uses}"
    print("✅ test_overchannel_second_use_self_damage passed")


def test_overchannel_reset_on_long_rest():
    """A Long Rest makes the next Overchannel free again."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = _make_evoker(engine, bm, 2, 2, level=14, intel=10)  # INT 10 → Empowered Evocation adds 0
    target = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 4, 2), hp=500)
    engine.set_agent_spells(bm, caster, [_overchannel_spell()])

    _cast(engine, bm, caster, target, slot_level=3, overchannel=True)
    assert engine.get_agent_stats(bm, caster).overchannel_uses == 1
    engine.apply_long_rest(bm)
    assert engine.get_agent_stats(bm, caster).overchannel_uses == 0, "Long Rest should reset Overchannel"

    # Re-arm slots consumed by the pre-rest cast, then the post-rest cast should be free again.
    s = engine.get_agent_stats(bm, caster); s.restore_spell_slots(); engine.set_agent_stats(bm, caster, s)
    hp_before = engine.get_agent_stats(bm, caster).hp_cur
    _cast(engine, bm, caster, target, slot_level=3, overchannel=True)
    cs = engine.get_agent_stats(bm, caster)
    assert cs.hp_cur == hp_before, "post-rest first Overchannel should again be free"
    assert cs.overchannel_uses == 1
    print("✅ test_overchannel_reset_on_long_rest passed")


def test_overchannel_ineligible_below_l14():
    """An Evoker below L14 cannot Overchannel: no max damage, no usage counter change."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = _make_evoker(engine, bm, 2, 2, level=13, intel=10)
    target = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 4, 2), hp=500)
    engine.set_agent_spells(bm, caster, [_overchannel_spell()])
    tr = _cast(engine, bm, caster, target, slot_level=3, overchannel=True).target_results[0]
    cs = engine.get_agent_stats(bm, caster)
    assert cs.overchannel_uses == 0, "L13 Evoker must not consume Overchannel"
    assert tr.total_damage <= 36, "sanity: 6d6 never exceeds 36"
    print("✅ test_overchannel_ineligible_below_l14 passed")


def test_overchannel_ineligible_above_l5_spell():
    """Overchannel only works on spells of effective level 1-5 (an L6 slot is ineligible)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = _make_evoker(engine, bm, 2, 2, level=20, intel=10)
    target = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 4, 2), hp=500)
    engine.set_agent_spells(bm, caster, [_overchannel_spell()])
    _cast(engine, bm, caster, target, slot_level=6, overchannel=True)
    cs = engine.get_agent_stats(bm, caster)
    assert cs.overchannel_uses == 0, "an effective-level-6 cast must not consume Overchannel"
    print("✅ test_overchannel_ineligible_above_l5_spell passed")


if __name__ == "__main__":
    tests = [
        test_empowered_evocation_adds_int_to_one_roll,
        test_empowered_evocation_gated_below_l10,
        test_empowered_evocation_evocation_only,
        test_potent_cantrip_half_on_miss,
        test_potent_cantrip_none_without_feature,
        test_overchannel_max_damage_first_use_free,
        test_overchannel_second_use_self_damage,
        test_overchannel_reset_on_long_rest,
        test_overchannel_ineligible_below_l14,
        test_overchannel_ineligible_above_l5_spell,
    ]
    print("Running Evoker Wizard tests...")
    print("=" * 60)
    passed = failed = 0
    for t in tests:
        try:
            t(); passed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}"); failed += 1
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
