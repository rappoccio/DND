#!/usr/bin/env python3
"""
Test suite for the OnSaveFail reaction window on SPELL SAVES (ONSAVEFAIL_PLAN.md).

After a directly-targeted (Single/Multiple geometry) Save-type spell pre-rolls a target's save and it
FAILS, a creature may reroll it — "raising-only" (a reroll can only turn a failure into a success):
  · Countercharm (L7+ Bard)    — reroll an ally's failed Charmed/Frightened save WITH ADVANTAGE; costs
                                  the bard's reaction. The reactor may be the failed creature itself.
  · Indomitable  (L9+ Fighter) — reroll your OWN failed save + your Fighter level; costs 1 Indomitable
                                  use (NOT the reaction).
The window is pre-rolled in advanceCast and executeSpell consumes the (possibly rerolled) save, so a
flip to success means half/no damage and no condition — identical to the Shield consume contract.

Auto/RL tests drive resolve_cast with a scripted CombatDecider; GUI tests drive begin_cast →
pending_decision → submit_decision with NO decider installed (the path main.py uses). Saves are random,
so tests use the repo's retry-loop idiom.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


class SaveDecider(rpg.CombatDecider):
    """At an OnSaveFail window, pick the option whose feature == `feature` (None → always Skip).
    Records every window seen and counts OnSaveFail offers."""
    def __init__(self, feature):
        super().__init__()
        self.feature = feature
        self.windows = []
        self.savefail_offers = 0
    def choose_reaction(self, ctx):
        self.windows.append(ctx.window)
        resp = rpg.ReactionResponse(); resp.option = -1
        if ctx.window == rpg.ReactionWindow.OnSaveFail:
            self.savefail_offers += 1
            if self.feature:
                for i, o in enumerate(ctx.options):
                    if o.kind == rpg.ReactionOptionKind.Feature and o.feature == self.feature:
                        resp.option = i
                        break
        return resp


# ── Spell builders ────────────────────────────────────────────────────────────
def _cause_fear():
    """Single-target WIS-save spell that applies Frightened on a fail (the Countercharm trigger)."""
    sp = rpg.Spell(); sp.name = "Cause Fear"; sp.level = 1
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = rpg.SaveAbility.SaveWis
    sp.geometry = rpg.SpellGeometry.Single
    c = rpg.AttackCondition()
    c.condition_name = "Frightened"; c.requires_save = True
    c.save_ability = rpg.SaveAbility.SaveWis; c.condition_duration = 10
    sp.conditions = [c]
    return sp


def _no_condition_save_spell():
    """Single-target WIS-save spell with no condition and no damage (does NOT trigger Countercharm)."""
    sp = rpg.Spell(); sp.name = "Bland Save"; sp.level = 1
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = rpg.SaveAbility.SaveWis
    sp.geometry = rpg.SpellGeometry.Single
    return sp


# ── Agent builders (configure an already-placed agent) ────────────────────────
def _make_caster(engine, bm, idx, spell):
    """A high-DC save caster (CHA 18, prof 3 → spell save DC 15) that knows `spell`."""
    s = engine.get_agent_stats(bm, idx)
    s.cha = 18; s.prof_bonus = 3; s.spellcasting_ability = 5      # 5 = CHA
    s.spell_slots_remaining = [9, 0, 0, 0, 0, 0, 0, 0, 0]
    s.hp_max = 40; s.hp_cur = 40
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_spells(bm, idx, [spell])


def _make_weak_target(engine, bm, idx, wis=10):
    """A target that fails WIS saves often (mod 0, no proficiency)."""
    s = engine.get_agent_stats(bm, idx)
    s.wis = wis; s.save_prof_wis = False; s.prof_bonus = 2
    s.hp_max = 60; s.hp_cur = 60
    engine.set_agent_stats(bm, idx, s)


def _make_bard(engine, bm, idx, level=7, cha=16):
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Bard, level)
    s.cha = cha; s.prof_bonus = 3
    s.initialize_class_resources(rpg.CharacterClass.Bard, level)
    s.hp_max = 30; s.hp_cur = 30
    engine.set_agent_stats(bm, idx, s)


def _make_fighter_target(engine, bm, idx, level=9, wis=10):
    """A L9+ Fighter target (has the Indomitable resource) that fails WIS saves often."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Fighter, level)
    s.wis = wis; s.save_prof_wis = False; s.prof_bonus = 4
    s.initialize_class_resources(rpg.CharacterClass.Fighter, level)
    s.hp_max = 80; s.hp_cur = 80
    engine.set_agent_stats(bm, idx, s)


