#!/usr/bin/env python3
"""
Test suite for the NPC-turn visual event stream (NPC turn playback).

While run_npc_turn drives an automated turn, the engine records rpg.NpcVisualEvent entries —
Move (the route actually walked), Announce (action text), Outcome (Hit/Miss/Saved/Failed flash
text + hp_after/died for the animation-synced HP bar) — which the GUI drains via
combat.take_npc_visual_events() and replays as an animation. These tests drive the recorder
headlessly: order, path integrity, drain semantics, and the recording gate (player-driven flows
never record).
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle, create_melee_weapon)

MOVE, ANNOUNCE, OUTCOME = 0, 1, 2   # NpcVisualEvent.Kind values


def _arm_melee(engine, bm, idx):
    weapons = [create_melee_weapon(), rpg.Weapon(), rpg.Weapon()]
    engine.set_agent_weapons(bm, idx, weapons)


def _automate(bm, idx, strategy=None):
    bm.set_agent_npc_automated(idx, True)
    if strategy is not None:
        bm.set_agent_npc_automation_strategy(idx, strategy)


def _save_aoe_cantrip(radius_ft=5, range_ft=60):
    """A Sphere Harm cantrip resolved by a DEX save, so an AoE cast records Saved/Failed
    outcomes for every creature in its area."""
    s = rpg.Spell()
    s.name = "Test Savey Blast"
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Sphere
    s.attack_type = rpg.SpellAttack.Save
    s.save_ability = rpg.SaveAbility.Dexterity
    s.range = range_ft
    s.radius = radius_ft
    s.level = 0
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Fire
    roll.num_dice = 2
    roll.die_size = 6
    s.magic_damage_rolls = [roll]
    return s


# ── Drain semantics ──────────────────────────────────────────────────────────
def test_drain_starts_empty_and_clears():
    """take_npc_visual_events starts empty, and draining twice yields an empty list."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    assert engine.take_npc_visual_events() == [], "no turn ran → no events"
    print("✅ test_drain_starts_empty_and_clears passed")


