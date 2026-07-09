#!/usr/bin/env python3
"""
Test Rogue Phase 1: chassis + Sneak Attack + core defensive features.

Covered: DEX/INT saves, Cunning Action gate, Slippery Mind, subclass round-trip,
Sneak Attack (advantage gate, finesse/ranged gate, once-per-turn, dice scaling),
Uncanny Dodge (halving + reaction), Evasion (DEX save → no/half), Elusive (advantage negated).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


class _UDDecider(rpg.CombatDecider):
    """At an OnHit defender window, pick the Uncanny Dodge option (else Skip). Records OnHit offers
    so a test can assert the window actually opened."""
    def __init__(self):
        super().__init__()
        self.onhit_offers = 0
    def choose_reaction(self, ctx):
        resp = rpg.ReactionResponse(); resp.option = -1
        if ctx.window == rpg.ReactionWindow.OnHit:
            self.onhit_offers += 1
            for i, o in enumerate(ctx.options):
                if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "UncannyDodge":
                    resp.option = i
                    break
        return resp


def _rogue(engine, bm, idx, level, subclass=None, dex=16):
    """Configure agent idx as a Rogue of the given level (+ optional subclass)."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Rogue, level)
    if subclass is not None:
        s.rogue_subclass = subclass
    s.dex = dex
    s.initialize_class_resources(rpg.CharacterClass.Rogue, level)
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


def _finesse_weapon():
    w = rpg.Weapon()
    w.name = "Test Dagger"
    w.type = rpg.WeaponType.Melee
    w.finesse = True
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.bonus_damage = 100  # flat, always added in rollDamage (independent of dice/ability mod)
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Piercing
    roll.num_dice = 1
    roll.die_size = 4
    w.physical_damage_types = [roll]
    return w


def _plain_melee_weapon():
    """A non-finesse, non-ranged melee weapon (Sneak Attack must NOT apply)."""
    w = _finesse_weapon()
    w.name = "Test Club"
    w.finesse = False
    return w


def _three(primary):
    """set_agent_weapons expects exactly 3 weapons; pad with unused fillers (attacks use idx 0)."""
    return [primary, rpg.Weapon(), rpg.Weapon()]


def _hit_once(engine, bm, atk, tgt, give_adv=False, wpn=0, tries=40):
    """Attack until it lands. A natural-1 auto-misses regardless of bonus, so a single seeded
    roll can fumble; misses deal no damage, so retrying is safe. Re-applies advantage each
    iteration when requested (advantage is required for Sneak Attack).

    Sneak Attack is applied out of band (Brutal-Strike-style): if the landed hit flags
    cunning_strike_available, this helper immediately applies the dice with no rider, so the
    returned AttackResult includes the Sneak Attack damage just like a full attack would."""
    for _ in range(tries):
        if give_adv:
            _give_advantage(engine, bm, atk)
        r = engine.execute_action(bm, rpg.Attack(atk, tgt, wpn))
        if r.hit:
            if engine.get_agent_conditions(bm, atk).cunning_strike_available:
                engine.apply_cunning_strike_effect(bm, atk, tgt, [], r)
            return r
    raise AssertionError(f"attack never landed in {tries} tries")


def _give_advantage(engine, bm, idx):
    c = engine.get_agent_conditions(bm, idx)
    c.has_advantage = True
    engine.set_agent_conditions(bm, idx, c)


def _breakdown_value(result, label):
    """Return the breakdown amount for a label, or None if absent."""
    for entry in result.damage_breakdown:
        lbl, val = entry[0], entry[1]
        if lbl == label:
            return val
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Chassis
# ─────────────────────────────────────────────────────────────────────────────

def test_rogue_chassis():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))

    s1 = _rogue(engine, bm, idx, 1)
    assert s1.save_prof_dex and s1.save_prof_intel, "Rogue has DEX + INT save proficiency"
    assert not s1.has_cunning_action, "Cunning Action is L2+, not L1"

    s2 = _rogue(engine, bm, idx, 2)
    assert s2.has_cunning_action, "Cunning Action available at L2+"

    s14 = _rogue(engine, bm, idx, 14)
    assert not (s14.save_prof_wis and s14.save_prof_cha), "Slippery Mind not before L15"

    s15 = _rogue(engine, bm, idx, 15)
    assert s15.save_prof_wis and s15.save_prof_cha, "Slippery Mind grants WIS + CHA saves at L15+"
    print("✅ test_rogue_chassis passed")


