#!/usr/bin/env python3
"""
Test suite for the Balor's two-weapon rework (BALOR_IMPLEMENTATION_PLAN.md Parts A + C).

  · Flame Whip (main_hand, reach 30): 3d6 Force + 5d6 Fire (+8), automatically
    Pulls the target 25 ft inward AND knocks it Prone with NO save (Part C's
    auto-Prone weapon condition).
  · Lightning Blade (off_hand, reach 10): 3d8 Force + 4d10 Lightning (+8), the
    target's reactions are denied until the balor's next turn (Part B).

These exercise the generic on-hit weapon-condition path (requires_save:false →
addAgentCondition), so the same behavior is available to any future monster.
"""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _flame_whip():
    """Balor Flame Whip: guaranteed-hit build; Pull 25 ft + automatic Prone (no save)."""
    w = rpg.Weapon()
    w.name = "Flame Whip"
    w.type = rpg.WeaponType.Melee
    w.proficient = True          # the Pull rider only fires for a proficient weapon
    w.reach_ft = 30
    w.bonus_hit = 50             # guaranteed hit for a deterministic test
    w.bonus_damage = 8

    pull = rpg.AttackCondition()
    pull.condition_name = "Pull"
    pull.push_ft = 25

    prone = rpg.AttackCondition()
    prone.condition_name = "Prone"
    prone.requires_save = False   # automatic — the crux of Part C

    w.conditions = [pull, prone]
    return [w, rpg.Weapon(), rpg.Weapon()]


def _lightning_blade():
    """Balor Lightning Blade: guaranteed-hit build; DenyReactions (no save) for 1 caster-turn."""
    w = rpg.Weapon()
    w.name = "Lightning Blade"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.off_hand = True
    w.reach_ft = 10
    w.bonus_hit = 50
    w.bonus_damage = 8

    deny = rpg.AttackCondition()
    deny.condition_name = "DenyReactions"
    deny.requires_save = False
    deny.condition_duration = 1
    deny.save_repeat_turns = -1   # else beginTurn's non-incap save loop strips it (HasteLethargy gotcha)

    w.conditions = [deny]
    return [w, rpg.Weapon(), rpg.Weapon()]


def _tough_saver(engine, bm, idx):
    """A high-DEX, high-HP target: it would trivially PASS any DEX save, proving the
    Prone/DenyReactions riders are automatic rather than save-gated."""
    s = engine.get_agent_stats(bm, idx)
    s.str = 20
    s.dex = 20                 # +5 DEX; a real save would nearly always succeed
    s.con = 20
    s.hp_max = 200
    s.hp_cur = 200
    s.base_ac = 10             # low AC so the (already guaranteed) attack lands
    engine.set_agent_stats(bm, idx, s)


def test_flame_whip_auto_prones_no_save():
    """A Flame Whip hit leaves an evasive (DEX 20) target Prone — proving no save is rolled."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    balor = add_agent_to_battle(engine, bm, create_test_agent("Balor", 2, 5), str=26)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 8, 5))
    _tough_saver(engine, bm, tgt)
    engine.set_agent_weapons(bm, balor, _flame_whip())

    res = engine.execute_action(bm, rpg.Attack(balor, tgt, 0))
    assert res.hit, "the reach-30 Flame Whip should land"

    tcond = engine.get_agent_conditions(bm, tgt)
    assert tcond.prone, "Flame Whip must knock the target Prone automatically (no save)"
    print("✅ test_flame_whip_auto_prones_no_save passed")


def test_flame_whip_pulls_and_prones_together():
    """Flame Whip reels the target 25 ft inward and knocks it Prone on the same hit."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # Balor at col 2, target 30 ft (6 cells) east at col 8.
    balor = add_agent_to_battle(engine, bm, create_test_agent("Balor", 2, 5), str=26)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 8, 5))
    _tough_saver(engine, bm, tgt)
    engine.set_agent_weapons(bm, balor, _flame_whip())

    start_col = bm.placed_agents[tgt].origin.col
    res = engine.execute_action(bm, rpg.Attack(balor, tgt, 0))
    assert res.hit

    end_col = bm.placed_agents[tgt].origin.col
    assert end_col < start_col, f"Pull should reel the target toward the balor ({start_col}→{end_col})"
    assert res.push_ft_applied == 25, f"Flame Whip should pull 25 ft, got {res.push_ft_applied}"
    assert engine.get_agent_conditions(bm, tgt).prone, "target should also be Prone"
    print("✅ test_flame_whip_pulls_and_prones_together passed")


