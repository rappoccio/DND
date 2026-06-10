#!/usr/bin/env python3
"""
Origin feat tests (2024 PHB): the combat-relevant feats wired into the C++ engine.

Covered: feat storage (feats / has_feat / add_feat), Tough (HP), Alert (initiative
proficiency + Initiative Swap), Lucky (Luck Points + Advantage), Savage Attacker
(damage reroll, once/turn), Tavern Brawler (Enhanced Unarmed Strike + Push).

Out-of-combat feats (Crafter, Skilled, Musician) and deferred benefits (Healer's
Battle Medic, Magic Initiate spell-grant, Lucky's reaction-Disadvantage) are tracked
in known_limitations.md, not here.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _place(engine, bm, name, col, row):
    return add_agent_to_battle(engine, bm, create_test_agent(name, col, row))


def _mk_weapon(name, die=8, attack_bonus=50, with_dice=True):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.proficient = True
    w.bonus_hit = attack_bonus      # real to-hit bonus: high so the attack lands vs AC 10
    if with_dice:
        pr = rpg.PhysicalDamageRoll()
        pr.type = rpg.PhysicalDamage.Slashing
        pr.num_dice = 1
        pr.die_size = die
        w.physical_damage_types = [pr]
    return w


def _three(weapons):
    weapons = list(weapons)
    while len(weapons) < 3:
        weapons.append(_mk_weapon("Filler"))
    return weapons[:3]


def _arm(engine, bm, idx, weapons, feats=None, strv=14, prof=2, level=1):
    s = engine.get_agent_stats(bm, idx)
    s.str = strv
    s.dex = 10
    s.prof_bonus = prof
    s.char_level = level
    s.hp_max = 80
    s.hp_cur = 80
    for f in (feats or []):
        s.add_feat(f)
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, _three(weapons))


def _target(engine, bm, idx, hp=400, ac=10):
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = hp
    s.hp_cur = hp
    s.base_ac = ac
    engine.set_agent_stats(bm, idx, s)


def _land_hit(engine, bm, a, t, weapon_idx=0, tries=30):
    for _ in range(tries):
        r = engine.execute_action(bm, rpg.Attack(a, t, weapon_idx))
        if r.hit:
            return r
    raise AssertionError("attack never landed")


def _land_noncrit_hit(engine, bm, a, t, weapon_idx=0, tries=60):
    """Land a hit that is not a critical (so doubled dice don't widen the damage range)."""
    for _ in range(tries):
        r = engine.execute_action(bm, rpg.Attack(a, t, weapon_idx))
        if r.hit and not r.critical:
            return r
    raise AssertionError("no non-crit hit landed")


def _reset_turn_flags(engine, bm, idx):
    """Clear the once-per-turn feat flags so a loop can exercise repeated triggers."""
    c = engine.get_agent_conditions(bm, idx)
    c.savage_attacker_used_this_turn = False
    c.tavern_brawler_push_used_this_turn = False
    engine.set_agent_conditions(bm, idx, c)


# ─────────────────────────────────────────────────────────────────────────────
#  Feat storage
# ─────────────────────────────────────────────────────────────────────────────

def test_feat_storage():
    s = rpg.Stats()
    assert not s.has_feat("Tough")
    assert list(s.feats) == []
    s.add_feat("Tough")
    assert s.has_feat("Tough")
    assert "Tough" in list(s.feats)
    # Idempotent: adding twice does not duplicate.
    s.add_feat("Tough")
    assert list(s.feats).count("Tough") == 1
    print("✅ test_feat_storage passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Tough
# ─────────────────────────────────────────────────────────────────────────────

def test_tough_hp():
    s = rpg.Stats()
    s.char_level = 5
    s.hp_max = 40
    s.hp_cur = 40
    s.add_feat("Tough")        # +2 HP per level = +10 at level 5
    assert s.hp_max == 50, f"expected hp_max 50, got {s.hp_max}"
    assert s.hp_cur == 50, f"expected hp_cur 50, got {s.hp_cur}"
    print("✅ test_tough_hp passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Alert
# ─────────────────────────────────────────────────────────────────────────────

def test_alert_initiative_prof():
    s = rpg.Stats()
    s.dex = 14          # +2
    s.prof_bonus = 3
    assert s.initiative_modifier == 2, "without Alert: DEX mod only"
    s.add_feat("Alert")
    assert s.initiative_prof
    assert s.initiative_modifier == 5, "with Alert: DEX mod + prof_bonus"
    print("✅ test_alert_initiative_prof passed")


def test_alert_initiative_swap():
    engine = setup_combat_engine()
    # Synthesize an order: agent 0 high, agent 1 low.
    e0 = rpg.InitiativeEntry(); e0.agent_idx = 0; e0.d20 = 18; e0.modifier = 2; e0.total = 20
    e1 = rpg.InitiativeEntry(); e1.agent_idx = 1; e1.d20 = 3;  e1.modifier = 1; e1.total = 4
    order = engine.swap_initiative([e0, e1], 0, 1)
    # After the swap, agent 1 holds the high total and leads the order.
    assert order[0].agent_idx == 1, "swapped: agent 1 should now act first"
    assert order[0].total == 20
    assert order[1].agent_idx == 0
    assert order[1].total == 4
    print("✅ test_alert_initiative_swap passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Lucky
# ─────────────────────────────────────────────────────────────────────────────

def test_lucky_points_init_and_refill():
    s = rpg.Stats()
    s.prof_bonus = 3
    s.add_feat("Lucky")
    assert s.luck_points == 3 and s.luck_points_max == 3
    s.luck_points = 0
    s.restore_resources_long_rest()
    assert s.luck_points == 3, "Long Rest restores Luck Points to max"
    print("✅ test_lucky_points_init_and_refill passed")


def test_lucky_spend_grants_advantage():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Lucky", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_mk_weapon("Sword")], feats=["Lucky"], prof=2)
    _target(engine, bm, t)

    s = engine.get_agent_stats(bm, a)
    assert s.luck_points == 2, "Luck Points = prof bonus (2)"

    assert engine.spend_luck_for_advantage(bm, a) is True
    assert engine.get_agent_stats(bm, a).luck_points == 1, "spending a point decrements"

    # The next attack roll should carry Advantage (consumed from the pending grant).
    r = engine.execute_action(bm, rpg.Attack(a, t, 0))
    assert r.advantage, "the d20 after spending a Luck Point has Advantage"

    # Exhaust the pool and confirm spend fails.
    engine.spend_luck_for_advantage(bm, a)
    assert engine.get_agent_stats(bm, a).luck_points == 0
    assert engine.spend_luck_for_advantage(bm, a) is False, "no points → cannot spend"
    print("✅ test_lucky_spend_grants_advantage passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Savage Attacker
# ─────────────────────────────────────────────────────────────────────────────

def test_savage_attacker_flag_once_per_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Savage", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_mk_weapon("Sword")], feats=["Savage Attacker"])
    _target(engine, bm, t)

    assert not engine.get_agent_conditions(bm, a).savage_attacker_used_this_turn
    _land_hit(engine, bm, a, t)
    assert engine.get_agent_conditions(bm, a).savage_attacker_used_this_turn, \
        "Savage Attacker marks itself used after a hit"

    # A second attack the same turn does not reset the flag (once per turn).
    engine.execute_action(bm, rpg.Attack(a, t, 0))
    assert engine.get_agent_conditions(bm, a).savage_attacker_used_this_turn
    print("✅ test_savage_attacker_flag_once_per_turn passed")


def test_savage_attacker_raises_average_damage():
    # Statistical: rerolling and keeping the higher roll lifts the mean weapon damage.
    N = 200
    def mean_damage(feats):
        bm = setup_battle_map(); engine = setup_combat_engine()
        a = _place(engine, bm, "A", 5, 5)
        t = _place(engine, bm, "T", 6, 5)
        _arm(engine, bm, a, [_mk_weapon("Greataxe", die=12)], feats=feats, strv=10)
        _target(engine, bm, t)
        total = 0
        for _ in range(N):
            _reset_turn_flags(engine, bm, a)
            r = engine.execute_action(bm, rpg.Attack(a, t, 0))
            total += r.total_damage
        return total / N

    plain = mean_damage([])
    savage = mean_damage(["Savage Attacker"])
    assert savage > plain + 0.5, f"Savage Attacker mean {savage:.2f} should beat plain {plain:.2f}"
    print(f"✅ test_savage_attacker_raises_average_damage passed (plain={plain:.2f}, savage={savage:.2f})")


# ─────────────────────────────────────────────────────────────────────────────
#  Tavern Brawler
# ─────────────────────────────────────────────────────────────────────────────

def test_tavern_brawler_enhanced_unarmed():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Brawler", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    # Bare "Unarmed" weapon (no damage dice) → STR mod only without the feat.
    unarmed = _mk_weapon("Unarmed", with_dice=False)
    _arm(engine, bm, a, [unarmed], feats=["Tavern Brawler"], strv=14)  # STR +2
    _target(engine, bm, t)

    r = _land_noncrit_hit(engine, bm, a, t)
    # Enhanced Unarmed Strike: 1d4 (min 1) + STR mod (2) → at least 3, at most 6.
    assert 3 <= r.total_damage <= 6, f"expected 1d4+2 in [3,6], got {r.total_damage}"
    assert rpg.PhysicalDamage.Bludgeoning in list(r.physical_damage_types), \
        "Enhanced Unarmed Strike deals Bludgeoning"
    print("✅ test_tavern_brawler_enhanced_unarmed passed")


def test_unarmed_without_feat_is_str_only():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Plain", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_mk_weapon("Unarmed", with_dice=False)], feats=[], strv=14)
    _target(engine, bm, t)
    r = _land_hit(engine, bm, a, t)   # no dice → crit-safe, but skip nat-1 misses
    assert r.total_damage == 2, f"bare unarmed = STR mod (2) without the feat, got {r.total_damage}"
    print("✅ test_unarmed_without_feat_is_str_only passed")


def test_tavern_brawler_push():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Brawler", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)   # directly east of the attacker
    _arm(engine, bm, a, [_mk_weapon("Unarmed", with_dice=False)], feats=["Tavern Brawler"])
    _target(engine, bm, t)

    _land_hit(engine, bm, a, t)
    moved_col = bm.placed_agents[t].origin.col
    assert moved_col == 7, f"target pushed 5 ft east from col 6 to 7, got {moved_col}"
    assert engine.get_agent_conditions(bm, a).tavern_brawler_push_used_this_turn
    print("✅ test_tavern_brawler_push passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Save/load round-trip
# ─────────────────────────────────────────────────────────────────────────────

def test_feats_round_trip_fields():
    s = rpg.Stats()
    s.prof_bonus = 4
    s.char_level = 8
    s.hp_max = 60
    s.hp_cur = 60
    s.add_feat("Tough")
    s.add_feat("Lucky")
    # Simulate a reload: a fresh Stats restoring the list directly (no re-apply).
    s2 = rpg.Stats()
    s2.feats = list(s.feats)
    s2.luck_points = s.luck_points
    s2.luck_points_max = s.luck_points_max
    s2.hp_max = s.hp_max
    assert s2.has_feat("Tough") and s2.has_feat("Lucky")
    assert s2.luck_points == 4 and s2.luck_points_max == 4
    assert s2.hp_max == 76, "Tough HP (60 + 2*8) is persisted, not re-applied on load"
    print("✅ test_feats_round_trip_fields passed")


# ─────────────────────────────────────────────────────────────────────────────
#  GUI feat picker — _set_origin_feat strip/apply idempotency
# ─────────────────────────────────────────────────────────────────────────────

def test_gui_set_origin_feat_idempotent():
    import os as _os
    _os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    _os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from main import App   # headless import (dummy SDL)

    s = rpg.Stats()
    s.char_level = 5
    s.prof_bonus = 3
    s.hp_max = 40
    s.hp_cur = 40

    # NONE → Tough: +2*level HP.
    App._set_origin_feat(s, "Tough", 5)
    assert s.has_feat("Tough") and s.hp_max == 50 and s.hp_cur == 50

    # Re-confirming the same feat must NOT double-apply (mirrors clicking OK again).
    App._set_origin_feat(s, "Tough", 5)
    assert s.hp_max == 50, "re-confirming Tough must not stack HP"

    # Tough → Lucky: strip the +10 HP, grant Luck Points.
    App._set_origin_feat(s, "Lucky", 5)
    assert not s.has_feat("Tough") and s.hp_max == 40, "Tough HP stripped on swap"
    assert s.has_feat("Lucky") and s.luck_points == 3 and s.luck_points_max == 3

    # Lucky → Alert: clear Luck Points, set initiative proficiency.
    App._set_origin_feat(s, "Alert", 5)
    assert not s.has_feat("Lucky") and s.luck_points_max == 0
    assert s.has_feat("Alert") and s.initiative_prof

    # Alert → NONE: clear the feat and its initiative proficiency.
    App._set_origin_feat(s, "NONE", 5)
    assert not s.has_feat("Alert") and not s.initiative_prof
    assert not any(f in App._ORIGIN_FEATS for f in list(s.feats))
    print("✅ test_gui_set_origin_feat_idempotent passed")


def main():
    print("Running Origin feat tests...\n")
    test_feat_storage()
    test_tough_hp()
    test_alert_initiative_prof()
    test_alert_initiative_swap()
    test_lucky_points_init_and_refill()
    test_lucky_spend_grants_advantage()
    test_savage_attacker_flag_once_per_turn()
    test_savage_attacker_raises_average_damage()
    test_tavern_brawler_enhanced_unarmed()
    test_unarmed_without_feat_is_str_only()
    test_tavern_brawler_push()
    test_feats_round_trip_fields()
    test_gui_set_origin_feat_idempotent()
    print("\n" + "=" * 60)
    print("✅ All Origin feat tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
