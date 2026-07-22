#!/usr/bin/env python3
"""
Test suite for the Vistani Curse "kickback" — the caster takes psychic damage when a curse
it inflicted ENDS (by any means) during combat.

The mechanism is a narrow, data-driven set of fields on ActiveAgentCondition
(kickback_dice / kickback_die_size / kickback_damage_type). When kickback_dice > 0,
ending the condition by ANY path deals kickback_dice × d(kickback_die_size) of the given
type to the CASTER (caster_idx), automatically — no save. It fires from BOTH removal
mechanisms:
  · Mechanism A — remove_agent_condition (save-success / concentration-drop / detonate)
  · Mechanism B — the tick loops on natural duration expiry
…and is SUPPRESSED when the cursed target has died (LOCKED decision: the Vistana is not
punished for killing its victim). See VISTANI_CURSE_KICKBACK_PLAN.md.

The final test guards the persistence round-trip (helpers._condition_to_dict /
_dict_to_condition) so a live curse — and its kickback — survives save/reload.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle
from helpers import _condition_to_dict, _dict_to_condition


def _curse(target_idx, caster_idx, dice=3, die=6, turns=5,
           damage_type=rpg.MagicDamage.Psychic, name="VistaniCurse"):
    """Author a Vistani-style curse condition on `target_idx`, cast by `caster_idx`.
    Ending it (by any path) rebounds dice×d(die) of `damage_type` onto the caster."""
    c = rpg.ActiveAgentCondition()
    c.agent_idx           = target_idx
    c.caster_idx          = caster_idx
    c.spell_idx           = -1
    c.condition_name      = name
    c.turns_remaining     = turns
    c.kickback_dice       = dice
    c.kickback_die_size   = die
    c.kickback_damage_type = damage_type
    return c


def _make_curse_spell(curse_kind, kickback_dice, condition_name="Cursed", die=6):
    """Build a Vistani curse spell (Single, Automatic, no damage) carrying the given
    curse_kind + kickback on its single AttackCondition — mirrors the spells.json records."""
    sp = rpg.Spell()
    sp.name        = "TestCurse"
    sp.type        = rpg.SpellType.Harm
    sp.geometry    = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range       = 30
    sp.duration    = 100
    sp.level       = 0
    sp.num_targets = 1
    sp.requires_los = False
    sp.requires_concentration = False
    c = rpg.AttackCondition()
    c.condition_name      = condition_name
    c.requires_save       = False
    c.curse_kind          = curse_kind
    c.kickback_dice       = kickback_dice
    c.kickback_die_size   = die
    c.kickback_damage_type = rpg.MagicDamage.Psychic
    sp.conditions = [c]
    return sp


def _cast_curse(engine, bm, caster, target, curse_kind, kickback_dice, curse_choice,
                condition_name="Cursed"):
    """Give `caster` a fresh curse spell and cast it on `target` with the sub-choice."""
    sp = _make_curse_spell(curse_kind, kickback_dice, condition_name)
    engine.set_agent_spells(bm, caster, [sp])
    act = rpg.SpellAction()
    act.caster_idx     = caster
    act.spell_idx      = 0
    act.target_indices = [target]
    act.curse_choice   = curse_choice
    engine.execute_spell(bm, act)


def _setup_pair(caster_hp=100):
    """A Vistana (caster) and a victim (target), both healthy. Returns (engine, bm, vistana, victim)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    vistana = add_agent_to_battle(engine, bm, create_test_agent("Vistana", 2, 5))
    victim  = add_agent_to_battle(engine, bm, create_test_agent("Victim", 4, 5))
    s = engine.get_agent_stats(bm, vistana)
    s.hp_max = caster_hp
    s.hp_cur = caster_hp
    engine.set_agent_stats(bm, vistana, s)
    return engine, bm, vistana, victim


def test_kickback_on_explicit_remove():
    """Mechanism A: removing the curse (the shared chokepoint for save-success /
    concentration-drop / detonate) rebounds 3d6 psychic onto the caster."""
    engine, bm, vistana, victim = _setup_pair()
    cid = engine.add_agent_condition(bm, _curse(victim, vistana))
    before = engine.get_agent_stats(bm, vistana).hp_cur

    engine.remove_agent_condition(bm, cid)

    after = engine.get_agent_stats(bm, vistana).hp_cur
    dealt = before - after
    assert 3 <= dealt <= 18, f"3d6 kickback should deal 3..18 to the caster, got {dealt}"
    print("✅ test_kickback_on_explicit_remove passed")