# ── Move + Announce + Outcome from a Simple melee turn ───────────────────────
def test_melee_turn_records_move_announce_outcome():
    """An automated melee NPC two cells from an enemy records, in order: a Move whose path runs
    from its old origin to its new one, an Announce naming the weapon, and one Outcome per swing
    anchored on the target with hp_after matching the target's real HP."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 8, 5), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, npc)
    _automate(bm, npc)

    old_origin = (bm.placed_agents[npc].origin.col, bm.placed_agents[npc].origin.row)
    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)
    assert status == rpg.FlowStatus.Completed

    events = engine.take_npc_visual_events()
    assert events, "an automated turn that moved and attacked must record events"
    kinds = [e.kind for e in events]

    # Move: recorded, path is the actual route old-origin → new-origin, contiguous steps.
    assert MOVE in kinds, f"expected a Move event, kinds={kinds}"
    mv = events[kinds.index(MOVE)]
    assert mv.agent_idx == npc
    path = mv.path
    assert len(path) >= 2
    assert (path[0].col, path[0].row) == old_origin, "path starts at the pre-turn origin"
    new_origin = (bm.placed_agents[npc].origin.col, bm.placed_agents[npc].origin.row)
    assert (path[-1].col, path[-1].row) == new_origin, "path ends where the NPC now stands"
    for a, b in zip(path, path[1:]):
        assert max(abs(a.col - b.col), abs(a.row - b.row)) == 1, "path cells are adjacent steps"

    # Announce: names attacker, target and weapon; comes after the Move and before its Outcome.
    ann = [e for e in events if e.kind == ANNOUNCE]
    assert ann, "the attack must be announced"
    assert "Longsword" in ann[0].text and "Goblin" in ann[0].text and "Hero" in ann[0].text, ann[0].text
    assert ann[0].agent_idx == npc and ann[0].target_idx == foe

    # Outcome: anchored on the target; hp_after matches the live post-turn HP; Hit→green / Miss→red
    # (the GUI's established FLASH_GOOD/FLASH_BAD convention).
    outs = [e for e in events if e.kind == OUTCOME]
    assert outs, "each swing records an outcome"
    last = outs[-1]
    assert last.agent_idx == foe
    assert last.hp_after == engine.get_agent_stats(bm, foe).hp_cur
    assert (last.text != "Miss") == last.good, f"good iff Hit: {last.text}/{last.good}"
    if last.text != "Miss":
        assert last.text.startswith("Hit ("), last.text

    # Order: the Move plays before the Announce, which plays before the Outcome.
    assert kinds.index(MOVE) < kinds.index(ANNOUNCE) < kinds.index(OUTCOME)

    assert engine.take_npc_visual_events() == [], "drain is move-out-and-clear"
    print("✅ test_melee_turn_records_move_announce_outcome passed")


# ── Save outcomes from an AoE cast ───────────────────────────────────────────
def test_aoe_save_records_saved_or_failed():
    """A PreferAOE cast on a cluster announces the spell and records a Saved/Failed outcome
    (flash-only: hp_after == -1, the HP bar catches up at playback end) for each creature."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Mage", 1, 1))
    a   = add_agent_to_battle(engine, bm, create_test_agent("FoeA", 6, 5), hp=30)
    b   = add_agent_to_battle(engine, bm, create_test_agent("FoeB", 6, 6), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(a, 2)
    bm.set_agent_faction(b, 2)
    engine.set_agent_spells(bm, npc, [_save_aoe_cantrip()])
    _automate(bm, npc, rpg.NpcAutomationStrategy.PreferAOE)

    engine.begin_turn(bm, npc)
    status = engine.run_npc_turn(bm, npc)
    assert status == rpg.FlowStatus.Completed

    events = engine.take_npc_visual_events()
    ann = [e for e in events if e.kind == ANNOUNCE]
    assert ann and "Test Savey Blast" in ann[0].text, "the cast must be announced"

    outs = [e for e in events if e.kind == OUTCOME]
    hit_targets = {e.agent_idx for e in outs}
    assert {a, b} <= hit_targets, f"both foes save vs the blast: {hit_targets}"
    for e in outs:
        assert e.text in ("Saved", "Failed"), e.text
        assert e.good == (e.text == "Saved")
        assert e.hp_after == -1, "save outcomes are flash-only (damage applies later in the pipeline)"
    print("✅ test_aoe_save_records_saved_or_failed passed")


# ── Recording gate: player-driven flows never record ─────────────────────────
def test_player_attack_records_nothing():
    """begin_attack outside run_npc_turn (a player-driven swing) records no events — the stream
    only runs while an automated turn is in flight."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Hero", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 6, 5), hp=20)
    bm.set_agent_faction(atk, 2)
    bm.set_agent_faction(foe, 1)
    _arm_melee(engine, bm, atk)

    engine.begin_turn(bm, atk)
    attack = rpg.Attack(atk, foe, 0)
    attack.attack_slot = "action"
    status = engine.begin_attack(bm, attack)
    assert status == rpg.FlowStatus.Completed
    assert engine.take_npc_visual_events() == [], "player swings must not record playback events"
    print("✅ test_player_attack_records_nothing passed")


# ── A fresh turn clears the previous turn's undrained events (headless cap) ──
def test_fresh_turn_clears_undrained_events():
    """Headless callers never drain; the next fresh run_npc_turn drops the stale events so the
    buffer stays bounded to one turn."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 7, 5), hp=200)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    _arm_melee(engine, bm, npc)
    _automate(bm, npc)

    engine.begin_turn(bm, npc)
    assert engine.run_npc_turn(bm, npc) == rpg.FlowStatus.Completed
    # NOT drained. Turn 1 moved into reach (1 Move) and swung once (1 Announce). Turn 2 starts
    # adjacent: 0 Moves, 1 Announce. Stale turn-1 events would double both counts.
    engine.begin_turn(bm, npc)
    assert engine.run_npc_turn(bm, npc) == rpg.FlowStatus.Completed
    events = engine.take_npc_visual_events()
    moves     = [e for e in events if e.kind == MOVE]
    announces = [e for e in events if e.kind == ANNOUNCE]
    assert len(moves) == 0, f"turn 1's Move must have been cleared, got {len(moves)}"
    assert len(announces) == 1, f"only turn 2's attack announce should remain, got {len(announces)}"
    print("✅ test_fresh_turn_clears_undrained_events passed")


# ── record_moves (M4b B-2): human moves record a Move too, only when switched on ──
def _ready_walker(engine, bm, idx, walk=60):
    """A walk budget on both sides of the split: the engine's turn and the Agent's own
    (BattleMap::moveAgent reads the latter, which begin_turn does not seed)."""
    s = engine.get_agent_stats(bm, idx)
    s.speed_walk = walk
    engine.set_agent_stats(bm, idx, s)
    engine.begin_turn(bm, idx)
    bm.placed_agents[idx].init_movement(walk, 0, 0, 0)


def _origin(bm, idx):
    o = bm.placed_agents[idx].origin
    return (o.col, o.row)


def _cells(path):
    return [(c.col, c.row) for c in path]


def test_record_moves_is_off_by_default():
    """RL and headless callers never set it, so a player-driven walk records nothing."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Hero", 5, 5))
    assert engine.record_moves is False, "record_moves must default to off"
    _ready_walker(engine, bm, m)
    status = engine.begin_move(bm, m, rpg.Cell(8, 5), rpg.MovementType.Walk)
    assert status == rpg.FlowStatus.Completed
    assert _origin(bm, m) == (8, 5)
    assert engine.take_npc_visual_events() == [], "a human move recorded with the switch off"
    print("✅ test_record_moves_is_off_by_default passed")


def test_record_moves_records_a_human_walk():
    """With the switch on, a player-driven begin_move records one Move, origin to dest."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Hero", 5, 5))
    engine.record_moves = True
    assert engine.record_moves is True
    _ready_walker(engine, bm, m)
    status = engine.begin_move(bm, m, rpg.Cell(8, 5), rpg.MovementType.Walk)
    assert status == rpg.FlowStatus.Completed
    events = engine.take_npc_visual_events()
    assert [e.kind for e in events] == [MOVE], f"expected one Move, got {[e.kind for e in events]}"
    path = _cells(events[0].path)
    assert events[0].agent_idx == m
    assert path[0] == (5, 5) and path[-1] == (8, 5), f"path {path} is not origin..dest"
    assert engine.take_npc_visual_events() == [], "the drain must clear the buffer"
    print("✅ test_record_moves_records_a_human_walk passed")


