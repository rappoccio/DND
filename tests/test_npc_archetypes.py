#!/usr/bin/env python3
"""NPC archetypes + the Level 5/6 fallback chain (NPC_LEARNING_PLAN.md Step 4).

npc_classify_archetype refines npc_classify_role: Melee/Ranged carry over, and a Caster splits into
Blaster / Controller / HealerSupport by the Level 4 planner its known spells feed (ties by summed spell
level). At Level 5/6, npc_decide walks the fallback chain:
  1. the archetype model's top action, if actionable;   2. a lower-ranked one;
  3. the archetype's own strategies, then its secondaries';   4. the Level 4 resolver;   5. Simple.
With no model loaded at all, Levels 5/6 run Level 4 exactly (rung Heuristic). Each rung is forced and
observed here, and the decision is checked through run_npc_turn, the trace and the Playback HUD.
"""

import os
import sys
import tempfile

import gui_driver   # noqa: F401 — sets the dummy SDL drivers and gui/ on sys.path first

import rpg_battle_map as rpg
import arena
import playback
import sim_trace
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle, create_melee_weapon)
from test_npc_automation import (_arm_ranged, _automate, _aoe_cantrip, _recharge_breath, _make_npc,
                                 _control_spell, _heal_spell, _buff_spell, _set_hp)

A = rpg.NpcArchetype
S = rpg.NpcAutomationStrategy
R = rpg.NpcFallbackRung


def _board():
    return setup_battle_map(), setup_combat_engine()


def _pair(bm, engine, npc_col=1, npc_row=1, foe_col=6, foe_row=5):
    """An NPC (faction 1) and one enemy (faction 2)."""
    npc = add_agent_to_battle(engine, bm, create_test_agent("Npc", npc_col, npc_row))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", foe_col, foe_row), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(foe, 2)
    return npc, foe


def _level(bm, idx, level):
    _automate(bm, idx)
    bm.set_agent_npc_automation_difficulty(idx, level)


def _leveled(spell, level):
    spell.level = level
    return spell


# ── Classification ──────────────────────────────────────────────────────────────

def test_classify_melee_and_ranged():
    bm, engine = _board()
    npc, foe = _pair(bm, engine)
    engine.set_agent_weapons(bm, npc, [create_melee_weapon(), rpg.Weapon(), rpg.Weapon()])
    assert engine.npc_classify_archetype(bm, npc) == A.Melee
    _arm_ranged(engine, bm, npc)
    assert engine.npc_classify_archetype(bm, npc) == A.Ranged
    print("✅ test_classify_melee_and_ranged passed")


def test_classify_caster_kinds():
    bm, engine = _board()
    npc, _ = _pair(bm, engine)
    cases = [
        ([_aoe_cantrip()], A.Blaster),
        ([_control_spell("Hold Person", rpg.SpellGeometry.Single, "Paralyzed")], A.Controller),
        ([_heal_spell("Cure Wounds"), _buff_spell()], A.HealerSupport),
        # Two heal/buff spells outnumber one blast.
        ([_aoe_cantrip(), _heal_spell("Cure Wounds"), _buff_spell()], A.HealerSupport),
    ]
    for spells, want in cases:
        engine.set_agent_spells(bm, npc, spells)
        assert engine.npc_classify_role(bm, npc) == rpg.NpcRole.Caster
        got = engine.npc_classify_archetype(bm, npc)
        assert got == want, f"{[s.name for s in spells]}: {got} != {want}"
    print("✅ test_classify_caster_kinds passed")


def test_classify_tie_goes_by_slot_weight():
    bm, engine = _board()
    npc, _ = _pair(bm, engine)
    hold = lambda: _control_spell("Hold Person", rpg.SpellGeometry.Single, "Paralyzed")
    engine.set_agent_spells(bm, npc, [_leveled(_aoe_cantrip(), 3), _leveled(hold(), 2)])
    assert engine.npc_classify_archetype(bm, npc) == A.Blaster
    engine.set_agent_spells(bm, npc, [_leveled(_aoe_cantrip(), 1), _leveled(hold(), 2)])
    assert engine.npc_classify_archetype(bm, npc) == A.Controller
    # A full tie (count and weight) keeps the earlier archetype: Blaster before Controller.
    engine.set_agent_spells(bm, npc, [_leveled(_aoe_cantrip(), 2), _leveled(hold(), 2)])
    assert engine.npc_classify_archetype(bm, npc) == A.Blaster
    print("✅ test_classify_tie_goes_by_slot_weight passed")