def test_kickback_on_tick_expiry():
    """Mechanism B: a curse that runs out its duration in tick_agent_conditions rebounds
    onto the caster (deferred past the container rebuild — no iterator invalidation)."""
    engine, bm, vistana, victim = _setup_pair()
    engine.add_agent_condition(bm, _curse(victim, vistana, turns=1))
    before = engine.get_agent_stats(bm, vistana).hp_cur

    removed = engine.tick_agent_conditions(bm)  # turns 1 → 0 → expires + kickback

    after = engine.get_agent_stats(bm, vistana).hp_cur
    dealt = before - after
    assert dealt >= 3, f"tick-expiry should fire the kickback, caster lost {dealt} HP"
    assert dealt <= 18, f"3d6 kickback capped at 18, got {dealt}"
    assert len(removed) == 1, "the expired curse should be reported removed"
    print("✅ test_kickback_on_tick_expiry passed")


def test_kickback_on_caster_tick_expiry():
    """Mechanism B, caster-scoped: the same kickback fires from tick_agent_conditions_for_caster
    (concentration/caster-duration expiry), not only the global tick."""
    engine, bm, vistana, victim = _setup_pair()
    engine.add_agent_condition(bm, _curse(victim, vistana, turns=1))
    before = engine.get_agent_stats(bm, vistana).hp_cur

    engine.tick_agent_conditions_for_caster(bm, vistana)

    dealt = before - engine.get_agent_stats(bm, vistana).hp_cur
    assert 3 <= dealt <= 18, f"caster-scoped tick should fire 3d6 kickback, got {dealt}"
    print("✅ test_kickback_on_caster_tick_expiry passed")


def test_blind_deafen_tier_is_5d6():
    """The blinded/deafened curse option carries the heavier 5d6 kickback."""
    engine, bm, vistana, victim = _setup_pair()
    cid = engine.add_agent_condition(bm, _curse(victim, vistana, dice=5, die=6))
    before = engine.get_agent_stats(bm, vistana).hp_cur

    engine.remove_agent_condition(bm, cid)

    dealt = before - engine.get_agent_stats(bm, vistana).hp_cur
    assert 5 <= dealt <= 30, f"5d6 kickback should deal 5..30, got {dealt}"
    print("✅ test_blind_deafen_tier_is_5d6 passed")


def test_no_kickback_on_target_death():
    """LOCKED decision: when the cursed target has DIED, ending the tracking entry must NOT
    rebound on the caster — the Vistana is not punished for killing its victim. This holds
    even though the entry may later reach an end-path (removal or tick) on the dead target."""
    engine, bm, vistana, victim = _setup_pair()
    cid = engine.add_agent_condition(bm, _curse(victim, vistana))

    # Kill the victim outright.
    vs = engine.get_agent_stats(bm, victim)
    vs.hp_cur = 0
    engine.set_agent_stats(bm, victim, vs)
    vc = engine.get_agent_conditions(bm, victim)
    vc.dead = True
    engine.set_agent_conditions(bm, victim, vc)

    before = engine.get_agent_stats(bm, vistana).hp_cur
    engine.remove_agent_condition(bm, cid)
    after = engine.get_agent_stats(bm, vistana).hp_cur

    assert after == before, f"no kickback should fire on target death (caster {before} → {after})"
    print("✅ test_no_kickback_on_target_death passed")


def test_plain_condition_has_no_kickback():
    """A normal condition (kickback_dice == 0) ends silently — the caster is untouched."""
    engine, bm, vistana, victim = _setup_pair()
    c = _curse(victim, vistana)
    c.kickback_dice = 0            # not a curse — an ordinary tracked condition
    cid = engine.add_agent_condition(bm, c)

    before = engine.get_agent_stats(bm, vistana).hp_cur
    engine.remove_agent_condition(bm, cid)
    after = engine.get_agent_stats(bm, vistana).hp_cur

    assert after == before, f"a plain condition must not damage the caster (was {before}, now {after})"
    print("✅ test_plain_condition_has_no_kickback passed")


def test_caster_resistance_halves_kickback():
    """The caster's own resistance to the kickback type is honored (psychic-resistant Vistana
    takes half). Guards that onConditionEnded routes through the damage-multiplier path."""
    engine, bm, vistana, victim = _setup_pair()
    s = engine.get_agent_stats(bm, vistana)
    # MagicDamage index for Psychic is 7 (Acid=0 … Psychic=7 … Thunder=9).
    s.set_magic_damage_multiplier(7, 0.0)   # immune → zero kickback
    engine.set_agent_stats(bm, vistana, s)

    cid = engine.add_agent_condition(bm, _curse(victim, vistana))
    before = engine.get_agent_stats(bm, vistana).hp_cur
    engine.remove_agent_condition(bm, cid)
    after = engine.get_agent_stats(bm, vistana).hp_cur

    assert after == before, f"a psychic-immune caster should take 0 kickback (was {before}, now {after})"
    print("✅ test_caster_resistance_halves_kickback passed")