def test_rogue_subclass_roundtrip():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))
    for sc in [rpg.RogueSubclass.ArcaneTrickster, rpg.RogueSubclass.Assassin,
               rpg.RogueSubclass.Soulknife, rpg.RogueSubclass.Thief]:
        s = _rogue(engine, bm, idx, 3, subclass=sc)
        assert s.rogue_subclass == sc, f"subclass {sc} should round-trip"
    print("✅ test_rogue_subclass_roundtrip passed")


# ─────────────────────────────────────────────────────────────────────────────
# Sneak Attack
# ─────────────────────────────────────────────────────────────────────────────

def test_sneak_attack_with_advantage():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), ac=1, hp=500)
    _rogue(engine, bm, atk, 5)  # 3d6 sneak
    engine.set_agent_weapons(bm, atk, _three(_finesse_weapon()))

    result = _hit_once(engine, bm, atk, tgt, give_adv=True)
    sneak = _breakdown_value(result, "sneak attack")
    assert sneak is not None, "Sneak Attack should be in the damage breakdown"
    assert 3 <= sneak <= 18, f"L5 Sneak Attack is 3d6 (3..18), got {sneak}"
    print("✅ test_sneak_attack_with_advantage passed")


def test_sneak_attack_once_per_turn():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), ac=1, hp=500)
    _rogue(engine, bm, atk, 5)
    engine.set_agent_weapons(bm, atk, _three(_finesse_weapon()))

    r1 = _hit_once(engine, bm, atk, tgt, give_adv=True)
    assert _breakdown_value(r1, "sneak attack") is not None, "first hit should Sneak Attack"

    r2 = _hit_once(engine, bm, atk, tgt, give_adv=True)
    assert _breakdown_value(r2, "sneak attack") is None, "Sneak Attack is once per turn"

    # Clear the per-turn flag (start of next turn) → it fires again.
    c = engine.get_agent_conditions(bm, atk)
    c.sneak_attack_used = False
    engine.set_agent_conditions(bm, atk, c)
    r3 = _hit_once(engine, bm, atk, tgt, give_adv=True)
    assert _breakdown_value(r3, "sneak attack") is not None, "Sneak Attack returns next turn"
    print("✅ test_sneak_attack_once_per_turn passed")


def test_sneak_attack_requires_advantage():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), ac=1, hp=500)
    _rogue(engine, bm, atk, 5)
    engine.set_agent_weapons(bm, atk, _three(_finesse_weapon()))
    # No advantage granted — even a landed hit must not Sneak Attack.
    result = _hit_once(engine, bm, atk, tgt, give_adv=False)
    assert _breakdown_value(result, "sneak attack") is None, \
        "Sneak Attack requires advantage (no ally-adjacency trigger in Phase 1)"
    print("✅ test_sneak_attack_requires_advantage passed")


def test_sneak_attack_requires_finesse_or_ranged():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), ac=1, hp=500)
    _rogue(engine, bm, atk, 5)
    engine.set_agent_weapons(bm, atk, _three(_plain_melee_weapon()))  # not finesse, not ranged
    result = _hit_once(engine, bm, atk, tgt, give_adv=True)
    assert _breakdown_value(result, "sneak attack") is None, \
        "Sneak Attack requires a Finesse or Ranged weapon"
    print("✅ test_sneak_attack_requires_finesse_or_ranged passed")


def test_sneak_attack_scaling_l19():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5), ac=1, hp=2000)
    _rogue(engine, bm, atk, 19)  # 10d6 sneak
    engine.set_agent_weapons(bm, atk, _three(_finesse_weapon()))
    result = _hit_once(engine, bm, atk, tgt, give_adv=True)
    sneak = _breakdown_value(result, "sneak attack")
    assert sneak is not None and 10 <= sneak <= 60, f"L19 Sneak Attack is 10d6 (10..60), got {sneak}"
    print("✅ test_sneak_attack_scaling_l19 passed")


# ─────────────────────────────────────────────────────────────────────────────
# Uncanny Dodge
# ─────────────────────────────────────────────────────────────────────────────