def test_record_moves_records_an_oa_parked_walk_on_resume():
    """A walk that provokes parks BEFORE it moves: advanceMove resolves every Opportunity
    Attack first and then commits the whole route once. So the park records nothing, and
    the resume records one Move from the origin to the destination."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    m = add_agent_to_battle(engine, bm, create_test_agent("Mover", 5, 5))
    a = add_agent_to_battle(engine, bm, create_test_agent("Threat", 4, 5))
    bm.set_agent_faction(m, 2)
    bm.set_agent_faction(a, 1)
    _arm_melee(engine, bm, a)
    engine.record_moves = True
    _ready_walker(engine, bm, m)

    status = engine.begin_move(bm, m, rpg.Cell(8, 5), rpg.MovementType.Walk)
    assert status == rpg.FlowStatus.AwaitingDecision, f"expected an OA park, got {status}"
    assert engine.take_npc_visual_events() == [], "the park moved nothing, so recorded nothing"
    resp = rpg.ReactionResponse()
    resp.option = -1   # skip the OA; the walk resumes
    status = engine.submit_decision(bm, resp)
    assert status == rpg.FlowStatus.Completed
    assert _origin(bm, m) == (8, 5)

    events = engine.take_npc_visual_events()
    assert [e.kind for e in events] == [MOVE], f"expected one Move, got {[e.kind for e in events]}"
    path = _cells(events[0].path)
    assert events[0].agent_idx == m
    assert path[0] == (5, 5) and path[-1] == (8, 5), f"path {path} is not origin..dest"
    print("✅ test_record_moves_records_an_oa_parked_walk_on_resume passed")


def test_record_moves_records_only_moves():
    """The switch is for routes. A player's swing still records no Announce or Outcome; the
    GUI's own flashes carry those (B-2)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Hero", 5, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 6, 5), hp=20)
    bm.set_agent_faction(atk, 2)
    bm.set_agent_faction(foe, 1)
    _arm_melee(engine, bm, atk)
    engine.record_moves = True
    engine.begin_turn(bm, atk)
    attack = rpg.Attack(atk, foe, 0)
    attack.attack_slot = "action"
    assert engine.begin_attack(bm, attack) == rpg.FlowStatus.Completed
    assert engine.take_npc_visual_events() == [], "record_moves leaked into the attack recorders"
    print("✅ test_record_moves_records_only_moves passed")


if __name__ == "__main__":
    test_drain_starts_empty_and_clears()
    test_melee_turn_records_move_announce_outcome()
    test_aoe_save_records_saved_or_failed()
    test_player_attack_records_nothing()
    test_fresh_turn_clears_undrained_events()
    test_record_moves_is_off_by_default()
    test_record_moves_records_a_human_walk()
    test_record_moves_records_an_oa_parked_walk_on_resume()
    test_record_moves_records_only_moves()
    print("\nAll NPC visual event tests passed! 🎉")