def _clear_frightened(engine, bm, idx):
    c = engine.get_agent_conditions(bm, idx)
    c.frightened = False; c.charmed = False; c.reaction_used = False; c.incapacitated = False
    engine.set_agent_conditions(bm, idx, c)


def _cast(engine, bm, caster, tgt, spell_idx=0):
    a = rpg.SpellAction(); a.caster_idx = caster; a.spell_idx = spell_idx; a.target_indices = [tgt]
    return a


# ── Auto/RL path (resolve_cast + scripted decider) ────────────────────────────
def test_countercharm_can_save():
    """A nearby L7 Bard is offered Countercharm on an ally's failed Frightened save; rerolling with
    advantage can flip the save to a success (→ no Frightened) and spends the bard's reaction."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    tgt    = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    bard   = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 7))
    _make_caster(engine, bm, caster, _cause_fear())
    _make_weak_target(engine, bm, tgt)
    _make_bard(engine, bm, bard)
    dec = SaveDecider("Countercharm"); engine.set_decider(dec)

    saw_window = saw_save = False
    for _ in range(400):
        _clear_frightened(engine, bm, tgt); _clear_frightened(engine, bm, bard)
        _make_bard(engine, bm, bard)                       # refill resources + reaction
        s = engine.get_agent_stats(bm, caster); s.spell_slots_remaining = [9,0,0,0,0,0,0,0,0]
        engine.set_agent_stats(bm, caster, s)
        before = dec.savefail_offers
        res = engine.resolve_cast(bm, _cast(engine, bm, caster, tgt))
        if dec.savefail_offers > before:                   # the window opened (the save failed)
            saw_window = True
            assert engine.get_agent_conditions(bm, bard).reaction_used, "Countercharm spends the reaction"
            saved = res.target_results[0].saved
            frightened = engine.get_agent_conditions(bm, tgt).frightened
            if saved:
                saw_save = True
                assert not frightened, "a flipped-to-success save applies no Frightened"
            else:
                assert frightened, "a still-failed save applies Frightened"
        if saw_window and saw_save:
            print("✅ test_countercharm_can_save passed")
            return
    assert False, "did not observe both a window and a flipped-to-success save in 400 casts"


def test_indomitable_self_reroll():
    """A L9 Fighter rerolls its OWN failed save (+ level), spending 1 Indomitable use, not the reaction."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    ftr    = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 6, 5))
    _make_caster(engine, bm, caster, _cause_fear())
    _make_fighter_target(engine, bm, ftr)
    dec = SaveDecider("Indomitable"); engine.set_decider(dec)

    saw_window = saw_save = False
    for _ in range(400):
        _clear_frightened(engine, bm, ftr)
        _make_fighter_target(engine, bm, ftr)              # refill Indomitable + reaction
        s = engine.get_agent_stats(bm, caster); s.spell_slots_remaining = [9,0,0,0,0,0,0,0,0]
        engine.set_agent_stats(bm, caster, s)
        ind_before = engine.get_agent_stats(bm, ftr).resources["Indomitable"].current
        before = dec.savefail_offers
        res = engine.resolve_cast(bm, _cast(engine, bm, caster, ftr))
        if dec.savefail_offers > before:
            saw_window = True
            assert engine.get_agent_stats(bm, ftr).resources["Indomitable"].current == ind_before - 1, \
                "Indomitable spends one use"
            assert not engine.get_agent_conditions(bm, ftr).reaction_used, \
                "Indomitable does NOT spend the reaction"
            if res.target_results[0].saved:
                saw_save = True
                assert not engine.get_agent_conditions(bm, ftr).frightened, \
                    "a flipped-to-success save applies no Frightened"
        if saw_window and saw_save:
            print("✅ test_indomitable_self_reroll passed")
            return
    assert False, "did not observe both a window and a flipped-to-success save in 400 casts"


