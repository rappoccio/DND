#!/usr/bin/env python3
"""
Tests for SPELL_IMPLEMENTATION_PLAN.md **Tier 1** — the 12 quick-win spells.

Each spell is loaded straight from `gui/spells.json` via the real `helpers._dict_to_spell`
path, so these tests cover BOTH the authored JSON payloads and the engine wiring
(new Agent::Stats buff/debuff flags, the addAgentCondition / clearSpellConditionEffect
branches, and the mechanic hooks in saveAdvantageFor / determineAdvantage / rollDamage /
applyCharmed). Saves are made deterministic by pitting a DC-24 caster against a
save-ability-1 victim (always fails) or a DC-8 caster against a save-ability-30 target
(always saves).

Covered: False Life, Longstrider, Expeditious Retreat, Blur, Barkskin,
Ray of Enfeeblement, Enlarge/Reduce, Regenerate, Divine Word, Dominate Monster,
Mind Blank, Foresight.
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
import helpers
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)

_GUI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")
PSYCHIC = 7  # MagicDamage_t::Psychic


def _load_spell(name):
    """Build an rpg.Spell straight from spells.json via the real loader."""
    with open(os.path.join(_GUI_DIR, "spells.json")) as f:
        data = json.load(f)
    for entry in data:
        if entry.get("name") == name:
            return helpers._dict_to_spell(entry)
    raise AssertionError(f"{name} not found in spells.json")


def _place(engine, bm, name, col, row, faction=1):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    bm.set_agent_faction(idx, faction)
    return idx


def _strong_caster(engine, bm, idx):
    """Spell save DC 24 (8 + prof 6 + CHA +10) — no ability-1 victim can beat it."""
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    s.spellcasting_ability = 5   # CHA
    s.cha = 30
    s.prof_bonus = 6
    engine.set_agent_stats(bm, idx, s)


def _weak_caster(engine, bm, idx):
    """Spell save DC 8 — an ability-30 target always saves."""
    s = engine.get_agent_stats(bm, idx)
    s.can_cast_spell = True
    s.spellcasting_ability = 5   # CHA
    s.cha = 10
    s.prof_bonus = 0
    engine.set_agent_stats(bm, idx, s)


def _set_ability(engine, bm, idx, **kw):
    s = engine.get_agent_stats(bm, idx)
    for k, v in kw.items():
        setattr(s, k, v)
    engine.set_agent_stats(bm, idx, s)


def _cast(engine, bm, caster, sp, targets, slot_level=None):
    engine.set_agent_spells(bm, caster, [sp])
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.slot_level = slot_level if slot_level is not None else sp.level
    action.target_indices = targets if isinstance(targets, list) else [targets]
    return engine.execute_spell(bm, action)


def _find_condition_id(engine, bm, agent_idx, name):
    for c in engine.active_agent_conditions:
        if c.agent_idx == agent_idx and c.condition_name == name:
            return c.condition_id
    return -1


# ─────────────────────────────────────────────────────────────────────────────
#  False Life
# ─────────────────────────────────────────────────────────────────────────────
def test_false_life_grants_temp_hp():
    """False Life grants a fixed 9 Temporary HP to the caster (hp_pool + pool_is_temp_hp)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    _strong_caster(engine, bm, caster)
    assert engine.get_agent_stats(bm, caster).temp_hp == 0
    _cast(engine, bm, caster, _load_spell("False Life"), [caster])
    assert engine.get_agent_stats(bm, caster).temp_hp == 9, "False Life should grant 9 temp HP"
    print("✅ test_false_life_grants_temp_hp passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Longstrider
# ─────────────────────────────────────────────────────────────────────────────
def test_longstrider_adds_speed_and_restores():
    """Longstrider adds +10 walk Speed; ending the condition restores it exactly."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Ranger", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _strong_caster(engine, bm, caster)
    base = engine.get_agent_stats(bm, ally).speed_walk
    _cast(engine, bm, caster, _load_spell("Longstrider"), [ally])

    s = engine.get_agent_stats(bm, ally)
    assert s.speed_walk == base + 10, f"speed should be +10, got {s.speed_walk} vs {base}"
    assert s.longstrider_bonus == 10

    cid = _find_condition_id(engine, bm, ally, "Longstriding")
    assert cid >= 0, "Longstriding condition should be tracked"
    engine.remove_agent_condition(bm, cid)
    s2 = engine.get_agent_stats(bm, ally)
    assert s2.speed_walk == base and s2.longstrider_bonus == 0, "speed should be restored on end"
    print("✅ test_longstrider_adds_speed_and_restores passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Expeditious Retreat
# ─────────────────────────────────────────────────────────────────────────────
def test_expeditious_retreat_grants_cunning_action():
    """Expeditious Retreat grants bonus-action Dash (Cunning Action); teardown removes it."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    _strong_caster(engine, bm, caster)
    assert not engine.get_agent_stats(bm, caster).has_cunning_action
    _cast(engine, bm, caster, _load_spell("Expeditious Retreat"), [caster])
    s = engine.get_agent_stats(bm, caster)
    assert s.has_cunning_action and s.expeditious_retreat, "should grant Cunning Action"

    engine.drop_concentration(bm, caster)   # concentration spell
    s2 = engine.get_agent_stats(bm, caster)
    assert not s2.has_cunning_action and not s2.expeditious_retreat, "teardown removes the grant"
    print("✅ test_expeditious_retreat_grants_cunning_action passed")


def test_expeditious_retreat_keeps_rogues_cunning_action():
    """The teardown must NOT strip a Rogue's innate Cunning Action (only the spell-granted one)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Rogue", 5, 5)
    _strong_caster(engine, bm, caster)
    _set_ability(engine, bm, caster, has_cunning_action=True)   # already a Rogue

    _cast(engine, bm, caster, _load_spell("Expeditious Retreat"), [caster])
    assert not engine.get_agent_stats(bm, caster).expeditious_retreat, \
        "already had Cunning Action → not marked spell-granted"
    engine.drop_concentration(bm, caster)
    assert engine.get_agent_stats(bm, caster).has_cunning_action, "Rogue keeps its Cunning Action"
    print("✅ test_expeditious_retreat_keeps_rogues_cunning_action passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Blur
# ─────────────────────────────────────────────────────────────────────────────
def test_blur_imposes_attacker_disadvantage():
    """Blur sets attackers_disadvantage; dropping concentration clears it."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Sorcerer", 5, 5)
    _strong_caster(engine, bm, caster)
    _cast(engine, bm, caster, _load_spell("Blur"), [caster])
    assert engine.get_agent_stats(bm, caster).attackers_disadvantage
    assert engine.get_agent_conditions(bm, caster).concentrating

    engine.drop_concentration(bm, caster)
    assert not engine.get_agent_stats(bm, caster).attackers_disadvantage
    print("✅ test_blur_imposes_attacker_disadvantage passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Barkskin
# ─────────────────────────────────────────────────────────────────────────────
def test_barkskin_raises_ac_to_17():
    """Barkskin raises a sub-17 AC to 17 and restores it on teardown."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Druid", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _strong_caster(engine, bm, caster)
    _set_ability(engine, bm, ally, base_ac=12)

    _cast(engine, bm, caster, _load_spell("Barkskin"), [ally])
    assert engine.get_agent_stats(bm, ally).base_ac == 17, "AC floored to 17"

    engine.drop_concentration(bm, caster)
    assert engine.get_agent_stats(bm, ally).base_ac == 12, "AC restored to original"
    print("✅ test_barkskin_raises_ac_to_17 passed")


def test_barkskin_does_not_lower_high_ac():
    """Barkskin never LOWERS an AC already at or above 17."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Druid", 5, 5)
    ally = _place(engine, bm, "Tank", 6, 5)
    _strong_caster(engine, bm, caster)
    _set_ability(engine, bm, ally, base_ac=20)

    _cast(engine, bm, caster, _load_spell("Barkskin"), [ally])
    s = engine.get_agent_stats(bm, ally)
    assert s.base_ac == 20 and s.barkskin_ac_bonus == 0, "AC 20 stays 20 (no floor applied)"
    print("✅ test_barkskin_does_not_lower_high_ac passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Ray of Enfeeblement
# ─────────────────────────────────────────────────────────────────────────────
def test_ray_of_enfeeblement_on_failed_save():
    """A failed CON save enfeebles; concentration drop clears it."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Warlock", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5, faction=2)
    _strong_caster(engine, bm, caster)
    _set_ability(engine, bm, foe, con=1)   # always fails DC 24

    _cast(engine, bm, caster, _load_spell("Ray of Enfeeblement"), [foe])
    assert engine.get_agent_stats(bm, foe).enfeebled, "failed save should enfeeble"

    engine.drop_concentration(bm, caster)
    assert not engine.get_agent_stats(bm, foe).enfeebled, "teardown clears enfeebled"
    print("✅ test_ray_of_enfeeblement_on_failed_save passed")


def test_ray_of_enfeeblement_saved():
    """A successful CON save is not enfeebled."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Warlock", 5, 5)
    foe = _place(engine, bm, "Stalwart", 6, 5, faction=2)
    _weak_caster(engine, bm, caster)       # DC 8
    _set_ability(engine, bm, foe, con=30)  # +10 → always saves

    _cast(engine, bm, caster, _load_spell("Ray of Enfeeblement"), [foe])
    assert not engine.get_agent_stats(bm, foe).enfeebled, "a save must not enfeeble"
    print("✅ test_ray_of_enfeeblement_saved passed")


