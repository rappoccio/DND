#!/usr/bin/env python3
"""
Test suite for Legendary Resistance + the Legendary Action data plumbing.

Legendary Resistance reuses the OnSaveFail reaction window (like Indomitable) but, instead of a
reroll, adds +99 to the failed save so it auto-succeeds, and spends one per-day use. It is used on
the creature's OWN save and does NOT cost a reaction.

The Legendary Action *interface* (turn-end offer menu, attack/Dash resolution) lives in the pygame
GUI (main.py) and isn't unit-tested here; what we cover engine-side is the per-round budget reset at
turn start, the out-of-turn movement-budget seeder, and that the bestiary loader populates the
fields.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)
from agent_loader import dict_to_stats


class LegendaryResistDecider(rpg.CombatDecider):
    """At an OnSaveFail window, pick the LegendaryResistance option if offered; else Skip."""
    def __init__(self):
        super().__init__()
        self.offers = 0
        self.offered_legendary = 0
    def choose_reaction(self, ctx):
        resp = rpg.ReactionResponse(); resp.option = -1
        if ctx.window == rpg.ReactionWindow.OnSaveFail:
            self.offers += 1
            for i, o in enumerate(ctx.options):
                if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "LegendaryResistance":
                    self.offered_legendary += 1
                    resp.option = i
                    break
        return resp


def _cause_fear():
    sp = rpg.Spell(); sp.name = "Cause Fear"; sp.level = 1
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = rpg.SaveAbility.SaveWis
    sp.geometry = rpg.SpellGeometry.Single
    c = rpg.AttackCondition()
    c.condition_name = "Frightened"; c.requires_save = True
    c.save_ability = rpg.SaveAbility.SaveWis; c.condition_duration = 10
    sp.conditions = [c]
    return sp


def _make_caster(engine, bm, idx, spell):
    s = engine.get_agent_stats(bm, idx)
    s.cha = 18; s.prof_bonus = 3; s.spellcasting_ability = 5
    s.spell_slots_remaining = [9, 0, 0, 0, 0, 0, 0, 0, 0]
    s.hp_max = 40; s.hp_cur = 40
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_spells(bm, idx, [spell])


def _make_legendary_target(engine, bm, idx, resist=3, wis=10):
    """A weak-save target (fails often) that has Legendary Resistance uses."""
    s = engine.get_agent_stats(bm, idx)
    s.wis = wis; s.save_prof_wis = False; s.prof_bonus = 2
    s.hp_max = 100; s.hp_cur = 100
    s.legendary_resistance_max = resist
    s.legendary_resistance_current = resist
    engine.set_agent_stats(bm, idx, s)


def _clear(engine, bm, idx):
    c = engine.get_agent_conditions(bm, idx)
    c.frightened = False; c.charmed = False; c.reaction_used = False; c.incapacitated = False
    engine.set_agent_conditions(bm, idx, c)


def _cast(caster, tgt):
    a = rpg.SpellAction(); a.caster_idx = caster; a.spell_idx = 0; a.target_indices = [tgt]
    return a


# ── Legendary Resistance (OnSaveFail) ──────────────────────────────────────────
def test_legendary_resistance_flips_failed_save():
    """When the target fails the save, choosing Legendary Resistance flips it to a success (no
    Frightened) and spends exactly one per-day use — without costing a reaction."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    tgt    = add_agent_to_battle(engine, bm, create_test_agent("Dragon", 6, 5))
    _make_caster(engine, bm, caster, _cause_fear())
    _make_legendary_target(engine, bm, tgt, resist=3)
    dec = LegendaryResistDecider(); engine.set_decider(dec)

    saw_flip = False
    for _ in range(400):
        _clear(engine, bm, tgt)
        # Refill the per-day uses + caster slots each iteration so each cast is independent.
        s = engine.get_agent_stats(bm, tgt); s.legendary_resistance_current = 3
        engine.set_agent_stats(bm, tgt, s)
        cs = engine.get_agent_stats(bm, caster); cs.spell_slots_remaining = [9,0,0,0,0,0,0,0,0]
        engine.set_agent_stats(bm, caster, cs)
        before = dec.offered_legendary
        res = engine.resolve_cast(bm, _cast(caster, tgt))
        if dec.offered_legendary > before:                 # the window opened AND offered LR
            saved = res.target_results[0].saved
            frightened = engine.get_agent_conditions(bm, tgt).frightened
            cur = engine.get_agent_stats(bm, tgt).legendary_resistance_current
            assert saved, "Legendary Resistance must turn the failed save into a success"
            assert not frightened, "a succeeded save applies no Frightened"
            assert cur == 2, f"exactly one LR use spent (3 -> 2), got {cur}"
            # Legendary Resistance is NOT a reaction.
            assert not engine.get_agent_conditions(bm, tgt).reaction_used, \
                "Legendary Resistance does not cost a reaction"
            saw_flip = True
            break
    assert saw_flip, "never observed a failed save offered Legendary Resistance in 400 casts"
    print("✅ test_legendary_resistance_flips_failed_save passed")


