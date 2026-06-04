#!/usr/bin/env python3
"""
Test suite for Counterspell via the OnDeclareCast window (ONDECLARECAST_PLAN.md, step 2).

2024 Counterspell: when a creature it can see within 60 ft casts a spell, a reactor may react by
casting Counterspell (spending an L3+ slot + its reaction). The original caster then makes a CON save
vs the counterspeller's spell save DC; on a FAIL the spell is countered (fizzles, but KEEPS its slot —
executeSpell never runs, so the caster's slot is never spent). Driven headlessly through the cast
interrupt (resolve_cast auto driver + begin_cast/submit_decision).

Save outcomes are made deterministic by stacking the counterspeller's DC vs the caster's CON:
  · "force counter"  → DC 19 (CHA 20, prof +6) vs caster CON 1  → max roll 20-5=15 < 19, always fails.
  · "force save"     → DC 10 (CHA 10, prof +2) vs caster CON 30 → min roll 1+16=17 ≥ 10, always saves.
(NB: the 12x12 test map tops out at ~55 ft, so the 60 ft range gate can't be exercised here.)
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


class CounterspellDecider(rpg.CombatDecider):
    """Reacts to an OnDeclareCast window by casting Counterspell (if cast=True) or skipping."""
    def __init__(self, cast):
        super().__init__()
        self._cast = cast
        self.windows = []
        self.last_options = []
    def choose_reaction(self, ctx):
        self.windows.append(ctx.window)
        self.last_options = [o.feature for o in ctx.options
                             if o.kind == rpg.ReactionOptionKind.Feature]
        resp = rpg.ReactionResponse()
        resp.option = -1
        if self._cast:
            for i, o in enumerate(ctx.options):
                if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "Counterspell":
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


def _force_barrage():
    """A non-Magic-Missile damaging spell (structurally a clone) — proves Counterspell isn't gated to
    Magic Missile while NOT opening a Shield window (Shield is gated to the literal 'Magic Missile')."""
    sp = _magic_missile()
    sp.name = "Force Barrage"
    return sp


def _counterspell():
    sp = rpg.Spell()
    sp.name = "Counterspell"
    sp.level = 3
    sp.geometry = rpg.SpellGeometry.Single
    return sp


def _shield_spell():
    sp = rpg.Spell()
    sp.name = "Shield"
    sp.level = 1
    sp.geometry = rpg.SpellGeometry.Single
    return sp


def _setup(engine, bm, *, give_cs=True, l3_slots=2, high_dc=True,
           caster_con=1, caster_con_prof=False, cs_spells=None):
    """Caster (Magic Missile) at (5,5); Victim at (7,5); Counterspeller 'Mage' at (5,7).

    high_dc → Mage DC 19 (forces a counter vs low-CON caster); else DC 10 (caster saves).
    cs_spells overrides the Mage's known spells (defaults to [Counterspell] / [] per give_cs)."""
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    victim = add_agent_to_battle(engine, bm, create_test_agent("Victim", 7, 5))
    mage   = add_agent_to_battle(engine, bm, create_test_agent("Mage", 5, 7))
    # Set stats/spells AFTER all adds (apply_agent_configs recreates earlier agents).
    engine.set_agent_spells(bm, caster, [_magic_missile()])
    cs = engine.get_agent_stats(bm, caster)
    cs.spell_slots_remaining = [9, 9, 9, 0, 0, 0, 0, 0, 0]
    cs.con = caster_con
    cs.save_prof_con = caster_con_prof
    engine.set_agent_stats(bm, caster, cs)

    vs = engine.get_agent_stats(bm, victim)
    vs.hp_max = 40; vs.hp_cur = 40
    engine.set_agent_stats(bm, victim, vs)

    if cs_spells is None:
        cs_spells = [_counterspell()] if give_cs else []
    engine.set_agent_spells(bm, mage, cs_spells)
    ms = engine.get_agent_stats(bm, mage)
    ms.hp_max = 40; ms.hp_cur = 40
    ms.spell_slots_remaining = [9, 9, l3_slots, 0, 0, 0, 0, 0, 0]
    ms.spellcasting_ability = 5  # CHA
    ms.cha = 20 if high_dc else 10
    ms.prof_bonus = 6 if high_dc else 2
    engine.set_agent_stats(bm, mage, ms)
    return caster, victim, mage