# ── Behavioral: the enfeebled −1d8 damage rider ──────────────────────────────
def _fixed_damage_attacker(engine, bm):
    """Attacker with a flat-20 weapon (20d1) vs an AC-1 dummy, so every non-crit hit deals 20
    before any spell rider. Returns (attacker_idx, dummy_idx)."""
    atk = _place(engine, bm, "Bruiser", 5, 5)
    tgt = _place(engine, bm, "Dummy", 6, 5, faction=2)
    _set_ability(engine, bm, atk, str=10)           # +0 mod → no ability damage
    _set_ability(engine, bm, tgt, base_ac=1, hp_max=500, hp_cur=500)
    w = rpg.Weapon(); w.name = "Club"; w.type = rpg.WeaponType.Melee; w.reach_ft = 5
    pr = rpg.PhysicalDamageRoll(); pr.type = rpg.PhysicalDamage.Bludgeoning
    pr.num_dice = 20; pr.die_size = 1                # 20d1 = flat 20
    w.physical_damage_types = [pr]
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])
    return atk, tgt


def _sample_hit_damages(engine, bm, atk, tgt, trials=80):
    dmgs = []
    for _ in range(trials):
        # keep the dummy alive
        _set_ability(engine, bm, tgt, hp_max=500, hp_cur=500)
        r = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
        if r.hit and not r.critical:
            dmgs.append(r.total_damage)
    return dmgs


