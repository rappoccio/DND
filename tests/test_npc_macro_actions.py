#!/usr/bin/env python3
"""Macro-actions, the policy seam and the entity observation (NPC_LEARNING_PLAN.md Step 5).

available_macro_actions lists every candidate (kind × target / spell) with a legal flag;
execute_macro_action runs one through the Level 4 executors with the chosen target forced; a
policy installed with set_npc_policy ranks the candidates at Levels 5/6 (rung 1 = its top
legal pick, rung 2 = a later one, nothing legal → the Step 4 chain from rung 3), and the
choice is recorded in the decision, the trace and the Playback HUD. npc_heuristic_macro_action
gives Level 4's choice as a candidate (Step 6's label). get_entity_observation is the D4
token set. With no policy installed nothing changes: the determinism golden is untouched.
"""

import json
import math
import os
import tempfile

import gui_driver   # noqa: F401 — sets the dummy SDL drivers and gui/ on sys.path first

import rpg_battle_map as rpg
import arena
import playback
import sim_trace
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle, create_melee_weapon)
from test_npc_automation import (_arm_ranged, _automate, _aoe_cantrip, _control_spell,
                                 _heal_spell, _buff_spell, _set_hp, _fp_dist)

K = rpg.NpcMacroKind
S = rpg.NpcAutomationStrategy
R = rpg.NpcFallbackRung
A = rpg.NpcArchetype


def _board():
    bm = setup_battle_map()
    _FACTIONS.pop(id(bm), None)
    return bm, setup_combat_engine()


_FACTIONS: dict[int, dict[int, int]] = {}


def _add(bm, engine, name, col, row, faction, hp=30):
    """Add an agent. apply_agent_configs rebuilds the roster and drops earlier factions, so every
    faction set so far on this board is re-applied after each add."""
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row), hp=hp)
    factions = _FACTIONS.setdefault(id(bm), {})
    factions[idx] = faction
    for i, f in factions.items():
        bm.set_agent_faction(i, f)
    return idx


def _arm_melee(engine, bm, idx):
    engine.set_agent_weapons(bm, idx, [create_melee_weapon(), rpg.Weapon(), rpg.Weapon()])


def _speed(engine, bm, idx, walk):
    s = engine.get_agent_stats(bm, idx); s.speed_walk = walk; engine.set_agent_stats(bm, idx, s)


def _hooked(engine):
    calls = []
    engine.set_render_attack_hook(lambda a, t: calls.append((a, t)))
    return calls


def _find(actions, kind, target=-1, spell=None):
    for a in actions:
        if a.kind == kind and a.target_agent == target and (spell is None or a.spell_idx == spell):
            return a
    raise AssertionError(f"no {kind} candidate for target {target}")


def _drive(engine, bm, idx, run):
    """Call `run` until the turn completes, Skipping any reaction it parks on."""
    status = run()
    while status == rpg.FlowStatus.AwaitingDecision:
        resp = rpg.ReactionResponse()
        resp.option = -1
        engine.submit_decision(bm, resp)
        status = run()
    return status


# ── Candidates ──────────────────────────────────────────────────────────────────

def test_candidates_order_and_legality():
    """A melee NPC with two enemies (one walled off from sight is still a candidate) and an ally."""
    bm, engine = _board()
    npc = _add(bm, engine, "Npc", 5, 5, 1)
    near = _add(bm, engine, "Near", 6, 5, 2)
    far = _add(bm, engine, "Far", 9, 9, 2)
    ally = _add(bm, engine, "Ally", 4, 5, 1)
    _arm_melee(engine, bm, npc)
    acts = engine.available_macro_actions(bm, npc)
    kinds = [a.kind for a in acts]
    assert kinds == [K.Attack, K.Attack, K.Kite, K.Kite, K.Hide, K.Dash, K.Dash,
                     K.Disengage, K.Dodge, K.Flee], kinds
    assert [a.target_agent for a in acts[:4]] == [near, far, near, far]
    assert all(a.legal for a in acts if a.kind != K.Hide), "no stealth tools → only Hide is illegal"
    assert not _find(acts, K.Hide).legal
    assert ally not in {a.target_agent for a in acts}, "allies are never weapon targets"
    assert _find(acts, K.Attack, near).target_cell.col == 6
    mask = engine.macro_action_mask(bm, npc)
    assert len(mask) == rpg.NPC_MACRO_KIND_COUNT == 11
    assert mask[int(K.Hide)] is False and mask[int(K.Attack)] is True and mask[int(K.Heal)] is False

    # A downed enemy is listed but can't be attacked; an incapacitated actor has nothing legal.
    _set_hp(engine, bm, far, 0)
    c = engine.get_agent_conditions(bm, far); c.unconscious = True; engine.set_agent_conditions(bm, far, c)
    assert not _find(engine.available_macro_actions(bm, npc), K.Attack, far).legal
    c = engine.get_agent_conditions(bm, npc); c.stunned = True; engine.set_agent_conditions(bm, npc, c)
    assert not any(a.legal for a in engine.available_macro_actions(bm, npc))
    print("✅ test_candidates_order_and_legality passed")


