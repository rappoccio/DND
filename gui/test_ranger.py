#!/usr/bin/env python3
"""
Ranger (2024 PHB) — Phase 1 (chassis) + Phase 2 (Hunter's Mark marked-target rider).

Covered here (the engine-level pieces):
  Chassis (initializeClassResources):
    · WIS spellcasting, STR+DEX save proficiencies, can_cast_spell
    · Extra Attack (num_attacks=2) at L5
    · Roving (+10 Speed, climb/swim = Speed) at L6
    · Favored Enemy free-cast uses = Proficiency Bonus (2/3/4/5/6 at L1/5/9/13/17)
    · Foe Slayer (L20) seeds the Hunter's Mark die to d10
  Marked-target rider (applyAttackResult, generic — also powers Warlock Hex):
    · a hit on the marked target adds the rider dice (Force for Hunter's Mark)
    · the rider fires ONLY on the marked target
    · die size / damage type are honoured (Hex = Necrotic; Foe Slayer = d10)
  Relentless Hunter (L13): damage can't break Concentration on Hunter's Mark.

The free-cast accounting (spend the "Favored Enemy" resource instead of a slot) and the
GUI re-mark-on-kill bonus action live in main.py and are not exercised here.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import json
import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle
from helpers import compute_companion_loadout, _dict_to_weapon

FORCE    = 3   # MagicDamage_t::Force
NECROTIC = 5   # MagicDamage_t::Necrotic
PSYCHIC  = 7   # MagicDamage_t::Psychic


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _place(engine, bm, name, col, row):
    return add_agent_to_battle(engine, bm, create_test_agent(name, col, row))


def _weapon(name="Sword", die=6):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.proficient = True
    w.bonus_hit = 50          # always land vs AC 10
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = 1
    pr.die_size = die
    w.physical_damage_types = [pr]
    return w


def _arm(engine, bm, idx):
    s = engine.get_agent_stats(bm, idx)
    s.str = 14
    s.prof_bonus = 2
    s.hp_max = 80
    s.hp_cur = 80
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [_weapon(), rpg.Weapon(), rpg.Weapon()])


def _target(engine, bm, idx, hp=400, ac=10):
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = hp
    s.hp_cur = hp
    s.base_ac = ac
    engine.set_agent_stats(bm, idx, s)


def _set_mark(engine, bm, attacker, target, dice=1, die=6, dtype=FORCE):
    s = engine.get_agent_stats(bm, attacker)
    s.hunters_mark_target    = target
    s.hunters_mark_dice      = dice
    s.hunters_mark_die_size  = die
    s.hunters_mark_damage_type = dtype
    engine.set_agent_stats(bm, attacker, s)


def _attack(engine, bm, a, t):
    return engine.execute_action(bm, rpg.Attack(a, t, 0))


def _land(engine, bm, a, t, tries=40):
    for _ in range(tries):
        r = _attack(engine, bm, a, t)
        if r.hit:
            return r
    raise AssertionError("attack never landed")


def _rider_amount(r):
    """Return the 'hunter's mark' rider amount in the breakdown, or None if absent."""
    for label, amount in r.damage_breakdown:
        if label == "hunter's mark":
            return amount
    return None


def _fresh(target_hp=400):
    bm = setup_battle_map()
    engine = setup_combat_engine()
    a = _place(engine, bm, "Ranger", 5, 5)
    t = _place(engine, bm, "Quarry", 5, 6)
    other = _place(engine, bm, "Bystander", 6, 5)
    _arm(engine, bm, a)
    _target(engine, bm, t, hp=target_hp)
    _target(engine, bm, other, hp=target_hp)
    return bm, engine, a, t, other


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 1 — chassis
# ─────────────────────────────────────────────────────────────────────────────

def test_chassis_spellcasting_and_saves():
    s = rpg.Stats()
    s.initialize_class_resources(rpg.CharacterClass.Ranger, 1)
    assert s.can_cast_spell, "Ranger can cast spells at L1"
    assert s.spellcasting_ability == 4, f"WIS (4) spellcasting, got {s.spellcasting_ability}"
    assert s.save_prof_str and s.save_prof_dex, "Ranger has STR + DEX save proficiencies"
    assert not s.save_prof_con, "Ranger does NOT have CON save proficiency"
    assert s.has_feat("Weapon Mastery"), "Ranger gains Weapon Mastery at L1"
    print("✅ test_chassis_spellcasting_and_saves")


def test_extra_attack_l5():
    s4 = rpg.Stats(); s4.initialize_class_resources(rpg.CharacterClass.Ranger, 4)
    assert s4.num_attacks == 1, f"no Extra Attack before L5, got {s4.num_attacks}"
    s5 = rpg.Stats(); s5.initialize_class_resources(rpg.CharacterClass.Ranger, 5)
    assert s5.num_attacks == 2, f"Extra Attack at L5, got {s5.num_attacks}"
    print("✅ test_extra_attack_l5")


def test_roving_speed_l6():
    s5 = rpg.Stats(); s5.initialize_class_resources(rpg.CharacterClass.Ranger, 5)
    assert s5.speed_walk == 30, f"no Roving before L6, got {s5.speed_walk}"
    s6 = rpg.Stats(); s6.initialize_class_resources(rpg.CharacterClass.Ranger, 6)
    assert s6.speed_walk == 40, f"Roving +10 ft at L6, got {s6.speed_walk}"
    assert s6.speed_climb == 40 and s6.speed_swim == 40, "Roving grants climb/swim = Speed"
    print("✅ test_roving_speed_l6")


