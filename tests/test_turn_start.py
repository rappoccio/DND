#!/usr/bin/env python3
"""
Test suite for the OnTurnStartNearby reaction window — window #7,
the last of the reaction framework.

Consumer: **Branches of the Tree** (Path of the World Tree, L6) — while the reactor's Rage is active and
a creature it can see starts its turn within 30 ft, the reactor may spend its reaction to force a STR
save (DC 8 + the reactor's STR mod + PB). On a failure the creature is teleported to an unoccupied space
within 5 ft of the reactor and its Speed is 0 until the end of the current turn (branches_speed_zeroed,
which canAgentMove reads). (Sentinel is NOT a turn-start reaction — it provokes an Opportunity Attack
when a creature Disengages out of reach; that lives in detectProvokes / test_reactions.py.)

The window rides on a NEW flow-checkpoint transport: begin_turn_flow runs beginTurn, then opens the
window (suspend for the GUI / inline via the installed decider for auto/RL), resumed by submit_decision.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


class TurnStartDecider(rpg.CombatDecider):
    """Auto/RL decider: pick the option whose feature matches `feature` (else Skip). Records calls."""
    def __init__(self, feature=None):
        super().__init__()
        self.feature = feature       # "BranchesOfTheTree" / None = Skip
        self.calls = 0
    def choose_reaction(self, ctx):
        self.calls += 1
        resp = rpg.ReactionResponse()
        resp.option = -1
        for i, opt in enumerate(ctx.options):
            if opt.feature == self.feature:
                resp.option = i
                break
        return resp


def _give_branches(engine, bm, idx, prof_bonus=6, str_score=20):
    """Branches reactor: raging, with the feature and a high STR-save DC (8 + PB + STR mod) so a
    low-STR source fails. The Rage is required by the feature ('While your Rage is active')."""
    s = engine.get_agent_stats(bm, idx)
    s.has_branches_of_the_tree = True
    s.prof_bonus = prof_bonus
    s.str = str_score
    engine.set_agent_stats(bm, idx, s)
    c = engine.get_agent_conditions(bm, idx)
    c.raging = True
    engine.set_agent_conditions(bm, idx, c)


def _weak_str(engine, bm, idx):
    s = engine.get_agent_stats(bm, idx); s.str = 1   # STR mod -5, max save 20-5=15 < a DC of 19
    engine.set_agent_stats(bm, idx, s)


def _cond(engine, bm, idx):
    return engine.get_agent_conditions(bm, idx)


def _foot_dist(bm, a, b):
    """Chebyshev footprint gap in cells between two size-1 agents (5 ft per cell)."""
    aa = bm.placed_agents[a].origin
    bb = bm.placed_agents[b].origin
    return max(abs(aa.col - bb.col), abs(aa.row - bb.row))


# ── Branches via the window (auto driver) ──────────────────────────────────────
def test_branches_via_auto_driver():
    """An enemy starting its turn within 30 ft of a raging Branches reactor → the decider takes it; a
    failing STR save leaves the source Speed-zeroed and the reactor's reaction spent."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    rea = add_agent_to_battle(engine, bm, create_test_agent("Treant", 8, 5))   # 3 cells = 15 ft (≤30)
    _give_branches(engine, bm, rea); _weak_str(engine, bm, src)
    dec = TurnStartDecider("BranchesOfTheTree"); engine.set_decider(dec)

    status = engine.begin_turn_flow(bm, src, False)   # auto driver resolves the window inline
    assert status == rpg.FlowStatus.Completed
    assert dec.calls >= 1, "the decider should have been consulted for the Branches reactor"
    assert _cond(engine, bm, rea).reaction_used, "Branches spends the reactor's reaction"
    assert _cond(engine, bm, src).branches_speed_zeroed, "a failed STR save zeroes the source's Speed"
    assert _foot_dist(bm, src, rea) <= 1, "a failed save yanks the source to within 5 ft of the reactor"
    assert not engine.last_turn_start_result().turn_skipped
    print("✅ test_branches_via_auto_driver passed")


