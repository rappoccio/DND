#!/usr/bin/env python3
"""
Test suite for the Roper's Reel — the data-driven on-hit "Pull" weapon condition.

The Roper's Tentacle grapples (escape DC 14) + poisons, and Reel pulls the
grappled target up to 30 ft toward the Roper. Reel is modeled as a "Pull"
on-hit weapon condition: the mirror of "Push", reusing BattleMap.force_move_agent
with pull=True. See known_limitations.md "Roper Reel" for the combat-sim
simplification (the reel is folded into the on-hit rider, not a separate
grapple-gated action).
"""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _tentacle():
    """A Roper-style Tentacle: long reach, no damage, grapples + reels 30 ft."""
    w = rpg.Weapon()
    w.name = "Tentacle"
    w.type = rpg.WeaponType.Melee
    w.proficient = True          # the Pull/Push rider only fires for a proficient weapon
    w.off_hand = True
    w.reach_ft = 60
    w.range_short_feet = 80
    w.range_long_feet = 320
    w.bonus_hit = 50          # guaranteed hit for a deterministic test
    w.bonus_damage = 0

    grapple = rpg.AttackCondition()
    grapple.condition_name = "Grappled"
    grapple.contested = False    # automatic on a hit
    grapple.escape_dc = 14

    pull = rpg.AttackCondition()
    pull.condition_name = "Pull"
    pull.push_ft = 30            # reel 30 ft toward the Roper

    w.conditions = [grapple, pull]
    return [w, rpg.Weapon(), rpg.Weapon()]


def _soft_target(engine, bm, idx):
    """A low-AC, low-save dummy so the tentacle reliably connects."""
    s = engine.get_agent_stats(bm, idx)
    s.str = 8
    s.dex = 8
    s.con = 10
    s.hp_max = 100
    s.hp_cur = 100
    s.base_ac = 10
    engine.set_agent_stats(bm, idx, s)


def test_roper_tentacle_grapples_and_pulls():
    """A tentacle hit grapples the target (escape DC 14) AND reels it 30 ft inward."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Roper at col 2, target 40 ft (8 cells) east at col 10, same row.
    roper = add_agent_to_battle(engine, bm, create_test_agent("Roper", 2, 5), str=18)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 10, 5))
    _soft_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, roper, _tentacle())

    assert bm.placed_agents[tgt].origin.col == 10, "precondition: target starts at col 10"

    res = engine.execute_action(bm, rpg.Attack(roper, tgt, 0))
    assert res.hit, "the long-reach tentacle should land at 40 ft"

    # Grappled rider (automatic on hit) with the fixed escape DC.
    tcond = engine.get_agent_conditions(bm, tgt)
    assert tcond.grappled, "tentacle hit should grapple the target"
    assert tcond.grappler_idx == roper, "grappler index should be the Roper"
    assert tcond.grapple_escape_dc == 14, f"escape DC should be 14, got {tcond.grapple_escape_dc}"

    # Reel: pulled 30 ft (6 cells) TOWARD the Roper (col 10 → col 4), no overshoot
    # since it stops 10 ft short of the Roper.
    assert res.push_ft_applied == 30, f"reel should move the target 30 ft, got {res.push_ft_applied}"
    assert bm.placed_agents[tgt].origin.col == 4, \
        f"reeled target should end 6 cells closer at col 4, got col {bm.placed_agents[tgt].origin.col}"
    print("✅ test_roper_tentacle_grapples_and_pulls passed")


def test_pull_reels_toward_not_away():
    """Sanity vs Push: 'Pull' moves the target TOWARD the attacker, the opposite of a shove."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    roper = add_agent_to_battle(engine, bm, create_test_agent("Roper", 2, 5), str=18)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 8, 5))
    _soft_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, roper, _tentacle())

    start_col = bm.placed_agents[tgt].origin.col
    res = engine.execute_action(bm, rpg.Attack(roper, tgt, 0))
    assert res.hit
    end_col = bm.placed_agents[tgt].origin.col
    assert end_col < start_col, \
        f"Pull must reel the target closer to the Roper (col {start_col} → {end_col})"
    print("✅ test_pull_reels_toward_not_away passed")


def test_pull_stops_adjacent_not_past_puller():
    """A pull that would overshoot stops adjacent to the puller — never onto or past it.

    Target 20 ft (4 cells) east of the Roper, reeled 30 ft (6 cells). Without the
    footprint clamp the fixed-direction pull would slide the target straight through
    the Roper and out the far (west) side. It must instead halt directly east-adjacent.
    """
    bm = setup_battle_map()
    engine = setup_combat_engine()

    roper = add_agent_to_battle(engine, bm, create_test_agent("Roper", 3, 5), str=18)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 7, 5))
    _soft_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, roper, _tentacle())

    res = engine.execute_action(bm, rpg.Attack(roper, tgt, 0))
    assert res.hit
    end_col = bm.placed_agents[tgt].origin.col
    # Roper at col 3; the target stops one cell east at col 4 (adjacent), not at/past col 3.
    assert end_col == 4, f"pull should stop adjacent (col 4), got col {end_col}"
    assert end_col > bm.placed_agents[roper].origin.col, "target must not be pulled past the Roper"
    assert res.push_ft_applied == 15, f"only 3 cells (15 ft) of the 30-ft reel should apply, got {res.push_ft_applied}"
    print("✅ test_pull_stops_adjacent_not_past_puller passed")


