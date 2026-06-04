#!/usr/bin/env python3
"""
Test suite for the Shield spell vs *attacks* via the OnHit window (ONDECLARECAST_PLAN.md, step 3a).

When a creature is hit by an attack, it may react by casting Shield (+5 AC). If the +5 turns the hit
into a miss, the attack deals no damage and fires no concentration save — the decision happens BEFORE
any HP changes (intercepted right after the attack roll, combat_attack.cpp), so there is no heal-back
and the "I shielded but still dropped" surprise is structurally impossible.

The first five tests exercise the auto/RL path (inline via a CombatDecider). The last three exercise
the GUI suspend/resume path (step 3b): begin_attack parks at the OnHit window (AwaitingDecision) with
no decider installed, and submit_decision routes the human's choice back, exactly as main.py does.

Because the d20 is random, tests use the repo's retry-loop idiom and classify each attack from
r.total_roll vs r.target_ac:
  · marginal hit (Shield could negate): r.hit and not r.critical and r.total_roll <  r.target_ac + 5
  · solid hit    (Shield can't negate): r.hit and not r.critical and r.total_roll >= r.target_ac + 5
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


class AttackShieldDecider(rpg.CombatDecider):
    """Reacts to an OnHit window by casting Shield (if cast=True) or skipping; records windows seen."""
    def __init__(self, cast):
        super().__init__()
        self._cast = cast
        self.windows = []
    def choose_reaction(self, ctx):
        self.windows.append(ctx.window)
        resp = rpg.ReactionResponse()
        resp.option = -1
        if self._cast:
            for i, o in enumerate(ctx.options):
                if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "Shield":
                    resp.option = i
                    break
        return resp


def _shield_spell():
    sp = rpg.Spell()
    sp.name = "Shield"
    sp.level = 1
    sp.geometry = rpg.SpellGeometry.Single
    return sp


def _setup(engine, bm, *, give_shield=True, l1_slots=2, ac=12):
    """Plain attacker with a Greataxe at (5,5); defender adjacent at (6,5) with Shield + L1 slots.
    base_ac=12 gives a healthy mix of marginal hits, solid hits, and misses across random rolls."""
    atk = add_agent_to_battle(engine, bm, create_test_agent("Atk", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Def", 6, 5))
    w = rpg.Weapon(); w.name = "Greataxe"; w.type = rpg.WeaponType.Melee; w.reach_ft = 5
    pr = rpg.PhysicalDamageRoll(); pr.type = rpg.PhysicalDamage.Slashing; pr.num_dice = 1; pr.die_size = 12
    w.physical_damage_types = [pr]
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])

    engine.set_agent_spells(bm, tgt, [_shield_spell()] if give_shield else [])
    ts = engine.get_agent_stats(bm, tgt)
    ts.base_ac = ac; ts.hp_max = 40; ts.hp_cur = 40
    ts.spell_slots_remaining = [l1_slots, 0, 0, 0, 0, 0, 0, 0, 0]
    engine.set_agent_stats(bm, tgt, ts)
    return atk, tgt


def _reset_defender(engine, bm, tgt, *, l1_slots=2, reaction_used=False):
    """Make each attack attempt independent: refill HP + L1 slot, clear an active Shield/reaction."""
    ts = engine.get_agent_stats(bm, tgt)
    ts.hp_cur = ts.hp_max
    ts.spell_slots_remaining = [l1_slots, 0, 0, 0, 0, 0, 0, 0, 0]
    ts.shield_active = False
    ts.ac_temporary_modifications = 0
    engine.set_agent_stats(bm, tgt, ts)
    c = engine.get_agent_conditions(bm, tgt); c.reaction_used = reaction_used
    engine.set_agent_conditions(bm, tgt, c)


def _hp(engine, bm, idx):    return engine.get_agent_stats(bm, idx).hp_cur
def _l1(engine, bm, idx):    return engine.get_agent_stats(bm, idx).spell_slots_remaining[0]
def _atk(engine, bm, a, t):  return engine.execute_action(bm, rpg.Attack(a, t, 0))


# ── Tests ────────────────────────────────────────────────────────────────────
def test_shield_negates_marginal_hit():
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt = _setup(engine, bm)
    dec = AttackShieldDecider(cast=True); engine.set_decider(dec)
    for _ in range(80):
        _reset_defender(engine, bm, tgt)
        before = len(dec.windows)
        r = _atk(engine, bm, atk, tgt)
        if len(dec.windows) > before:                      # the OnHit window opened (a marginal hit)
            assert rpg.ReactionWindow.OnHit in dec.windows
            assert not r.hit, "Shield (+5 AC) turns the marginal hit into a miss"
            assert _hp(engine, bm, tgt) == 40, "a negated hit deals no damage (no heal-back needed)"
            assert _l1(engine, bm, tgt) == 1, "Shield spends one L1 slot"
            assert engine.get_agent_conditions(bm, tgt).reaction_used, "Shield consumes the reaction"
            print("✅ test_shield_negates_marginal_hit passed")
            return
    assert False, "no marginal hit occurred in 80 attacks — setup can't open the window"


def test_declined_shield_takes_damage():
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt = _setup(engine, bm)
    dec = AttackShieldDecider(cast=False); engine.set_decider(dec)
    for _ in range(80):
        _reset_defender(engine, bm, tgt)
        before = len(dec.windows)
        r = _atk(engine, bm, atk, tgt)
        if len(dec.windows) > before:
            assert r.hit, "declining Shield → the marginal hit lands"
            assert _hp(engine, bm, tgt) < 40, "the hit deals damage"
            assert _l1(engine, bm, tgt) == 2 and not engine.get_agent_conditions(bm, tgt).reaction_used, \
                "skipping Shield spends nothing"
            print("✅ test_declined_shield_takes_damage passed")
            return
    assert False, "no marginal hit occurred in 80 attacks"


def test_solid_hit_not_offered_shield():
    """A solid hit (roll ≥ AC+5, which +5 AC could not negate) must NOT open the Shield window."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt = _setup(engine, bm)
    dec = AttackShieldDecider(cast=True); engine.set_decider(dec)
    for _ in range(120):
        _reset_defender(engine, bm, tgt)
        before = len(dec.windows)
        r = _atk(engine, bm, atk, tgt)
        if r.hit and not r.critical and r.total_roll >= r.target_ac + 5:
            assert len(dec.windows) == before, "a solid hit must not offer Shield (+5 wouldn't help)"
            assert r.hit and _hp(engine, bm, tgt) < 40, "the solid hit lands for damage"
            print("✅ test_solid_hit_not_offered_shield passed")
            return
    assert False, "no solid hit occurred in 120 attacks"