def test_uncanny_dodge():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 6, 5), ac=1, hp=500)

    # Attacker is a plain Fighter (no Sneak Attack to confuse the breakdown).
    afs = engine.get_agent_stats(bm, atk)
    afs.character_class = rpg.CharacterClass.Fighter
    afs.str = 16
    engine.set_agent_stats(bm, atk, afs)
    w = _finesse_weapon()
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = 4
    roll.die_size = 6  # 4d6 base so damage is comfortably > 0
    w.physical_damage_types = [roll]
    engine.set_agent_weapons(bm, atk, _three(w))

    _rogue(engine, bm, tgt, 5)  # Uncanny Dodge available at L5

    # Uncanny Dodge is now an OnHit defender reaction routed through the framework: the auto/RL path
    # asks the installed decider (no decider → skipped, like every other reaction).
    dec = _UDDecider(); engine.set_decider(dec)
    result = _hit_once(engine, bm, atk, tgt, give_adv=True)  # advantage just to land the hit
    assert dec.onhit_offers >= 1, "the OnHit defender window should have opened for the Rogue"
    reduction = _breakdown_value(result, "uncanny dodge")
    assert reduction is not None and reduction < 0, \
        f"Uncanny Dodge should record a negative reduction, got {reduction}"
    # Breakdown must still sum to total_damage.
    assert sum(e[1] for e in result.damage_breakdown) == result.total_damage, \
        "damage_breakdown must sum to total_damage after Uncanny Dodge"
    # Reaction consumed.
    assert engine.get_agent_conditions(bm, tgt).reaction_used, "Uncanny Dodge consumes the reaction"
    print("✅ test_uncanny_dodge passed")


def test_uncanny_dodge_skipped_without_decider():
    # Framework convention: with no decider installed (headless), every reaction window — Uncanny Dodge
    # included — is skipped. This is the deliberate change from the old auto-apply behavior.
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 6, 5), ac=1, hp=500)
    afs = engine.get_agent_stats(bm, atk); afs.str = 16
    engine.set_agent_stats(bm, atk, afs)
    w = _finesse_weapon()
    roll = rpg.PhysicalDamageRoll(); roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = 4; roll.die_size = 6
    w.physical_damage_types = [roll]
    engine.set_agent_weapons(bm, atk, _three(w))
    _rogue(engine, bm, tgt, 5)

    result = _hit_once(engine, bm, atk, tgt, give_adv=True)  # NO decider installed
    assert _breakdown_value(result, "uncanny dodge") is None, \
        "without a decider the Uncanny Dodge window is skipped (no auto-apply)"
    assert not engine.get_agent_conditions(bm, tgt).reaction_used, \
        "no reaction is spent when the window is skipped"
    print("✅ test_uncanny_dodge_skipped_without_decider passed")


def test_uncanny_dodge_gui_window():
    # GUI path: begin_attack suspends at the OnHit defender window; submit_decision(UncannyDodge)
    # halves the damage. No decider is installed (the human is expressed via submit_decision).
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Fighter", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 6, 5), ac=1, hp=500)
    afs = engine.get_agent_stats(bm, atk); afs.str = 16
    engine.set_agent_stats(bm, atk, afs)
    w = _finesse_weapon()
    roll = rpg.PhysicalDamageRoll(); roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = 4; roll.die_size = 6
    w.physical_damage_types = [roll]
    engine.set_agent_weapons(bm, atk, _three(w))
    _rogue(engine, bm, tgt, 5)

    status = None
    for _ in range(40):
        _give_advantage(engine, bm, atk)
        status = engine.begin_attack(bm, rpg.Attack(atk, tgt, 0))
        if status == rpg.FlowStatus.AwaitingDecision:
            break
        # a miss/fumble finishes immediately with no window — retry to land a hit
    assert status == rpg.FlowStatus.AwaitingDecision, "a landed hit on a Rogue should open the OnHit window"
    pd = engine.pending_decision()
    assert pd.active and pd.ctx.window == rpg.ReactionWindow.OnHit
    ud = next(i for i, o in enumerate(pd.ctx.options)
              if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "UncannyDodge")
    resp = rpg.ReactionResponse(); resp.option = ud
    status = engine.submit_decision(bm, resp)
    assert status == rpg.FlowStatus.Completed
    result = engine.last_attack_result()
    assert _breakdown_value(result, "uncanny dodge") is not None, "the GUI window should apply Uncanny Dodge"
    assert engine.get_agent_conditions(bm, tgt).reaction_used, "the reaction is consumed"
    print("✅ test_uncanny_dodge_gui_window passed")


# ─────────────────────────────────────────────────────────────────────────────
# Evasion
# ─────────────────────────────────────────────────────────────────────────────