def test_countercharm_not_offered_non_charm():
    """Countercharm is NOT offered on a save spell that applies no Charmed/Frightened condition."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    tgt    = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    bard   = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 7))
    _make_caster(engine, bm, caster, _no_condition_save_spell())
    _make_weak_target(engine, bm, tgt)
    _make_bard(engine, bm, bard)
    dec = SaveDecider("Countercharm"); engine.set_decider(dec)
    for _ in range(50):
        _clear_frightened(engine, bm, tgt); _clear_frightened(engine, bm, bard)
        s = engine.get_agent_stats(bm, caster); s.spell_slots_remaining = [9,0,0,0,0,0,0,0,0]
        engine.set_agent_stats(bm, caster, s)
        engine.resolve_cast(bm, _cast(engine, bm, caster, tgt))
    assert dec.savefail_offers == 0, "Countercharm must not be offered on a non-charm/frighten save spell"
    print("✅ test_countercharm_not_offered_non_charm passed")


def test_reaction_used_not_offered():
    """A bard whose reaction is already spent is not offered Countercharm."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    tgt    = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    bard   = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 7))
    _make_caster(engine, bm, caster, _cause_fear())
    _make_weak_target(engine, bm, tgt)
    _make_bard(engine, bm, bard)
    dec = SaveDecider("Countercharm"); engine.set_decider(dec)
    for _ in range(80):
        _clear_frightened(engine, bm, tgt)
        bc = engine.get_agent_conditions(bm, bard); bc.reaction_used = True   # reaction already spent
        engine.set_agent_conditions(bm, bard, bc)
        s = engine.get_agent_stats(bm, caster); s.spell_slots_remaining = [9,0,0,0,0,0,0,0,0]
        engine.set_agent_stats(bm, caster, s)
        engine.resolve_cast(bm, _cast(engine, bm, caster, tgt))
    assert dec.savefail_offers == 0, "a bard whose reaction is spent is never offered Countercharm"
    print("✅ test_reaction_used_not_offered passed")


def test_no_indomitable_use_not_offered():
    """A L9 Fighter with 0 Indomitable uses is not offered the reroll."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    ftr    = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 6, 5))
    _make_caster(engine, bm, caster, _cause_fear())
    _make_fighter_target(engine, bm, ftr)
    dec = SaveDecider("Indomitable"); engine.set_decider(dec)
    for _ in range(80):
        _clear_frightened(engine, bm, ftr)
        s = engine.get_agent_stats(bm, ftr); s.resources["Indomitable"].current = 0   # drain the resource
        engine.set_agent_stats(bm, ftr, s)
        cs = engine.get_agent_stats(bm, caster); cs.spell_slots_remaining = [9,0,0,0,0,0,0,0,0]
        engine.set_agent_stats(bm, caster, cs)
        engine.resolve_cast(bm, _cast(engine, bm, caster, ftr))
    assert dec.savefail_offers == 0, "no Indomitable uses → no reroll offered"
    print("✅ test_no_indomitable_use_not_offered passed")


# ── GUI suspend/resume path (begin_cast → pending_decision → submit_decision; NO decider) ──
def _feat_opt(ctx, feature):
    return next(i for i, o in enumerate(ctx.options)
               if o.kind == rpg.ReactionOptionKind.Feature and o.feature == feature)

def _skip_opt(ctx):
    return next(i for i, o in enumerate(ctx.options) if o.kind == rpg.ReactionOptionKind.Skip)

def _submit(engine, bm, option):
    resp = rpg.ReactionResponse(); resp.option = option
    return engine.submit_decision(bm, resp)


def test_gui_suspend_countercharm():
    """begin_cast parks at the OnSaveFail window on a failed save; submitting Countercharm spends the
    reaction and the rerolled save can flip to a success (no Frightened)."""
    bm = setup_battle_map(); engine = setup_combat_engine()      # no set_decider — GUI path
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    tgt    = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    bard   = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 7))
    _make_caster(engine, bm, caster, _cause_fear())
    _make_weak_target(engine, bm, tgt)
    _make_bard(engine, bm, bard)
    for _ in range(400):
        _clear_frightened(engine, bm, tgt); _clear_frightened(engine, bm, bard)
        _make_bard(engine, bm, bard)
        s = engine.get_agent_stats(bm, caster); s.spell_slots_remaining = [9,0,0,0,0,0,0,0,0]
        engine.set_agent_stats(bm, caster, s)
        status = engine.begin_cast(bm, _cast(engine, bm, caster, tgt))
        if status == rpg.FlowStatus.AwaitingDecision:
            pd = engine.pending_decision()
            assert pd.active and pd.ctx.window == rpg.ReactionWindow.OnSaveFail
            assert pd.ctx.reactor_idx == bard and pd.ctx.source_idx == tgt
            status = _submit(engine, bm, _feat_opt(pd.ctx, "Countercharm"))
            assert status == rpg.FlowStatus.Completed and not engine.pending_decision().active
            assert engine.get_agent_conditions(bm, bard).reaction_used, "Countercharm spent the reaction"
            res = engine.last_cast_result()
            if res.target_results[0].saved:
                assert not engine.get_agent_conditions(bm, tgt).frightened, "a flip applies no Frightened"
            print("✅ test_gui_suspend_countercharm passed")
            return
    assert False, "no OnSaveFail window parked in 400 begin_cast calls"


def test_gui_suspend_skip():
    """Submitting Skip spends nothing and the save stays failed → Frightened is applied."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    tgt    = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    bard   = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 7))
    _make_caster(engine, bm, caster, _cause_fear())
    _make_weak_target(engine, bm, tgt)
    _make_bard(engine, bm, bard)
    for _ in range(400):
        _clear_frightened(engine, bm, tgt); _clear_frightened(engine, bm, bard)
        _make_bard(engine, bm, bard)
        s = engine.get_agent_stats(bm, caster); s.spell_slots_remaining = [9,0,0,0,0,0,0,0,0]
        engine.set_agent_stats(bm, caster, s)
        status = engine.begin_cast(bm, _cast(engine, bm, caster, tgt))
        if status == rpg.FlowStatus.AwaitingDecision:
            status = _submit(engine, bm, _skip_opt(engine.pending_decision().ctx))
            assert status == rpg.FlowStatus.Completed
            assert not engine.get_agent_conditions(bm, bard).reaction_used, "Skip spends no reaction"
            res = engine.last_cast_result()
            assert not res.target_results[0].saved, "skipping the reroll → the save stays failed"
            assert engine.get_agent_conditions(bm, tgt).frightened, "a still-failed save applies Frightened"
            print("✅ test_gui_suspend_skip passed")
            return
    assert False, "no OnSaveFail window parked in 400 begin_cast calls"