def test_favored_enemy_uses_track_proficiency_bonus():
    # Favored Enemy column: 2/3/4/5/6 at L1/5/9/13/17 — exactly the proficiency bonus.
    for level, expect in [(1, 2), (4, 2), (5, 3), (8, 3), (9, 4), (13, 5), (17, 6), (20, 6)]:
        s = rpg.Stats()
        s.initialize_class_resources(rpg.CharacterClass.Ranger, level)
        fe = s.get_resource("Favored Enemy")
        assert fe is not None, f"L{level}: Favored Enemy resource exists"
        assert fe.max == expect, f"L{level}: expected {expect} free casts, got {fe.max}"
    print("✅ test_favored_enemy_uses_track_proficiency_bonus")


def test_foe_slayer_seeds_d10():
    s17 = rpg.Stats(); s17.initialize_class_resources(rpg.CharacterClass.Ranger, 17)
    assert s17.hunters_mark_die_size == 6, "die stays d6 before L20"
    s20 = rpg.Stats(); s20.initialize_class_resources(rpg.CharacterClass.Ranger, 20)
    assert s20.hunters_mark_die_size == 10, f"Foe Slayer seeds d10, got {s20.hunters_mark_die_size}"
    print("✅ test_foe_slayer_seeds_d10")


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 2 — marked-target rider
# ─────────────────────────────────────────────────────────────────────────────

def test_rider_adds_force_damage_on_marked_target():
    bm, engine, a, t, other = _fresh()
    _set_mark(engine, bm, a, t, dice=1, die=6, dtype=FORCE)
    r = _land(engine, bm, a, t)
    amt = _rider_amount(r)
    assert amt is not None, "the marked-target rider appears in the damage breakdown"
    assert 1 <= amt <= 6, f"a 1d6 Force rider is in [1,6], got {amt}"
    assert FORCE in [int(x) for x in r.magic_damage_types], "rider tags Force damage"
    print("✅ test_rider_adds_force_damage_on_marked_target")


def test_rider_only_on_marked_target():
    bm, engine, a, t, other = _fresh()
    _set_mark(engine, bm, a, t, dice=1, die=6, dtype=FORCE)
    # Attack the OTHER creature (not marked) — no rider.
    r = _land(engine, bm, a, other)
    assert _rider_amount(r) is None, "no rider when hitting a creature that isn't the mark"
    print("✅ test_rider_only_on_marked_target")


def test_no_rider_without_a_mark():
    bm, engine, a, t, other = _fresh()
    # hunters_mark_target defaults to -1 (no mark)
    r = _land(engine, bm, a, t)
    assert _rider_amount(r) is None, "no rider when the attacker has no active mark"
    print("✅ test_no_rider_without_a_mark")


def test_foe_slayer_rider_uses_d10():
    bm, engine, a, t, other = _fresh()
    _set_mark(engine, bm, a, t, dice=1, die=10, dtype=FORCE)
    # Sample several hits; at least one should exceed 6 (impossible on a d6), proving d10 is in effect.
    seen = []
    for _ in range(40):
        r = _attack(engine, bm, a, t)
        if r.hit:
            amt = _rider_amount(r)
            if amt is not None:
                seen.append(amt)
        # keep the quarry alive
        _target(engine, bm, t, hp=400)
    assert seen, "rider fired at least once"
    assert all(1 <= x <= 10 for x in seen), f"d10 rider stays in [1,10], got {seen}"
    assert max(seen) > 6, f"a d10 rider should sometimes exceed 6, got max {max(seen)}"
    print("✅ test_foe_slayer_rider_uses_d10")


def test_hex_rider_is_necrotic():
    bm, engine, a, t, other = _fresh()
    _set_mark(engine, bm, a, t, dice=1, die=6, dtype=NECROTIC)
    r = _land(engine, bm, a, t)
    assert _rider_amount(r) is not None, "Hex-style rider fires on the marked target"
    assert NECROTIC in [int(x) for x in r.magic_damage_types], "Hex rider tags Necrotic damage"
    print("✅ test_hex_rider_is_necrotic")


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 2 — Relentless Hunter (L13)
# ─────────────────────────────────────────────────────────────────────────────

def _make_concentrator(engine, bm, idx, level, spell_name):
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Ranger, level)
    s.con = 10
    s.hp_max = 200
    s.hp_cur = 200
    engine.set_agent_stats(bm, idx, s)
    c = engine.get_agent_conditions(bm, idx)
    c.concentrating = True
    c.concentrating_on = spell_name
    engine.set_agent_conditions(bm, idx, c)


def test_relentless_hunter_holds_hunters_mark():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _place(engine, bm, "Ranger", 5, 5)
    _make_concentrator(engine, bm, idx, level=13, spell_name="Hunter's Mark")
    # Massive damage (DC would be 500) — without Relentless Hunter this always breaks.
    lost = engine.check_concentration_on_damage(bm, idx, 1000)
    assert lost is False, "Relentless Hunter: damage can't break Concentration on Hunter's Mark"
    c = engine.get_agent_conditions(bm, idx)
    assert c.concentrating, "still concentrating after the hit"
    print("✅ test_relentless_hunter_holds_hunters_mark")


def test_relentless_hunter_does_not_protect_other_spells():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _place(engine, bm, "Ranger", 5, 5)
    _make_concentrator(engine, bm, idx, level=13, spell_name="Conjure Animals")
    lost = engine.check_concentration_on_damage(bm, idx, 1000)
    assert lost is True, "Relentless Hunter is specific to Hunter's Mark; other spells still break"
    print("✅ test_relentless_hunter_does_not_protect_other_spells")