def test_classify_caster_with_no_planner_spell_is_ranged():
    """A caster whose spells feed none of the three planners (single-target damage only) is Ranged."""
    bm, engine = _board()
    npc, _ = _pair(bm, engine)
    bolt = rpg.Spell()
    bolt.name = "Firebolt"
    engine.set_agent_spells(bm, npc, [bolt])
    assert engine.npc_classify_role(bm, npc) == rpg.NpcRole.Caster
    assert engine.npc_classify_archetype(bm, npc) == A.Ranged
    print("✅ test_classify_caster_with_no_planner_spell_is_ranged passed")


def test_chain_tables():
    eng = rpg.CombatEngine
    assert eng.npc_archetype_chain(A.Melee) == [A.Melee]
    assert eng.npc_archetype_chain(A.Ranged) == [A.Ranged, A.Melee]
    assert eng.npc_archetype_chain(A.Blaster) == [A.Blaster, A.Ranged, A.Melee]
    assert eng.npc_archetype_chain(A.Controller) == [A.Controller, A.Blaster, A.Ranged, A.Melee]
    assert eng.npc_archetype_chain(A.HealerSupport) == [A.HealerSupport, A.Controller, A.Ranged, A.Melee]
    assert eng.npc_archetype_strategies(A.Ranged) == [S.PreferHide, S.PreferRange]
    assert eng.npc_archetype_strategies(A.HealerSupport) == [S.PreferHeal, S.PreferSupport]
    print("✅ test_chain_tables passed")


# ── The chain ───────────────────────────────────────────────────────────────────

def test_no_model_runs_level4():
    """Levels 5/6 with no model loaded resolve exactly as Level 4, rung Heuristic."""
    bm, engine = _board()
    npc, _ = _pair(bm, engine)
    engine.set_agent_spells(bm, npc, [_aoe_cantrip()])
    _level(bm, npc, 4)
    l4 = engine.resolve_strategy(bm, npc)
    for lv in (5, 6):
        _level(bm, npc, lv)
        d = engine.npc_decide(bm, npc)
        assert not engine.npc_models_loaded()
        assert d.rung == R.Heuristic and d.level == lv and d.archetype == A.Blaster
        assert d.strategy == l4 == S.PreferAOE
    print("✅ test_no_model_runs_level4 passed")


def test_rung1_tree_top():
    bm, engine = _board()
    npc, foe = _pair(bm, engine, foe_col=6, foe_row=5)
    engine.set_agent_spells(bm, npc, [_aoe_cantrip()])
    _level(bm, npc, 5)
    engine.set_npc_archetype_model(A.Blaster, [S.PreferAOE, S.Simple])
    d = engine.npc_decide(bm, npc)
    assert (d.rung, d.strategy) == (R.TreeTop, S.PreferAOE)

    # And through run_npc_turn: the decision is kept, and the blast lands.
    engine.begin_turn(bm, npc)
    assert engine.run_npc_turn(bm, npc) == rpg.FlowStatus.Completed
    last = engine.last_npc_decision()
    assert (last.agent_idx, last.rung, last.strategy) == (npc, R.TreeTop, S.PreferAOE)
    assert engine.get_agent_stats(bm, foe).hp_cur < 30
    print("✅ test_rung1_tree_top passed")


def test_rung2_tree_ranked():
    """The top choice (heal, with no heal spell) isn't actionable; the next ranked one is."""
    bm, engine = _board()
    npc, _ = _pair(bm, engine)
    engine.set_agent_spells(bm, npc, [_aoe_cantrip()])
    _level(bm, npc, 5)
    engine.set_npc_archetype_model(A.Blaster, [S.PreferHeal, S.PreferAOE])
    d = engine.npc_decide(bm, npc)
    assert (d.rung, d.strategy) == (R.TreeRanked, S.PreferAOE)
    print("✅ test_rung2_tree_ranked passed")