def test_caster_can_die_from_own_kickback():
    """A low-HP caster is dropped by its own rebounding curse (re-entrancy: the kickback path
    may cascade into applyUnconscious → dropConcentration without corrupting the list)."""
    engine, bm, vistana, victim = _setup_pair(caster_hp=2)
    cid = engine.add_agent_condition(bm, _curse(victim, vistana))

    engine.remove_agent_condition(bm, cid)

    assert engine.get_agent_stats(bm, vistana).hp_cur <= 0, "2-HP caster should drop to 0 from 3d6 kickback"
    print("✅ test_caster_can_die_from_own_kickback passed")


def test_condition_serializer_roundtrip():
    """Persistence slice: a live curse survives save/reload. Every field written by
    _condition_to_dict must be read back by _dict_to_condition (round-trip discipline) —
    especially the kickback_* fields and turns_remaining, or a reloaded curse loses its bite."""
    c = _curse(target_idx=3, caster_idx=1, dice=5, die=6, turns=7,
               damage_type=rpg.MagicDamage.Psychic, name="VistaniCurse")
    c.save_dc         = 15
    c.save_ability    = rpg.SaveAbility.SaveCha
    c.save_repeat_turns = 2
    c.next_save_turn  = 4

    back = _dict_to_condition(_condition_to_dict(c))

    assert back.agent_idx  == 3, "agent_idx must survive"
    assert back.caster_idx == 1, "caster_idx must survive"
    assert back.condition_name == "VistaniCurse"
    assert back.turns_remaining == 7, "turns_remaining must survive (curse can outlast a battle)"
    assert back.save_dc == 15
    assert back.save_ability == rpg.SaveAbility.SaveCha
    assert back.save_repeat_turns == 2
    assert back.next_save_turn == 4
    assert back.kickback_dice == 5, "kickback_dice must survive"
    assert back.kickback_die_size == 6, "kickback_die_size must survive"
    assert back.kickback_damage_type == rpg.MagicDamage.Psychic, "kickback_damage_type must survive"
    print("✅ test_condition_serializer_roundtrip passed")


def test_reloaded_curse_still_kicks_back():
    """End-to-end for the persistence slice: a curse serialized then rebuilt and re-added to a
    fresh engine still rebounds on its caster when it ends."""
    engine, bm, vistana, victim = _setup_pair()
    original = _curse(victim, vistana)
    revived  = _dict_to_condition(_condition_to_dict(original))
    cid = engine.add_agent_condition(bm, revived)

    before = engine.get_agent_stats(bm, vistana).hp_cur
    engine.remove_agent_condition(bm, cid)
    dealt = before - engine.get_agent_stats(bm, vistana).hp_cur

    assert 3 <= dealt <= 18, f"a reloaded curse should still fire 3d6 kickback, got {dealt}"
    print("✅ test_reloaded_curse_still_kicks_back passed")


# ─────────────────────────────────────────────────────────────────────────────
#  The three curse OPTIONS (effect application via the spell chokepoint)
# ─────────────────────────────────────────────────────────────────────────────

def test_curse_of_vulnerability_applies_and_restores():
    """Curse of Vulnerability sets the target's chosen-type multiplier to 2.0×, and the
    multiplier is RESTORED to its prior value when the curse ends (+ the 3d6 kickback)."""
    engine, bm, vistana, victim = _setup_pair()
    FIRE = 2  # MagicDamage_t: Acid=0, Cold=1, Fire=2, …
    _cast_curse(engine, bm, vistana, victim, curse_kind=1, kickback_dice=3, curse_choice=FIRE)

    mult = list(engine.get_agent_stats(bm, victim).magic_damage_multipliers)[FIRE]
    assert mult == 2.0, f"cursed target should be 2.0× vulnerable to Fire, got {mult}"

    curse = [c for c in engine.active_agent_conditions
             if c.agent_idx == victim and c.curse_vuln_type_code == FIRE]
    assert curse, "the vulnerability curse should be tracked with its type code"

    before = engine.get_agent_stats(bm, vistana).hp_cur
    engine.remove_agent_condition(bm, curse[0].condition_id)

    restored = list(engine.get_agent_stats(bm, victim).magic_damage_multipliers)[FIRE]
    assert restored == 1.0, f"multiplier must restore to 1.0 when the curse ends, got {restored}"
    dealt = before - engine.get_agent_stats(bm, vistana).hp_cur
    assert 3 <= dealt <= 18, f"3d6 kickback expected on end, got {dealt}"
    print("✅ test_curse_of_vulnerability_applies_and_restores passed")