def test_relentless_hunter_requires_level_13():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = _place(engine, bm, "Ranger", 5, 5)
    _make_concentrator(engine, bm, idx, level=12, spell_name="Hunter's Mark")
    lost = engine.check_concentration_on_damage(bm, idx, 1000)
    assert lost is True, "before L13, Hunter's Mark concentration can still be broken"
    print("✅ test_relentless_hunter_requires_level_13")


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 2 — Precise Hunter (L17, now testable via r.advantage)
# ─────────────────────────────────────────────────────────────────────────────

def test_precise_hunter_advantage_vs_mark():
    bm, engine, a, t, other = _fresh()
    s = engine.get_agent_stats(bm, a)
    s.set_class_level(rpg.CharacterClass.Ranger, 17)
    engine.set_agent_stats(bm, a, s)
    _set_mark(engine, bm, a, t)
    r = _attack(engine, bm, a, t)
    assert r.advantage, "Precise Hunter grants Advantage on attacks vs the marked target"
    # A non-marked creature gets no Precise Hunter advantage.
    r2 = _attack(engine, bm, a, other)
    assert not r2.advantage, "no Precise Hunter advantage vs an unmarked creature"
    print("✅ test_precise_hunter_advantage_vs_mark")


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 3.1 — Hunter subclass
# ─────────────────────────────────────────────────────────────────────────────

def _make_hunter(engine, bm, idx, level, prey=None, tactics=None):
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Ranger, level)
    s.ranger_subclass = rpg.RangerSubclass.Hunter
    if prey is not None:
        s.hunter_prey = prey
    if tactics is not None:
        s.defensive_tactics = tactics
    s.str = 14
    s.prof_bonus = 2 + (level - 1) // 4
    s.hp_max = 200
    s.hp_cur = 200
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [_weapon(), rpg.Weapon(), rpg.Weapon()])


def _colossus_amount(r):
    for label, amount in r.damage_breakdown:
        if label == "colossus slayer":
            return amount
    return None


def test_colossus_slayer_hits_wounded_target():
    bm, engine, a, t, other = _fresh()
    _make_hunter(engine, bm, a, 3, prey=rpg.HunterPrey.ColossusSlayer)
    _target(engine, bm, t, hp=400)
    s = engine.get_agent_stats(bm, t); s.hp_cur = 300; engine.set_agent_stats(bm, t, s)  # wounded
    r = _land(engine, bm, a, t)
    amt = _colossus_amount(r)
    assert amt is not None and 1 <= amt <= 8, f"Colossus Slayer adds 1d8 to a wounded target, got {amt}"
    print("✅ test_colossus_slayer_hits_wounded_target")


def test_colossus_slayer_not_on_full_hp_first_hit():
    bm, engine, a, t, other = _fresh()
    _make_hunter(engine, bm, a, 3, prey=rpg.HunterPrey.ColossusSlayer)
    _target(engine, bm, t, hp=400)  # full HP
    r = _land(engine, bm, a, t)
    assert _colossus_amount(r) is None, "no Colossus Slayer on the first hit against a full-HP target"
    print("✅ test_colossus_slayer_not_on_full_hp_first_hit")


def test_colossus_slayer_once_per_turn():
    bm, engine, a, t, other = _fresh()
    _make_hunter(engine, bm, a, 3, prey=rpg.HunterPrey.ColossusSlayer)
    _target(engine, bm, t, hp=400)
    s = engine.get_agent_stats(bm, t); s.hp_cur = 300; engine.set_agent_stats(bm, t, s)
    r1 = _land(engine, bm, a, t)
    assert _colossus_amount(r1) is not None, "first hit gets Colossus Slayer"
    # Same turn (no turn() reset), second hit must NOT get it.
    fired_again = False
    for _ in range(20):
        r2 = _attack(engine, bm, a, t)
        if r2.hit and _colossus_amount(r2) is not None:
            fired_again = True
            break
    assert not fired_again, "Colossus Slayer is once per turn"
    print("✅ test_colossus_slayer_once_per_turn")


def test_horde_breaker_sets_available_flag():
    bm, engine, a, t, other = _fresh()
    _make_hunter(engine, bm, a, 3, prey=rpg.HunterPrey.HordeBreaker)
    _target(engine, bm, t, hp=400)
    _land(engine, bm, a, t)
    c = engine.get_agent_conditions(bm, a)
    assert c.horde_breaker_available, "a weapon hit flags the Horde Breaker extra attack as available"
    print("✅ test_horde_breaker_sets_available_flag")


def test_escape_the_horde_opportunity_disadvantage():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = _place(engine, bm, "Goblin", 5, 5)
    hunter = _place(engine, bm, "Hunter", 5, 6)
    _arm(engine, bm, atk)
    _make_hunter(engine, bm, hunter, 7, tactics=rpg.DefensiveTactics.EscapeTheHorde)
    # An Opportunity Attack against the Hunter has Disadvantage.
    action = rpg.Attack(atk, hunter, 0)
    action.opportunity = True
    r = engine.execute_action(bm, action)
    assert r.disadvantage, "Escape the Horde imposes Disadvantage on Opportunity Attacks vs the Hunter"
    # A normal (non-OA) attack is unaffected.
    r2 = engine.execute_action(bm, rpg.Attack(atk, hunter, 0))
    assert not r2.disadvantage, "Escape the Horde only affects Opportunity Attacks"
    print("✅ test_escape_the_horde_opportunity_disadvantage")