def test_enfeebled_reduces_weapon_damage():
    """An enfeebled attacker's flat-20 hit is reduced by 1d8 (12..19); baseline is exactly 20."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    atk, tgt = _fixed_damage_attacker(engine, bm)

    base = _sample_hit_damages(engine, bm, atk, tgt)
    assert base and all(d == 20 for d in base), f"baseline non-crit hits should be 20, got {set(base)}"

    _set_ability(engine, bm, atk, enfeebled=True)
    enf = _sample_hit_damages(engine, bm, atk, tgt)
    assert enf, "expected some non-crit hits while enfeebled"
    assert all(12 <= d <= 19 for d in enf), f"enfeebled should subtract 1..8, got {sorted(set(enf))}"
    print("✅ test_enfeebled_reduces_weapon_damage passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Enlarge/Reduce  (ships as Reduce — the debuff)
# ─────────────────────────────────────────────────────────────────────────────
def test_reduce_on_failed_save():
    """Enlarge/Reduce on an unwilling creature that fails its CON save → Reduced (size_damage_dice -1)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5, faction=2)
    _strong_caster(engine, bm, caster)
    _set_ability(engine, bm, foe, con=1)

    _cast(engine, bm, caster, _load_spell("Enlarge/Reduce"), [foe])
    assert engine.get_agent_stats(bm, foe).size_damage_dice == -1, "Reduce sets size_damage_dice -1"

    engine.drop_concentration(bm, caster)
    assert engine.get_agent_stats(bm, foe).size_damage_dice == 0, "teardown clears size_damage_dice"
    print("✅ test_reduce_on_failed_save passed")


