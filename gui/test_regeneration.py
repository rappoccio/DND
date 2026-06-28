#!/usr/bin/env python3
"""
Test suite for Regeneration (Troll, Slaad, …).

A regenerating creature regains `regeneration_amount` HP at the start of each of
its turns (capped at effective max HP, requires >= 1 HP). Regeneration is shut off
for one turn when the creature takes a damage type in `regen_interrupt_damage_types`
(Troll = [Acid, Fire]) — the engine sets the transient `regen_suppressed` flag,
which begin_turn consumes.

NOTE: 2024 vampires do NOT passively regenerate — the 2014 Regeneration trait was
cut, and a 2024 vampire heals only via its Bite Life Drain (modelled elsewhere). The
two "regenerator in Sunlight" tests below use a vampire *fixture* (is_vampire triggers
the Sunlight 20-radiant) with a homebrew regen value purely to exercise the general
coupling: the Sunlight block reuses the same `regen_suppressed` flag. They are NOT a
claim that vampires regenerate. See known_limitations.md "Regeneration".
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

FIRE = int(rpg.MagicDamage.Fire)
COLD = int(rpg.MagicDamage.Cold)
ACID = int(rpg.MagicDamage.Acid)
RADIANT = int(rpg.MagicDamage.Radiant)


def _make_regenerator(engine, bm, idx, amount=15, interrupts=(ACID, FIRE),
                      hp_cur=50, hp_max=100, vampire=False):
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = hp_max
    s.hp_cur = hp_cur
    s.base_ac = 10
    s.str = 8
    s.dex = 8
    s.con = 14
    s.regeneration_amount = amount
    s.regen_interrupt_damage_types = list(interrupts)
    s.is_vampire = vampire
    engine.set_agent_stats(bm, idx, s)
    return s


def _fire_weapon(num_dice=4, die_size=6, bonus=20, dtype=FIRE):
    """A guaranteed-hit melee weapon dealing only magic damage of `dtype`."""
    w = rpg.Weapon()
    w.name = "Flametongue"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.reach_ft = 10
    w.attack_bonus = 50
    w.bonus_hit = 50
    w.bonus_damage = 0
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage(dtype)
    roll.num_dice = num_dice
    roll.die_size = die_size
    roll.bonus = bonus
    w.magic_damage_types = [roll]
    return [w, rpg.Weapon(), rpg.Weapon()]


# ─────────────────────────────────────────────────────────────────────────────
#  Turn-start regeneration
# ─────────────────────────────────────────────────────────────────────────────

def test_regeneration_heals_at_turn_start():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    troll = add_agent_to_battle(engine, bm, create_test_agent("Troll", 5, 5))
    _make_regenerator(engine, bm, troll, amount=15, hp_cur=50, hp_max=100)

    engine.begin_turn(bm, troll)

    hp = engine.get_agent_stats(bm, troll).hp_cur
    assert hp == 65, f"Troll should regen 15 (50 -> 65), got {hp}"
    print("✅ Regeneration heals 15 HP at turn start (50 -> 65)")


def test_regeneration_caps_at_max_hp():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    troll = add_agent_to_battle(engine, bm, create_test_agent("Troll", 5, 5))
    _make_regenerator(engine, bm, troll, amount=15, hp_cur=95, hp_max=100)

    engine.begin_turn(bm, troll)

    hp = engine.get_agent_stats(bm, troll).hp_cur
    assert hp == 100, f"Regen should cap at max HP (95 + 15 -> 100), got {hp}"
    print("✅ Regeneration caps at max HP (95 -> 100, not 110)")


def test_regeneration_requires_alive():
    """A creature at 0 HP does not regenerate (the 'dies only at 0' RAW is deferred)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    troll = add_agent_to_battle(engine, bm, create_test_agent("Troll", 5, 5))
    _make_regenerator(engine, bm, troll, amount=15, hp_cur=0, hp_max=100)

    engine.begin_turn(bm, troll)

    hp = engine.get_agent_stats(bm, troll).hp_cur
    assert hp == 0, f"A downed regenerator should stay at 0 HP, got {hp}"
    print("✅ No regeneration while at 0 HP")