def test_multiattack_defense_second_attack_disadvantage():
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = _place(engine, bm, "Ogre", 5, 5)
    hunter = _place(engine, bm, "Hunter", 5, 6)
    _arm(engine, bm, atk)
    _make_hunter(engine, bm, hunter, 7, tactics=rpg.DefensiveTactics.MultiattackDefense)
    # First attack must HIT to register the attacker.
    _land(engine, bm, atk, hunter)
    c = engine.get_agent_conditions(bm, hunter)
    assert atk in list(c.multiattack_def_hit_by), "the attacker is recorded after hitting the Hunter"
    # Subsequent attacks by the same creature this turn have Disadvantage.
    r2 = engine.execute_action(bm, rpg.Attack(atk, hunter, 0))
    assert r2.disadvantage, "Multiattack Defense: a creature that hit the Hunter has Disadvantage on later attacks"
    print("✅ test_multiattack_defense_second_attack_disadvantage")


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 3.2 — Gloom Stalker subclass (Dread Ambusher / Iron Mind / Stalker's Flurry)
# ─────────────────────────────────────────────────────────────────────────────

def _gloom_stats(level, wis=16):
    """A bare Stats configured as a Gloom Stalker Ranger of the given level."""
    s = rpg.Stats()
    s.wis = wis
    s.set_class_level(rpg.CharacterClass.Ranger, level)
    s.ranger_subclass = rpg.RangerSubclass.GloomStalker
    s.initialize_class_resources(rpg.CharacterClass.Ranger, level)
    return s


def _make_gloom(engine, bm, idx, level=3, wis=16):
    s = engine.get_agent_stats(bm, idx)
    s.wis = wis
    s.set_class_level(rpg.CharacterClass.Ranger, level)
    s.ranger_subclass = rpg.RangerSubclass.GloomStalker
    s.initialize_class_resources(rpg.CharacterClass.Ranger, level)
    s.str = 14
    s.hp_max = 200
    s.hp_cur = 200
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [_weapon(), rpg.Weapon(), rpg.Weapon()])


def _arm_dreadful(engine, bm, idx):
    c = engine.get_agent_conditions(bm, idx)
    c.dreadful_strike_armed = True
    engine.set_agent_conditions(bm, idx, c)


def _dreadful_amount(r):
    for label, amount in r.damage_breakdown:
        if label == "dreadful strike":
            return amount
    return None


def test_gloom_stalker_chassis():
    s = _gloom_stats(3, wis=16)   # WIS +3
    assert s.dread_ambusher, "Dread Ambusher Initiative Bonus flag set at L3"
    assert s.dreadful_strike_dice == 2, "Dreadful Strike is 2 dice"
    assert s.dreadful_strike_die_size == 6, "Dreadful Strike is 2d6 before L11"
    da = s.get_resource("Dread Ambusher")
    assert da is not None and da.max == 3, f"uses = WIS mod (3), got {da.max if da else None}"
    assert not s.save_prof_wis, "Iron Mind (WIS save) only kicks in at L7"
    # A non-Gloom-Stalker Ranger has neither the flag nor the resource.
    plain = rpg.Stats(); plain.initialize_class_resources(rpg.CharacterClass.Ranger, 3)
    assert not plain.dread_ambusher, "no Initiative Bonus without Gloom Stalker"
    assert plain.get_resource("Dread Ambusher") is None, "no Dread Ambusher resource without the subclass"
    print("✅ test_gloom_stalker_chassis")


def test_dread_ambusher_uses_min_one():
    s = _gloom_stats(3, wis=8)    # WIS -1 → min one use
    da = s.get_resource("Dread Ambusher")
    assert da is not None and da.max == 1, f"at least 1 use even with a negative WIS mod, got {da.max}"
    print("✅ test_dread_ambusher_uses_min_one")


def test_initiative_bonus_adds_wis():
    # initiativeModifier folds in the WIS mod only when dread_ambusher is set.
    s = _gloom_stats(3, wis=16)   # DEX 10 (+0), WIS 16 (+3)
    s.dex = 10
    assert s.initiative_modifier == 3, f"Gloom Stalker initiative = DEX(0)+WIS(3), got {s.initiative_modifier}"
    plain = rpg.Stats(); plain.dex = 10; plain.wis = 16
    plain.initialize_class_resources(rpg.CharacterClass.Ranger, 3)
    assert plain.initiative_modifier == 0, "a plain Ranger gets no WIS-to-initiative"
    print("✅ test_initiative_bonus_adds_wis")


def test_iron_mind_wis_save_l7():
    s6 = _gloom_stats(6)
    assert not s6.save_prof_wis, "no WIS save proficiency before L7"
    s7 = _gloom_stats(7)
    assert s7.save_prof_wis, "Iron Mind grants WIS save proficiency at L7"
    print("✅ test_iron_mind_wis_save_l7")


def test_stalkers_flurry_upgrades_die_l11():
    s10 = _gloom_stats(10)
    assert s10.dreadful_strike_die_size == 6, "still 2d6 before L11"
    s11 = _gloom_stats(11)
    assert s11.dreadful_strike_die_size == 8, "Stalker's Flurry upgrades Dreadful Strike to 2d8 at L11"
    print("✅ test_stalkers_flurry_upgrades_die_l11")


def test_dreadful_strike_adds_psychic():
    bm, engine, a, t, other = _fresh()
    _make_gloom(engine, bm, a, level=3)
    _arm_dreadful(engine, bm, a)
    r = _land(engine, bm, a, t)
    amt = _dreadful_amount(r)
    assert amt is not None and 2 <= amt <= 12, f"Dreadful Strike adds 2d6 Psychic, got {amt}"
    assert PSYCHIC in [int(x) for x in r.magic_damage_types], "Dreadful Strike tags Psychic damage"
    print("✅ test_dreadful_strike_adds_psychic")