def test_spell_candidates():
    bm, engine = _board()
    npc = _add(bm, engine, "Cleric", 1, 1, 1)
    hurt = _add(bm, engine, "Hurt", 2, 1, 1, hp=40)
    fine = _add(bm, engine, "Fine", 3, 1, 1, hp=40)
    foe = _add(bm, engine, "Foe", 8, 8, 2)
    engine.set_agent_spells(bm, npc, [
        _aoe_cantrip(),                                                        # 0: AoE
        _control_spell("Hold Person", rpg.SpellGeometry.Single, "Paralyzed"),  # 1: Control
        _heal_spell("Cure Wounds"),                                            # 2: Heal
        _buff_spell()])                                                        # 3: Support
    _set_hp(engine, bm, hurt, 35)        # barely scratched: Level 4 wouldn't heal it, a policy may
    acts = engine.available_macro_actions(bm, npc)

    aoe = _find(acts, K.AoE, foe, 0)
    assert aoe.legal and (aoe.target_cell.col, aoe.target_cell.row) == (8, 8)
    assert _find(acts, K.Control, foe, 1).legal, "casts are legal out of range (the executor closes)"
    assert _find(acts, K.Heal, hurt, 2).legal
    assert not _find(acts, K.Heal, fine, 2).legal, "a full-HP ally is no heal target"
    assert _find(acts, K.Heal, npc, 2) is not None, "self is a heal candidate"
    assert _find(acts, K.Support, fine, 3).legal

    # An ally already carrying the buff is no longer a Support target.
    engine.execute_macro_action(bm, npc, _find(acts, K.Support, fine, 3))
    assert not _find(engine.available_macro_actions(bm, npc), K.Support, fine, 3).legal
    print("✅ test_spell_candidates passed")


# ── Execution ───────────────────────────────────────────────────────────────────

def test_attack_forced_target():
    """Attack(far) swings at the chosen enemy even with another one adjacent; Level 4 would hit the
    adjacent one."""
    bm, engine = _board()
    npc = _add(bm, engine, "Npc", 5, 5, 1)
    near = _add(bm, engine, "Near", 6, 5, 2)
    far = _add(bm, engine, "Far", 5, 8, 2)
    _arm_melee(engine, bm, npc)
    calls = _hooked(engine)
    engine.begin_turn(bm, npc)
    act = _find(engine.available_macro_actions(bm, npc), K.Attack, far)
    assert _drive(engine, bm, npc, lambda: engine.execute_macro_action(bm, npc, act)) \
        == rpg.FlowStatus.Completed
    assert calls and all(t == far for _, t in calls), calls
    assert _fp_dist(bm, npc, far) == 1
    print("✅ test_attack_forced_target passed")


def test_attack_unreachable_target_dashes_instead_of_retargeting():
    bm, engine = _board()
    npc = _add(bm, engine, "Npc", 1, 1, 1)
    near = _add(bm, engine, "Near", 2, 1, 2)
    far = _add(bm, engine, "Far", 11, 11, 2)
    _arm_melee(engine, bm, npc)
    _speed(engine, bm, npc, 10)
    calls = _hooked(engine)
    before = _fp_dist(bm, npc, far)
    engine.begin_turn(bm, npc)
    act = _find(engine.available_macro_actions(bm, npc), K.Attack, far)
    _drive(engine, bm, npc, lambda: engine.execute_macro_action(bm, npc, act))
    assert calls == [], "the forced target is out of reach: no swing at the adjacent enemy"
    assert engine.get_agent_conditions(bm, npc).dashing
    assert _fp_dist(bm, npc, far) < before
    assert near >= 0
    print("✅ test_attack_unreachable_target_dashes_instead_of_retargeting passed")