def test_pull_stops_adjacent_to_large_puller():
    """The clamp respects a Large (2×2) puller's footprint, not just its origin cell."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Large Roper occupying cols 2-3 (origin col 2, size 2), target 5 cells east at col 7.
    big = create_test_agent("Roper", 2, 5)
    big.size = 2
    roper = add_agent_to_battle(engine, bm, big, str=18)
    assert bm.placed_agents[roper].size == 2, "precondition: Roper should be Large (size 2)"
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 7, 5))
    _soft_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, roper, _tentacle())

    res = engine.execute_action(bm, rpg.Attack(roper, tgt, 0))
    assert res.hit
    end_col = bm.placed_agents[tgt].origin.col
    # The Roper's east edge is col 3, so the target halts adjacent at col 4 — never inside cols 2-3.
    assert end_col == 4, f"pull should stop adjacent to the 2×2 footprint (col 4), got col {end_col}"
    print("✅ test_pull_stops_adjacent_to_large_puller passed")


def test_pull_no_corner_cut_around_large_puller():
    """A DIAGONAL reel onto a Large (2×2) puller must stop adjacent — not slide around the corner.

    This is the live-play bug: the target is almost never on the same row as the Roper's top-left
    origin, so the reel runs on a diagonal. With only a "don't step onto the body" guard, a diagonal
    pull cuts the corner of the 2×2 footprint — every cell stays footprint-distance 1 while crossing
    from the south/east side clear past to the west side ("flying past" the Roper). The reel must
    instead end the instant it is adjacent.

    Large Roper origin (2,5) → occupies cols 2-3, rows 5-6. Target south-east at (5,10), reeled 30 ft.
    """
    bm = setup_battle_map()
    engine = setup_combat_engine()

    big = create_test_agent("Roper", 2, 5)
    big.size = 2
    roper = add_agent_to_battle(engine, bm, big, str=18)
    assert bm.placed_agents[roper].size == 2, "precondition: Roper should be Large (size 2)"
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 5, 10))
    _soft_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, roper, _tentacle())

    res = engine.execute_action(bm, rpg.Attack(roper, tgt, 0))
    assert res.hit

    end = bm.placed_agents[tgt].origin
    roper_origin = bm.placed_agents[roper].origin

    # Must end ADJACENT (footprint gap of exactly 1 cell), never overlapping or on the far side.
    gap = rpg.footprint_distance(end, 1, roper_origin, 2)
    assert gap == 1, f"reel must end adjacent to the 2×2 puller (gap 1 cell), got gap {gap} at ({end.col},{end.row})"
    # And specifically must NOT have crossed to the west of the Roper's footprint (cols 2-3).
    assert end.col >= 2, f"target flew PAST the Roper to the west (col {end.col}); the reel should stop on contact"
    print("✅ test_pull_no_corner_cut_around_large_puller passed")


def test_pull_straight_in_aligned_with_footprint():
    """A victim aligned with a footprint row pulls STRAIGHT in — no drift toward the origin corner.

    Direction was computed against the Large puller's top-left origin cell, so a victim level with
    the BOTTOM row of a 2×2 Roper got reeled diagonally up to the origin corner instead of straight
    across. Direction is now computed against the whole footprint span: an axis the victim already
    shares with the footprint contributes 0, so it reels in along one line.

    Large Roper origin (2,5) → occupies cols 2-3, rows 5-6. Victim due east at (8,6), level with the
    footprint's bottom row (row 6). It must reel straight west along row 6 to the east-adjacent cell.
    """
    bm = setup_battle_map()
    engine = setup_combat_engine()

    big = create_test_agent("Roper", 2, 5)
    big.size = 2
    roper = add_agent_to_battle(engine, bm, big, str=18)
    assert bm.placed_agents[roper].size == 2, "precondition: Roper should be Large (size 2)"
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 8, 6))
    _soft_target(engine, bm, tgt)
    engine.set_agent_weapons(bm, roper, _tentacle())

    res = engine.execute_action(bm, rpg.Attack(roper, tgt, 0))
    assert res.hit

    end = bm.placed_agents[tgt].origin
    assert end.row == 6, f"victim must reel straight along row 6, not drift to the origin corner (got row {end.row})"
    assert end.col == 4, f"victim should stop east-adjacent at col 4, got col {end.col}"
    print("✅ test_pull_straight_in_aligned_with_footprint passed")


def test_roper_json_carries_pull_rider():
    """Guard the data: the shipped Roper record must wire Grappled + Poisoned + Pull(30)."""
    stats_path = os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"), "DND2024_MonsterStats.json")
    with open(stats_path) as f:
        data = json.load(f)

    tentacle = data["Roper"]["weapons"]["off_hand"]
    conds = {c["condition_name"]: c for c in tentacle["conditions"]}
    assert "Grappled" in conds, "Roper tentacle should still grapple"
    assert conds["Grappled"].get("escape_dc") == 14, "grapple escape DC should be 14"
    assert "Poisoned" in conds, "Roper tentacle should still poison"
    assert "Pull" in conds, "Roper tentacle should carry the Reel ('Pull') rider"
    assert conds["Pull"].get("push_ft") == 30, "Reel should pull 30 ft"
    print("✅ test_roper_json_carries_pull_rider passed")


if __name__ == "__main__":
    test_roper_tentacle_grapples_and_pulls()
    test_pull_reels_toward_not_away()
    test_pull_stops_adjacent_not_past_puller()
    test_pull_stops_adjacent_to_large_puller()
    test_pull_no_corner_cut_around_large_puller()
    test_pull_straight_in_aligned_with_footprint()
    test_roper_json_carries_pull_rider()
    print("\nAll Roper tests passed ✅")
