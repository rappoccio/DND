#!/usr/bin/env python3
"""
Epic Boon tests — Phase E2 (SRD 5.2 p.88). See EPIC_BOONS_PLAN.md.

  · Boon of Combat Prowess (Peerless Aim) — turn a missed attack into a hit, once until the
      start of your next turn. NPCs auto-fire on their first missed weapon attack of the turn
      (maybePeerlessAim); PCs get the deferred peerless_aim_available prompt and convert via
      apply_peerless_aim_effect.
  · Boon of Dimensional Travel (Blink Steps) — a free ≤30-ft teleport armed after the Attack/Magic
      action (blink_steps_available). The teleport itself reuses the existing teleport primitives
      (teleport_agent / is_valid_teleport_destination / has_line_of_sight), driven from the GUI;
      the engine side is just the arming flag + its turn-start reset.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine
from test_feats import _place, _target


# ─────────────────────────────────────────────────────────────────────────────
#  helpers
# ─────────────────────────────────────────────────────────────────────────────

def _flat_weapon(total=10):
    """A melee weapon with NO to-hit bonus (so it misses a high-AC wall) dealing `total` Slashing
    deterministically (`total` dice of d1)."""
    w = rpg.Weapon()
    w.name = "Blade"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.proficient = True
    w.bonus_hit = 0
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = total
    pr.die_size = 1
    w.physical_damage_types = [pr]
    return w


def _missing_attacker(engine, bm, idx, is_npc):
    """A Combat-Prowess boon-holder whose weapons never land on their own (bonus_hit 0 vs a wall of
    AC), so a Peerless-Aim promotion is the only way the attack can hit."""
    s = engine.get_agent_stats(bm, idx)
    s.str = 10; s.dex = 10; s.prof_bonus = 2
    s.hp_max = 80; s.hp_cur = 80
    s.is_npc = is_npc
    s.feats = ["Boon of Combat Prowess"]
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [_flat_weapon(), _flat_weapon(), _flat_weapon()])


def _reset_peerless(engine, bm, idx):
    c = engine.get_agent_conditions(bm, idx)
    c.peerless_aim_used = False
    c.peerless_aim_available = False
    engine.set_agent_conditions(bm, idx, c)


# ─────────────────────────────────────────────────────────────────────────────
#  Boon of Combat Prowess — Peerless Aim (NPC auto-fire)
# ─────────────────────────────────────────────────────────────────────────────

def test_peerless_aim_npc_autofires_on_miss():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Warlord", 5, 5)
    t = _place(engine, bm, "Wall", 6, 5)
    _missing_attacker(engine, bm, a, is_npc=True)
    _target(engine, bm, t, hp=1_000_000, ac=40)       # unreachable AC → raw rolls always miss

    for _ in range(300):
        _reset_peerless(engine, bm, a)
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if r.d20 == 20:
            continue                                   # a natural 20 hits on its own — not a promotion
        assert r.hit, "an NPC boon-holder's raw miss auto-promotes to a hit (Peerless Aim)"
        assert r.total_damage == 10, f"the promoted hit rolls normal (non-crit) damage, got {r.total_damage}"
        assert engine.get_agent_conditions(bm, a).peerless_aim_used, \
            "the once-per-turn Peerless Aim flag is committed after the auto-fire"
        print("✅ test_peerless_aim_npc_autofires_on_miss passed")
        return
    raise AssertionError("never rolled a raw miss to promote")


def test_peerless_aim_once_per_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Warlord", 5, 5)
    t = _place(engine, bm, "Wall", 6, 5)
    _missing_attacker(engine, bm, a, is_npc=True)
    _target(engine, bm, t, hp=1_000_000, ac=40)
    _reset_peerless(engine, bm, a)

    # Burn the once-per-turn use on the first raw miss.
    for _ in range(300):
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if r.d20 != 20 and r.hit:
            break
    else:
        raise AssertionError("never promoted a first miss")
    assert engine.get_agent_conditions(bm, a).peerless_aim_used

    # A subsequent raw miss this turn must NOT be promoted.
    for _ in range(300):
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if r.d20 != 20:
            assert not r.hit, "the second raw miss of the turn is not promoted (once per turn)"
            print("✅ test_peerless_aim_once_per_turn passed")
            return
    raise AssertionError("never rolled a second raw miss")


def test_peerless_aim_resets_at_turn_start():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Warlord", 5, 5)
    c = engine.get_agent_conditions(bm, a)
    c.peerless_aim_used = True
    engine.set_agent_conditions(bm, a, c)
    engine.begin_turn(bm, a)
    assert not engine.get_agent_conditions(bm, a).peerless_aim_used, \
        "Peerless Aim's once-per-turn use resets at the start of the holder's turn"
    print("✅ test_peerless_aim_resets_at_turn_start passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Boon of Combat Prowess — Peerless Aim (PC deferred prompt)
# ─────────────────────────────────────────────────────────────────────────────

def test_peerless_aim_pc_deferred_then_apply():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Fencer", 5, 5)
    t = _place(engine, bm, "Wall", 6, 5)
    _missing_attacker(engine, bm, a, is_npc=False)     # PC — no auto-fire
    _target(engine, bm, t, hp=1_000_000, ac=40)

    for _ in range(300):
        _reset_peerless(engine, bm, a)
        action = rpg.Attack(a, t, 0)
        r = engine.execute_action(bm, action)
        if r.d20 == 20 or r.hit:
            continue                                   # need a genuine miss left un-promoted
        assert engine.get_agent_conditions(bm, a).peerless_aim_available, \
            "a PC boon-holder's miss arms the deferred Peerless Aim prompt (no auto-fire)"
        hp_before = engine.get_agent_stats(bm, t).hp_cur
        engine.apply_peerless_aim_effect(bm, action, r)
        assert r.hit, "apply_peerless_aim_effect turns the miss into a hit"
        assert engine.get_agent_stats(bm, t).hp_cur == hp_before - 10, "the promoted hit deals its damage"
        c = engine.get_agent_conditions(bm, a)
        assert c.peerless_aim_used and not c.peerless_aim_available, \
            "applying Peerless Aim consumes the use and clears the deferred flag"
        print("✅ test_peerless_aim_pc_deferred_then_apply passed")
        return
    raise AssertionError("never left a PC miss un-promoted")


# ─────────────────────────────────────────────────────────────────────────────
#  Boon of Dimensional Travel — Blink Steps (engine side: arming flag + reuse)
# ─────────────────────────────────────────────────────────────────────────────

def test_blink_steps_flag_resets_at_turn_start():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Blinker", 5, 5)
    c = engine.get_agent_conditions(bm, a)
    c.blink_steps_available = True
    engine.set_agent_conditions(bm, a, c)
    assert engine.get_agent_conditions(bm, a).blink_steps_available
    engine.begin_turn(bm, a)
    assert not engine.get_agent_conditions(bm, a).blink_steps_available, \
        "the Blink Steps arming clears at the start of the holder's turn"
    print("✅ test_blink_steps_flag_resets_at_turn_start passed")


def test_blink_steps_reuses_teleport_primitives():
    """Blink Steps has no bespoke engine path: it composes teleport_agent + is_valid_teleport_
    destination (the exact primitives the GUI's _resolve_blink_steps calls). Exercise them directly."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Blinker", 5, 5)
    dest_col, dest_row = 9, 5                           # 20 ft away (4 cells)
    assert engine.is_valid_teleport_destination(bm, dest_col, dest_row), "open destination is valid"
    assert engine.teleport_agent(bm, a, dest_col, dest_row), "teleport_agent moves the actor"
    o = bm.placed_agents[a].origin
    assert (o.col, o.row) == (dest_col, dest_row), "the actor now stands on the Blink Steps destination"
    print("✅ test_blink_steps_reuses_teleport_primitives passed")


def main():
    print("Running Epic Boon (E2 — Combat Prowess + Dimensional Travel) tests...\n")
    test_peerless_aim_npc_autofires_on_miss()
    test_peerless_aim_once_per_turn()
    test_peerless_aim_resets_at_turn_start()
    test_peerless_aim_pc_deferred_then_apply()
    test_blink_steps_flag_resets_at_turn_start()
    test_blink_steps_reuses_teleport_primitives()
    print("\n" + "=" * 60)
    print("✅ All Epic Boon (E2) tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