def test_evasion_no_damage_on_save():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    rogue = add_agent_to_battle(engine, bm, create_test_agent("Rogue", 7, 5))
    plain = add_agent_to_battle(engine, bm, create_test_agent("Plain", 8, 5))

    # Weak caster → low save DC; high-DEX targets → both auto-succeed the DEX save.
    cs = engine.get_agent_stats(bm, caster)
    cs.set_class_level(rpg.CharacterClass.Wizard, 1)
    cs.intel = 8                 # INT mod -1
    cs.prof_bonus = 2
    cs.spellcasting_ability = 3  # INT → save DC = 8 + 2 - 1 = 9 (targets with DEX 30 auto-save)
    cs.can_cast_spell = True
    engine.set_agent_stats(bm, caster, cs)

    # Evasion rogue (L7) and a non-rogue control, both DEX 30.
    _rogue(engine, bm, rogue, 7, dex=30)
    rs = engine.get_agent_stats(bm, rogue); rs.hp_max = 100; rs.hp_cur = 100
    engine.set_agent_stats(bm, rogue, rs)

    ps = engine.get_agent_stats(bm, plain)
    ps.character_class = rpg.CharacterClass.Fighter
    ps.dex = 30; ps.hp_max = 100; ps.hp_cur = 100
    engine.set_agent_stats(bm, plain, ps)

    # DEX-save spell, 10 deterministic damage (die_size 1 → always 1).
    spell = rpg.Spell()
    spell.name = "Test Burst"
    spell.level = 1
    spell.attack_type = rpg.SpellAttack.Save
    spell.save_ability = rpg.SaveAbility.Dexterity
    spell.geometry = rpg.SpellGeometry.Multiple
    spell.num_targets = 2  # engine caps Multiple-geometry casts to num_targets; this hits both
    spell.range = 60
    dmg = rpg.MagicDamageRoll()
    dmg.type = rpg.MagicDamage.Force
    dmg.num_dice = 10
    dmg.die_size = 1
    spell.magic_damage_rolls = [dmg]
    engine.set_agent_spells(bm, caster, [spell])

    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.target_indices = [rogue, plain]
    engine.execute_spell(bm, action)

    rogue_dmg = 100 - engine.get_agent_stats(bm, rogue).hp_cur
    plain_dmg = 100 - engine.get_agent_stats(bm, plain).hp_cur
    assert rogue_dmg == 0, f"Evasion: Rogue L7 takes 0 on a successful DEX save, got {rogue_dmg}"
    assert plain_dmg == 5, f"Non-Evasion control takes half (5) on a successful save, got {plain_dmg}"
    print("✅ test_evasion_no_damage_on_save passed")


# ─────────────────────────────────────────────────────────────────────────────
# Elusive
# ─────────────────────────────────────────────────────────────────────────────

def test_elusive_negates_advantage():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    # Attacker 1 vs an L18 Rogue (Elusive); attacker 2 vs a plain dummy — both with advantage.
    atk1 = add_agent_to_battle(engine, bm, create_test_agent("Rogue1", 5, 5))
    elusive = add_agent_to_battle(engine, bm, create_test_agent("Elusive", 6, 5), ac=1, hp=2000)
    atk2 = add_agent_to_battle(engine, bm, create_test_agent("Rogue2", 5, 8))
    dummy = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 8), ac=1, hp=2000)

    _rogue(engine, bm, atk1, 5)
    _rogue(engine, bm, atk2, 5)
    _rogue(engine, bm, elusive, 18)  # Elusive at L18
    engine.set_agent_weapons(bm, atk1, _three(_finesse_weapon()))
    engine.set_agent_weapons(bm, atk2, _three(_finesse_weapon()))

    # atk1's advantage is negated by Elusive (normal roll); atk2's advantage stands.
    r_elusive = _hit_once(engine, bm, atk1, elusive, give_adv=True)
    r_dummy = _hit_once(engine, bm, atk2, dummy, give_adv=True)

    assert _breakdown_value(r_elusive, "sneak attack") is None, \
        "Elusive negates the attacker's advantage → no Sneak Attack"
    assert _breakdown_value(r_dummy, "sneak attack") is not None, \
        "Control: advantage stands vs a non-Elusive target → Sneak Attack fires"
    print("✅ test_elusive_negates_advantage passed")


if __name__ == "__main__":
    test_rogue_chassis()
    test_rogue_subclass_roundtrip()
    test_sneak_attack_with_advantage()
    test_sneak_attack_once_per_turn()
    test_sneak_attack_requires_advantage()
    test_sneak_attack_requires_finesse_or_ranged()
    test_sneak_attack_scaling_l19()
    test_uncanny_dodge()
    test_uncanny_dodge_skipped_without_decider()
    test_uncanny_dodge_gui_window()
    test_evasion_no_damage_on_save()
    test_elusive_negates_advantage()
    print("\n✅ All Rogue Phase 1 tests passed!")