def test_skip_keeps_reaction():
    """A decider that Skips leaves the reactor's reaction intact and the source free to move."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    rea = add_agent_to_battle(engine, bm, create_test_agent("Treant", 6, 5))
    _give_branches(engine, bm, rea); _weak_str(engine, bm, src)
    dec = TurnStartDecider(None); engine.set_decider(dec)   # Skip

    status = engine.begin_turn_flow(bm, src, False)
    assert status == rpg.FlowStatus.Completed
    assert dec.calls >= 1
    assert not _cond(engine, bm, rea).reaction_used, "Skip must not spend the reaction"
    assert not _cond(engine, bm, src).branches_speed_zeroed
    print("✅ test_skip_keeps_reaction passed")


def test_out_of_reach_not_offered():
    """A reactor 7 cells away is out of the 30 ft window — not eligible, window never opens."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 2, 2))
    rea = add_agent_to_battle(engine, bm, create_test_agent("Treant", 9, 9))   # 7 cells = 35 ft (>30)
    _give_branches(engine, bm, rea)
    assert not engine.can_branches_of_tree(bm, rea, src), "out of 30 ft → not eligible"
    dec = TurnStartDecider("BranchesOfTheTree"); engine.set_decider(dec)
    status = engine.begin_turn_flow(bm, src, False)
    assert status == rpg.FlowStatus.Completed
    assert dec.calls == 0, "no reactor in reach → decider never consulted"
    print("✅ test_out_of_reach_not_offered passed")


def test_not_raging_not_offered():
    """A reactor with the feature but NOT raging is ineligible ('While your Rage is active')."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    rea = add_agent_to_battle(engine, bm, create_test_agent("Treant", 6, 5))
    _give_branches(engine, bm, rea)
    c = _cond(engine, bm, rea); c.raging = False; engine.set_agent_conditions(bm, rea, c)
    assert not engine.can_branches_of_tree(bm, rea, src), "not raging → not eligible"
    print("✅ test_not_raging_not_offered passed")


def test_no_feat_no_window():
    """A reactor without the feat is not eligible (no window opens)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    rea = add_agent_to_battle(engine, bm, create_test_agent("Bystander", 6, 5))
    assert not engine.can_branches_of_tree(bm, rea, src)
    print("✅ test_no_feat_no_window passed")


# ── Branches save resolution (direct) ──────────────────────────────────────────
def test_branches_teleports_on_failed_save():
    """A guaranteed-fail STR save (low STR vs a high DC) → the source is yanked to within 5 ft of the
    reactor, its Speed is zeroed, and the reaction is spent."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 3, 5))
    rea = add_agent_to_battle(engine, bm, create_test_agent("Treant", 8, 5))   # 5 cells = 25 ft (≤30)
    _give_branches(engine, bm, rea); _weak_str(engine, bm, src)   # DC 19, save max 15

    assert _foot_dist(bm, src, rea) > 1, "source starts farther than 5 ft so the teleport is observable"
    yanked = engine.apply_branches_of_tree(bm, rea, src)
    assert yanked, "a STR save that cannot reach the DC must fail → teleport + Speed 0"
    assert _foot_dist(bm, src, rea) <= 1, "source teleported to within 5 ft of the reactor"
    assert _cond(engine, bm, src).branches_speed_zeroed, "source's Speed is 0 until end of turn"
    assert not engine.can_agent_move(bm, src), "Speed 0 → cannot move this turn"
    assert _cond(engine, bm, rea).reaction_used, "Branches spends the reactor's reaction"
    assert not _cond(engine, bm, src).grappled, "the 2024 effect is teleport + Speed 0, NOT Grappled"
    print("✅ test_branches_teleports_on_failed_save passed")


def test_branches_passed_save_no_effect():
    """A guaranteed-pass STR save (high STR/prof vs a low DC) → no teleport, no Speed change."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Ogre", 3, 5))
    rea = add_agent_to_battle(engine, bm, create_test_agent("Sapling", 8, 5))
    _give_branches(engine, bm, rea, prof_bonus=0, str_score=10)        # DC = 8 + 0 + 0 = 8
    ss = engine.get_agent_stats(bm, src)
    ss.str = 20; ss.save_prof_str = True; ss.prof_bonus = 6            # +5 + prof 6 = +11, min 1+11=12 ≥ 8
    engine.set_agent_stats(bm, src, ss)
    start = _foot_dist(bm, src, rea)

    yanked = engine.apply_branches_of_tree(bm, rea, src)
    assert not yanked, "a STR save that always meets the DC must pass → no effect"
    assert _foot_dist(bm, src, rea) == start, "a passed save does not teleport the source"
    assert not _cond(engine, bm, src).branches_speed_zeroed
    print("✅ test_branches_passed_save_no_effect passed")