def test_no_shield_known_no_window():
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt = _setup(engine, bm, give_shield=False)
    dec = AttackShieldDecider(cast=True); engine.set_decider(dec)
    saw_marginal = False
    for _ in range(120):
        _reset_defender(engine, bm, tgt)
        r = _atk(engine, bm, atk, tgt)
        if r.hit and not r.critical and r.total_roll < r.target_ac + 5:
            saw_marginal = True  # a hit Shield *could* have negated, had the defender known it
    assert saw_marginal, "expected at least one marginal hit to prove the window would apply"
    assert dec.windows == [], "no Shield known → the OnHit window never opens"
    print("✅ test_no_shield_known_no_window passed")


def test_used_reaction_no_window():
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt = _setup(engine, bm)
    dec = AttackShieldDecider(cast=True); engine.set_decider(dec)
    saw_marginal = False
    for _ in range(120):
        _reset_defender(engine, bm, tgt, reaction_used=True)   # reaction already spent each attempt
        r = _atk(engine, bm, atk, tgt)
        if r.hit and not r.critical and r.total_roll < r.target_ac + 5:
            saw_marginal = True
    assert saw_marginal, "expected at least one marginal hit"
    assert dec.windows == [], "reaction already used → no Shield window"
    print("✅ test_used_reaction_no_window passed")


# ── GUI suspend/resume path (begin_attack → pending_decision → submit_decision, step 3b) ──────────
# No CombatDecider installed: the GUI expresses the human as submitted events, so begin_attack PARKS
# at the OnHit Shield window (AwaitingDecision) and the click is routed back via submit_decision.

def _shield_opt(ctx):
    return next(i for i, o in enumerate(ctx.options)
               if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "Shield")

