#!/usr/bin/env python3
"""
Test suite for the Pit Fiend (PIT_FIEND_PLAN.md).

Covers the engine features the rebuild added, all of which are generic and reusable:

  · Damage-over-time / no-heal condition rider (AttackCondition/ActiveAgentCondition
    dot_dice/dot_die_size/dot_damage_type + prevents_healing): the Pit Fiend's Bite
    poison deals 6d6 Poison at the start of each turn and blocks all HP regain while
    it lasts. Ticked in beginTurn (like Burning); healAgent + Regeneration honor it.
  · Magic Resistance (Stats.magic_resistance): Advantage on saving throws against
    spells / magical effects — wired into rollSpellSave.
  · The shipped bestiary record + the two new spells (Fear Aura emanation, Hellfire).
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
import helpers
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

_GUI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")
_STATS_JSON = os.path.join(_GUI, "DND2024_MonsterStats.json")
_SPELLS_JSON = os.path.join(_GUI, "spells.json")


def _poison_dot_condition(tgt, dice=6, die=6, prevents_healing=True):
    """A Pit-Fiend-style Poisoned condition carrying a 6d6 Poison DoT that also blocks healing.
    save_dc set impossibly high so the target never shrugs it off during the test."""
    c = rpg.ActiveAgentCondition()
    c.agent_idx = tgt
    c.condition_name = "Poisoned"
    c.turns_remaining = 99
    c.save_ability = rpg.SaveAbility.SaveCon
    c.save_dc = 999               # never saved during the test
    c.save_repeat_turns = 1
    c.dot_dice = dice
    c.dot_die_size = die
    c.dot_damage_type = rpg.MagicDamage.Poison
    c.prevents_healing = prevents_healing
    return c


# ─────────────────────────────────────────────────────────────────────────────
#  Binding sanity
# ─────────────────────────────────────────────────────────────────────────────

def test_dot_fields_bound():
    """The new DoT/no-heal fields round-trip on both condition structs and on Stats."""
    ac = rpg.AttackCondition()
    assert ac.dot_dice == 0 and ac.dot_die_size == 0 and ac.dot_flat_bonus == 0
    assert ac.prevents_healing is False
    ac.dot_dice = 6; ac.dot_die_size = 6; ac.dot_damage_type = rpg.MagicDamage.Poison
    ac.prevents_healing = True
    assert ac.dot_dice == 6 and ac.prevents_healing is True

    live = rpg.ActiveAgentCondition()
    assert live.dot_dice == 0 and live.prevents_healing is False
    live.dot_flat_bonus = 3
    assert live.dot_flat_bonus == 3

    s = rpg.Stats()
    assert s.magic_resistance is False
    s.magic_resistance = True
    assert s.magic_resistance is True
    print("✅ test_dot_fields_bound passed")


# ─────────────────────────────────────────────────────────────────────────────
#  DoT tick + no-heal
# ─────────────────────────────────────────────────────────────────────────────

def test_dot_ticks_poison_each_turn():
    """A DoT condition deals its 6d6 Poison at the start of the affected creature's turn."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 5, 5), con=10, hp=100)

    engine.add_agent_condition(bm, _poison_dot_condition(tgt))
    assert engine.get_agent_conditions(bm, tgt).poisoned, "should also carry the ordinary Poisoned flag"

    engine.begin_turn(bm, tgt)
    hp = engine.get_agent_stats(bm, tgt).hp_cur
    assert 100 - 36 <= hp <= 100 - 6, f"6d6 Poison should knock off 6..36 HP, got {100 - hp}"
    print(f"✅ test_dot_ticks_poison_each_turn passed (took {100 - hp} poison)")