def test_kite_forced_target():
    bm, engine = _board()
    npc = _add(bm, engine, "Archer", 5, 5, 1)
    weak = _add(bm, engine, "Weak", 8, 5, 2, hp=5)
    tough = _add(bm, engine, "Tough", 5, 8, 2, hp=50)
    _arm_ranged(engine, bm, npc)
    calls = _hooked(engine)
    engine.begin_turn(bm, npc)
    act = _find(engine.available_macro_actions(bm, npc), K.Kite, tough)
    _drive(engine, bm, npc, lambda: engine.execute_macro_action(bm, npc, act))
    assert calls and all(t == tough for _, t in calls), "Level 4 would focus the weak one; the policy chose"
    assert weak >= 0
    print("✅ test_kite_forced_target passed")


def test_heal_and_control_forced_targets():
    bm, engine = _board()
    npc = _add(bm, engine, "Cleric", 1, 1, 1)
    worst = _add(bm, engine, "Worst", 2, 1, 1, hp=40)
    other = _add(bm, engine, "Other", 3, 1, 1, hp=40)
    foe1 = _add(bm, engine, "Foe1", 4, 4, 2)
    foe2 = _add(bm, engine, "Foe2", 6, 6, 2)
    engine.set_agent_spells(bm, npc, [_heal_spell("Cure Wounds", num_dice=0, bonus=10),
                                      _control_spell("Hold Person", rpg.SpellGeometry.Single, "Paralyzed")])
    _set_hp(engine, bm, worst, 2)
    _set_hp(engine, bm, other, 30)

    engine.begin_turn(bm, npc)
    act = _find(engine.available_macro_actions(bm, npc), K.Heal, other, 0)
    _drive(engine, bm, npc, lambda: engine.execute_macro_action(bm, npc, act))
    assert engine.get_agent_stats(bm, other).hp_cur == 40, "the chosen ally is healed"
    assert engine.get_agent_stats(bm, worst).hp_cur == 2, "not Level 4's neediest pick"

    engine.begin_turn(bm, npc)
    act = _find(engine.available_macro_actions(bm, npc), K.Control, foe2, 1)
    _drive(engine, bm, npc, lambda: engine.execute_macro_action(bm, npc, act))
    assert engine.get_agent_conditions(bm, foe2).paralyzed
    assert not engine.get_agent_conditions(bm, foe1).paralyzed, "Level 4 would hold the nearest"
    print("✅ test_heal_and_control_forced_targets passed")


def test_cast_out_of_range_closes_first():
    """A Control cast on a target beyond the spell's range approaches, then casts."""
    bm, engine = _board()
    npc = _add(bm, engine, "Mage", 1, 1, 1)
    foe = _add(bm, engine, "Foe", 8, 1, 2)
    engine.set_agent_spells(bm, npc, [_control_spell("Hold Person", rpg.SpellGeometry.Single,
                                                     "Paralyzed", range_ft=15)])
    before = _fp_dist(bm, npc, foe)
    engine.begin_turn(bm, npc)
    act = _find(engine.available_macro_actions(bm, npc), K.Control, foe, 0)
    assert act.legal
    _drive(engine, bm, npc, lambda: engine.execute_macro_action(bm, npc, act))
    assert _fp_dist(bm, npc, foe) < before
    assert engine.get_agent_conditions(bm, foe).paralyzed
    print("✅ test_cast_out_of_range_closes_first passed")


