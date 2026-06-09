#!/usr/bin/env python3
"""
Test suite for the Shield spell vs *spell attacks* via the OnHit window. This is the spell analog of test_shield_vs_attack.py.

executeSpell's per-target to-hit roll was extracted into rollSpellAttack so a single-target attack
spell (Fire Bolt, Guiding Bolt, Chromatic Orb, Ray of Frost…) can offer the target a reactive Shield
between the attack roll and damage — exactly like a weapon attack. If the +5 AC turns the hit into a
miss, the spell deals no damage and fires no concentration save (the roll the player saw is the one
that lands — executeSpell consumes the pre-rolled to-hit).

Three behaviours are covered:
  · Auto/RL path (a CombatDecider is installed) — single-target, driven by resolve_cast: the inline
    maybeDefenderShieldInlineSpell asks the decider at the OnHit window.
  · GUI suspend path (no decider) — single-target, driven by begin_cast: it PARKS at the OnHit window
    (AwaitingDecision) and submit_decision routes the human's choice back, as main.py does.
  · GUI multi-beam (no decider) — a multi-target attack spell auto-fires Shield inline (no per-beam
    decision cursor yet; documented in known_limitations.md).

Because the d20 is random, tests use the repo's retry-loop idiom and classify each hit from
total_roll vs target_ac (marginal = Shield could negate: hit, not crit, total < ac + 5).
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


class SpellShieldDecider(rpg.CombatDecider):
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


def _firebolt(num_targets=1):
    sp = rpg.Spell()
    sp.name = "Fire Bolt"
    sp.level = 0
    sp.attack_type = rpg.SpellAttack.AttackRoll
    sp.geometry = rpg.SpellGeometry.Single if num_targets == 1 else rpg.SpellGeometry.Multiple
    sp.range = 120
    sp.num_targets = num_targets
    d = rpg.MagicDamageRoll(); d.type = rpg.MagicDamage.Fire; d.num_dice = 1; d.die_size = 10; d.bonus = 0
    sp.magic_damage_rolls = [d]
    return sp


def _shield_spell():
    sp = rpg.Spell()
    sp.name = "Shield"
    sp.level = 1
    sp.geometry = rpg.SpellGeometry.Single
    return sp


def _setup(engine, bm, *, give_shield=True, l1_slots=2, ac=13, num_targets=1):
    """Caster with Fire Bolt at (5,5); defender well away at (10,5) (no engagement disadvantage), with
    Shield + L1 slots. The caster's +5 spell-attack mod vs base_ac 13 yields a mix of marginal/solid/miss."""
    cst = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Def", 10, 5))
    engine.set_agent_spells(bm, cst, [_firebolt(num_targets)])
    cs = engine.get_agent_stats(bm, cst)
    cs.intel = 16; cs.spellcasting_ability = 3; cs.prof_bonus = 2   # spellAttackMod = +5
    cs.spell_slots_remaining = [9, 9, 9, 9, 9, 0, 0, 0, 0]
    engine.set_agent_stats(bm, cst, cs)

    engine.set_agent_spells(bm, tgt, [_shield_spell()] if give_shield else [])
    ts = engine.get_agent_stats(bm, tgt)
    ts.base_ac = ac; ts.hp_max = 40; ts.hp_cur = 40
    ts.spell_slots_remaining = [l1_slots, 0, 0, 0, 0, 0, 0, 0, 0]
    engine.set_agent_stats(bm, tgt, ts)
    return cst, tgt


def _reset_defender(engine, bm, tgt, *, l1_slots=2, reaction_used=False):
    """Make each cast attempt independent: refill HP + L1 slot, clear an active Shield/reaction."""
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
def _used(engine, bm, idx):  return engine.get_agent_conditions(bm, idx).reaction_used

def _cast_action(cst, tgt, *, beams=1):
    a = rpg.SpellAction()
    a.caster_idx = cst
    a.spell_idx = 0
    a.target_indices = [tgt] * beams
    return a