def test_dot_blocks_healing_and_regen():
    """prevents_healing stops healAgent AND Regeneration; clearing the condition restores healing."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 5, 5), con=10, hp=100)

    # Wound it, add regeneration, then poison it.
    s = engine.get_agent_stats(bm, tgt)
    s.hp_cur = 50
    s.regeneration_amount = 10
    engine.set_agent_stats(bm, tgt, s)

    cond_id = engine.add_agent_condition(bm, _poison_dot_condition(tgt))
    assert engine.get_agent_stats(bm, tgt).cant_heal, "prevents_healing must set the derived cant_heal flag"

    # healAgent is a no-op while poisoned.
    before = engine.get_agent_stats(bm, tgt).hp_cur
    rpg.CombatEngine.heal_agent(bm, tgt, 40)
    assert engine.get_agent_stats(bm, tgt).hp_cur == before, "healAgent must not raise HP while cant_heal"

    # A turn ticks the DoT but Regeneration is blocked → HP only ever goes DOWN.
    hp_start = engine.get_agent_stats(bm, tgt).hp_cur
    engine.begin_turn(bm, tgt)
    hp_after = engine.get_agent_stats(bm, tgt).hp_cur
    assert hp_after < hp_start, f"regen must not fire while poisoned (start {hp_start}, after {hp_after})"

    # End the poison → cant_heal clears and healing works again.
    engine.remove_agent_condition(bm, cond_id)
    assert not engine.get_agent_stats(bm, tgt).cant_heal, "cant_heal must clear when the last poison ends"
    low = engine.get_agent_stats(bm, tgt).hp_cur
    rpg.CombatEngine.heal_agent(bm, tgt, 25)
    assert engine.get_agent_stats(bm, tgt).hp_cur == low + 25, "healAgent works again after the poison ends"
    print("✅ test_dot_blocks_healing_and_regen passed")


def test_two_poisons_keep_no_heal_until_both_end():
    """cant_heal stays set while ANY prevents_healing condition remains (recompute on teardown)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 5, 5), con=10, hp=100)

    id1 = engine.add_agent_condition(bm, _poison_dot_condition(tgt))
    id2 = engine.add_agent_condition(bm, _poison_dot_condition(tgt))
    assert engine.get_agent_stats(bm, tgt).cant_heal

    engine.remove_agent_condition(bm, id1)
    assert engine.get_agent_stats(bm, tgt).cant_heal, "one poison remains → still can't heal"

    engine.remove_agent_condition(bm, id2)
    assert not engine.get_agent_stats(bm, tgt).cant_heal, "both poisons gone → healing restored"
    print("✅ test_two_poisons_keep_no_heal_until_both_end passed")


# ─────────────────────────────────────────────────────────────────────────────
#  End-to-end: the Bite weapon rider carries the DoT
# ─────────────────────────────────────────────────────────────────────────────

def _pit_fiend_bite():
    """Build the shipped Pit Fiend Bite from the bestiary, forced to hit for a deterministic test."""
    data = json.load(open(_STATS_JSON))
    bite = helpers._dict_to_weapon(data["Pit Fiend"]["weapons"][0])
    bite.bonus_hit = 50   # guaranteed hit
    return [bite, rpg.Weapon(), rpg.Weapon()]