def test_no_regeneration_when_amount_zero():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    a = add_agent_to_battle(engine, bm, create_test_agent("Plain", 5, 5))
    _make_regenerator(engine, bm, a, amount=0, hp_cur=50, hp_max=100)

    engine.begin_turn(bm, a)

    hp = engine.get_agent_stats(bm, a).hp_cur
    assert hp == 50, f"No regen with amount 0, got {hp}"
    print("✅ No regeneration when regeneration_amount == 0")


# ─────────────────────────────────────────────────────────────────────────────
#  Suppression flag
# ─────────────────────────────────────────────────────────────────────────────

def test_suppressed_flag_skips_one_turn_then_resumes():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    troll = add_agent_to_battle(engine, bm, create_test_agent("Troll", 5, 5))
    s = _make_regenerator(engine, bm, troll, amount=15, hp_cur=50, hp_max=100)
    s.regen_suppressed = True
    engine.set_agent_stats(bm, troll, s)

    # First turn: suppressed, no heal, flag consumed.
    engine.begin_turn(bm, troll)
    s1 = engine.get_agent_stats(bm, troll)
    assert s1.hp_cur == 50, f"Suppressed turn should not heal, got {s1.hp_cur}"
    assert not s1.regen_suppressed, "Suppression flag should be consumed after one turn"

    # Second turn: regen resumes.
    engine.begin_turn(bm, troll)
    s2 = engine.get_agent_stats(bm, troll)
    assert s2.hp_cur == 65, f"Regen should resume next turn (50 -> 65), got {s2.hp_cur}"
    print("✅ Suppression skips exactly one turn, then regeneration resumes")


# ─────────────────────────────────────────────────────────────────────────────
#  Damage-type interrupt (integration through the attack damage path)
# ─────────────────────────────────────────────────────────────────────────────

def test_interrupting_damage_suppresses_next_regen():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    troll = add_agent_to_battle(engine, bm, create_test_agent("Troll", 5, 5))
    attacker = add_agent_to_battle(engine, bm, create_test_agent("Pyro", 6, 5), str=18)
    _make_regenerator(engine, bm, troll, amount=15, interrupts=(ACID, FIRE),
                      hp_cur=50, hp_max=100)
    engine.set_agent_weapons(bm, attacker, _fire_weapon(dtype=FIRE))

    res = engine.execute_action(bm, rpg.Attack(attacker, troll, 0))
    assert res.hit, "fire weapon should hit (bonus_hit=50)"
    assert engine.get_agent_stats(bm, troll).regen_suppressed, \
        "fire damage should flag the troll's regeneration as suppressed"

    hp_before = engine.get_agent_stats(bm, troll).hp_cur
    engine.begin_turn(bm, troll)
    hp_after = engine.get_agent_stats(bm, troll).hp_cur
    assert hp_after == hp_before, \
        f"the turn after fire damage should NOT regen ({hp_before} -> {hp_after})"
    print("✅ Fire damage suppresses the troll's next regeneration")


def test_noninterrupting_damage_does_not_suppress():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    troll = add_agent_to_battle(engine, bm, create_test_agent("Troll", 5, 5))
    attacker = add_agent_to_battle(engine, bm, create_test_agent("Frost", 6, 5), str=18)
    _make_regenerator(engine, bm, troll, amount=15, interrupts=(ACID, FIRE),
                      hp_cur=50, hp_max=100)
    # Cold is NOT in the troll's interrupt list.
    engine.set_agent_weapons(bm, attacker, _fire_weapon(dtype=COLD))

    res = engine.execute_action(bm, rpg.Attack(attacker, troll, 0))
    assert res.hit, "cold weapon should hit"
    assert not engine.get_agent_stats(bm, troll).regen_suppressed, \
        "cold damage must NOT suppress a troll (acid/fire only)"

    hp_before = engine.get_agent_stats(bm, troll).hp_cur
    engine.begin_turn(bm, troll)
    hp_after = engine.get_agent_stats(bm, troll).hp_cur
    assert hp_after == min(100, hp_before + 15), \
        f"troll should still regen after cold damage ({hp_before} -> {hp_after})"
    print("✅ Non-interrupting (cold) damage leaves regeneration intact")