def test_legendary_resistance_not_offered_when_exhausted():
    """With 0 uses left, the OnSaveFail window must not offer Legendary Resistance."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    tgt    = add_agent_to_battle(engine, bm, create_test_agent("Dragon", 6, 5))
    _make_caster(engine, bm, caster, _cause_fear())
    _make_legendary_target(engine, bm, tgt, resist=0)      # exhausted
    dec = LegendaryResistDecider(); engine.set_decider(dec)

    for _ in range(200):
        _clear(engine, bm, tgt)
        cs = engine.get_agent_stats(bm, caster); cs.spell_slots_remaining = [9,0,0,0,0,0,0,0,0]
        engine.set_agent_stats(bm, caster, cs)
        engine.resolve_cast(bm, _cast(caster, tgt))
    assert dec.offered_legendary == 0, "LR must not be offered with 0 uses remaining"
    print("✅ test_legendary_resistance_not_offered_when_exhausted passed")


# ── Legendary Action budget (engine-side support for the GUI) ──────────────────
def test_begin_turn_resets_legendary_actions():
    """A creature regains all legendary actions at the start of its own turn (C++ beginTurn)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Dragon", 5, 5))
    s = engine.get_agent_stats(bm, idx)
    s.has_legendary_actions = True
    s.legendary_actions_max = 3
    s.legendary_actions_current = 1        # spent two during the previous round
    engine.set_agent_stats(bm, idx, s)
    engine.begin_turn(bm, idx)
    cur = engine.get_agent_stats(bm, idx).legendary_actions_current
    assert cur == 3, f"legendary actions reset to max at turn start, got {cur}"
    print("✅ test_begin_turn_resets_legendary_actions passed")


def test_seed_move_budgets_for_out_of_turn_dash():
    """seed_move_budgets grants an out-of-turn movement budget (the legendary Dash mechanism)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Dragon", 5, 5))
    engine.seed_move_budgets(idx, 40, 80, 0, 0)
    assert engine.get_walk_remaining(idx) == 40
    assert engine.get_fly_remaining(idx) == 80
    assert engine.get_swim_remaining(idx) == 0
    # Negative values clamp to 0.
    engine.seed_move_budgets(idx, -5, 0, 0, 0)
    assert engine.get_walk_remaining(idx) == 0
    print("✅ test_seed_move_budgets_for_out_of_turn_dash passed")


# ── Bestiary loader plumbing ───────────────────────────────────────────────────
def test_loader_populates_legendary_fields():
    """dict_to_stats reads a bestiary meta.legendary block and starts with a full action budget."""
    sd = {
        "hp_max": 256, "hp_cur": 256,
        "legendary": {
            "resistance": 3, "resistance_in_lair": 4,
            "actions": 3, "actions_in_lair": 4,
            "has_lair": False,
            "action_names": ["Bite", "Claw", "DashHalf"],
        },
    }
    s = dict_to_stats(sd)
    assert s.has_legendary_actions is True
    assert s.legendary_actions_max == 3
    assert s.legendary_actions_current == 3, "starts the encounter with a full round of actions"
    assert s.legendary_resistance_max == 3
    assert s.legendary_resistance_current == 3
    assert s.is_in_lair is False
    assert list(s.legendary_action_names) == ["Bite", "Claw", "DashHalf"]
    print("✅ test_loader_populates_legendary_fields passed")


def test_loader_uses_in_lair_counts():
    """When has_lair is true, the in-lair resistance/action counts are used."""
    sd = {
        "hp_max": 256, "hp_cur": 256,
        "legendary": {
            "resistance": 3, "resistance_in_lair": 4,
            "actions": 3, "actions_in_lair": 4,
            "has_lair": True,
        },
    }
    s = dict_to_stats(sd)
    assert s.is_in_lair is True
    assert s.legendary_actions_max == 4, "in-lair action count"
    assert s.legendary_resistance_max == 4, "in-lair resistance count"
    print("✅ test_loader_uses_in_lair_counts passed")


def test_loader_no_legendary_block_is_inert():
    """A creature without legendary data has the feature disabled."""
    s = dict_to_stats({"hp_max": 10, "hp_cur": 10})
    assert s.has_legendary_actions is False
    assert s.legendary_actions_max == 0
    assert s.legendary_resistance_max == 0
    print("✅ test_loader_no_legendary_block_is_inert passed")


if __name__ == "__main__":
    test_legendary_resistance_flips_failed_save()
    test_legendary_resistance_not_offered_when_exhausted()
    test_begin_turn_resets_legendary_actions()
    test_seed_move_budgets_for_out_of_turn_dash()
    test_loader_populates_legendary_fields()
    test_loader_uses_in_lair_counts()
    test_loader_no_legendary_block_is_inert()
    print("\n✅ All legendary tests passed")