# ── Auto/RL path (decider installed, single-target, resolve_cast) ─────────────────────────────────
def test_decider_shield_negates_marginal_spell_hit():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cst, tgt = _setup(engine, bm)
    dec = SpellShieldDecider(cast=True); engine.set_decider(dec)
    for _ in range(120):
        _reset_defender(engine, bm, tgt)
        before = len(dec.windows)
        engine.resolve_cast(bm, _cast_action(cst, tgt))
        if len(dec.windows) > before:                          # the OnHit window opened (a marginal hit)
            r = engine.last_cast_result().target_results[0]
            assert dec.windows[-1] == rpg.ReactionWindow.OnHit
            assert not r.hit, "Shield (+5 AC) turns the marginal spell hit into a miss"
            assert _hp(engine, bm, tgt) == 40, "a negated spell hit deals no damage"
            assert _l1(engine, bm, tgt) == 1, "Shield spends one L1 slot"
            assert _used(engine, bm, tgt), "Shield consumes the reaction"
            print("✅ test_decider_shield_negates_marginal_spell_hit passed")
            return
    assert False, "no marginal spell hit occurred in 120 casts — setup can't open the window"


def test_decider_declined_shield_spell_takes_damage():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cst, tgt = _setup(engine, bm)
    dec = SpellShieldDecider(cast=False); engine.set_decider(dec)
    for _ in range(120):
        _reset_defender(engine, bm, tgt)
        before = len(dec.windows)
        engine.resolve_cast(bm, _cast_action(cst, tgt))
        if len(dec.windows) > before:
            r = engine.last_cast_result().target_results[0]
            assert r.hit, "declining Shield → the marginal spell hit lands"
            assert _hp(engine, bm, tgt) < 40, "the spell hit deals damage"
            assert _l1(engine, bm, tgt) == 2 and not _used(engine, bm, tgt), "skipping Shield spends nothing"
            print("✅ test_decider_declined_shield_spell_takes_damage passed")
            return
    assert False, "no marginal spell hit occurred in 120 casts"


def test_solid_spell_hit_not_offered_shield():
    """A solid spell hit (roll ≥ AC+5) must NOT open the Shield window."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cst, tgt = _setup(engine, bm)
    dec = SpellShieldDecider(cast=True); engine.set_decider(dec)
    for _ in range(160):
        _reset_defender(engine, bm, tgt)
        before = len(dec.windows)
        engine.resolve_cast(bm, _cast_action(cst, tgt))
        r = engine.last_cast_result().target_results[0]
        if r.hit and not r.critical and r.total_roll >= r.target_ac + 5:
            assert len(dec.windows) == before, "a solid spell hit must not offer Shield (+5 wouldn't help)"
            assert _hp(engine, bm, tgt) < 40, "the solid spell hit lands for damage"
            print("✅ test_solid_spell_hit_not_offered_shield passed")
            return
    assert False, "no solid spell hit occurred in 160 casts"


def test_no_shield_known_no_spell_window():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cst, tgt = _setup(engine, bm, give_shield=False)
    dec = SpellShieldDecider(cast=True); engine.set_decider(dec)
    saw_marginal = False
    for _ in range(160):
        _reset_defender(engine, bm, tgt)
        engine.resolve_cast(bm, _cast_action(cst, tgt))
        r = engine.last_cast_result().target_results[0]
        if r.hit and not r.critical and r.total_roll < r.target_ac + 5:
            saw_marginal = True   # a hit Shield *could* have negated, had the defender known it
    assert saw_marginal, "expected at least one marginal spell hit to prove the window would apply"
    assert dec.windows == [], "no Shield known → the OnHit window never opens"
    print("✅ test_no_shield_known_no_spell_window passed")


# ── GUI suspend/resume path (begin_cast → pending_decision → submit_decision, single-target) ───────
def _shield_opt(ctx):
    return next(i for i, o in enumerate(ctx.options)
               if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "Shield")

def _skip_opt(ctx):
    return next(i for i, o in enumerate(ctx.options) if o.kind == rpg.ReactionOptionKind.Skip)

def _submit(engine, bm, option):
    resp = rpg.ReactionResponse(); resp.option = option
    return engine.submit_decision(bm, resp)


def test_begin_cast_suspend_shield_negates_spell():
    """begin_cast parks at the OnHit window on a marginal spell hit; submit_decision(Shield) negates it."""
    bm = setup_battle_map(); engine = setup_combat_engine()   # NOTE: no set_decider — GUI path
    cst, tgt = _setup(engine, bm)
    for _ in range(160):
        _reset_defender(engine, bm, tgt)
        status = engine.begin_cast(bm, _cast_action(cst, tgt))
        if status == rpg.FlowStatus.AwaitingDecision:
            pd = engine.pending_decision()
            assert pd.active and pd.ctx.window == rpg.ReactionWindow.OnHit
            assert pd.ctx.reactor_idx == tgt and pd.ctx.source_idx == cst
            assert pd.ctx.spell_idx == 0, "the OnHit window carries the spell index (vs a weapon attack)"
            status2 = _submit(engine, bm, _shield_opt(pd.ctx))
            assert status2 == rpg.FlowStatus.Completed
            assert not engine.pending_decision().active, "the engine is no longer parked"
            assert not engine.last_cast_result().target_results[0].hit, "Shield turns the spell hit into a miss"
            assert _hp(engine, bm, tgt) == 40, "a negated spell hit deals no damage"
            assert _l1(engine, bm, tgt) == 1, "Shield spends one L1 slot"
            assert _used(engine, bm, tgt), "Shield consumes the reaction"
            print("✅ test_begin_cast_suspend_shield_negates_spell passed")
            return
    assert False, "no marginal spell hit parked the window in 160 begin_cast calls"


def test_begin_cast_suspend_skip_spell_takes_damage():
    """Submitting Skip at the parked OnHit window lets the marginal spell hit land, spends nothing."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cst, tgt = _setup(engine, bm)
    for _ in range(160):
        _reset_defender(engine, bm, tgt)
        status = engine.begin_cast(bm, _cast_action(cst, tgt))
        if status == rpg.FlowStatus.AwaitingDecision:
            status2 = _submit(engine, bm, _skip_opt(engine.pending_decision().ctx))
            assert status2 == rpg.FlowStatus.Completed
            assert engine.last_cast_result().target_results[0].hit, "skipping Shield → the spell hit lands"
            assert _hp(engine, bm, tgt) < 40, "the spell hit deals damage"
            assert _l1(engine, bm, tgt) == 2 and not _used(engine, bm, tgt), "skipping Shield spends nothing"
            print("✅ test_begin_cast_suspend_skip_spell_takes_damage passed")
            return
    assert False, "no marginal spell hit parked the window in 160 begin_cast calls"