def test_rung3_archetype_without_model():
    """Models are loaded, but none for this archetype: the chain starts at rung 3."""
    bm, engine = _board()
    npc, _ = _pair(bm, engine)
    engine.set_agent_spells(bm, npc, [_aoe_cantrip()])
    _level(bm, npc, 5)
    engine.set_npc_archetype_model(A.Melee, [S.Simple])
    d = engine.npc_decide(bm, npc)
    assert (d.archetype, d.rung, d.strategy) == (A.Blaster, R.Archetype, S.PreferAOE)
    print("✅ test_rung3_archetype_without_model passed")


def test_rung3_blaster_out_of_blasts_goes_ranged():
    """Blaster with its only blast expended → Ranged (bow + LOS) → PreferRange; without the bow → Melee."""
    bm, engine = _board()
    npc, _ = _pair(bm, engine)
    _make_npc(engine, bm, npc)
    engine.set_agent_spells(bm, npc, [_recharge_breath(expended=True)])
    _arm_ranged(engine, bm, npc)
    _level(bm, npc, 5)
    engine.set_npc_archetype_model(A.Blaster, [S.PreferAOE])
    assert engine.npc_classify_archetype(bm, npc) == A.Blaster
    assert not engine.npc_strategy_actionable(bm, npc, S.PreferAOE)
    d = engine.npc_decide(bm, npc)
    assert (d.rung, d.strategy) == (R.Archetype, S.PreferRange)

    engine.set_agent_weapons(bm, npc, [create_melee_weapon(), rpg.Weapon(), rpg.Weapon()])
    d = engine.npc_decide(bm, npc)
    assert (d.rung, d.strategy) == (R.Archetype, S.Simple)
    print("✅ test_rung3_blaster_out_of_blasts_goes_ranged passed")


def test_rung3_ranged_without_los_goes_melee():
    """Ranged with no line of sight to any enemy → Melee (Simple)."""
    bm, engine = _board()
    npc, _ = _pair(bm, engine, npc_col=5, npc_row=5, foe_col=1, foe_row=5)
    _arm_ranged(engine, bm, npc)
    _level(bm, npc, 5)
    engine.set_npc_archetype_model(A.Ranged, [S.PreferRange])
    assert engine.npc_decide(bm, npc).strategy == S.PreferRange   # sees the foe: rung 1
    for row in (3, 4, 5, 6, 7):                                    # wall it off
        bm.set_terrain_type(rpg.Cell(3, row), rpg.TerrainType.Wall)
    assert not engine.npc_strategy_actionable(bm, npc, S.PreferRange)
    d = engine.npc_decide(bm, npc)
    assert (d.rung, d.strategy) == (R.Archetype, S.Simple)
    print("✅ test_rung3_ranged_without_los_goes_melee passed")


def test_rung4_level4_resolver():
    """Nothing on the Blaster chain has work (blast expended, no enemy), but Level 4's pick does: heal
    the wounded ally."""
    bm, engine = _board()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Npc", 1, 1))
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 2, 1), hp=30)
    bm.set_agent_faction(npc, 1)
    bm.set_agent_faction(ally, 1)
    _make_npc(engine, bm, npc)
    engine.set_agent_spells(bm, npc, [_recharge_breath(expended=True),
                                      _leveled(_aoe_cantrip(), 3), _heal_spell("Cure Wounds")])
    s = engine.get_agent_stats(bm, npc); s.spell_slots_remaining = [0] * 9; engine.set_agent_stats(bm, npc, s)
    _set_hp(engine, bm, ally, 2)
    _level(bm, npc, 5)
    engine.set_npc_archetype_model(A.Blaster, [S.PreferAOE])
    assert engine.npc_classify_archetype(bm, npc) == A.Blaster
    d = engine.npc_decide(bm, npc)
    assert (d.rung, d.strategy) == (R.Level4, S.PreferHeal), (d.rung, d.strategy)
    print("✅ test_rung4_level4_resolver passed")