def test_aoe_forced_aim():
    """AoE aimed at the lone foe, not the pair Level 4 would catch."""
    bm, engine = _board()
    npc = _add(bm, engine, "Mage", 1, 1, 1)
    lone = _add(bm, engine, "Lone", 1, 6, 2)
    p1 = _add(bm, engine, "P1", 6, 1, 2)
    p2 = _add(bm, engine, "P2", 6, 2, 2)
    engine.set_agent_spells(bm, npc, [_aoe_cantrip(radius_ft=5, range_ft=60)])
    engine.begin_turn(bm, npc)
    act = _find(engine.available_macro_actions(bm, npc), K.AoE, lone, 0)
    _drive(engine, bm, npc, lambda: engine.execute_macro_action(bm, npc, act))
    assert engine.get_agent_stats(bm, lone).hp_cur < 30
    assert engine.get_agent_stats(bm, p1).hp_cur == 30 and engine.get_agent_stats(bm, p2).hp_cur == 30
    print("✅ test_aoe_forced_aim passed")


def test_move_only_macros():
    def setup():
        bm, engine = _board()
        npc = _add(bm, engine, "Npc", 5, 5, 1)
        foe = _add(bm, engine, "Foe", 6, 5, 2)
        _arm_melee(engine, bm, foe)
        _speed(engine, bm, npc, 15)
        engine.begin_turn(bm, npc)
        return bm, engine, npc, foe

    bm, engine, npc, foe = setup()
    calls = _hooked(engine)
    assert engine.execute_macro_action(bm, npc, rpg.NpcMacroAction(K.Dodge)) == rpg.FlowStatus.Completed
    assert engine.get_agent_conditions(bm, npc).dodging and calls == []
    assert _fp_dist(bm, npc, foe) == 1

    bm, engine, npc, foe = setup()
    st = engine.execute_macro_action(bm, npc, rpg.NpcMacroAction(K.Disengage))
    assert st == rpg.FlowStatus.Completed, "a Disengaging creature provokes no opportunity attack"
    assert engine.get_agent_conditions(bm, npc).disengaging
    assert _fp_dist(bm, npc, foe) == 4, "a 15 ft move straight away"

    bm, engine, npc, foe = setup()
    act = rpg.NpcMacroAction(K.Flee)
    _drive(engine, bm, npc, lambda: engine.execute_macro_action(bm, npc, act))
    assert engine.get_agent_conditions(bm, npc).dashing
    assert _fp_dist(bm, npc, foe) > 4, "Flee dashes: farther than one move"

    bm, engine = _board()
    npc = _add(bm, engine, "Npc", 1, 1, 1)
    foe = _add(bm, engine, "Foe", 11, 11, 2)
    _speed(engine, bm, npc, 15)
    before = _fp_dist(bm, npc, foe)
    engine.begin_turn(bm, npc)
    calls = _hooked(engine)
    act = _find(engine.available_macro_actions(bm, npc), K.Dash, foe)
    engine.execute_macro_action(bm, npc, act)
    assert engine.get_agent_conditions(bm, npc).dashing
    # Diagonals alternate 5/10 ft: a plain 15 ft move closes 2 cells, the dashed 30 ft more.
    assert before - _fp_dist(bm, npc, foe) >= 3
    assert calls == []
    print("✅ test_move_only_macros passed")


# ── The policy seam ─────────────────────────────────────────────────────────────