def test_bite_applies_poison_dot_rider():
    """A Bite hit against a feeble-CON target applies the Poisoned+DoT+no-heal rider."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    pf = add_agent_to_battle(engine, bm, create_test_agent("Pit Fiend", 5, 5), con=24)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 6, 5), con=1, hp=200, ac=10)

    # DC = 8 + prof + attacker CON mod = 8 + 6 + 7 = 21; target CON 1 can never reach it.
    s = engine.get_agent_stats(bm, pf); s.prof_bonus = 6; engine.set_agent_stats(bm, pf, s)
    engine.set_agent_weapons(bm, pf, _pit_fiend_bite())

    res = engine.execute_action(bm, rpg.Attack(pf, tgt, 0))
    assert res.hit, "the forced Bite should land"

    poisons = [c for c in engine.active_agent_conditions
               if c.agent_idx == tgt and c.condition_name == "Poisoned"]
    assert poisons, "Bite should apply a Poisoned condition on a failed CON save"
    p = poisons[0]
    assert p.dot_dice == 6 and p.dot_die_size == 6, f"poison DoT should be 6d6, got {p.dot_dice}d{p.dot_die_size}"
    assert p.dot_damage_type == rpg.MagicDamage.Poison
    assert p.prevents_healing is True, "the Bite poison must block healing"
    assert engine.get_agent_stats(bm, tgt).cant_heal, "cant_heal set from the applied rider"
    print("✅ test_bite_applies_poison_dot_rider passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Magic Resistance
# ─────────────────────────────────────────────────────────────────────────────

def _load_spell(name):
    d = next(s for s in json.load(open(_SPELLS_JSON)) if s["name"] == name)
    return helpers._dict_to_spell(d)


def test_magic_resistance_grants_save_advantage():
    """A creature with Magic Resistance rolls saving throws vs spells at Advantage (logged)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    logger = rpg.MessageLogger()
    engine.set_logger(logger)

    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Fiend", 6, 5), wis=14, hp=200)

    cs = engine.get_agent_stats(bm, caster)
    cs.spellcasting_ability = 5   # CHA
    cs.prof_bonus = 4
    cs.spell_slots_remaining = [9, 9, 9, 9, 9, 9, 9, 9, 9]
    engine.set_agent_stats(bm, caster, cs)

    ts = engine.get_agent_stats(bm, tgt)
    ts.magic_resistance = True
    engine.set_agent_stats(bm, tgt, ts)

    engine.set_agent_spells(bm, caster, [_load_spell("Hold Monster")])
    logger.flush()
    act = rpg.SpellAction()
    act.caster_idx = caster
    act.spell_idx = 0
    act.target_indices = [tgt]
    engine.execute_spell(bm, act)

    msgs = logger.flush()
    assert any("Magic Resistance" in m for m in msgs), \
        f"expected a Magic Resistance advantage line, got: {msgs}"
    print("✅ test_magic_resistance_grants_save_advantage passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Shipped data guards
# ─────────────────────────────────────────────────────────────────────────────

def test_pit_fiend_json_wiring():
    """Guard the shipped Pit Fiend record: weapons, multiattack, MR, poison rider, spells."""
    pf = json.load(open(_STATS_JSON))["Pit Fiend"]
    st = pf["stats"]

    assert st["magic_resistance"] is True
    assert st["is_fiend"] is True
    assert st["spellcasting_ability"] == "cha"
    # 1 Bite (slot 0), 2 Devilish Claw (slot 1), 1 Fiery Mace (slot 2).
    assert st["multiattack"] == [[0, 1], [1, 2], [2, 1]], f"bad multiattack: {st['multiattack']}"

    names = [w["name"] for w in pf["weapons"]]
    assert names == ["Bite", "Devilish Claw", "Fiery Mace"], names

    bite = pf["weapons"][0]
    assert (bite["physical_damage_types"][0]["num_dice"],
            bite["physical_damage_types"][0]["die_size"]) == (3, 6)
    # bonus_damage is 0: the "+8" in "3d6+8" is the STR modifier the engine adds automatically
    # (damage_mod = ability_mod + bonus_damage). Setting it to 8 would double-count STR → +16.
    assert bite["bonus_damage"] == 0
    pc = bite["conditions"][0]
    assert pc["condition_name"] == "Poisoned"
    assert pc["dot_dice"] == 6 and pc["dot_die_size"] == 6 and pc["dot_damage_type"] == "Poison"
    assert pc["prevents_healing"] is True
    assert pc["save_ability"] == "SaveCon"

    claw = pf["weapons"][1]["magic_damage_types"][0]
    assert (claw["type"], claw["num_dice"], claw["die_size"]) == ("Necrotic", 4, 8)

    mace = {d["type"]: (d["num_dice"], d["die_size"]) for d in pf["weapons"][2]["magic_damage_types"]}
    assert mace["Force"] == (4, 6) and mace["Fire"] == (6, 6), mace

    assert pf["spell_indices"] == ["PitFiendFearAura", "Hellfire"]
    assert pf["npc_spell_groups"]["99"] == ["PitFiendFearAura"]  # persistent aura
    assert pf["npc_spell_groups"]["1"] == ["Hellfire"]           # recharge action (uses_max 1)
    print("✅ test_pit_fiend_json_wiring passed")


def test_new_spells_defined():
    """The Fear Aura emanation and the Hellfire recharge spell are present + well-formed."""
    catalog = {s["name"]: s for s in json.load(open(_SPELLS_JSON))}

    aura = catalog["PitFiendFearAura"]
    assert aura["geometry"] == "Sphere" and aura["moves_with_caster"] is True
    assert aura["radius"] == 20 and aura["duration"] == 99
    fr = aura["conditions"][0]
    assert fr["condition_name"] == "Frightened" and fr["save_dc_ability"] == "SaveSpellcasterMod"

    hell = catalog["Hellfire"]
    assert hell["recharge_min"] == 5, "Hellfire is Recharge 5-6"
    dmg = hell["magic_damage_types"][0]
    assert (dmg["type"], dmg["num_dice"], dmg["die_size"]) == ("Fire", 12, 6), "Fireball @ 7th level = 12d6"
    print("✅ test_new_spells_defined passed")


if __name__ == "__main__":
    test_dot_fields_bound()
    test_dot_ticks_poison_each_turn()
    test_dot_blocks_healing_and_regen()
    test_two_poisons_keep_no_heal_until_both_end()
    test_bite_applies_poison_dot_rider()
    test_magic_resistance_grants_save_advantage()
    test_pit_fiend_json_wiring()
    test_new_spells_defined()
    print("\nAll Pit Fiend tests passed ✅")