def test_rung5_simple():
    """No enemy, nobody to heal: nothing is actionable anywhere, so Simple."""
    bm, engine = _board()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Npc", 1, 1))
    bm.set_agent_faction(npc, 1)
    _level(bm, npc, 6)
    engine.set_npc_archetype_model(A.Melee, [S.Simple])
    d = engine.npc_decide(bm, npc)
    assert (d.rung, d.strategy) == (R.Simple, S.Simple)
    print("✅ test_rung5_simple passed")


def test_heuristic_levels_unchanged_and_decision_reset():
    """Levels 1-4 report rung Heuristic and the same strategy resolve_strategy gives; a turn that never
    reaches the resolver (a corpse) reports no decision rather than the previous one."""
    bm, engine = _board()
    npc, _ = _pair(bm, engine)
    engine.set_agent_spells(bm, npc, [_aoe_cantrip()])
    engine.set_npc_archetype_model(A.Blaster, [S.Simple])   # models don't touch Levels 1-4
    for lv in (1, 2, 3, 4):
        _level(bm, npc, lv)
        d = engine.npc_decide(bm, npc)
        assert d.rung == R.Heuristic and d.strategy == engine.resolve_strategy(bm, npc)
    engine.begin_turn(bm, npc)
    engine.run_npc_turn(bm, npc)
    assert engine.last_npc_decision().agent_idx == npc
    _set_hp(engine, bm, npc, 0)
    engine.run_npc_turn(bm, npc)
    assert engine.last_npc_decision().agent_idx == -1
    print("✅ test_heuristic_levels_unchanged_and_decision_reset passed")


# ── Trace + Playback HUD ────────────────────────────────────────────────────────

def test_decision_in_trace_and_hud():
    bm, engine = _board()
    npc, _ = _pair(bm, engine)
    engine.set_agent_spells(bm, npc, [_aoe_cantrip()])
    _level(bm, npc, 5)
    engine.set_npc_archetype_model(A.Melee, [S.Simple])
    d = engine.npc_decide(bm, npc)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.jsonl")
        w = sim_trace.TraceWriter(path, map_path="m.png", agents={"agents": []}, seed=1,
                                  npc_policy="level5", pc_mode="Heuristic")
        w.begin_turn(round_num=0, actor=npc, actor_name="Npc", driver=sim_trace.DRIVER_NPC, snapshot={})
        w.set_decision(d)
        w.begin_turn(round_num=0, actor=1, actor_name="Foe", driver=sim_trace.DRIVER_HUMAN, snapshot={})
        w.close({})
        tr = sim_trace.load_trace(path)
    assert tr.turns[0].decision == {"level": 5, "archetype": "Blaster", "rung": "Archetype",
                                    "strategy": "PreferAOE"}
    assert tr.turns[1].decision is None
    assert playback.decision_text(tr.turns[0].decision) == " · Blaster: PreferAOE (rung 3 archetype)"
    assert playback.decision_text({"archetype": "Melee", "rung": "Heuristic", "strategy": "Simple"}) \
        == " · Melee: Simple"
    assert playback.decision_text(None) == ""
    print("✅ test_decision_in_trace_and_hud passed")


def test_arena_trace_records_decisions():
    """An arena episode's trace carries a decision on the NPC turns that reached the resolver."""
    sc = arena.generate_scenario(3)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "ep.jsonl")
        arena.run_episode(sc, 3, "level4", trace_path=path)
        tr = sim_trace.load_trace(path)
    decided = [t for t in tr.turns if t.decision]
    assert decided, "no turn recorded a decision"
    for t in decided:
        assert t.decision["rung"] == "Heuristic"
        assert t.decision["archetype"] in {"Melee", "Ranged", "Blaster", "Controller", "HealerSupport"}
    print("✅ test_arena_trace_records_decisions passed")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"\nAll {len(tests)} NPC archetype tests passed.")