def test_speed_zero_clears_next_turn():
    """branches_speed_zeroed lasts only the current turn — Agent::turn() (beginTurn) clears it so the
    source can move again on its next turn."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 3, 5))
    rea = add_agent_to_battle(engine, bm, create_test_agent("Treant", 8, 5))
    _give_branches(engine, bm, rea); _weak_str(engine, bm, src)

    assert engine.apply_branches_of_tree(bm, rea, src)
    assert _cond(engine, bm, src).branches_speed_zeroed
    engine.begin_turn_flow(bm, src, True)                 # the source's next turn starts → turn() clears it
    assert not _cond(engine, bm, src).branches_speed_zeroed, "Speed 0 expires at the source's next turn"
    print("✅ test_speed_zero_clears_next_turn passed")


# ── Economy / eligibility ───────────────────────────────────────────────────────
def test_used_reaction_blocks_offer():
    """A reactor that already spent its reaction is not eligible for the turn-start reaction."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    rea = add_agent_to_battle(engine, bm, create_test_agent("Treant", 6, 5))
    _give_branches(engine, bm, rea)
    c = _cond(engine, bm, rea); c.reaction_used = True
    engine.set_agent_conditions(bm, rea, c)
    assert not engine.can_branches_of_tree(bm, rea, src)
    print("✅ test_used_reaction_blocks_offer passed")


def test_down_source_opens_no_window():
    """A creature that is down (hp <= 0) at turn start isn't 'present' to be reacted to."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    rea = add_agent_to_battle(engine, bm, create_test_agent("Treant", 6, 5))
    _give_branches(engine, bm, rea)
    s = engine.get_agent_stats(bm, src); s.hp_cur = 0; engine.set_agent_stats(bm, src, s)
    c = _cond(engine, bm, src); c.unconscious = True; c.stabilized = True   # stable & down → no death save
    engine.set_agent_conditions(bm, src, c)

    status = engine.begin_turn_flow(bm, src, True)          # interactive: would park if a window opened
    assert status == rpg.FlowStatus.Completed
    assert not engine.pending_decision().active, "no window should open for a down creature"
    assert not _cond(engine, bm, rea).reaction_used
    print("✅ test_down_source_opens_no_window passed")


# ── GUI suspend / resume + multi-reactor cursor ────────────────────────────────
def test_gui_suspend_resume_cursor_order():
    """Two Branches reactors flank the source. interactive=True parks each in order; Skip then take."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    src   = add_agent_to_battle(engine, bm, create_test_agent("Goblin", 5, 5))
    rea_a = add_agent_to_battle(engine, bm, create_test_agent("TreantA", 6, 5))  # idx 1
    rea_b = add_agent_to_battle(engine, bm, create_test_agent("TreantB", 4, 5))  # idx 2
    _give_branches(engine, bm, rea_a); _give_branches(engine, bm, rea_b)

    status = engine.begin_turn_flow(bm, src, True)          # no decider → suspend
    pd = engine.pending_decision()
    assert status == rpg.FlowStatus.AwaitingDecision and pd.active
    assert pd.ctx.window == rpg.ReactionWindow.OnTurnStartNearby
    assert pd.ctx.reactor_idx == rea_a, "reactors are offered in ascending index order (A first)"
    assert pd.ctx.source_idx == src

    skip = rpg.ReactionResponse(); skip.option = -1         # A skips
    status = engine.submit_decision(bm, skip)
    pd = engine.pending_decision()
    assert status == rpg.FlowStatus.AwaitingDecision and pd.active
    assert pd.ctx.reactor_idx == rea_b, "after A skips, B is offered"

    take = rpg.ReactionResponse(); take.option = 0          # B takes Branches (option 0 = the feature)
    status = engine.submit_decision(bm, take)
    assert status == rpg.FlowStatus.Completed
    assert not engine.pending_decision().active
    assert not _cond(engine, bm, rea_a).reaction_used, "A skipped → reaction intact"
    assert _cond(engine, bm, rea_b).reaction_used, "B took the reaction → reaction spent"
    assert _cond(engine, bm, src).branches_speed_zeroed, "B's Branches zeroed the source's Speed"
    print("✅ test_gui_suspend_resume_cursor_order passed")


def run_all():
    test_branches_via_auto_driver()
    test_skip_keeps_reaction()
    test_out_of_reach_not_offered()
    test_not_raging_not_offered()
    test_no_feat_no_window()
    test_branches_teleports_on_failed_save()
    test_branches_passed_save_no_effect()
    test_speed_zero_clears_next_turn()
    test_used_reaction_blocks_offer()
    test_down_source_opens_no_window()
    test_gui_suspend_resume_cursor_order()
    print("\nAll OnTurnStartNearby tests passed ✅")


if __name__ == "__main__":
    run_all()