def test_policy_rungs_and_decision():
    bm, engine = _board()
    npc = _add(bm, engine, "Npc", 5, 5, 1)
    near = _add(bm, engine, "Near", 6, 5, 2)
    far = _add(bm, engine, "Far", 5, 8, 2)
    _arm_melee(engine, bm, npc)
    _automate(bm, npc)
    bm.set_agent_npc_automation_difficulty(npc, 5)
    seen = []

    def pick(*wanted):
        def rank(idx, archetype, actions):
            seen.append((idx, archetype, len(actions)))
            out = []
            for kind, tgt in wanted:
                out += [i for i, a in enumerate(actions) if a.kind == kind and a.target_agent == tgt]
            return out
        return rank

    assert not engine.npc_policy_loaded()
    engine.set_npc_policy(pick((K.Attack, far)))
    assert engine.npc_policy_loaded() and engine.npc_models_loaded()
    d = engine.npc_decide(bm, npc)
    assert (d.rung, d.strategy, d.has_macro) == (R.TreeTop, S.Policy, True)
    assert (d.macro.kind, d.macro.target_agent) == (K.Attack, far)
    assert d.macro_text == "Attack → Far", d.macro_text
    assert seen[-1][:2] == (npc, A.Melee)

    # An illegal top pick (Hide, no stealth tools) → rung 2; an out-of-range index is skipped too.
    engine.set_npc_policy(lambda i, a, acts: [999, next(k for k, x in enumerate(acts) if x.kind == K.Hide),
                                              next(k for k, x in enumerate(acts) if x.kind == K.Dodge)])
    d = engine.npc_decide(bm, npc)
    assert (d.rung, d.macro.kind) == (R.TreeRanked, K.Dodge)

    # Nothing legal → the Step 4 chain from rung 3 (Melee → Simple).
    engine.set_npc_policy(lambda i, a, acts: [])
    d = engine.npc_decide(bm, npc)
    assert (d.rung, d.strategy, d.has_macro) == (R.Archetype, S.Simple, False)

    # Through run_npc_turn: the policy's target is hit, and the decision is kept.
    engine.set_npc_policy(pick((K.Attack, far)))
    calls = _hooked(engine)
    engine.begin_turn(bm, npc)
    _drive(engine, bm, npc, lambda: engine.run_npc_turn(bm, npc))
    assert calls and all(t == far for _, t in calls)
    last = engine.last_npc_decision()
    assert (last.strategy, last.macro.target_agent) == (S.Policy, far)

    # Levels 1-4 never consult it; clearing it restores the Level 4 clamp.
    bm.set_agent_npc_automation_difficulty(npc, 4)
    n = len(seen)
    assert engine.npc_decide(bm, npc).rung == R.Heuristic and len(seen) == n
    engine.clear_npc_policy()
    bm.set_agent_npc_automation_difficulty(npc, 5)
    assert engine.npc_decide(bm, npc).rung == R.Heuristic
    assert near >= 0
    print("✅ test_policy_rungs_and_decision passed")


def test_policy_strategy_at_level0():
    """The manual Policy strategy asks the policy; with none installed it fights Simple."""
    bm, engine = _board()
    npc = _add(bm, engine, "Npc", 5, 5, 1)
    _add(bm, engine, "Foe", 6, 5, 2)
    _automate(bm, npc, S.Policy)
    assert engine.npc_decide(bm, npc).strategy == S.Simple
    engine.set_npc_policy(lambda i, a, acts: [k for k, x in enumerate(acts) if x.kind == K.Dodge])
    d = engine.npc_decide(bm, npc)
    assert (d.strategy, d.macro.kind, d.level) == (S.Policy, K.Dodge, 0)
    print("✅ test_policy_strategy_at_level0 passed")


def test_policy_error_propagates():
    bm, engine = _board()
    npc = _add(bm, engine, "Npc", 5, 5, 1)
    _add(bm, engine, "Foe", 6, 5, 2)
    _automate(bm, npc)
    bm.set_agent_npc_automation_difficulty(npc, 5)

    def broken(i, a, acts):
        raise RuntimeError("policy blew up")
    engine.set_npc_policy(broken)
    for call in (lambda: engine.npc_decide(bm, npc), lambda: engine.run_npc_turn(bm, npc)):
        try:
            call()
        except RuntimeError as e:
            assert "policy blew up" in str(e)
        else:
            raise AssertionError("the policy's exception was swallowed")
    engine.set_npc_policy(lambda i, a, acts: [])
    assert engine.npc_decide(bm, npc).rung == R.Archetype, "a stale error is not re-raised"
    print("✅ test_policy_error_propagates passed")


def test_policy_turn_parks_and_resumes_with_its_macro():
    """A Policy Flee from an armed, adjacent foe parks on the opportunity attack. The parked turn's
    macro is in the snapshot; the resume finishes it without asking the policy again."""
    bm, engine = _board()
    npc = _add(bm, engine, "Npc", 5, 5, 1)
    foe = _add(bm, engine, "Foe", 6, 5, 2)
    _arm_melee(engine, bm, foe)
    _speed(engine, bm, npc, 30)
    _automate(bm, npc)
    bm.set_agent_npc_automation_difficulty(npc, 5)
    asked = []

    def flee(i, a, acts):
        asked.append(i)
        return [k for k, x in enumerate(acts) if x.kind == K.Flee]
    engine.set_npc_policy(flee)
    engine.begin_turn(bm, npc)
    st = engine.run_npc_turn(bm, npc)
    assert st == rpg.FlowStatus.AwaitingDecision, "fleeing out of reach provokes the foe's OA"
    turn = json.loads(engine.snapshot_json())["npc_turn"]
    assert turn["has_macro"] and turn["macro"]["kind"] == int(K.Flee), turn
    assert turn["resolved_strategy"] == int(S.Policy)

    resp = rpg.ReactionResponse()
    resp.option = -1                                  # Skip the OA; the move then resolves
    engine.submit_decision(bm, resp)
    _drive(engine, bm, npc, lambda: engine.run_npc_turn(bm, npc))
    assert asked == [npc], "the resume reuses the stamped macro"
    assert _fp_dist(bm, npc, foe) > 1
    assert not engine.pending_decision().active
    print("✅ test_policy_turn_parks_and_resumes_with_its_macro passed")