def test_dreadful_strike_requires_arming():
    bm, engine, a, t, other = _fresh()
    _make_gloom(engine, bm, a, level=3)   # NOT armed
    r = _land(engine, bm, a, t)
    assert _dreadful_amount(r) is None, "no Dreadful Strike damage until the class action arms it"
    print("✅ test_dreadful_strike_requires_arming")


def test_dreadful_strike_consumed_after_one_hit():
    bm, engine, a, t, other = _fresh()
    _make_gloom(engine, bm, a, level=3)
    _arm_dreadful(engine, bm, a)
    r1 = _land(engine, bm, a, t)
    assert _dreadful_amount(r1) is not None, "the armed hit gets Dreadful Strike"
    c = engine.get_agent_conditions(bm, a)
    assert not c.dreadful_strike_armed, "Dreadful Strike disarms after it lands"
    fired = False
    for _ in range(20):
        r2 = _attack(engine, bm, a, t)
        if r2.hit and _dreadful_amount(r2) is not None:
            fired = True
            break
        _target(engine, bm, t, hp=400)
    assert not fired, "Dreadful Strike fires only once per arming"
    print("✅ test_dreadful_strike_consumed_after_one_hit")


def test_dreadful_strike_l11_uses_2d8():
    bm, engine, a, t, other = _fresh()
    _make_gloom(engine, bm, a, level=11)
    seen = []
    for _ in range(60):
        _arm_dreadful(engine, bm, a)     # re-arm each swing
        r = _attack(engine, bm, a, t)
        if r.hit:
            amt = _dreadful_amount(r)
            if amt is not None:
                seen.append(amt)
        _target(engine, bm, t, hp=400)
    assert seen, "Dreadful Strike fired at least once"
    assert all(2 <= x <= 16 for x in seen), f"2d8 stays in [2,16], got {seen}"
    assert max(seen) > 12, f"a 2d8 rider should sometimes exceed 12 (2d6 max), got max {max(seen)}"
    print("✅ test_dreadful_strike_l11_uses_2d8")


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 3.4 — Fey Wanderer: Dreadful Strikes (rider) + Beguiling Twist (saves)
# ─────────────────────────────────────────────────────────────────────────────

def _fey_stats(level, wis=16):
    """A bare Stats configured as a Fey Wanderer Ranger of the given level."""
    s = rpg.Stats()
    s.wis = wis
    s.set_class_level(rpg.CharacterClass.Ranger, level)
    s.ranger_subclass = rpg.RangerSubclass.FeyWanderer
    s.initialize_class_resources(rpg.CharacterClass.Ranger, level)
    return s


def _make_fey(engine, bm, idx, level=3, wis=16):
    s = engine.get_agent_stats(bm, idx)
    s.wis = wis
    s.set_class_level(rpg.CharacterClass.Ranger, level)
    s.ranger_subclass = rpg.RangerSubclass.FeyWanderer
    s.initialize_class_resources(rpg.CharacterClass.Ranger, level)
    s.str = 14
    s.hp_max = 200
    s.hp_cur = 200
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [_weapon(), rpg.Weapon(), rpg.Weapon()])


def _fey_amount(r):
    for label, amount in r.damage_breakdown:
        if label == "dreadful strikes":
            return amount
    return None


def _reset_fey_used(engine, bm, idx):
    """Clear the once-per-turn flag, simulating a fresh turn."""
    c = engine.get_agent_conditions(bm, idx)
    c.fey_dreadful_strikes_used = False
    engine.set_agent_conditions(bm, idx, c)


def test_fey_wanderer_chassis():
    s3 = _fey_stats(3)
    assert s3.fey_dreadful_strikes, "Dreadful Strikes flag set at FeyWanderer L3"
    assert s3.fey_dreadful_strikes_die_size == 4, "Dreadful Strikes is 1d4 before L11"
    # Not before L3, and not for a plain Ranger.
    s2 = _fey_stats(2)
    assert not s2.fey_dreadful_strikes, "no Dreadful Strikes before L3"
    plain = rpg.Stats(); plain.initialize_class_resources(rpg.CharacterClass.Ranger, 3)
    assert not plain.fey_dreadful_strikes, "no Dreadful Strikes without the Fey Wanderer subclass"
    print("✅ test_fey_wanderer_chassis")


def test_fey_dreadful_strikes_upgrades_die_l11():
    s10 = _fey_stats(10)
    assert s10.fey_dreadful_strikes_die_size == 4, "still 1d4 before L11"
    s11 = _fey_stats(11)
    assert s11.fey_dreadful_strikes_die_size == 6, "Dreadful Strikes upgrades to 1d6 at L11"
    print("✅ test_fey_dreadful_strikes_upgrades_die_l11")


def test_fey_dreadful_strikes_adds_psychic_once_per_turn():
    bm, engine, a, t, other = _fresh()
    _make_fey(engine, bm, a, level=3)
    r1 = _land(engine, bm, a, t)
    amt = _fey_amount(r1)
    assert amt is not None and 1 <= amt <= 4, f"Dreadful Strikes adds 1d4 Psychic, got {amt}"
    assert PSYCHIC in [int(x) for x in r1.magic_damage_types], "Dreadful Strikes tags Psychic damage"
    # Once per turn: a second hit this turn carries no rider.
    r2 = _land(engine, bm, a, t)
    assert _fey_amount(r2) is None, "Dreadful Strikes fires only once per turn"
    # Fresh turn re-arms it.
    _reset_fey_used(engine, bm, a)
    r3 = _land(engine, bm, a, t)
    assert _fey_amount(r3) is not None, "Dreadful Strikes fires again on a new turn"
    print("✅ test_fey_dreadful_strikes_adds_psychic_once_per_turn")