def test_reduce_reduces_weapon_damage():
    """A reduced attacker's flat-20 hit is reduced by 1d4 (16..19)."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    atk, tgt = _fixed_damage_attacker(engine, bm)
    _set_ability(engine, bm, atk, size_damage_dice=-1)
    red = _sample_hit_damages(engine, bm, atk, tgt)
    assert red, "expected some non-crit hits while reduced"
    assert all(16 <= d <= 19 for d in red), f"reduce should subtract 1..4, got {sorted(set(red))}"
    print("✅ test_reduce_reduces_weapon_damage passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Regenerate
# ─────────────────────────────────────────────────────────────────────────────
def test_regenerate_heals_and_sets_regeneration():
    """Regenerate heals the burst 4d8+15 and grants 1 HP/turn regeneration; teardown restores prior."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Cleric", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _strong_caster(engine, bm, caster)
    _set_ability(engine, bm, ally, hp_max=100, hp_cur=10)

    _cast(engine, bm, caster, _load_spell("Regenerate"), [ally])
    s = engine.get_agent_stats(bm, ally)
    assert s.hp_cur >= 10 + 19, f"burst heal (>=4d8+15+mod) expected, hp {s.hp_cur}"
    assert s.regeneration_amount >= 1, "should grant turn-start regeneration"

    hp_before = engine.get_agent_stats(bm, ally).hp_cur
    engine.begin_turn(bm, ally)
    assert engine.get_agent_stats(bm, ally).hp_cur >= hp_before + 1, "regeneration heals 1 at turn start"

    cid = _find_condition_id(engine, bm, ally, "Regenerating")
    engine.remove_agent_condition(bm, cid)
    assert engine.get_agent_stats(bm, ally).regenerate_saved == -1, "teardown restores prior regen state"
    print("✅ test_regenerate_heals_and_sets_regeneration passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Divine Word  (HP-threshold tiers on a failed CHA save)
# ─────────────────────────────────────────────────────────────────────────────
def _divine_word_on(engine, bm, hp):
    caster = _place(engine, bm, "Cleric", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5, faction=2)
    _strong_caster(engine, bm, caster)
    _set_ability(engine, bm, foe, cha=1, hp_max=max(hp, 60), hp_cur=hp)
    _cast(engine, bm, caster, _load_spell("Divine Word"), [foe])
    return foe


def test_divine_word_kills_at_low_hp():
    """0–20 HP: the target dies."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    foe = _divine_word_on(engine, bm, 15)
    assert engine.get_agent_conditions(bm, foe).dead, "≤20 HP target should die"
    print("✅ test_divine_word_kills_at_low_hp passed")


def test_divine_word_stuns_mid_low_hp():
    """21–30 HP: Blinded + Deafened + Stunned."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    foe = _divine_word_on(engine, bm, 25)
    c = engine.get_agent_conditions(bm, foe)
    assert c.blinded and c.deafened and c.stunned and not c.dead, "21–30 HP → blind+deaf+stun"
    print("✅ test_divine_word_stuns_mid_low_hp passed")


def test_divine_word_deafens_high_hp():
    """41–50 HP: Deafened only."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    foe = _divine_word_on(engine, bm, 45)
    c = engine.get_agent_conditions(bm, foe)
    assert c.deafened and not c.blinded and not c.stunned, "41–50 HP → deafened only"
    print("✅ test_divine_word_deafens_high_hp passed")


def test_divine_word_no_effect_above_50():
    """> 50 HP: no effect."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    foe = _divine_word_on(engine, bm, 60)
    c = engine.get_agent_conditions(bm, foe)
    assert not (c.deafened or c.blinded or c.stunned or c.dead), ">50 HP → unaffected"
    print("✅ test_divine_word_no_effect_above_50 passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Dominate Monster
# ─────────────────────────────────────────────────────────────────────────────
def test_dominate_monster_charms_on_failed_save():
    """A failed WIS save leaves the target Charmed; a success does not."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5, faction=2)
    _strong_caster(engine, bm, caster)
    _set_ability(engine, bm, foe, wis=1)
    _cast(engine, bm, caster, _load_spell("Dominate Monster"), [foe])
    assert engine.get_agent_conditions(bm, foe).charmed, "failed WIS save should Charm"
    print("✅ test_dominate_monster_charms_on_failed_save passed")


def test_dominate_monster_saved():
    """A successful WIS save is not Charmed."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    foe = _place(engine, bm, "Willful", 6, 5, faction=2)
    _weak_caster(engine, bm, caster)
    _set_ability(engine, bm, foe, wis=30)
    _cast(engine, bm, caster, _load_spell("Dominate Monster"), [foe])
    assert not engine.get_agent_conditions(bm, foe).charmed, "a save must not Charm"
    print("✅ test_dominate_monster_saved passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Mind Blank
# ─────────────────────────────────────────────────────────────────────────────
def test_mind_blank_grants_immunities():
    """Mind Blank sets immune_charm and zeroes the Psychic multiplier, and blocks Charmed."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _strong_caster(engine, bm, caster)

    _cast(engine, bm, caster, _load_spell("Mind Blank"), [ally])
    s = engine.get_agent_stats(bm, ally)
    assert s.immune_charm, "Mind Blank grants Charmed immunity"
    assert s.get_magic_damage_multiplier(PSYCHIC) == 0.0, "Mind Blank grants Psychic immunity"

    # A direct Charmed application is refused.
    c = rpg.ActiveAgentCondition()
    c.agent_idx = ally
    c.condition_name = "Charmed"
    c.turns_remaining = 10
    engine.add_agent_condition(bm, c)
    assert not engine.get_agent_conditions(bm, ally).charmed, "Mind Blank blocks the Charmed condition"

    cid = _find_condition_id(engine, bm, ally, "MindBlank")
    engine.remove_agent_condition(bm, cid)
    s2 = engine.get_agent_stats(bm, ally)
    assert not s2.immune_charm and s2.get_magic_damage_multiplier(PSYCHIC) == 1.0, \
        "teardown restores the Psychic multiplier and charm vulnerability"
    print("✅ test_mind_blank_grants_immunities passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Foresight
# ─────────────────────────────────────────────────────────────────────────────
def test_foresight_grants_advantage():
    """Foresight sets has_foresight (advantage on saves via save_advantage_for) and
    attackers_disadvantage; teardown clears both."""
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Wizard", 5, 5)
    ally = _place(engine, bm, "Ally", 6, 5)
    _strong_caster(engine, bm, caster)

    _cast(engine, bm, caster, _load_spell("Foresight"), [ally])
    s = engine.get_agent_stats(bm, ally)
    assert s.has_foresight and s.attackers_disadvantage
    # Advantage on ALL saves, not just one ability.
    for ab in (rpg.SaveAbility.Strength, rpg.SaveAbility.Dexterity, rpg.SaveAbility.Constitution,
               rpg.SaveAbility.Intelligence, rpg.SaveAbility.Wisdom, rpg.SaveAbility.Charisma):
        assert engine.save_advantage_for(bm, ally, ab), f"Foresight → advantage on {ab} saves"

    cid = _find_condition_id(engine, bm, ally, "Foresight")
    engine.remove_agent_condition(bm, cid)
    s2 = engine.get_agent_stats(bm, ally)
    assert not s2.has_foresight and not s2.attackers_disadvantage, "teardown clears Foresight"
    assert not engine.save_advantage_for(bm, ally, rpg.SaveAbility.Wisdom)
    print("✅ test_foresight_grants_advantage passed")


def run_all():
    test_false_life_grants_temp_hp()
    test_longstrider_adds_speed_and_restores()
    test_expeditious_retreat_grants_cunning_action()
    test_expeditious_retreat_keeps_rogues_cunning_action()
    test_blur_imposes_attacker_disadvantage()
    test_barkskin_raises_ac_to_17()
    test_barkskin_does_not_lower_high_ac()
    test_ray_of_enfeeblement_on_failed_save()
    test_ray_of_enfeeblement_saved()
    test_enfeebled_reduces_weapon_damage()
    test_reduce_on_failed_save()
    test_reduce_reduces_weapon_damage()
    test_regenerate_heals_and_sets_regeneration()
    test_divine_word_kills_at_low_hp()
    test_divine_word_stuns_mid_low_hp()
    test_divine_word_deafens_high_hp()
    test_divine_word_no_effect_above_50()
    test_dominate_monster_charms_on_failed_save()
    test_dominate_monster_saved()
    test_mind_blank_grants_immunities()
    test_foresight_grants_advantage()
    print("\n✅ All Tier 1 spell tests passed")


if __name__ == "__main__":
    run_all()