def test_gui_multi_reactor_cursor():
    """Two eligible bards are both offered for one failed save, in index order; skipping advances."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    tgt    = add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    bard1  = add_agent_to_battle(engine, bm, create_test_agent("Bard1", 5, 7))
    bard2  = add_agent_to_battle(engine, bm, create_test_agent("Bard2", 7, 5))
    _make_caster(engine, bm, caster, _cause_fear())
    _make_weak_target(engine, bm, tgt)
    _make_bard(engine, bm, bard1); _make_bard(engine, bm, bard2)
    for _ in range(400):
        _clear_frightened(engine, bm, tgt)
        _make_bard(engine, bm, bard1); _make_bard(engine, bm, bard2)
        s = engine.get_agent_stats(bm, caster); s.spell_slots_remaining = [9,0,0,0,0,0,0,0,0]
        engine.set_agent_stats(bm, caster, s)
        status = engine.begin_cast(bm, _cast(engine, bm, caster, tgt))
        if status == rpg.FlowStatus.AwaitingDecision:
            seen = []
            while status == rpg.FlowStatus.AwaitingDecision:
                ctx = engine.pending_decision().ctx
                if ctx.window != rpg.ReactionWindow.OnSaveFail:
                    break
                seen.append(ctx.reactor_idx)
                status = _submit(engine, bm, _skip_opt(ctx))
            assert seen == [bard1, bard2], f"both bards offered in index order, got {seen}"
            print("✅ test_gui_multi_reactor_cursor passed")
            return
    assert False, "no OnSaveFail window parked in 400 begin_cast calls"


def run_all():
    test_countercharm_can_save()
    test_indomitable_self_reroll()
    test_countercharm_not_offered_non_charm()
    test_reaction_used_not_offered()
    test_no_indomitable_use_not_offered()
    test_gui_suspend_countercharm()
    test_gui_suspend_skip()
    test_gui_multi_reactor_cursor()
    print("\nAll OnSaveFail (Countercharm / Indomitable) tests passed ✅")


if __name__ == "__main__":
    run_all()