def test_fey_dreadful_strikes_d6_at_l11():
    bm, engine, a, t, other = _fresh()
    _make_fey(engine, bm, a, level=11)
    seen = []
    for _ in range(80):
        _reset_fey_used(engine, bm, a)   # one rider per (simulated) turn
        r = _attack(engine, bm, a, t)
        if r.hit:
            amt = _fey_amount(r)
            if amt is not None:
                seen.append(amt)
        _target(engine, bm, t, hp=400)
    assert seen, "Dreadful Strikes fired at least once"
    assert all(1 <= x <= 6 for x in seen), f"1d6 stays in [1,6], got {seen}"
    assert max(seen) > 4, f"a 1d6 rider should sometimes exceed 4 (1d4 max), got max {max(seen)}"
    print("✅ test_fey_dreadful_strikes_d6_at_l11")


def _cause_fear_spell():
    """Single-target WIS-save spell that applies Frightened on a fail."""
    sp = rpg.Spell(); sp.name = "Cause Fear"; sp.level = 1
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = rpg.SaveAbility.SaveWis
    sp.geometry = rpg.SpellGeometry.Single
    c = rpg.AttackCondition()
    c.condition_name = "Frightened"; c.requires_save = True
    c.save_ability = rpg.SaveAbility.SaveWis; c.condition_duration = 10
    sp.conditions = [c]
    return sp


def _fear_caster(engine, bm, idx):
    """A moderate-DC fear caster (CHA 14, prof 2 → spell save DC 12)."""
    s = engine.get_agent_stats(bm, idx)
    s.cha = 14; s.prof_bonus = 2; s.spellcasting_ability = 5  # 5 = CHA
    s.spell_slots_remaining = [99, 0, 0, 0, 0, 0, 0, 0, 0]
    s.hp_max = 40; s.hp_cur = 40
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_spells(bm, idx, [_cause_fear_spell()])


def _fear_save_failures(engine, bm, caster, tgt, trials=300):
    """Cast Cause Fear `trials` times at tgt; count Frightened applications (failed saves).
    Clears Frightened/reaction between casts so each cast is an independent save."""
    fails = 0
    for _ in range(trials):
        c = engine.get_agent_conditions(bm, tgt)
        c.frightened = False; c.reaction_used = False; c.incapacitated = False
        engine.set_agent_conditions(bm, tgt, c)
        a = rpg.SpellAction(); a.caster_idx = caster; a.spell_idx = 0; a.target_indices = [tgt]
        engine.execute_spell(bm, a)
        if engine.get_agent_conditions(bm, tgt).frightened:
            fails += 1
    return fails


def test_beguiling_twist_advantage_vs_fear():
    # A Fey Wanderer L7 saving vs a Frighten spell rolls with Advantage and so fails the
    # save substantially less often than a plain Ranger L7 with identical ability scores.
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = _place(engine, bm, "Caster", 5, 5)
    fey    = _place(engine, bm, "FeyWanderer", 6, 5)
    plain  = _place(engine, bm, "PlainRanger", 7, 5)
    _fear_caster(engine, bm, caster)
    for idx, sub in [(fey, rpg.RangerSubclass.FeyWanderer), (plain, rpg.RangerSubclass.NONE)]:
        s = engine.get_agent_stats(bm, idx)
        s.set_class_level(rpg.CharacterClass.Ranger, 7)
        s.ranger_subclass = sub
        s.wis = 10  # +0, no proficiency seeded here → fails the DC 12 save often
        s.save_prof_wis = False
        s.initialize_class_resources(rpg.CharacterClass.Ranger, 7)
        s.hp_max = 200; s.hp_cur = 200
        engine.set_agent_stats(bm, idx, s)

    fey_fails   = _fear_save_failures(engine, bm, caster, fey)
    plain_fails = _fear_save_failures(engine, bm, caster, plain)
    assert plain_fails > 0, "control should fail the save sometimes"
    assert fey_fails < plain_fails * 0.8, \
        f"Beguiling Twist (Advantage) should fail markedly less: fey={fey_fails} vs plain={plain_fails}"
    print(f"✅ test_beguiling_twist_advantage_vs_fear (fey={fey_fails} < plain={plain_fails})")


def test_beguiling_twist_requires_l7():
    # A Fey Wanderer L6 does NOT yet have Beguiling Twist, so it fails like a plain Ranger.
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = _place(engine, bm, "Caster", 5, 5)
    fey6   = _place(engine, bm, "FeyL6", 6, 5)
    plain  = _place(engine, bm, "PlainRanger", 7, 5)
    _fear_caster(engine, bm, caster)
    for idx, lvl, sub in [(fey6, 6, rpg.RangerSubclass.FeyWanderer),
                          (plain, 6, rpg.RangerSubclass.NONE)]:
        s = engine.get_agent_stats(bm, idx)
        s.set_class_level(rpg.CharacterClass.Ranger, lvl)
        s.ranger_subclass = sub
        s.wis = 10; s.save_prof_wis = False
        s.initialize_class_resources(rpg.CharacterClass.Ranger, lvl)
        s.hp_max = 200; s.hp_cur = 200
        engine.set_agent_stats(bm, idx, s)
    fey_fails   = _fear_save_failures(engine, bm, caster, fey6, trials=200)
    plain_fails = _fear_save_failures(engine, bm, caster, plain, trials=200)
    # No advantage at L6 → roughly comparable failure rates (within 25%).
    assert abs(fey_fails - plain_fails) <= plain_fails * 0.25 + 10, \
        f"L6 Fey Wanderer should NOT get advantage: fey={fey_fails} vs plain={plain_fails}"
    print(f"✅ test_beguiling_twist_requires_l7 (fey={fey_fails} ≈ plain={plain_fails})")


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 3.3 — Beast Master: Primal Companion (engine-level invariants)
#
#  The summon flow itself lives in main.py (GUI); these tests pin the engine-facing
#  pieces: the PrimalCompanion enum round-trips on Stats, the level/PB scaling
#  (helpers.compute_companion_loadout), and that an attack built from that loadout
#  resolves with to-hit = the Ranger's spell-attack modifier and damage bonus = PB.
# ─────────────────────────────────────────────────────────────────────────────