# ── Level 4 as a macro-action (Step 6's label) ──────────────────────────────────

def test_heuristic_macro_labels():
    bm, engine = _board()
    npc = _add(bm, engine, "Npc", 5, 5, 1)
    near = _add(bm, engine, "Near", 6, 5, 2)
    _add(bm, engine, "Far", 9, 9, 2)
    _arm_melee(engine, bm, npc)
    lab = engine.npc_heuristic_macro_action(bm, npc)
    assert (lab.kind, lab.target_agent, lab.legal) == (K.Attack, near, True)

    bm, engine = _board()
    healer = _add(bm, engine, "Cleric", 1, 1, 1)
    hurt = _add(bm, engine, "Hurt", 2, 1, 1, hp=40)
    _add(bm, engine, "Foe", 8, 8, 2)
    engine.set_agent_spells(bm, healer, [_heal_spell("Cure Wounds")])
    _set_hp(engine, bm, hurt, 5)
    lab = engine.npc_heuristic_macro_action(bm, healer)
    assert (lab.kind, lab.target_agent, lab.spell_idx, lab.legal) == (K.Heal, hurt, 0, True)

    bm, engine = _board()
    mage = _add(bm, engine, "Mage", 1, 1, 1)
    foe = _add(bm, engine, "Foe", 6, 6, 2)
    engine.set_agent_spells(bm, mage, [_aoe_cantrip()])
    lab = engine.npc_heuristic_macro_action(bm, mage)
    assert (lab.kind, lab.target_agent, lab.spell_idx, lab.legal) == (K.AoE, foe, 0, True)
    assert engine.describe_macro_action(bm, mage, lab).startswith("AoE: ")

    bm, engine = _board()
    archer = _add(bm, engine, "Archer", 1, 1, 1)
    _add(bm, engine, "Tough", 4, 1, 2, hp=50)
    weak = _add(bm, engine, "Weak", 1, 6, 2, hp=5)
    _arm_ranged(engine, bm, archer)
    lab = engine.npc_heuristic_macro_action(bm, archer)
    assert (lab.kind, lab.target_agent) == (K.Kite, weak)
    print("✅ test_heuristic_macro_labels passed")


# ── Entity observation ──────────────────────────────────────────────────────────

