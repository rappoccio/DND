#!/usr/bin/env python3
"""
Test suite for the Shield spell via the OnDeclareCast window (ONDECLARECAST_PLAN.md, step 1).

A creature targeted by Magic Missile may react by casting Shield → it takes no damage from the
Magic Missile, spends an L1+ slot + its reaction, and gains +5 AC until its next turn. Driven
headlessly through the cast interrupt (resolve_cast auto driver + begin_cast/submit_decision).
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


class ShieldDecider(rpg.CombatDecider):
    """Reacts to an OnDeclareCast window by casting Shield (if cast=True) or skipping."""
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


def _magic_missile():
    sp = rpg.Spell()
    sp.name = "Magic Missile"
    sp.level = 1
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.geometry = rpg.SpellGeometry.Multiple
    d = rpg.MagicDamageRoll(); d.type = rpg.MagicDamage.Force; d.num_dice = 1; d.die_size = 4; d.bonus = 1
    sp.magic_damage_rolls = [d]
    return sp


def _shield_spell():
    sp = rpg.Spell()
    sp.name = "Shield"
    sp.level = 1
    sp.geometry = rpg.SpellGeometry.Single
    return sp


def _setup(engine, bm, give_shield=True, l1_slots=2):
    """Caster with Magic Missile at (5,5); defender at (7,5) with Shield + L1 slots."""
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    defender = add_agent_to_battle(engine, bm, create_test_agent("Defender", 7, 5))
    # Set stats/spells AFTER both adds (apply_agent_configs resets the earlier agent).
    engine.set_agent_spells(bm, caster, [_magic_missile()])
    cs = engine.get_agent_stats(bm, caster)
    cs.spell_slots_remaining = [9, 0, 0, 0, 0, 0, 0, 0, 0]
    engine.set_agent_stats(bm, caster, cs)

    engine.set_agent_spells(bm, defender, [_shield_spell()] if give_shield else [])
    ds = engine.get_agent_stats(bm, defender)
    ds.hp_max = 40; ds.hp_cur = 40
    ds.spell_slots_remaining = [l1_slots, 0, 0, 0, 0, 0, 0, 0, 0]
    engine.set_agent_stats(bm, defender, ds)
    return caster, defender


def _mm_action(caster, defender):
    a = rpg.SpellAction()
    a.caster_idx = caster
    a.spell_idx = 0
    a.target_indices = [defender]
    return a


def _hp(engine, bm, idx):  return engine.get_agent_stats(bm, idx).hp_cur


# ── Tests ────────────────────────────────────────────────────────────────────
def test_shield_negates_magic_missile():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, defender = _setup(engine, bm)
    dec = ShieldDecider(cast=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _mm_action(caster, defender))

    assert rpg.ReactionWindow.OnDeclareCast in dec.windows, "Magic Missile should open OnDeclareCast"
    assert _hp(engine, bm, defender) == 40, "Shield → immune to Magic Missile (no damage)"
    ds = engine.get_agent_stats(bm, defender)
    assert ds.shield_active, "Shield should be active"
    assert ds.ac_temporary_modifications == 5, "Shield grants +5 AC"
    assert ds.spell_slots_remaining[0] == 1, "Shield spends one L1 slot"
    assert engine.get_agent_conditions(bm, defender).reaction_used, "Shield consumes the reaction"
    print("✅ test_shield_negates_magic_missile passed")


def test_skipped_shield_takes_full_damage():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, defender = _setup(engine, bm)
    dec = ShieldDecider(cast=False); engine.set_decider(dec)
    engine.resolve_cast(bm, _mm_action(caster, defender))

    assert rpg.ReactionWindow.OnDeclareCast in dec.windows, "the window is still offered"
    assert _hp(engine, bm, defender) < 40, "declining Shield → takes Magic Missile damage"
    ds = engine.get_agent_stats(bm, defender)
    assert not ds.shield_active and ds.spell_slots_remaining[0] == 2, "skip spends nothing"
    assert not engine.get_agent_conditions(bm, defender).reaction_used
    print("✅ test_skipped_shield_takes_full_damage passed")


def test_no_shield_spell_no_window():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, defender = _setup(engine, bm, give_shield=False)
    dec = ShieldDecider(cast=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _mm_action(caster, defender))
    assert dec.windows == [], "no Shield known → no OnDeclareCast window"
    assert _hp(engine, bm, defender) < 40, "takes Magic Missile damage"
    print("✅ test_no_shield_spell_no_window passed")


def test_no_slot_no_window():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, defender = _setup(engine, bm, l1_slots=0)
    dec = ShieldDecider(cast=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _mm_action(caster, defender))
    assert dec.windows == [], "no L1 slot → can't cast Shield → no window"
    assert _hp(engine, bm, defender) < 40
    print("✅ test_no_slot_no_window passed")


def test_used_reaction_no_window():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, defender = _setup(engine, bm)
    c = engine.get_agent_conditions(bm, defender); c.reaction_used = True
    engine.set_agent_conditions(bm, defender, c)
    dec = ShieldDecider(cast=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _mm_action(caster, defender))
    assert dec.windows == [], "reaction already used → no Shield window"
    assert _hp(engine, bm, defender) < 40
    print("✅ test_used_reaction_no_window passed")


def test_begin_submit_suspend_resume_path():
    """GUI path: begin_cast parks at the Shield checkpoint; submit_decision resolves it."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, defender = _setup(engine, bm)  # no decider installed → interactive suspend
    status = engine.begin_cast(bm, _mm_action(caster, defender))
    assert status == rpg.FlowStatus.AwaitingDecision, f"expected suspend, got {status}"
    pd = engine.pending_decision()
    assert pd.active and pd.ctx.window == rpg.ReactionWindow.OnDeclareCast
    assert pd.ctx.reactor_idx == defender
    # Choose the Shield option.
    opt = next(i for i, o in enumerate(pd.ctx.options)
               if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "Shield")
    resp = rpg.ReactionResponse(); resp.option = opt
    status = engine.submit_decision(bm, resp)
    assert status == rpg.FlowStatus.Completed
    assert _hp(engine, bm, defender) == 40, "Shield negated the Magic Missile"
    assert engine.get_agent_stats(bm, defender).shield_active
    print("✅ test_begin_submit_suspend_resume_path passed")


def test_shield_ac_clears_at_next_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, defender = _setup(engine, bm)
    dec = ShieldDecider(cast=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _mm_action(caster, defender))
    assert engine.get_agent_stats(bm, defender).ac_temporary_modifications == 5
    engine.begin_turn(bm, defender)
    ds = engine.get_agent_stats(bm, defender)
    assert not ds.shield_active, "Shield ends at the start of your next turn"
    assert ds.ac_temporary_modifications == 0, "the +5 AC is removed"
    print("✅ test_shield_ac_clears_at_next_turn passed")


def run_all():
    test_shield_negates_magic_missile()
    test_skipped_shield_takes_full_damage()
    test_no_shield_spell_no_window()
    test_no_slot_no_window()
    test_used_reaction_no_window()
    test_begin_submit_suspend_resume_path()
    test_shield_ac_clears_at_next_turn()
    print("\nAll Shield (OnDeclareCast) tests passed ✅")


if __name__ == "__main__":
    run_all()