def _companion_blocks():
    path = os.path.join(os.path.dirname(__file__), "primal_companions.json")
    with open(path) as f:
        return {b["form"]: b for b in json.load(f)}


def _spawn_companion(engine, bm, block, pb, level, wis_mod, col, row):
    """Apply a Primal Companion loadout to a fresh agent; return its index."""
    stats_d, weapon_d = compute_companion_loadout(block, pb, level, wis_mod)
    idx = _place(engine, bm, block["name"], col, row)
    cs = engine.get_agent_stats(bm, idx)
    for k, v in stats_d.items():
        setattr(cs, k, v)
    engine.set_agent_stats(bm, idx, cs)
    engine.set_agent_weapons(bm, idx, [_dict_to_weapon(weapon_d), rpg.Weapon(), rpg.Weapon()])
    return idx


def test_primal_companion_enum_roundtrips():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "BeastMaster", 5, 5)
    s = engine.get_agent_stats(bm, a)
    for form in (rpg.PrimalCompanion.Land, rpg.PrimalCompanion.Sea, rpg.PrimalCompanion.Sky):
        s.primal_companion = form
        engine.set_agent_stats(bm, a, s)
        assert engine.get_agent_stats(bm, a).primal_companion == form
    print("✅ test_primal_companion_enum_roundtrips")


def test_companion_hp_ac_scale_with_ranger():
    blocks = _companion_blocks()
    land, _ = compute_companion_loadout(blocks["Land"], pb=4, level=11, wis_mod=3)
    assert land["hp_max"] == 5 + 5 * 11, land["hp_max"]   # Land: 5 + 5×level
    assert land["base_ac"] == 13 + 4, land["base_ac"]      # AC = 13 + PB
    sky, _ = compute_companion_loadout(blocks["Sky"], pb=3, level=5, wis_mod=2)
    assert sky["hp_max"] == 4 + 4 * 5, sky["hp_max"]       # Sky: 4 + 4×level
    print("✅ test_companion_hp_ac_scale_with_ranger")


def test_companion_attack_uses_spell_attack_mod():
    bm = setup_battle_map(); engine = setup_combat_engine()
    blocks = _companion_blocks()
    pb, wis_mod = 4, 3                       # Ranger spell-attack mod = 7
    # Place the target FIRST: _place() runs apply_agent_configs(), which recreates every agent
    # from its config and wipes stats/weapons set afterward. Spawning the companion last keeps its
    # loadout intact; the target's stats are then set with no further apply_agent_configs after.
    t = _place(engine, bm, "Dummy", 5, 6)
    comp = _spawn_companion(engine, bm, blocks["Land"], pb, 11, wis_mod, 5, 5)
    _target(engine, bm, t, hp=400, ac=1)
    r = _land(engine, bm, comp, t)
    assert r.attack_mod == pb + wis_mod, f"to-hit should be spell-attack mod {pb+wis_mod}, got {r.attack_mod}"
    assert r.damage_mod == pb, f"damage bonus should equal PB {pb}, got {r.damage_mod}"
    print("✅ test_companion_attack_uses_spell_attack_mod")


def test_sky_companion_attacks_with_dex():
    # The Sky beast has STR 6 but a finesse beak, so its to-hit still equals the
    # Ranger's spell-attack modifier rather than collapsing to the STR penalty.
    bm = setup_battle_map(); engine = setup_combat_engine()
    blocks = _companion_blocks()
    pb, wis_mod = 3, 2
    # Target placed before the companion: _place() → apply_agent_configs() recreates all agents and
    # would wipe a previously-configured companion. Spawn the companion last (see sibling test).
    t = _place(engine, bm, "Dummy", 5, 6)
    comp = _spawn_companion(engine, bm, blocks["Sky"], pb, 5, wis_mod, 5, 5)
    _target(engine, bm, t, hp=400, ac=1)
    r = _land(engine, bm, comp, t)
    assert r.attack_mod == pb + wis_mod, r.attack_mod
    assert r.damage_mod == pb, r.damage_mod
    print("✅ test_sky_companion_attacks_with_dex")


def test_bestial_fury_second_attack_at_l11():
    blocks = _companion_blocks()
    below, _ = compute_companion_loadout(blocks["Land"], pb=3, level=10, wis_mod=2)
    at,    _ = compute_companion_loadout(blocks["Land"], pb=4, level=11, wis_mod=3)
    assert below["num_attacks"] == 1, below["num_attacks"]
    assert at["num_attacks"] == 2, at["num_attacks"]       # Bestial Fury
    print("✅ test_bestial_fury_second_attack_at_l11")


def test_exceptional_training_l7():
    # L7 Exceptional Training: the companion gains Cunning Action (bonus-action Dash/Disengage/Hide)
    # and its natural weapon switches from its normal physical type to Force (a magic damage type).
    blocks = _companion_blocks()
    below, w_below = compute_companion_loadout(blocks["Land"], pb=3, level=6, wis_mod=2)
    at,    w_at    = compute_companion_loadout(blocks["Land"], pb=3, level=7, wis_mod=2)
    assert not below["has_cunning_action"], "no Cunning Action before L7"
    assert at["has_cunning_action"], "Exceptional Training grants Cunning Action at L7"
    assert w_below["physical_damage_types"] and not w_below["magic_damage_types"], "physical below L7"
    assert not w_at["physical_damage_types"], "no physical roll at L7+"
    assert w_at["magic_damage_types"] and w_at["magic_damage_types"][0]["type"] == "Force", \
        f"L7+ attack deals Force, got {w_at['magic_damage_types']}"
    print("✅ test_exceptional_training_l7")