def test_lightning_blade_denies_reactions():
    """A Lightning Blade hit denies the target its reactions (no save)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    balor = add_agent_to_battle(engine, bm, create_test_agent("Balor", 4, 5), str=26)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 6, 5))
    _tough_saver(engine, bm, tgt)
    engine.set_agent_weapons(bm, balor, _lightning_blade())

    res = engine.execute_action(bm, rpg.Attack(balor, tgt, 0))
    assert res.hit, "the reach-10 Lightning Blade should land"

    tcond = engine.get_agent_conditions(bm, tgt)
    assert tcond.reactions_denied, "Lightning Blade must deny the target's reactions"
    print("✅ test_lightning_blade_denies_reactions passed")


def test_balor_json_wires_both_attacks():
    """Guard the shipped Balor record: Flame Whip + Lightning Blade with their riders."""
    stats_path = os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"), "DND2024_MonsterStats.json")
    with open(stats_path) as f:
        data = json.load(f)

    balor = data["Balor"]
    mh = balor["weapons"]["main_hand"]
    oh = balor["weapons"]["off_hand"]

    # Flame Whip: Force 3d6 first (the +8 rides it), then Fire 5d6.
    assert mh["name"] == "Flame Whip"
    assert mh["reach_ft"] == 30
    assert mh["bonus_damage"] == 8
    dmg = [(d["type"], d["num_dice"], d["die_size"]) for d in mh["magic_damage_types"]]
    assert dmg == [("Force", 3, 6), ("Fire", 5, 6)], f"Flame Whip damage order wrong: {dmg}"
    mh_conds = {c["condition_name"]: c for c in mh["conditions"]}
    assert mh_conds["Pull"]["push_ft"] == 25
    assert mh_conds["Prone"]["requires_save"] is False

    # Lightning Blade: Force 3d8 first, then Lightning 4d10; DenyReactions rider.
    assert oh["name"] == "Lightning Blade"
    assert oh["reach_ft"] == 10
    assert oh["bonus_damage"] == 8
    assert oh.get("off_hand") is True
    odmg = [(d["type"], d["num_dice"], d["die_size"]) for d in oh["magic_damage_types"]]
    assert odmg == [("Force", 3, 8), ("Lightning", 4, 10)], f"Lightning Blade damage order wrong: {odmg}"
    oh_conds = {c["condition_name"]: c for c in oh["conditions"]}
    assert "DenyReactions" in oh_conds
    assert oh_conds["DenyReactions"]["requires_save"] is False
    assert oh_conds["DenyReactions"]["condition_duration"] == 1
    assert oh_conds["DenyReactions"]["save_repeat_turns"] == -1

    # Multiattack stays locked to one of each (slot 0 ×1 then slot 1 ×1).
    assert balor["stats"]["multiattack"] == [[0, 1], [1, 1]], "Balor multiattack must be 1 Flame Whip + 1 Lightning Blade"
    print("✅ test_balor_json_wires_both_attacks passed")


if __name__ == "__main__":
    test_flame_whip_auto_prones_no_save()
    test_flame_whip_pulls_and_prones_together()
    test_lightning_blade_denies_reactions()
    test_balor_json_wires_both_attacks()
    print("\nAll Balor attack tests passed ✅")
