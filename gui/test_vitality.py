#!/usr/bin/env python3
"""
Test suite for World Tree Barbarian "Vitality of the Tree" — the second OnTurnStartNearby consumer
(ONTURNSTARTNEARBY_PLAN.md / REACTION_SYSTEM_PLAN.md §9).

Unlike Branches of the Tree (a reaction to ANOTHER creature's turn start), Vitality fires on the
Barbarian's OWN turn start: while raging, it may grant one creature within 10 ft Xd6 temp HP
(X = Rage Damage bonus, min 1 die). It is FREE (not the reaction) but once per turn, and the granted
temp HP vanishes when the Rage ends. The window offers the source itself a self-option that needs a
target pick (ReactionResponse.target_idx).
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


class VitalityDecider(rpg.CombatDecider):
    """Auto/RL decider: take the Vitality self-option (if offered) and pick `target`, else Skip."""
    def __init__(self, target=-1):
        super().__init__()
        self.target = target
        self.calls = 0
    def choose_reaction(self, ctx):
        self.calls += 1
        resp = rpg.ReactionResponse()
        resp.option = -1
        for i, opt in enumerate(ctx.options):
            if opt.feature == "VitalityOfTheTree":
                resp.option = i
                resp.target_idx = self.target
                break
        return resp


def _world_tree_rager(engine, bm, idx, level=3):
    """Turn idx into a raging World Tree Barbarian of the given level."""
    s = engine.get_agent_stats(bm, idx)
    s.character_class = rpg.CharacterClass.Barbarian
    s.barbarian_subclass = rpg.BarbianSubclass.WorldTree
    s.char_level = level
    engine.set_agent_stats(bm, idx, s)
    c = engine.get_agent_conditions(bm, idx)
    c.raging = True
    c.vitality_used_this_turn = False
    engine.set_agent_conditions(bm, idx, c)


def _stats(engine, bm, idx):
    return engine.get_agent_stats(bm, idx)


def _cond(engine, bm, idx):
    return engine.get_agent_conditions(bm, idx)


# ── Eligibility gates ───────────────────────────────────────────────────────────
def test_eligible_world_tree_rager():
    """A raging World Tree Barbarian L3 with a creature within 10 ft is eligible."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    _world_tree_rager(engine, bm, barb)
    assert engine.can_vitality_of_tree(bm, barb)
    print("✅ test_eligible_world_tree_rager passed")


def test_gate_not_raging():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    _world_tree_rager(engine, bm, barb)
    c = _cond(engine, bm, barb); c.raging = False; engine.set_agent_conditions(bm, barb, c)
    assert not engine.can_vitality_of_tree(bm, barb), "not raging → ineligible"
    print("✅ test_gate_not_raging passed")


def test_gate_wrong_subclass():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    _world_tree_rager(engine, bm, barb)
    s = _stats(engine, bm, barb); s.barbarian_subclass = rpg.BarbianSubclass.NONE
    engine.set_agent_stats(bm, barb, s)
    assert not engine.can_vitality_of_tree(bm, barb), "non-World-Tree → ineligible"
    print("✅ test_gate_wrong_subclass passed")


def test_gate_low_level():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    _world_tree_rager(engine, bm, barb, level=2)
    assert not engine.can_vitality_of_tree(bm, barb), "L<3 → ineligible"
    print("✅ test_gate_low_level passed")


def test_gate_no_creature_in_range():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    add_agent_to_battle(engine, bm, create_test_agent("Ally", 9, 9))   # >10 ft (Chebyshev 4 cells)
    _world_tree_rager(engine, bm, barb)
    assert not engine.can_vitality_of_tree(bm, barb), "no creature within 10 ft → ineligible"
    print("✅ test_gate_no_creature_in_range passed")


def test_gate_already_used_this_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    _world_tree_rager(engine, bm, barb)
    c = _cond(engine, bm, barb); c.vitality_used_this_turn = True
    engine.set_agent_conditions(bm, barb, c)
    assert not engine.can_vitality_of_tree(bm, barb), "once per turn → ineligible after use"
    print("✅ test_gate_already_used_this_turn passed")


# ── Grant mechanics ─────────────────────────────────────────────────────────────
def test_grant_gives_temp_hp_and_marks_used():
    """Grant gives Xd6 (X=2 at L3) temp HP with max() semantics; marks the per-turn flag; FREE
    (does not spend the reaction)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    _world_tree_rager(engine, bm, barb)

    granted = engine.apply_vitality_of_tree(bm, barb, ally)
    assert granted
    thp = _stats(engine, bm, ally).temp_hp
    assert 2 <= thp <= 12, f"2d6 expected (2..12), got {thp}"
    assert _cond(engine, bm, barb).vitality_used_this_turn, "grant marks once-per-turn flag"
    assert not _cond(engine, bm, barb).reaction_used, "Vitality is FREE — not the reaction"
    assert _stats(engine, bm, ally).rage_thp_source_idx == barb, "temp HP tagged with the granter"
    print("✅ test_grant_gives_temp_hp_and_marks_used passed")


def test_grant_max_semantics_no_stack():
    """A lower roll never reduces existing higher temp HP (5e temp HP never stacks)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    _world_tree_rager(engine, bm, barb)
    s = _stats(engine, bm, ally); s.temp_hp = 50; engine.set_agent_stats(bm, ally, s)

    engine.apply_vitality_of_tree(bm, barb, ally)
    assert _stats(engine, bm, ally).temp_hp == 50, "max() semantics: 50 > any 2d6, unchanged"
    print("✅ test_grant_max_semantics_no_stack passed")