def test_bestial_fury_hm_splash_once_per_turn():
    # L11 Bestial Fury: the first time each turn the companion hits the creature marked by its
    # owning Ranger's Hunter's Mark, it deals extra (Force) damage equal to the mark's dice.
    bm = setup_battle_map(); engine = setup_combat_engine()
    blocks = _companion_blocks()
    pb, wis_mod, lvl = 4, 3, 11
    # Place everyone FIRST (each _place runs apply_agent_configs and wipes prior stats), then config.
    t      = _place(engine, bm, "Quarry", 5, 6)
    ranger = _place(engine, bm, "BeastMaster", 6, 6)
    comp   = _place(engine, bm, blocks["Land"]["name"], 5, 5)
    _target(engine, bm, t, hp=600, ac=1)
    rs = engine.get_agent_stats(bm, ranger)
    rs.character_class = rpg.CharacterClass.Ranger
    rs.ranger_subclass = rpg.RangerSubclass.BeastMaster
    rs.char_level = lvl
    rs.prof_bonus = pb
    rs.hunters_mark_target     = t
    rs.hunters_mark_dice       = 1
    rs.hunters_mark_die_size   = 6
    rs.hunters_mark_damage_type = FORCE
    engine.set_agent_stats(bm, ranger, rs)
    stats_d, weapon_d = compute_companion_loadout(blocks["Land"], pb, lvl, wis_mod)
    cs = engine.get_agent_stats(bm, comp)
    for k, v in stats_d.items():
        setattr(cs, k, v)
    engine.set_agent_stats(bm, comp, cs)
    engine.set_agent_weapons(bm, comp, [_dict_to_weapon(weapon_d), rpg.Weapon(), rpg.Weapon()])
    bm.set_agent_summoner_idx(comp, ranger)
    bm.set_agent_summon_spell(comp, "Primal Companion")

    def _has_fury(r):
        return any(lbl == "bestial fury" for lbl, _ in r.damage_breakdown)

    r1 = _land(engine, bm, comp, t)
    assert _has_fury(r1), f"first marked hit should carry Bestial Fury: {r1.damage_breakdown}"
    r2 = _land(engine, bm, comp, t)
    assert not _has_fury(r2), f"once per turn — second hit no Fury: {r2.damage_breakdown}"
    print("✅ test_bestial_fury_hm_splash_once_per_turn")


def test_bestial_fury_only_on_marked_target():
    # The splash fires only against the Ranger's Hunter's Mark target, not bystanders.
    bm = setup_battle_map(); engine = setup_combat_engine()
    blocks = _companion_blocks()
    pb, wis_mod, lvl = 4, 3, 11
    marked   = _place(engine, bm, "Quarry", 5, 6)
    other    = _place(engine, bm, "Bystander", 6, 6)
    ranger   = _place(engine, bm, "BeastMaster", 7, 6)
    comp     = _place(engine, bm, blocks["Land"]["name"], 5, 5)
    _target(engine, bm, marked, hp=600, ac=1)
    _target(engine, bm, other, hp=600, ac=1)
    rs = engine.get_agent_stats(bm, ranger)
    rs.character_class = rpg.CharacterClass.Ranger
    rs.ranger_subclass = rpg.RangerSubclass.BeastMaster
    rs.char_level = lvl
    rs.prof_bonus = pb
    rs.hunters_mark_target     = marked
    rs.hunters_mark_dice       = 1
    rs.hunters_mark_die_size   = 6
    rs.hunters_mark_damage_type = FORCE
    engine.set_agent_stats(bm, ranger, rs)
    stats_d, weapon_d = compute_companion_loadout(blocks["Land"], pb, lvl, wis_mod)
    cs = engine.get_agent_stats(bm, comp)
    for k, v in stats_d.items():
        setattr(cs, k, v)
    engine.set_agent_stats(bm, comp, cs)
    engine.set_agent_weapons(bm, comp, [_dict_to_weapon(weapon_d), rpg.Weapon(), rpg.Weapon()])
    bm.set_agent_summoner_idx(comp, ranger)
    bm.set_agent_summon_spell(comp, "Primal Companion")
    r = _land(engine, bm, comp, other)
    assert not any(lbl == "bestial fury" for lbl, _ in r.damage_breakdown), \
        f"no Fury vs an unmarked bystander: {r.damage_breakdown}"
    print("✅ test_bestial_fury_only_on_marked_target")


def test_companion_movement_modes():
    blocks = _companion_blocks()
    sky, _  = compute_companion_loadout(blocks["Sky"],  pb=2, level=3, wis_mod=2)
    land, _ = compute_companion_loadout(blocks["Land"], pb=2, level=3, wis_mod=2)
    sea, _  = compute_companion_loadout(blocks["Sea"],  pb=2, level=3, wis_mod=2)
    assert sky["speed_fly"] == 60 and land["speed_fly"] == 0
    assert sea["speed_swim"] == 40 and land["speed_swim"] == 0
    assert land["speed_walk"] == 40
    print("✅ test_companion_movement_modes")


# ─────────────────────────────────────────────────────────────────────────────

def run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\n🎉 All {len(fns)} Ranger tests passed")


if __name__ == "__main__":
    run_all()
