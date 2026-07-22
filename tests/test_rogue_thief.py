#!/usr/bin/env python3
"""
Test Rogue — Thief subclass (2024).

Covered engine-side features:
  · Second-Story Work (L3): Climber — Climb Speed equal to your Speed.
  · Supreme Sneak (L9): Stealth Attack — a Cunning Strike option (effect 6) that spends 1 Sneak
    Attack die so the strike doesn't end your Hide (modeled as restoring Invisible after the hit).
    Gated Thief-only, L9+, and only when this attack came from stealth
    (Conditions.attacked_while_invisible, set when an attack ends Invisibility).

Thief's Reflexes (L17) is pure GUI initiative manipulation (no engine call) — not covered here;
it is verified manually in-app (see known_limitations.md / Rogue).

Fast Hands (L3) is deferred — it needs the Doors & locking / object-interaction infra (TODO.md).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle
from test_rogue_phase2 import _finesse_weapon, _three, _breakdown_value, _high_ac_target


def _rogue_sub(engine, bm, idx, level, subclass, dex=20):
    """Configure agent idx as a Rogue of the given level + subclass."""
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
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), ac=1, hp=500)
    _rogue_sub(engine, bm, atk, level, subclass)
    if high_ac_target:
        _high_ac_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, atk, _three(_finesse_weapon()))
    return bm, engine, atk, tgt


def _sneak_hit(engine, bm, atk, tgt, effects, from_stealth=False):
    """Land an attack (optionally from Invisibility) then apply Sneak Attack + riders out of band."""
    for _ in range(60):
        c = engine.get_agent_conditions(bm, atk)
        c.has_advantage = True
        if from_stealth:
            c.invisible = True
        engine.set_agent_conditions(bm, atk, c)
        result = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
        if result.hit:
            break
    else:
        raise AssertionError("attack never landed in 60 tries")
    cond = engine.get_agent_conditions(bm, atk)
    assert cond.cunning_strike_available, "a qualifying Rogue hit should flag cunning_strike_available"
    if from_stealth:
        assert cond.attacked_while_invisible, "attacking from Invisibility should set the gate flag"
        assert not cond.invisible, "Invisibility ends on the attack (before Stealth Attack can restore it)"
    engine.apply_cunning_strike_effect(bm, atk, tgt, effects, result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Second-Story Work (L3): Climber
# ─────────────────────────────────────────────────────────────────────────────

def test_second_story_work_climb_speed():
    bm, engine, atk, _ = _setup(3, rpg.RogueSubclass.Thief)
    s = engine.get_agent_stats(bm, atk)
    assert s.speed_climb == s.speed_walk, \
        f"Thief L3 should have Climb Speed == Walk Speed, got {s.speed_climb} vs {s.speed_walk}"
    assert s.speed_climb > 0
    print("✅ test_second_story_work_climb_speed passed")


def test_no_climb_speed_before_l3_or_other_subclass():
    # Non-Thief Rogue: no climb speed.
    bm, engine, atk, _ = _setup(9, rpg.RogueSubclass.Assassin)
    assert engine.get_agent_stats(bm, atk).speed_climb == 0, "Assassin should not gain Climb Speed"
    # Thief below L3: no climb speed.
    bm2, engine2, atk2, _ = _setup(2, rpg.RogueSubclass.Thief)
    assert engine2.get_agent_stats(bm2, atk2).speed_climb == 0, "Thief below L3 → no Climb Speed"
    print("✅ test_no_climb_speed_before_l3_or_other_subclass passed")


# ─────────────────────────────────────────────────────────────────────────────
# Supreme Sneak (L9): Stealth Attack
# ─────────────────────────────────────────────────────────────────────────────

def test_stealth_attack_keeps_hidden():
    bm, engine, atk, tgt = _setup(9, rpg.RogueSubclass.Thief)
    result = _sneak_hit(engine, bm, atk, tgt, [6], from_stealth=True)

    # 5d6 at L9, minus 1 die cost = 4d6 (4..24).
    sneak_val = _breakdown_value(result, "sneak attack")
    assert sneak_val is not None, "Sneak Attack should be applied"
    assert 4 <= sneak_val <= 24, f"L9 Stealth Attack (4d6) should be 4..24, got {sneak_val}"
    assert engine.get_agent_conditions(bm, atk).invisible, \
        "Stealth Attack should keep the Thief hidden (Invisible restored) after the strike"
    print("✅ test_stealth_attack_keeps_hidden passed")


def test_stealth_attack_rejected_when_not_from_stealth():
    bm, engine, atk, tgt = _setup(9, rpg.RogueSubclass.Thief)
    result = _sneak_hit(engine, bm, atk, tgt, [6], from_stealth=False)

    # Not from stealth → effect rejected → full 5d6 (5..30), no invisibility.
    sneak_val = _breakdown_value(result, "sneak attack")
    assert 5 <= sneak_val <= 30, f"rejected Stealth Attack → full 5d6, got {sneak_val}"
    assert not engine.get_agent_conditions(bm, atk).invisible, \
        "Stealth Attack must not grant Invisibility when not attacking from stealth"
    print("✅ test_stealth_attack_rejected_when_not_from_stealth passed")


def test_stealth_attack_rejected_for_non_thief():
    # Assassin (also has Sneak Attack) attacking from stealth must NOT get Stealth Attack.
    bm, engine, atk, tgt = _setup(9, rpg.RogueSubclass.Assassin)
    result = _sneak_hit(engine, bm, atk, tgt, [6], from_stealth=True)

    sneak_val = _breakdown_value(result, "sneak attack")
    assert 5 <= sneak_val <= 30, f"non-Thief Stealth Attack rejected → full 5d6, got {sneak_val}"
    assert not engine.get_agent_conditions(bm, atk).invisible, \
        "non-Thief must not stay hidden via Stealth Attack"
    print("✅ test_stealth_attack_rejected_for_non_thief passed")


def test_stealth_attack_rejected_below_l9():
    bm, engine, atk, tgt = _setup(5, rpg.RogueSubclass.Thief)
    result = _sneak_hit(engine, bm, atk, tgt, [6], from_stealth=True)

    # Below L9 → rejected → full 3d6 (3..18).
    sneak_val = _breakdown_value(result, "sneak attack")
    assert 3 <= sneak_val <= 18, f"Stealth Attack below L9 rejected → full 3d6, got {sneak_val}"
    assert not engine.get_agent_conditions(bm, atk).invisible
    print("✅ test_stealth_attack_rejected_below_l9 passed")


if __name__ == "__main__":
    test_second_story_work_climb_speed()
    test_no_climb_speed_before_l3_or_other_subclass()
    test_stealth_attack_keeps_hidden()
    test_stealth_attack_rejected_when_not_from_stealth()
    test_stealth_attack_rejected_for_non_thief()
    test_stealth_attack_rejected_below_l9()
    print("\n✅ All Thief subclass tests passed")