def _skip_opt(ctx):
    return next(i for i, o in enumerate(ctx.options) if o.kind == rpg.ReactionOptionKind.Skip)

def _submit(engine, bm, option):
    resp = rpg.ReactionResponse(); resp.option = option
    return engine.submit_decision(bm, resp)


def test_begin_attack_suspend_shield_negates():
    """begin_attack parks at the OnHit window on a marginal hit; submit_decision(Shield) negates it."""
    bm = setup_battle_map(); engine = setup_combat_engine()   # NOTE: no set_decider — GUI path
    atk, tgt = _setup(engine, bm)
    for _ in range(120):
        _reset_defender(engine, bm, tgt)
        status = engine.begin_attack(bm, rpg.Attack(atk, tgt, 0))
        if status == rpg.FlowStatus.AwaitingDecision:
            pd = engine.pending_decision()
            assert pd.active and pd.ctx.window == rpg.ReactionWindow.OnHit
            assert pd.ctx.reactor_idx == tgt and pd.ctx.source_idx == atk
            status2 = _submit(engine, bm, _shield_opt(pd.ctx))
            assert status2 == rpg.FlowStatus.Completed
            assert not engine.pending_decision().active, "the engine is no longer parked"
            assert not engine.last_attack_result().hit, "Shield (+5 AC) turns the marginal hit into a miss"
            assert _hp(engine, bm, tgt) == 40, "a negated hit deals no damage"
            assert _l1(engine, bm, tgt) == 1, "Shield spends one L1 slot"
            assert engine.get_agent_conditions(bm, tgt).reaction_used, "Shield consumes the reaction"
            print("✅ test_begin_attack_suspend_shield_negates passed")
            return
    assert False, "no marginal hit parked the window in 120 begin_attack calls"


def test_begin_attack_suspend_skip_takes_damage():
    """Submitting Skip at the parked OnHit window lets the marginal hit land for damage, spends nothing."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt = _setup(engine, bm)
    for _ in range(120):
        _reset_defender(engine, bm, tgt)
        status = engine.begin_attack(bm, rpg.Attack(atk, tgt, 0))
        if status == rpg.FlowStatus.AwaitingDecision:
            status2 = _submit(engine, bm, _skip_opt(engine.pending_decision().ctx))
            assert status2 == rpg.FlowStatus.Completed
            assert engine.last_attack_result().hit, "skipping Shield → the hit lands"
            assert _hp(engine, bm, tgt) < 40, "the hit deals damage"
            assert _l1(engine, bm, tgt) == 2 and not engine.get_agent_conditions(bm, tgt).reaction_used, \
                "skipping Shield spends nothing"
            print("✅ test_begin_attack_suspend_skip_takes_damage passed")
            return
    assert False, "no marginal hit parked the window in 120 begin_attack calls"


def test_begin_attack_no_window_completes_directly():
    """A miss / solid hit / crit opens no window: begin_attack returns Completed and the result is set."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt = _setup(engine, bm)
    for _ in range(120):
        _reset_defender(engine, bm, tgt)
        hp_before = _hp(engine, bm, tgt)
        status = engine.begin_attack(bm, rpg.Attack(atk, tgt, 0))
        if status == rpg.FlowStatus.Completed:
            r = engine.last_attack_result()
            assert r.valid and not engine.pending_decision().active
            if r.hit:
                assert _hp(engine, bm, tgt) < hp_before, "a non-windowed hit applies damage"
            # No Shield offered → the defender's slot + reaction are untouched in every Completed case.
            assert _l1(engine, bm, tgt) == 2 and not engine.get_agent_conditions(bm, tgt).reaction_used
            print("✅ test_begin_attack_no_window_completes_directly passed")
            return
    assert False, "no Completed begin_attack in 120 calls"


def run_all():
    test_shield_negates_marginal_hit()
    test_declined_shield_takes_damage()
    test_solid_hit_not_offered_shield()
    test_no_shield_known_no_window()
    test_used_reaction_no_window()
    test_begin_attack_suspend_shield_negates()
    test_begin_attack_suspend_skip_takes_damage()
    test_begin_attack_no_window_completes_directly()
    print("\nAll Shield-vs-attack (OnHit: auto + GUI suspend/resume) tests passed ✅")


if __name__ == "__main__":
    run_all()