# ─────────────────────────────────────────────────────────────────────────────
#  Sunlight reuses the same interrupt mechanism (vampire fixture, homebrew regen —
#  2024 vampires do NOT passively regenerate; see module docstring)
# ─────────────────────────────────────────────────────────────────────────────

def _load_daylight(engine, bm, caster_idx, col, row):
    """Grant slots, give the caster Daylight, and cast it centered on (col, row).
    Mirrors test_light_effects._cast_light (slots set post-placement so the
    applyAgentConfigs rebuilds don't wipe them)."""
    import json
    import helpers
    catalog = json.load(open(os.path.join(os.path.dirname(__file__), "spells.json")))
    daylight = next(s for s in catalog if s["name"] == "Daylight")
    sp = helpers._dict_to_spell(daylight)

    stats = engine.get_agent_stats(bm, caster_idx)
    stats.spell_slots_remaining = [999] * 9
    engine.set_agent_stats(bm, caster_idx, stats)
    engine.set_agent_spells(bm, caster_idx, [sp])

    act = rpg.SpellAction()
    act.caster_idx = caster_idx
    act.spell_idx = 0
    act.target_indices = []
    act.aoe_col = col
    act.aoe_row = row
    act.aoe_col2 = col
    act.aoe_row2 = row
    return engine.execute_spell(bm, act)


def test_vampire_in_sunlight_takes_radiant_and_skips_regen():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    vampire = add_agent_to_battle(engine, bm, create_test_agent("Vampire", 5, 5))
    wizard = add_agent_to_battle(engine, bm, create_test_agent("Wizard", 2, 2), intel=16)
    # Homebrew regen on a vampire fixture: is_vampire triggers the Sunlight 20-radiant;
    # the regen value just lets us observe that Sunlight suppresses it (not canon).
    _make_regenerator(engine, bm, vampire, amount=20, interrupts=(RADIANT,),
                      hp_cur=100, hp_max=100, vampire=True)

    result = _load_daylight(engine, bm, wizard, col=5, row=5)
    assert result.valid, "Daylight should be valid"
    effects = bm.active_light_effects
    assert any(e.light_level == rpg.VisibilityLevel.Sunlight for e in effects), "should have Sunlight"

    engine.begin_turn(bm, vampire)

    hp = engine.get_agent_stats(bm, vampire).hp_cur
    # 20 radiant from Sunlight, and regeneration suppressed (no 20 healed back).
    assert hp == 80, f"vampire in sunlight: 100 - 20 radiant, no regen -> 80, got {hp}"
    print("✅ Vampire in Sunlight takes 20 radiant AND does not regenerate (100 -> 80)")


def test_vampire_outside_sunlight_regenerates():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    vampire = add_agent_to_battle(engine, bm, create_test_agent("Vampire", 9, 9))
    wizard = add_agent_to_battle(engine, bm, create_test_agent("Wizard", 2, 2), intel=16)
    # Homebrew regen on a vampire fixture (not canon) — see module docstring.
    _make_regenerator(engine, bm, vampire, amount=20, interrupts=(RADIANT,),
                      hp_cur=60, hp_max=100, vampire=True)

    # Daylight far away — vampire's cell is not in Sunlight.
    result = _load_daylight(engine, bm, wizard, col=2, row=2)
    assert result.valid

    engine.begin_turn(bm, vampire)

    hp = engine.get_agent_stats(bm, vampire).hp_cur
    assert hp == 80, f"vampire out of sunlight should regen 20 (60 -> 80), got {hp}"
    print("✅ Vampire outside Sunlight regenerates normally (60 -> 80)")


if __name__ == "__main__":
    test_regeneration_heals_at_turn_start()
    test_regeneration_caps_at_max_hp()
    test_regeneration_requires_alive()
    test_no_regeneration_when_amount_zero()
    test_suppressed_flag_skips_one_turn_then_resumes()
    test_interrupting_damage_suppresses_next_regen()
    test_noninterrupting_damage_does_not_suppress()
    test_vampire_in_sunlight_takes_radiant_and_skips_regen()
    test_vampire_outside_sunlight_regenerates()
    print("\n✅ All regeneration tests passed!")