def test_grant_rejects_out_of_range_target():
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    near = add_agent_to_battle(engine, bm, create_test_agent("Near", 6, 5))   # in range (keeps barb eligible)
    far  = add_agent_to_battle(engine, bm, create_test_agent("Far", 11, 11))  # out of range
    _world_tree_rager(engine, bm, barb)
    assert not engine.apply_vitality_of_tree(bm, barb, far), "target >10 ft → no grant"
    assert _stats(engine, bm, far).temp_hp == 0
    assert not _cond(engine, bm, barb).vitality_used_this_turn, "rejected grant must not consume the per-turn use"
    print("✅ test_grant_rejects_out_of_range_target passed")


# ── Vanish when Rage ends ────────────────────────────────────────────────────────
def test_vanishes_on_rage_end():
    """endRage clears exactly the granter's rage-sourced temp HP; an unrelated creature's
    non-rage temp HP is untouched."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb     = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    ally     = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    bystander = add_agent_to_battle(engine, bm, create_test_agent("Bystander", 4, 5))
    _world_tree_rager(engine, bm, barb)
    # Bystander has unrelated (non-rage) temp HP.
    s = _stats(engine, bm, bystander); s.temp_hp = 7; engine.set_agent_stats(bm, bystander, s)

    engine.apply_vitality_of_tree(bm, barb, ally)
    assert _stats(engine, bm, ally).temp_hp > 0

    engine.end_rage(bm, barb)
    assert _stats(engine, bm, ally).temp_hp == 0, "rage-sourced temp HP vanishes on Rage end"
    assert _stats(engine, bm, ally).rage_thp_source_idx == -1, "provenance cleared"
    assert _stats(engine, bm, bystander).temp_hp == 7, "unrelated temp HP untouched"
    print("✅ test_vanishes_on_rage_end passed")


def test_entry_temp_hp_persists_past_rage():
    """The entry temp HP grant (= Barbarian level on entering Rage) is NOT rage-tagged, so it
    persists after Rage ends."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    s = _stats(engine, bm, barb)
    s.character_class = rpg.CharacterClass.Barbarian
    s.barbarian_subclass = rpg.BarbianSubclass.WorldTree
    s.char_level = 5
    engine.set_agent_stats(bm, barb, s)

    engine.activate_rage(bm, barb)                          # grants entry temp HP = level (5), untagged
    assert _stats(engine, bm, barb).temp_hp == 5
    engine.end_rage(bm, barb)
    assert _stats(engine, bm, barb).temp_hp == 5, "entry temp HP persists past Rage end"
    print("✅ test_entry_temp_hp_persists_past_rage passed")


# ── Window integration ───────────────────────────────────────────────────────────
def test_self_option_via_auto_driver():
    """begin_turn_flow on the Barbarian's own turn offers the Vitality self-option; the decider takes
    it and grants temp HP to its chosen target."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    _world_tree_rager(engine, bm, barb)
    dec = VitalityDecider(target=ally); engine.set_decider(dec)

    status = engine.begin_turn_flow(bm, barb, False)        # auto driver resolves inline
    assert status == rpg.FlowStatus.Completed
    assert dec.calls >= 1, "the source itself should be offered the self-option"
    assert _stats(engine, bm, ally).temp_hp > 0, "decider's target received temp HP"
    assert _cond(engine, bm, barb).vitality_used_this_turn
    print("✅ test_self_option_via_auto_driver passed")


def test_window_interactive_parks_self_option():
    """interactive=True parks the self-option (reactor==source) for the GUI; submit with a target
    completes the window."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    _world_tree_rager(engine, bm, barb)

    status = engine.begin_turn_flow(bm, barb, True)         # no decider → suspend
    pd = engine.pending_decision()
    assert status == rpg.FlowStatus.AwaitingDecision and pd.active
    assert pd.ctx.window == rpg.ReactionWindow.OnTurnStartNearby
    assert pd.ctx.reactor_idx == barb and pd.ctx.source_idx == barb, "self-option: reactor == source"
    assert any(o.feature == "VitalityOfTheTree" for o in pd.ctx.options)

    take = rpg.ReactionResponse(); take.option = 0; take.target_idx = ally
    status = engine.submit_decision(bm, take)
    assert status == rpg.FlowStatus.Completed
    assert _stats(engine, bm, ally).temp_hp > 0
    print("✅ test_window_interactive_parks_self_option passed")


def test_begin_turn_resets_used_flag():
    """beginTurn re-arms vitality_used_this_turn so the grant is available again next turn."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    barb = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    _world_tree_rager(engine, bm, barb)
    c = _cond(engine, bm, barb); c.vitality_used_this_turn = True
    engine.set_agent_conditions(bm, barb, c)

    engine.begin_turn(bm, barb)
    assert not _cond(engine, bm, barb).vitality_used_this_turn, "beginTurn resets the per-turn flag"
    print("✅ test_begin_turn_resets_used_flag passed")


def run_all():
    test_eligible_world_tree_rager()
    test_gate_not_raging()
    test_gate_wrong_subclass()
    test_gate_low_level()
    test_gate_no_creature_in_range()
    test_gate_already_used_this_turn()
    test_grant_gives_temp_hp_and_marks_used()
    test_grant_max_semantics_no_stack()
    test_grant_rejects_out_of_range_target()
    test_vanishes_on_rage_end()
    test_entry_temp_hp_persists_past_rage()
    test_self_option_via_auto_driver()
    test_window_interactive_parks_self_option()
    test_begin_turn_resets_used_flag()
    print("\nAll Vitality of the Tree tests passed ✅")


if __name__ == "__main__":
    run_all()
