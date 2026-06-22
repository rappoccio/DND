#!/usr/bin/env python3
"""
Test Rogue — Assassin subclass (2024).

Covered engine-side features:
  · Assassinate (L3):
      - Initiative: Advantage on Initiative rolls (rollInitiative / rollInitiativeFor).
      - Advantage on attack rolls vs any creature that hasn't taken a turn in the current combat
        (Conditions.has_taken_turn_this_combat, set in beginTurn, reset at combat start).
      - A Sneak hit during the first round (round_num == 0) deals +Rogue-level flat damage.
  · Envenom Weapons (L13): the Poison option of Cunning Strike costs 0 Sneak Attack dice and, on a
    failed save, deals 2d6 Poison that ignores Resistance to Poison (Immunity/Vulnerability stand).
  · Death Strike (L17): a first-round Sneak hit forces a CON save (DC 8 + DEX + PB); on a failure the
    whole attack's damage is doubled.

Scope note: Assassinate's bonus damage + Death Strike are folded into the Sneak Attack path
(applyCunningStrikeEffect), so they fire on a qualifying Sneak hit. See known_limitations.md / Rogue.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle
from test_rogue_phase2 import _finesse_weapon, _three, _breakdown_value, _high_ac_target


def _rogue_sub(engine, bm, idx, level, subclass, dex=20):
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Rogue, level)
    s.rogue_subclass = subclass
    s.dex = dex
    s.initialize_class_resources(rpg.CharacterClass.Rogue, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _setup(level, subclass, high_ac_target=True):
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), ac=1, hp=2000)
    _rogue_sub(engine, bm, atk, level, subclass)
    if high_ac_target:
        _high_ac_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, atk, _three(_finesse_weapon()))
    return bm, engine, atk, tgt


def _sneak_hit(engine, bm, atk, tgt, effects, round_num=-1, force_adv=True):
    """Land an attack (with advantage by default), then apply Sneak Attack + riders for round_num.

    Resets the per-turn Sneak gate first so the helper can be called repeatedly in one test.
    """
    c = engine.get_agent_conditions(bm, atk)
    c.sneak_attack_used = False
    c.cunning_strike_available = False
    engine.set_agent_conditions(bm, atk, c)
    for _ in range(60):
        c = engine.get_agent_conditions(bm, atk)
        if force_adv:
            c.has_advantage = True
        engine.set_agent_conditions(bm, atk, c)
        result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
        if result.hit:
            break
    else:
        raise AssertionError("attack never landed in 60 tries")
    engine.apply_cunning_strike_effect(bm, atk, tgt, effects, result, round_num)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Assassinate (L3) — Initiative Advantage
# ─────────────────────────────────────────────────────────────────────────────

def test_assassinate_initiative_advantage():
    bm, engine, atk, _ = _setup(3, rpg.RogueSubclass.Assassin)
    bm2, engine2, atk2, _ = _setup(3, rpg.RogueSubclass.Thief)
    N = 400
    a_mean = sum(engine.roll_initiative_for(bm, atk).d20 for _ in range(N)) / N
    t_mean = sum(engine2.roll_initiative_for(bm2, atk2).d20 for _ in range(N)) / N
    # Advantage shifts the mean d20 to ~13.8; a flat d20 averages ~10.5.
    assert a_mean > 12.5, f"Assassin should roll Initiative at Advantage (mean d20 {a_mean:.2f})"
    assert t_mean < 12.0, f"Thief rolls a flat Initiative d20 (mean d20 {t_mean:.2f})"
    print(f"✅ test_assassinate_initiative_advantage passed (assassin {a_mean:.2f} vs thief {t_mean:.2f})")


def test_no_initiative_advantage_below_l3():
    bm, engine, atk, _ = _setup(2, rpg.RogueSubclass.Assassin)
    N = 400
    mean = sum(engine.roll_initiative_for(bm, atk).d20 for _ in range(N)) / N
    assert mean < 12.0, f"Assassin below L3 has no Initiative Advantage (mean d20 {mean:.2f})"
    print("✅ test_no_initiative_advantage_below_l3 passed")


# ─────────────────────────────────────────────────────────────────────────────
# Assassinate (L3) — Advantage vs creatures that haven't acted
# ─────────────────────────────────────────────────────────────────────────────

def test_assassinate_advantage_vs_not_acted():
    # No manually-set advantage: a Rogue Sneak Attack only flags when the attack had Advantage,
    # so cunning_strike_available proves Assassinate granted it (target hasn't acted by default).
    bm, engine, atk, tgt = _setup(3, rpg.RogueSubclass.Assassin)
    assert not engine.get_agent_conditions(bm, tgt).has_taken_turn_this_combat
    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit
    assert engine.get_agent_conditions(bm, atk).cunning_strike_available, \
        "Assassinate should grant Advantage vs a creature that hasn't acted → Sneak Attack qualifies"
    print("✅ test_assassinate_advantage_vs_not_acted passed")


def test_no_assassinate_advantage_when_target_acted():
    bm, engine, atk, tgt = _setup(3, rpg.RogueSubclass.Assassin)
    tc = engine.get_agent_conditions(bm, tgt)
    tc.has_taken_turn_this_combat = True
    engine.set_agent_conditions(bm, tgt, tc)
    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit
    assert not engine.get_agent_conditions(bm, atk).cunning_strike_available, \
        "no Advantage source once the target has acted → Sneak Attack must not qualify"
    print("✅ test_no_assassinate_advantage_when_target_acted passed")


def test_not_acted_advantage_only_for_assassin():
    # A Thief vs a not-acted target gets no special Advantage.
    bm, engine, atk, tgt = _setup(3, rpg.RogueSubclass.Thief)
    assert not engine.get_agent_conditions(bm, tgt).has_taken_turn_this_combat
    result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
    assert result.hit
    assert not engine.get_agent_conditions(bm, atk).cunning_strike_available, \
        "non-Assassin gets no not-acted Advantage → no Sneak Attack"
    print("✅ test_not_acted_advantage_only_for_assassin passed")


# ─────────────────────────────────────────────────────────────────────────────
# Assassinate (L3) — first-round Sneak bonus damage
# ─────────────────────────────────────────────────────────────────────────────

def test_assassinate_round1_bonus_damage():
    bm, engine, atk, tgt = _setup(5, rpg.RogueSubclass.Assassin)
    result = _sneak_hit(engine, bm, atk, tgt, [], round_num=0)
    bonus = _breakdown_value(result, "Assassinate")
    assert bonus == 5, f"Assassinate should add +Rogue level (5) on a first-round Sneak hit, got {bonus}"
    print("✅ test_assassinate_round1_bonus_damage passed")


def test_assassinate_no_bonus_after_round1():
    bm, engine, atk, tgt = _setup(5, rpg.RogueSubclass.Assassin)
    result = _sneak_hit(engine, bm, atk, tgt, [], round_num=1)
    assert _breakdown_value(result, "Assassinate") is None, \
        "Assassinate bonus should only apply during the first round"
    print("✅ test_assassinate_no_bonus_after_round1 passed")


def test_assassinate_bonus_requires_assassin():
    bm, engine, atk, tgt = _setup(5, rpg.RogueSubclass.Thief)
    result = _sneak_hit(engine, bm, atk, tgt, [], round_num=0)
    assert _breakdown_value(result, "Assassinate") is None, \
        "non-Assassin Rogues get no Assassinate bonus"
    print("✅ test_assassinate_bonus_requires_assassin passed")


# ─────────────────────────────────────────────────────────────────────────────
# Envenom Weapons (L13)
# ─────────────────────────────────────────────────────────────────────────────

def test_envenom_free_poison_die():
    # L13 Sneak Attack = 7d6. With Envenom the Poison rider costs 0 dice → full 7d6 (7..42), plus
    # a 2d6 Poison rider and the Poisoned condition. round_num=-1 to isolate (no Assassinate/Death).
    bm, engine, atk, tgt = _setup(13, rpg.RogueSubclass.Assassin)
    result = _sneak_hit(engine, bm, atk, tgt, [0], round_num=-1)
    sneak = _breakdown_value(result, "sneak attack")
    assert sneak is not None and 7 <= sneak <= 42, \
        f"Envenom makes Poison free → full 7d6 (7..42), got {sneak}"
    env = _breakdown_value(result, "Envenom (Poison)")
    assert env is not None and 2 <= env <= 12, f"Envenom 2d6 Poison should be 2..12, got {env}"
    assert engine.get_agent_conditions(bm, tgt).poisoned, "Poison rider should still apply Poisoned"
    print("✅ test_envenom_free_poison_die passed")


def test_envenom_not_for_non_assassin_or_below_l13():
    # Thief L13 Poison rider: normal 1-die cost (6d6) and NO Envenom 2d6.
    bm, engine, atk, tgt = _setup(13, rpg.RogueSubclass.Thief)
    result = _sneak_hit(engine, bm, atk, tgt, [0], round_num=-1)
    sneak = _breakdown_value(result, "sneak attack")
    assert sneak is not None and 6 <= sneak <= 36, f"Thief pays the Poison die → 6d6 (6..36), got {sneak}"
    assert _breakdown_value(result, "Envenom (Poison)") is None, "non-Assassin gets no Envenom 2d6"
    # Assassin L11 (below 13): also no Envenom.
    bm2, engine2, atk2, tgt2 = _setup(11, rpg.RogueSubclass.Assassin)
    r2 = _sneak_hit(engine2, bm2, atk2, tgt2, [0], round_num=-1)
    assert _breakdown_value(r2, "Envenom (Poison)") is None, "Assassin below L13 gets no Envenom 2d6"
    print("✅ test_envenom_not_for_non_assassin_or_below_l13 passed")


def test_envenom_ignores_poison_resistance():
    # Target resistant to Poison: the Envenom 2d6 must NOT be halved. Halved 2d6 caps at 6, so seeing
    # any value >= 7 across many tries proves Resistance is ignored.
    bm, engine, atk, tgt = _setup(13, rpg.RogueSubclass.Assassin)
    ts = engine.get_agent_stats(bm, tgt)
    ts.set_magic_damage_multiplier(rpg.MagicDamage.Poison, 0.5)
    engine.set_agent_stats(bm, tgt, ts)
    max_env = 0
    for _ in range(80):
        result = _sneak_hit(engine, bm, atk, tgt, [0], round_num=-1)
        env = _breakdown_value(result, "Envenom (Poison)")
        if env is not None:
            max_env = max(max_env, env)
    assert max_env >= 7, f"Envenom should ignore Poison Resistance (max 2d6 seen {max_env}, halved caps at 6)"
    print(f"✅ test_envenom_ignores_poison_resistance passed (max Envenom {max_env})")


def test_envenom_respects_poison_immunity():
    bm, engine, atk, tgt = _setup(13, rpg.RogueSubclass.Assassin)
    ts = engine.get_agent_stats(bm, tgt)
    ts.set_magic_damage_multiplier(rpg.MagicDamage.Poison, 0.0)
    engine.set_agent_stats(bm, tgt, ts)
    result = _sneak_hit(engine, bm, atk, tgt, [0], round_num=-1)
    env = _breakdown_value(result, "Envenom (Poison)")
    assert env in (None, 0), f"Poison Immunity should zero the Envenom damage, got {env}"
    print("✅ test_envenom_respects_poison_immunity passed")


# ─────────────────────────────────────────────────────────────────────────────
# Death Strike (L17)
# ─────────────────────────────────────────────────────────────────────────────

def test_death_strike_doubles_round1():
    # L17 PB 6, DEX +5 → DC 19. Target CON mod -5, no save prof → always fails → damage doubled.
    bm, engine, atk, tgt = _setup(17, rpg.RogueSubclass.Assassin)
    result = _sneak_hit(engine, bm, atk, tgt, [], round_num=0)
    dbl = _breakdown_value(result, "Death Strike (doubled)")
    assert dbl is not None, "Death Strike should double damage on a failed CON save in round 1"
    assert dbl * 2 == result.total_damage, \
        f"Death Strike doubles the whole attack: {dbl}*2 should equal total {result.total_damage}"
    print("✅ test_death_strike_doubles_round1 passed")


def test_death_strike_save_success_no_double():
    # Sky-high CON → the save always beats DC 19, so no doubling.
    bm, engine, atk, tgt = _setup(17, rpg.RogueSubclass.Assassin)
    ts = engine.get_agent_stats(bm, tgt)
    ts.con = 60          # mod +25: passes DC 19 even on a natural 1
    ts.save_prof_con = True
    engine.set_agent_stats(bm, tgt, ts)
    result = _sneak_hit(engine, bm, atk, tgt, [], round_num=0)
    assert _breakdown_value(result, "Death Strike (doubled)") is None, \
        "a successful CON save means no Death Strike doubling"
    print("✅ test_death_strike_save_success_no_double passed")


def test_death_strike_only_round1_and_l17():
    # Round 2: no Death Strike.
    bm, engine, atk, tgt = _setup(17, rpg.RogueSubclass.Assassin)
    r = _sneak_hit(engine, bm, atk, tgt, [], round_num=1)
    assert _breakdown_value(r, "Death Strike (doubled)") is None, "Death Strike is first-round only"
    # L13 Assassin, round 1: below L17 → no Death Strike.
    bm2, engine2, atk2, tgt2 = _setup(13, rpg.RogueSubclass.Assassin)
    r2 = _sneak_hit(engine2, bm2, atk2, tgt2, [], round_num=0)
    assert _breakdown_value(r2, "Death Strike (doubled)") is None, "Death Strike needs L17"
    print("✅ test_death_strike_only_round1_and_l17 passed")


if __name__ == "__main__":
    test_assassinate_initiative_advantage()
    test_no_initiative_advantage_below_l3()
    test_assassinate_advantage_vs_not_acted()
    test_no_assassinate_advantage_when_target_acted()
    test_not_acted_advantage_only_for_assassin()
    test_assassinate_round1_bonus_damage()
    test_assassinate_no_bonus_after_round1()
    test_assassinate_bonus_requires_assassin()
    test_envenom_free_poison_die()
    test_envenom_not_for_non_assassin_or_below_l13()
    test_envenom_ignores_poison_resistance()
    test_envenom_respects_poison_immunity()
    test_death_strike_doubles_round1()
    test_death_strike_save_success_no_double()
    test_death_strike_only_round1_and_l17()
    print("\n✅ All Assassin subclass tests passed")