def _mm_action(caster, victim):
    a = rpg.SpellAction()
    a.caster_idx = caster
    a.spell_idx = 0
    a.target_indices = [victim]
    return a


def _hp(engine, bm, idx):    return engine.get_agent_stats(bm, idx).hp_cur
def _l3(engine, bm, idx):    return engine.get_agent_stats(bm, idx).spell_slots_remaining[2]
def _l1(engine, bm, idx):    return engine.get_agent_stats(bm, idx).spell_slots_remaining[0]
def _react(engine, bm, idx): return engine.get_agent_conditions(bm, idx).reaction_used


# ── Tests ────────────────────────────────────────────────────────────────────
def test_counterspell_counters_on_failed_save():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, mage = _setup(engine, bm, high_dc=True, caster_con=1)
    dec = CounterspellDecider(cast=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _mm_action(caster, victim))

    assert rpg.ReactionWindow.OnDeclareCast in dec.windows, "casting should open OnDeclareCast"
    assert engine.last_cast_countered(), "failed CON save → spell countered"
    assert _hp(engine, bm, victim) == 40, "countered Magic Missile deals no damage"
    assert _l1(engine, bm, caster) == 9, "countered spell KEEPS its slot (executeSpell never ran)"
    assert _l3(engine, bm, mage) == 1, "Counterspell spends one L3 slot"
    assert _react(engine, bm, mage), "Counterspell consumes the reaction"
    print("✅ test_counterspell_counters_on_failed_save passed")


def test_counterspell_fails_on_successful_save():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, mage = _setup(engine, bm, high_dc=False, caster_con=30, caster_con_prof=True)
    dec = CounterspellDecider(cast=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _mm_action(caster, victim))

    assert rpg.ReactionWindow.OnDeclareCast in dec.windows, "the window is still offered"
    assert not engine.last_cast_countered(), "successful CON save → spell is NOT countered"
    assert _hp(engine, bm, victim) < 40, "the spell resolves → Victim takes damage"
    assert _l1(engine, bm, caster) == 8, "a resolved spell spends its slot normally"
    assert _l3(engine, bm, mage) == 1, "Counterspell was still cast (slot + reaction spent)"
    assert _react(engine, bm, mage), "Counterspell consumes the reaction even on a save"
    print("✅ test_counterspell_fails_on_successful_save passed")


def test_skipped_counterspell_resolves():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, mage = _setup(engine, bm, high_dc=True, caster_con=1)
    dec = CounterspellDecider(cast=False); engine.set_decider(dec)
    engine.resolve_cast(bm, _mm_action(caster, victim))

    assert rpg.ReactionWindow.OnDeclareCast in dec.windows, "the window is offered"
    assert not engine.last_cast_countered(), "skipping Counterspell → spell resolves"
    assert _hp(engine, bm, victim) < 40, "Victim takes damage"
    assert _l3(engine, bm, mage) == 2 and not _react(engine, bm, mage), "skip spends nothing"
    print("✅ test_skipped_counterspell_resolves passed")


def test_no_counterspell_known_no_window():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, mage = _setup(engine, bm, give_cs=False)
    dec = CounterspellDecider(cast=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _mm_action(caster, victim))
    assert dec.windows == [], "no Counterspell known → no window"
    assert _hp(engine, bm, victim) < 40, "spell resolves"
    print("✅ test_no_counterspell_known_no_window passed")