def test_curse_of_weakness_sets_save_disadvantage():
    """Curse of Weakness gives Disadvantage on saves tied to the chosen ability (WIS), and only
    that ability — other saves are unaffected. The disadvantage lifts when the curse ends."""
    engine, bm, vistana, victim = _setup_pair()
    WIS = int(rpg.SaveAbility.SaveWis)
    _cast_curse(engine, bm, vistana, victim, curse_kind=2, kickback_dice=3, curse_choice=WIS)

    assert engine.curse_save_disadvantage(bm, victim, rpg.SaveAbility.SaveWis), \
        "WIS saves should be at Disadvantage under the curse"
    assert not engine.curse_save_disadvantage(bm, victim, rpg.SaveAbility.SaveStr), \
        "a non-cursed ability (STR) must be unaffected"

    curse = [c for c in engine.active_agent_conditions
             if c.agent_idx == victim and c.curse_disadv_ability == WIS]
    assert curse, "the weakness curse should carry the cursed ability"

    before = engine.get_agent_stats(bm, vistana).hp_cur
    engine.remove_agent_condition(bm, curse[0].condition_id)
    assert not engine.curse_save_disadvantage(bm, victim, rpg.SaveAbility.SaveWis), \
        "Disadvantage must lift when the curse ends"
    dealt = before - engine.get_agent_stats(bm, vistana).hp_cur
    assert 3 <= dealt <= 18, f"3d6 kickback expected on end, got {dealt}"
    print("✅ test_curse_of_weakness_sets_save_disadvantage passed")


def test_curse_of_affliction_sets_flags():
    """Curse of Affliction applies Blinded (choice 0), Deafened (1), or Both (2)."""
    for choice, exp_blind, exp_deaf in [(0, True, False), (1, False, True), (2, True, True)]:
        engine, bm, vistana, victim = _setup_pair()
        _cast_curse(engine, bm, vistana, victim, curse_kind=3, kickback_dice=5,
                    curse_choice=choice, condition_name="Blinded")
        vc = engine.get_agent_conditions(bm, victim)
        assert vc.blinded == exp_blind, f"choice {choice}: blinded should be {exp_blind}"
        assert vc.deafened == exp_deaf, f"choice {choice}: deafened should be {exp_deaf}"
    print("✅ test_curse_of_affliction_sets_flags passed")


def test_curse_of_affliction_both_kicks_back_once():
    """'Both' applies two conditions but only ONE carries the 5d6 kickback, so ending the pair
    rebounds 5d6 a single time (not 10d6)."""
    engine, bm, vistana, victim = _setup_pair()
    _cast_curse(engine, bm, vistana, victim, curse_kind=3, kickback_dice=5,
                curse_choice=2, condition_name="Blinded")
    afflictions = [c for c in engine.active_agent_conditions
                   if c.agent_idx == victim and c.condition_name in ("Blinded", "Deafened")]
    assert len(afflictions) == 2, f"'Both' should apply two conditions, got {len(afflictions)}"
    assert sorted(c.kickback_dice for c in afflictions) == [0, 5], \
        "exactly one of the pair carries the 5d6 kickback"

    before = engine.get_agent_stats(bm, vistana).hp_cur
    for c in afflictions:
        engine.remove_agent_condition(bm, c.condition_id)
    dealt = before - engine.get_agent_stats(bm, vistana).hp_cur
    assert 5 <= dealt <= 30, f"'Both' should rebound 5d6 ONCE, got {dealt}"
    print("✅ test_curse_of_affliction_both_kicks_back_once passed")


def test_curse_effect_fields_roundtrip():
    """The new curse-effect state (disadv ability / vuln type + prior multiplier) survives
    save/reload, or a reloaded curse of vulnerability could never restore its multiplier."""
    c = _curse(target_idx=3, caster_idx=1)
    c.curse_disadv_ability = 4      # SaveWis
    c.curse_vuln_type_code = 2      # Fire
    c.curse_vuln_prev_mult = 0.5    # target was resistant before the curse
    back = _dict_to_condition(_condition_to_dict(c))
    assert back.curse_disadv_ability == 4, "curse_disadv_ability must survive"
    assert back.curse_vuln_type_code == 2, "curse_vuln_type_code must survive"
    assert abs(back.curse_vuln_prev_mult - 0.5) < 1e-6, "curse_vuln_prev_mult must survive"
    print("✅ test_curse_effect_fields_roundtrip passed")


if __name__ == "__main__":
    test_kickback_on_explicit_remove()
    test_kickback_on_tick_expiry()
    test_kickback_on_caster_tick_expiry()
    test_blind_deafen_tier_is_5d6()
    test_no_kickback_on_target_death()
    test_plain_condition_has_no_kickback()
    test_caster_resistance_halves_kickback()
    test_caster_can_die_from_own_kickback()
    test_condition_serializer_roundtrip()
    test_reloaded_curse_still_kicks_back()
    test_curse_of_vulnerability_applies_and_restores()
    test_curse_of_weakness_sets_save_disadvantage()
    test_curse_of_affliction_sets_flags()
    test_curse_of_affliction_both_kicks_back_once()
    test_curse_effect_fields_roundtrip()
    print("\nAll Vistani curse tests passed ✅")