def test_entity_observation():
    bm, engine = _board()
    npc = _add(bm, engine, "Npc", 5, 5, 1, hp=20)
    ally = _add(bm, engine, "Ally", 4, 5, 1)
    foe = _add(bm, engine, "Foe", 8, 5, 2, hp=40)
    gone = _add(bm, engine, "Gone", 9, 9, 2)
    _arm_melee(engine, bm, npc)
    _arm_melee(engine, bm, foe)
    _set_hp(engine, bm, foe, 10)
    c = engine.get_agent_conditions(bm, gone); c.dead = True; engine.set_agent_conditions(bm, gone, c)

    fields = rpg.CombatEngine.entity_observation_fields()
    mfields = rpg.CombatEngine.map_observation_fields()
    assert len(fields) == len(set(fields))
    obs = engine.get_entity_observation(bm, npc)
    assert obs.actor_idx == npc
    assert obs.agent_indices == [npc, ally, foe], "self first; the dead are left out"
    assert all(len(t) == len(fields) for t in obs.creature_tokens)
    assert len(obs.map_token) == len(mfields)
    assert all(math.isfinite(v) for t in obs.creature_tokens for v in t)
    assert all(math.isfinite(v) for v in obs.map_token)

    tok = {idx: dict(zip(fields, t)) for idx, t in zip(obs.agent_indices, obs.creature_tokens)}
    me, fr, en = tok[npc], tok[ally], tok[foe]
    assert (me["is_self"], me["is_ally"], me["is_enemy"]) == (1, 1, 0)
    assert (fr["is_self"], fr["is_ally"], en["is_enemy"]) == (0, 1, 1)
    assert en["arch_melee"] == 1 and en["perceived"] == 1
    assert abs(en["hp_frac"] - 0.25) < 1e-6
    assert abs(en["dx"] - 3 / 20) < 1e-6 and en["dy"] == 0 and abs(en["distance"] - 3 / 20) < 1e-6
    assert me["dx"] == 0 and me["distance"] == 0 and me["los"] == 1 and en["los"] == 1
    assert en["threatens_actor"] == 1 and en["actor_threatens"] == 1, "3 cells: a 30 ft move + 5 ft reach"
    assert me["threatens_actor"] == 0 and fr["actor_threatens"] == 0
    assert abs(en["melee_reach"] - 5 / 30) < 1e-6

    c = engine.get_agent_conditions(bm, foe); c.hidden = True; engine.set_agent_conditions(bm, foe, c)
    obs = engine.get_entity_observation(bm, npc)
    assert dict(zip(fields, obs.creature_tokens[2]))["perceived"] == 0
    print("✅ test_entity_observation passed")


# ── Trace, HUD and the arena ────────────────────────────────────────────────────

def test_macro_in_trace_and_hud():
    bm, engine = _board()
    npc = _add(bm, engine, "Npc", 5, 5, 1)
    foe = _add(bm, engine, "Goblin", 6, 5, 2)
    _automate(bm, npc)
    bm.set_agent_npc_automation_difficulty(npc, 5)
    engine.set_npc_policy(lambda i, a, acts: [k for k, x in enumerate(acts)
                                              if x.kind == K.Attack and x.target_agent == foe])
    d = engine.npc_decide(bm, npc)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.jsonl")
        w = sim_trace.TraceWriter(path, map_path="m.png", agents={"agents": []}, seed=1,
                                  npc_policy="l4-macro", pc_mode="Heuristic")
        w.begin_turn(round_num=0, actor=npc, actor_name="Npc", driver=sim_trace.DRIVER_NPC, snapshot={})
        w.set_decision(d)
        w.close({})
        tr = sim_trace.load_trace(path)
    dec = tr.turns[0].decision
    assert dec["strategy"] == "Policy" and dec["rung"] == "TreeTop"
    assert dec["macro"] == {"kind": "Attack", "target": foe, "cell": [6, 5], "spell": -1,
                            "text": "Attack → Goblin"}
    assert playback.decision_text(dec) == " · Melee: Attack → Goblin (rung 1 tree)"
    print("✅ test_macro_in_trace_and_hud passed")


def test_arena_macro_policies():
    """l4-macro runs Level 4's choices through the macro path, deterministically per seed, and every
    NPC decision it records is a policy pick; random-macro plays a fight to the end."""
    sc = arena.generate_scenario(3)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "ep.jsonl")
        a = arena.run_episode(sc, 3, "l4-macro", trace_path=path)
        tr = sim_trace.load_trace(path)
    b = arena.run_episode(sc, 3, "l4-macro")
    keep = ("winner", "reason", "rounds", "turns")
    assert {k: a[k] for k in keep} == {k: b[k] for k in keep}
    npc_decisions = [t.decision for t in tr.turns if t.decision and t.decision["level"] == 5]
    assert npc_decisions, "no NPC turn reached the resolver"
    assert all(d["strategy"] == "Policy" and d["rung"] == "TreeTop" for d in npc_decisions), \
        [d for d in npc_decisions if d["strategy"] != "Policy"][:3]
    pc_decisions = [t.decision for t in tr.turns if t.decision and t.decision["level"] == 4]
    assert all("macro" not in d for d in pc_decisions), "the PCs stay on Level 4"

    r = arena.run_episode(sc, 5, "random-macro")
    assert r["reason"] in ("victory", "round_cap")
    print("✅ test_arena_macro_policies passed")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"\nAll {len(tests)} NPC macro-action tests passed.")
