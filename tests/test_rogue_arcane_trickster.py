#!/usr/bin/env python3
"""
Test Rogue — Arcane Trickster subclass (2024).

Covered engine-side features:
  · Spellcasting (L3): third-caster slot table + INT spellcasting ability (initializeClassResources
    override, mirrors Eldritch Knight).
  · Magical Ambush (L9): when the AT is Hidden/Invisible while casting a save spell, the target has
    Disadvantage on the save (rollSpellSave clause).
  · Versatile Trickster (L13): a creature within 5 ft of the AT's Mage Hand summon is attacked with
    Advantage (determineAdvantage clause keyed on summon_spell == "Mage Hand").
  · Spell Thief (L17): an OnDeclareCast reaction — the caster makes an INT save vs the AT's spell save
    DC; on a failure the cast is countered AND the spell is added to the caster's stolen_spell_names
    (it can't recast it until a long rest).

Scope note: Spell Thief negates via the same "countered" fizzle Counterspell uses, and the
"AT may now cast the stolen spell" half is deferred (flavor). See known_limitations.md / Rogue.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle
from test_rogue_phase2 import _finesse_weapon, _three


AT = rpg.RogueSubclass.ArcaneTrickster


def _arcane_trickster(engine, bm, idx, level, intel=20, prof=None):
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Rogue, level)
    s.rogue_subclass = AT
    s.dex = 20
    s.intel = intel
    s.initialize_class_resources(rpg.CharacterClass.Rogue, level)
    if prof is not None:
        s.prof_bonus = prof
    engine.set_agent_stats(bm, idx, s)
    return engine.get_agent_stats(bm, idx)


# ─────────────────────────────────────────────────────────────────────────────
# Spellcasting chassis (L3)
# ─────────────────────────────────────────────────────────────────────────────

def test_third_caster_chassis():
    bm = setup_battle_map(); engine = setup_combat_engine()
    at = add_agent_to_battle(engine, bm, create_test_agent("AT", 5, 5))
    s = _arcane_trickster(engine, bm, at, 3)
    assert s.spellcasting_ability == 3, f"AT casts off INT (3), got {s.spellcasting_ability}"
    assert s.can_cast_spell, "AT L3 can cast spells"
    assert s.spell_slots_max[0] == 2, f"third-caster L3 has 2 first-level slots, got {s.spell_slots_max[0]}"
    # L7: 4 L1 + 2 L2 slots.
    s7 = _arcane_trickster(engine, bm, at, 7)
    assert s7.spell_slots_max[0] == 4 and s7.spell_slots_max[1] == 2, \
        f"third-caster L7 = 4/2, got {s7.spell_slots_max[0]}/{s7.spell_slots_max[1]}"
    print("✅ test_third_caster_chassis passed")


def test_no_spellcasting_below_l3():
    bm = setup_battle_map(); engine = setup_combat_engine()
    at = add_agent_to_battle(engine, bm, create_test_agent("AT", 5, 5))
    s = _arcane_trickster(engine, bm, at, 2)
    assert s.spell_slots_max[0] == 0, "AT below L3 has no spell slots"
    assert not s.can_cast_spell, "AT below L3 cannot cast"
    print("✅ test_no_spellcasting_below_l3 passed")


# ─────────────────────────────────────────────────────────────────────────────
# Magical Ambush (L9)
# ─────────────────────────────────────────────────────────────────────────────

def _save_fear_spell():
    """Single-target WIS-save spell that applies Frightened on a failure."""
    sp = rpg.Spell(); sp.name = "Cause Fear"; sp.level = 1
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = rpg.SaveAbility.SaveWis
    sp.geometry = rpg.SpellGeometry.Single
    c = rpg.AttackCondition()
    c.condition_name = "Frightened"; c.requires_save = True
    c.save_ability = rpg.SaveAbility.SaveWis; c.condition_duration = 10
    sp.conditions = [c]
    return sp


def _frighten_rate(engine, bm, at, tgt, hidden, n=200):
    """Cast the save spell n times; return how often the target ends up Frightened (failed save)."""
    fails = 0
    for _ in range(n):
        c = engine.get_agent_conditions(bm, tgt)
        c.frightened = False
        engine.set_agent_conditions(bm, tgt, c)
        ac = engine.get_agent_conditions(bm, at)
        ac.hidden = hidden
        engine.set_agent_conditions(bm, at, ac)
        action = rpg.SpellAction(); action.caster_idx = at; action.spell_idx = 0
        action.target_indices = [tgt]
        engine.resolve_cast(bm, action)
        if engine.get_agent_conditions(bm, tgt).frightened:
            fails += 1
    return fails / n


def test_magical_ambush_disadvantage_when_hidden():
    bm = setup_battle_map(); engine = setup_combat_engine()
    at  = add_agent_to_battle(engine, bm, create_test_agent("AT", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Tgt", 6, 5))
    # AT L9, DC 11 (prof 2, INT 12 → mod +1, 8+2+1). Target WIS mod 0 → needs 11 to save (~50%).
    _arcane_trickster(engine, bm, at, 9, intel=12, prof=2)
    engine.set_agent_spells(bm, at, [_save_fear_spell()])
    ts = engine.get_agent_stats(bm, tgt)
    ts.wis = 10; ts.save_prof_wis = False; ts.prof_bonus = 2; ts.hp_max = 200; ts.hp_cur = 200
    engine.set_agent_stats(bm, tgt, ts)

    open_rate   = _frighten_rate(engine, bm, at, tgt, hidden=False)
    hidden_rate = _frighten_rate(engine, bm, at, tgt, hidden=True)
    # Disadvantage on the save → the target fails (gets Frightened) noticeably more often.
    assert hidden_rate > open_rate + 0.12, \
        f"Magical Ambush should raise the failure rate (open {open_rate:.2f} vs hidden {hidden_rate:.2f})"
    print(f"✅ test_magical_ambush_disadvantage_when_hidden passed (open {open_rate:.2f} → hidden {hidden_rate:.2f})")


def test_no_magical_ambush_below_l9():
    bm = setup_battle_map(); engine = setup_combat_engine()
    at  = add_agent_to_battle(engine, bm, create_test_agent("AT", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Tgt", 6, 5))
    _arcane_trickster(engine, bm, at, 8, intel=12, prof=2)   # L8 < 9
    engine.set_agent_spells(bm, at, [_save_fear_spell()])
    ts = engine.get_agent_stats(bm, tgt)
    ts.wis = 10; ts.save_prof_wis = False; ts.prof_bonus = 2; ts.hp_max = 200; ts.hp_cur = 200
    engine.set_agent_stats(bm, tgt, ts)
    open_rate   = _frighten_rate(engine, bm, at, tgt, hidden=False)
    hidden_rate = _frighten_rate(engine, bm, at, tgt, hidden=True)
    # No Magical Ambush yet → being hidden must not change the save odds (allow noise).
    assert abs(hidden_rate - open_rate) < 0.12, \
        f"below L9, hidden should not change the save (open {open_rate:.2f} vs hidden {hidden_rate:.2f})"
    print("✅ test_no_magical_ambush_below_l9 passed")


# ─────────────────────────────────────────────────────────────────────────────
# Versatile Trickster (L13)
# ─────────────────────────────────────────────────────────────────────────────

def _spawn_mage_hand(bm, summoner_idx, col, row):
    cfg = rpg.AgentConfig()
    cfg.name = "Mage Hand"; cfg.sprite_path = "test.png"; cfg.size = 1
    cfg.start_col = col; cfg.start_row = row
    idx = bm.spawn_agent(cfg)
    bm.set_agent_summoner_idx(idx, summoner_idx)
    bm.set_agent_summon_spell(idx, "Mage Hand")
    return idx


def test_versatile_trickster_advantage_near_hand():
    bm = setup_battle_map(); engine = setup_combat_engine()
    at  = add_agent_to_battle(engine, bm, create_test_agent("AT", 7, 8))   # adjacent → in melee range
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Tgt", 8, 8), ac=1, hp=2000)
    _arcane_trickster(engine, bm, at, 13)
    engine.set_agent_weapons(bm, at, _three(_finesse_weapon()))
    # Target has already acted → no other Rogue advantage source; a Rogue Sneak only flags
    # cunning_strike_available when the hit had Advantage, so it proves Versatile Trickster fired.
    tc = engine.get_agent_conditions(bm, tgt)
    tc.has_taken_turn_this_combat = True
    engine.set_agent_conditions(bm, tgt, tc)
    # Mage Hand adjacent to the target (8,8) → Advantage.
    _spawn_mage_hand(bm, at, 8, 9)
    result = engine.execute_action(bm, rpg.Attack(at, tgt, 0))
    assert result.hit
    assert engine.get_agent_conditions(bm, at).cunning_strike_available, \
        "a creature next to the Mage Hand should be attacked with Advantage (→ Sneak qualifies)"
    print("✅ test_versatile_trickster_advantage_near_hand passed")


def test_no_versatile_trickster_when_hand_far():
    bm = setup_battle_map(); engine = setup_combat_engine()
    at  = add_agent_to_battle(engine, bm, create_test_agent("AT", 7, 8))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Tgt", 8, 8), ac=1, hp=2000)
    _arcane_trickster(engine, bm, at, 13)
    engine.set_agent_weapons(bm, at, _three(_finesse_weapon()))
    tc = engine.get_agent_conditions(bm, tgt)
    tc.has_taken_turn_this_combat = True
    engine.set_agent_conditions(bm, tgt, tc)
    _spawn_mage_hand(bm, at, 2, 3)   # hand far from the target
    result = engine.execute_action(bm, rpg.Attack(at, tgt, 0))
    assert result.hit
    assert not engine.get_agent_conditions(bm, at).cunning_strike_available, \
        "with the Mage Hand far away there is no Versatile Trickster Advantage → no Sneak"
    print("✅ test_no_versatile_trickster_when_hand_far passed")


def test_no_versatile_trickster_below_l13():
    bm = setup_battle_map(); engine = setup_combat_engine()
    at  = add_agent_to_battle(engine, bm, create_test_agent("AT", 7, 8))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Tgt", 8, 8), ac=1, hp=2000)
    _arcane_trickster(engine, bm, at, 11)   # < 13
    engine.set_agent_weapons(bm, at, _three(_finesse_weapon()))
    tc = engine.get_agent_conditions(bm, tgt)
    tc.has_taken_turn_this_combat = True
    engine.set_agent_conditions(bm, tgt, tc)
    _spawn_mage_hand(bm, at, 8, 9)
    result = engine.execute_action(bm, rpg.Attack(at, tgt, 0))
    assert result.hit
    assert not engine.get_agent_conditions(bm, at).cunning_strike_available, \
        "Versatile Trickster needs L13"
    print("✅ test_no_versatile_trickster_below_l13 passed")


# ─────────────────────────────────────────────────────────────────────────────
# Spell Thief (L17)
# ─────────────────────────────────────────────────────────────────────────────

class SpellThiefDecider(rpg.CombatDecider):
    """Reacts to an OnDeclareCast window by using Spell Thief (if steal=True) or skipping."""
    def __init__(self, steal):
        super().__init__()
        self._steal = steal
        self.windows = []
        self.last_options = []
    def choose_reaction(self, ctx):
        self.windows.append(ctx.window)
        self.last_options = [o.feature for o in ctx.options if o.kind == rpg.ReactionOptionKind.Feature]
        resp = rpg.ReactionResponse(); resp.option = -1
        if self._steal:
            for i, o in enumerate(ctx.options):
                if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "SpellThief":
                    resp.option = i; break
        return resp


def _fireball_like():
    """A damaging spell (so 'resolved' is detectable via target HP). Not Magic Missile, so no Shield
    window confounds the Spell Thief window."""
    sp = rpg.Spell(); sp.name = "Scorching Ray"; sp.level = 2
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.geometry = rpg.SpellGeometry.Multiple
    d = rpg.MagicDamageRoll(); d.type = rpg.MagicDamage.Fire; d.num_dice = 2; d.die_size = 6; d.bonus = 0
    sp.magic_damage_rolls = [d]
    return sp


def _spell_thief_setup(engine, bm, *, at_level=17, caster_intel=1):
    """Caster (Scorching Ray) at (5,5); Victim at (6,5); Arcane Trickster at (5,7)."""
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    victim = add_agent_to_battle(engine, bm, create_test_agent("Victim", 6, 5))
    at     = add_agent_to_battle(engine, bm, create_test_agent("AT", 5, 7))
    engine.set_agent_spells(bm, caster, [_fireball_like()])
    cs = engine.get_agent_stats(bm, caster)
    cs.spell_slots_remaining = [9, 9, 9, 0, 0, 0, 0, 0, 0]
    cs.intel = caster_intel; cs.save_prof_intel = False
    engine.set_agent_stats(bm, caster, cs)
    vs = engine.get_agent_stats(bm, victim)
    vs.hp_max = 200; vs.hp_cur = 200
    engine.set_agent_stats(bm, victim, vs)
    # AT L17, INT 20, prof 6 → spell save DC 19.
    _arcane_trickster(engine, bm, at, at_level, intel=20, prof=6)
    return caster, victim, at


def _cast_action(caster, victim):
    a = rpg.SpellAction(); a.caster_idx = caster; a.spell_idx = 0; a.target_indices = [victim]
    return a


def test_spell_thief_steals_on_failed_save():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, at = _spell_thief_setup(engine, bm, caster_intel=1)  # always fails DC 19
    dec = SpellThiefDecider(steal=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _cast_action(caster, victim))

    assert rpg.ReactionWindow.OnDeclareCast in dec.windows, "casting opens OnDeclareCast"
    assert "SpellThief" in dec.last_options, "the AT should be offered Spell Thief"
    assert engine.last_cast_countered(), "a failed INT save counters the cast"
    assert engine.get_agent_stats(bm, victim).hp_cur == 200, "a stolen cast deals no damage"
    assert "Scorching Ray" in list(engine.get_agent_stats(bm, caster).stolen_spell_names), \
        "the spell should be added to the caster's stolen list"
    assert engine.get_agent_conditions(bm, at).reaction_used, "Spell Thief spends the reaction"
    print("✅ test_spell_thief_steals_on_failed_save passed")


def test_spell_thief_fails_on_successful_save():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, at = _spell_thief_setup(engine, bm, caster_intel=60)  # mod +25 → always beats DC 19
    dec = SpellThiefDecider(steal=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _cast_action(caster, victim))

    assert not engine.last_cast_countered(), "a successful INT save → not countered"
    assert engine.get_agent_stats(bm, victim).hp_cur < 200, "the spell resolves → Victim takes damage"
    assert not list(engine.get_agent_stats(bm, caster).stolen_spell_names), "nothing is stolen on a save"
    assert engine.get_agent_conditions(bm, at).reaction_used, "the reaction is spent either way"
    print("✅ test_spell_thief_fails_on_successful_save passed")


def test_stolen_spell_cannot_be_recast():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, at = _spell_thief_setup(engine, bm, caster_intel=1)
    dec = SpellThiefDecider(steal=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _cast_action(caster, victim))
    assert "Scorching Ray" in list(engine.get_agent_stats(bm, caster).stolen_spell_names)
    # The caster tries again: the spell is locked → no effect (the AT already used its reaction).
    hp_before = engine.get_agent_stats(bm, victim).hp_cur
    res = engine.resolve_cast(bm, _cast_action(caster, victim))
    assert not res.valid, "a stolen spell can't be cast (executeSpell refuses it)"
    assert engine.get_agent_stats(bm, victim).hp_cur == hp_before, "the locked spell deals no damage"
    print("✅ test_stolen_spell_cannot_be_recast passed")


def test_long_rest_clears_stolen_spells():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, at = _spell_thief_setup(engine, bm, caster_intel=1)
    dec = SpellThiefDecider(steal=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _cast_action(caster, victim))
    assert list(engine.get_agent_stats(bm, caster).stolen_spell_names), "spell stolen"
    engine.apply_long_rest(bm)
    assert not list(engine.get_agent_stats(bm, caster).stolen_spell_names), \
        "a long rest clears the 8-hour Spell Thief lock"
    # And the caster can cast it again.
    engine.set_decider(SpellThiefDecider(steal=False))
    res = engine.resolve_cast(bm, _cast_action(caster, victim))
    assert res.valid, "after a long rest the spell works again"
    print("✅ test_long_rest_clears_stolen_spells passed")


def test_no_spell_thief_below_l17():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, at = _spell_thief_setup(engine, bm, at_level=16, caster_intel=1)  # L16 < 17
    dec = SpellThiefDecider(steal=True); engine.set_decider(dec)
    engine.resolve_cast(bm, _cast_action(caster, victim))
    assert "SpellThief" not in dec.last_options, "Spell Thief needs L17"
    assert not engine.last_cast_countered(), "no steal below L17"
    assert not list(engine.get_agent_stats(bm, caster).stolen_spell_names)
    print("✅ test_no_spell_thief_below_l17 passed")


def test_spell_thief_skip_resolves():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster, victim, at = _spell_thief_setup(engine, bm, caster_intel=1)
    dec = SpellThiefDecider(steal=False); engine.set_decider(dec)   # offered but declines
    engine.resolve_cast(bm, _cast_action(caster, victim))
    assert "SpellThief" in dec.last_options, "still offered the option"
    assert not engine.last_cast_countered(), "declining → the spell resolves"
    assert engine.get_agent_stats(bm, victim).hp_cur < 200, "Victim takes damage"
    assert not engine.get_agent_conditions(bm, at).reaction_used, "skipping spends no reaction"
    print("✅ test_spell_thief_skip_resolves passed")


if __name__ == "__main__":
    test_third_caster_chassis()
    test_no_spellcasting_below_l3()
    test_magical_ambush_disadvantage_when_hidden()
    test_no_magical_ambush_below_l9()
    test_versatile_trickster_advantage_near_hand()
    test_no_versatile_trickster_when_hand_far()
    test_no_versatile_trickster_below_l13()
    test_spell_thief_steals_on_failed_save()
    test_spell_thief_fails_on_successful_save()
    test_stolen_spell_cannot_be_recast()
    test_long_rest_clears_stolen_spells()
    test_no_spell_thief_below_l17()
    test_spell_thief_skip_resolves()
    print("\n✅ All Arcane Trickster subclass tests passed")