def test_no_l3_slot_no_window():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, mage = _setup(engine, bm, l3_slots=0)  # only L1/L2 slots
    dec = CounterspellDecider(cast=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _mm_action(caster, victim))
    assert dec.windows == [], "no L3+ slot → can't cast Counterspell → no window"
    assert _hp(engine, bm, victim) < 40
    print("✅ test_no_l3_slot_no_window passed")


def test_used_reaction_no_window():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, mage = _setup(engine, bm)
    c = engine.get_agent_conditions(bm, mage); c.reaction_used = True
    engine.set_agent_conditions(bm, mage, c)
    dec = CounterspellDecider(cast=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _mm_action(caster, victim))
    assert dec.windows == [], "reaction already used → no Counterspell window"
    assert _hp(engine, bm, victim) < 40
    print("✅ test_used_reaction_no_window passed")


def test_counterspell_works_on_non_magic_missile():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, mage = _setup(engine, bm, high_dc=True, caster_con=1)
    engine.set_agent_spells(bm, caster, [_force_barrage()])  # not "Magic Missile"
    dec = CounterspellDecider(cast=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _mm_action(caster, victim))
    assert rpg.ReactionWindow.OnDeclareCast in dec.windows, "any spell opens a Counterspell window"
    assert dec.last_options == ["Counterspell"], "no Shield offered for a non-Magic-Missile spell"
    assert engine.last_cast_countered(), "Force Barrage is countered"
    assert _hp(engine, bm, victim) == 40, "countered → no damage"
    print("✅ test_counterspell_works_on_non_magic_missile passed")


def test_counter_and_shield_both_offered():
    """A Magic Missile TARGET that knows both Counterspell and Shield is offered BOTH in one window."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, mage = _setup(engine, bm, high_dc=True, caster_con=1,
                                  cs_spells=[_counterspell(), _shield_spell()])
    dec = CounterspellDecider(cast=False); engine.set_decider(dec)  # observe options, don't cast
    engine.resolve_cast(bm, _mm_action(caster, mage))  # Magic Missile AT the mage (a target)
    assert set(dec.last_options) == {"Counterspell", "Shield"}, \
        f"both reactions offered, got {dec.last_options}"
    print("✅ test_counter_and_shield_both_offered passed")


def test_begin_submit_counterspell_path():
    """GUI path: begin_cast parks at the Counterspell checkpoint; submit_decision resolves it."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, mage = _setup(engine, bm, high_dc=True, caster_con=1)  # no decider → suspend
    status = engine.begin_cast(bm, _mm_action(caster, victim))
    assert status == rpg.FlowStatus.AwaitingDecision, f"expected suspend, got {status}"
    pd = engine.pending_decision()
    assert pd.active and pd.ctx.window == rpg.ReactionWindow.OnDeclareCast
    assert pd.ctx.reactor_idx == mage
    opt = next(i for i, o in enumerate(pd.ctx.options)
               if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "Counterspell")
    resp = rpg.ReactionResponse(); resp.option = opt
    status = engine.submit_decision(bm, resp)
    assert status == rpg.FlowStatus.Completed
    assert engine.last_cast_countered(), "submit_decision resolved the Counterspell"
    assert _hp(engine, bm, victim) == 40, "Magic Missile was countered"
    assert _l1(engine, bm, caster) == 9, "countered spell kept its slot"
    print("✅ test_begin_submit_counterspell_path passed")


def run_all():
    test_counterspell_counters_on_failed_save()
    test_counterspell_fails_on_successful_save()
    test_skipped_counterspell_resolves()
    test_no_counterspell_known_no_window()
    test_no_l3_slot_no_window()
    test_used_reaction_no_window()
    test_counterspell_works_on_non_magic_missile()
    test_counter_and_shield_both_offered()
    test_begin_submit_counterspell_path()
    print("\nAll Counterspell (OnDeclareCast) tests passed ✅")


if __name__ == "__main__":
    run_all()