def test_begin_cast_no_window_completes_directly():
    """A miss / solid hit / crit opens no window: begin_cast returns Completed and the result is set."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cst, tgt = _setup(engine, bm)
    for _ in range(160):
        _reset_defender(engine, bm, tgt)
        status = engine.begin_cast(bm, _cast_action(cst, tgt))
        if status == rpg.FlowStatus.Completed:
            r = engine.last_cast_result().target_results[0]
            assert not engine.pending_decision().active
            # No Shield was offered/cast → the defender's slot + reaction are untouched.
            assert _l1(engine, bm, tgt) == 2 and not _used(engine, bm, tgt)
            print("✅ test_begin_cast_no_window_completes_directly passed")
            return
    assert False, "no Completed begin_cast in 160 calls"


# ── GUI multi-beam: no decider, no per-beam cursor → Shield auto-fires inline (documented) ─────────
def test_multibeam_gui_autofires_shield():
    """A 2-beam attack spell in the GUI (no decider) auto-casts the target's Shield on a marginal beam:
    begin_cast returns Completed (no suspend) and the defender's slot + reaction are spent."""
    bm = setup_battle_map(); engine = setup_combat_engine()   # no decider → GUI
    cst, tgt = _setup(engine, bm, num_targets=2)
    for _ in range(200):
        _reset_defender(engine, bm, tgt)
        status = engine.begin_cast(bm, _cast_action(cst, tgt, beams=2))
        assert status == rpg.FlowStatus.Completed, "multi-beam never suspends — Shield auto-fires inline"
        assert not engine.pending_decision().active
        if engine.get_agent_stats(bm, tgt).shield_active:      # a marginal beam triggered the auto-Shield
            assert _l1(engine, bm, tgt) == 1, "auto-Shield spends one L1 slot"
            assert _used(engine, bm, tgt), "auto-Shield consumes the reaction"
            print("✅ test_multibeam_gui_autofires_shield passed")
            return
    assert False, "no marginal beam auto-fired Shield in 200 two-beam casts"


def run_all():
    test_decider_shield_negates_marginal_spell_hit()
    test_decider_declined_shield_spell_takes_damage()
    test_solid_spell_hit_not_offered_shield()
    test_no_shield_known_no_spell_window()
    test_begin_cast_suspend_shield_negates_spell()
    test_begin_cast_suspend_skip_spell_takes_damage()
    test_begin_cast_no_window_completes_directly()
    test_multibeam_gui_autofires_shield()
    print("\nAll Shield-vs-spell-attack (OnHit: auto + GUI suspend + multi-beam auto-fire) tests passed ✅")


if __name__ == "__main__":
    run_all()
