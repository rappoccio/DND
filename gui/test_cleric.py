#!/usr/bin/env python3
"""Cleric class features (engine-level pieces): Channel Divinity uses, Blessed Strikes
(Divine Strike rider + Potent Spellcasting cantrip bonus)."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _add(engine, bm, name, col, row, hp=40, wis=10):
    return add_agent_to_battle(engine, bm, create_test_agent(name, col, row), wis=wis, hp=hp)


def _cd(engine, bm, idx):
    return engine.get_agent_stats(bm, idx).resources["Channel Divinity"].current


def test_channel_divinity_uses_by_level():
    # 2024: Channel Divinity has 2 uses at L2, 3 at L6, 4 at L18 (none before L2).
    cases = [(1, 0), (2, 2), (5, 2), (6, 3), (17, 3), (18, 4), (20, 4)]
    for level, expected in cases:
        s = rpg.Stats()
        s.wis = 16
        s.initialize_class_resources(rpg.CharacterClass.Cleric, level)
        cd = s.resources["Channel Divinity"]
        assert cd.max == expected, f"L{level}: expected max {expected}, got {cd.max}"
        assert cd.current == expected, f"L{level}: expected current {expected}, got {cd.current}"
        assert cd.short_rest_regen == 1, f"L{level}: short-rest regen should be 1"
        assert cd.long_rest_regen == expected, f"L{level}: long-rest regen should restore to {expected}"
    print("✅ test_channel_divinity_uses_by_level passed")


def _melee_weapon():
    w = rpg.Weapon()
    w.name = "Mace"
    w.attack_bonus = 30  # effectively always hits (only a natural 1 misses)
    w.range_short_feet = 5
    w.range_long_feet = 5
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Bludgeoning
    pr.num_dice = 1
    pr.die_size = 4
    w.physical_damage_types = [pr]
    return w


def _arm_divine_strike_cleric(engine, bm, idx, level):
    s = engine.get_agent_stats(bm, idx)
    s.character_class = rpg.CharacterClass.Cleric
    s.char_level = level
    s.wis = 16
    s.hp_max = 40
    s.hp_cur = 40
    s.blessed_strike = rpg.BlessedStrike.DivineStrike
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [_melee_weapon()] * 3)


def _land_hit(engine, bm, attacker, target):
    attack = rpg.Attack(attacker, target, 0)
    for _ in range(12):
        r = engine.execute_action(bm, attack)
        if r.hit:
            return r
    return None


def test_divine_strike_adds_damage_once_per_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 5, 5)
    target = _add(engine, bm, "Goblin", 6, 5, hp=200)
    _arm_divine_strike_cleric(engine, bm, cleric, level=7)

    r = _land_hit(engine, bm, cleric, target)
    assert r is not None, "attack should land"
    assert engine.get_agent_conditions(bm, cleric).divine_strike_available, \
        "Divine Strike should be available after a qualifying weapon hit"

    base = r.total_damage
    hp_before = engine.get_agent_stats(bm, target).hp_cur
    engine.apply_divine_strike_effect(bm, cleric, target, True, r)  # Radiant
    extra = r.total_damage - base
    assert 1 <= extra <= 8, f"L7 Divine Strike should add 1d8, got {extra}"
    assert hp_before - engine.get_agent_stats(bm, target).hp_cur == extra, "target HP should drop by the extra damage"
    assert engine.get_agent_conditions(bm, cleric).divine_strike_used, "Divine Strike should be marked used"

    # Once per turn: a second application does nothing.
    base2 = r.total_damage
    engine.apply_divine_strike_effect(bm, cleric, target, True, r)
    assert r.total_damage == base2, "Divine Strike is once per turn"
    print("✅ test_divine_strike_adds_damage_once_per_turn passed")


def test_divine_strike_scales_at_14():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 5, 5)
    target = _add(engine, bm, "Goblin", 6, 5, hp=200)
    _arm_divine_strike_cleric(engine, bm, cleric, level=14)

    r = _land_hit(engine, bm, cleric, target)
    assert r is not None, "attack should land"
    base = r.total_damage
    engine.apply_divine_strike_effect(bm, cleric, target, False, r)  # Necrotic
    extra = r.total_damage - base
    assert 2 <= extra <= 16, f"L14 Divine Strike should add 2d8, got {extra}"
    print("✅ test_divine_strike_scales_at_14 passed")


def _potent_cantrip():
    s = rpg.Spell()
    s.name = "Test Cantrip"
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.Automatic
    s.range = 30
    s.level = 0
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Radiant
    roll.num_dice = 1
    roll.die_size = 8
    s.magic_damage_rolls = [roll]
    return s


def _cantrip_damage(blessed_strike):
    """Cast an identical damaging cantrip from a WIS-20 Cleric L7 and return damage dealt.
    Both engines share seed 42, so the 1d8 is identical — only the Potent bonus differs."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 5, 5)
    enemy = _add(engine, bm, "Goblin", 6, 5, hp=200)
    s = engine.get_agent_stats(bm, cleric)
    s.character_class = rpg.CharacterClass.Cleric
    s.char_level = 7
    s.wis = 20
    s.can_cast_spell = True
    s.blessed_strike = blessed_strike
    engine.set_agent_stats(bm, cleric, s)
    engine.set_agent_spells(bm, cleric, [_potent_cantrip()])

    action = rpg.SpellAction()
    action.caster_idx = cleric
    action.spell_idx = 0
    action.target_indices = [enemy]
    engine.execute_spell(bm, action)
    return 200 - engine.get_agent_stats(bm, enemy).hp_cur


def test_potent_spellcasting_adds_wis_to_cantrip():
    with_potent = _cantrip_damage(rpg.BlessedStrike.PotentSpellcasting)
    without = _cantrip_damage(rpg.BlessedStrike.NONE)
    assert with_potent == without + 5, \
        f"Potent Spellcasting should add WIS mod (+5) to cantrip damage: {with_potent} vs {without}"
    print("✅ test_potent_spellcasting_adds_wis_to_cantrip passed")


def test_turn_undead_frightens_sears_and_filters():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric     = _add(engine, bm, "Cleric",   5, 5)
    undead_in  = _add(engine, bm, "Skeleton",  6, 5, hp=100)
    undead_out = _add(engine, bm, "Zombie",   10, 10, hp=100)  # ~35 ft away, out of range
    nonundead  = _add(engine, bm, "Bandit",    5, 6, hp=100)

    cs = engine.get_agent_stats(bm, cleric)
    cs.character_class = rpg.CharacterClass.Cleric
    cs.char_level = 5            # Sear Undead online
    cs.wis = 20
    cs.prof_bonus = 3            # WIS save DC = 8 + 3 + 5 = 16
    cs.initialize_class_resources(rpg.CharacterClass.Cleric, 5)  # 2 Channel Divinity uses
    engine.set_agent_stats(bm, cleric, cs)
    for idx in (undead_in, undead_out):
        s = engine.get_agent_stats(bm, idx)
        s.is_undead = True
        s.wis = 1                # save tops out at 15 < DC 16 -> always fails
        s.hp_max = 100           # re-set: the later add_agent_to_battle calls rebuilt configs
        s.hp_cur = 100
        engine.set_agent_stats(bm, idx, s)
    # nonundead stays a living creature (is_undead False)
    ns = engine.get_agent_stats(bm, nonundead); ns.wis = 1; engine.set_agent_stats(bm, nonundead, ns)

    res = engine.use_turn_undead(bm, cleric)
    assert res.valid, "L5 Cleric with Channel Divinity should be able to Turn Undead"
    assert undead_in in list(res.turned), "in-range undead should be turned"
    assert undead_out not in list(res.turned) and undead_out not in list(res.resisted), \
        "out-of-range undead must be untouched"
    assert nonundead not in list(res.turned) and nonundead not in list(res.resisted), \
        "non-undead must be unaffected by Turn Undead"

    ci = engine.get_agent_conditions(bm, undead_in)
    assert ci.frightened and ci.incapacitated, "turned undead is Frightened + Incapacitated"
    assert res.sear_damage > 0, "Sear Undead should roll Radiant damage at L5"
    assert engine.get_agent_stats(bm, undead_in).hp_cur == 100 - res.sear_damage, \
        "Sear Undead damage should be applied to the turned undead"
    assert engine.get_agent_stats(bm, cleric).resources["Channel Divinity"].current == 1, \
        "Turn Undead spends one Channel Divinity use"
    print("✅ test_turn_undead_frightens_sears_and_filters passed")


def test_turn_undead_ends_on_damage():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric    = _add(engine, bm, "Cleric",   5, 5)
    undead_in = _add(engine, bm, "Skeleton",  6, 5, hp=200)

    cs = engine.get_agent_stats(bm, cleric)
    cs.character_class = rpg.CharacterClass.Cleric
    cs.char_level = 2            # no Sear (so the turn isn't self-cancelled by its own damage)
    cs.wis = 20
    cs.prof_bonus = 3
    cs.can_cast_spell = True
    cs.initialize_class_resources(rpg.CharacterClass.Cleric, 2)
    engine.set_agent_stats(bm, cleric, cs)
    s = engine.get_agent_stats(bm, undead_in); s.is_undead = True; s.wis = 1
    engine.set_agent_stats(bm, undead_in, s)

    engine.use_turn_undead(bm, cleric)
    assert engine.get_agent_conditions(bm, undead_in).frightened, "undead should be turned"

    # Any damage ends the turn effect (on_damage = End).
    action = rpg.SpellAction()  # use a quick automatic damage spell from the cleric
    zap = rpg.Spell(); zap.name = "Zap"; zap.type = rpg.SpellType.Harm
    zap.geometry = rpg.SpellGeometry.Single; zap.attack_type = rpg.SpellAttack.Automatic
    zap.range = 30; zap.level = 0
    roll = rpg.MagicDamageRoll(); roll.type = rpg.MagicDamage.Force; roll.num_dice = 1; roll.die_size = 4
    zap.magic_damage_rolls = [roll]
    engine.set_agent_spells(bm, cleric, [zap])
    action.caster_idx = cleric; action.spell_idx = 0; action.target_indices = [undead_in]
    engine.execute_spell(bm, action)

    ci = engine.get_agent_conditions(bm, undead_in)
    assert not ci.frightened and not ci.incapacitated, "taking damage ends Turn Undead"
    print("✅ test_turn_undead_ends_on_damage passed")


def _radiance(level):
    s = rpg.Spell()
    s.name = "Radiance of the Dawn"
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Sphere
    s.moves_with_caster = True   # 30-ft Emanation centered on the caster
    s.attack_type = rpg.SpellAttack.Save
    s.save_ability = rpg.SaveAbility.Constitution
    s.range = 0
    s.radius = 30
    s.duration = 1
    s.level = 0
    s.resource_name = "Channel Divinity"
    s.resource_cost = 1
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Radiant
    roll.num_dice = 2
    roll.die_size = 10
    roll.bonus = level           # 2d10 + Cleric level
    s.magic_damage_rolls = [roll]
    return s


def test_radiance_of_the_dawn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 5, 5)
    near   = _add(engine, bm, "Goblin", 6, 5, hp=200)
    far    = _add(engine, bm, "Ogre",  10, 10, hp=200)   # ~35 ft away, out of the 30-ft emanation

    cs = engine.get_agent_stats(bm, cleric)
    cs.character_class = rpg.CharacterClass.Cleric
    cs.cleric_subclass = rpg.ClericSubclass.LightDomain
    cs.char_level = 5
    cs.wis = 16
    cs.prof_bonus = 3
    cs.hp_max = 40; cs.hp_cur = 40
    cs.can_cast_spell = True
    cs.initialize_class_resources(rpg.CharacterClass.Cleric, 5)  # 2 Channel Divinity uses
    engine.set_agent_stats(bm, cleric, cs)
    for idx in (near, far):
        s = engine.get_agent_stats(bm, idx)
        s.hp_max = 200; s.hp_cur = 200  # re-set: later adds rebuilt configs
        engine.set_agent_spells(bm, idx, [])
        engine.set_agent_stats(bm, idx, s)
    engine.set_agent_spells(bm, cleric, [_radiance(5)])

    before_cd = _cd(engine, bm, cleric)
    action = rpg.SpellAction()
    action.caster_idx = cleric
    action.spell_idx = 0
    action.aoe_col = 5
    action.aoe_row = 5            # ignored for a moves_with_caster Sphere (centers on caster)
    res = engine.execute_spell(bm, action)

    assert res.valid, "Radiance should be a valid cast"
    hit = {tr.target_idx for tr in res.target_results}
    assert near in hit, "creature within 30 ft should be in the emanation"
    assert far not in hit, "creature beyond 30 ft must be untouched"
    assert cleric not in hit, "the caster is never affected by its own emanation"
    assert engine.get_agent_stats(bm, near).hp_cur < 200, "in-range creature should take Radiant damage"
    assert engine.get_agent_stats(bm, far).hp_cur == 200, "out-of-range creature takes none"
    assert _cd(engine, bm, cleric) == before_cd - 1, "Radiance spends one Channel Divinity"
    print("✅ test_radiance_of_the_dawn passed")


def test_war_priest_resource():
    s = rpg.Stats()
    s.wis = 16
    s.cleric_subclass = rpg.ClericSubclass.WarDomain
    s.initialize_class_resources(rpg.CharacterClass.Cleric, 3)
    wp = s.resources["War Priest"]
    assert wp.max == 3 and wp.current == 3, f"WIS 16 -> 3 War Priest uses, got {wp.max}"

    s2 = rpg.Stats()
    s2.wis = 16
    s2.initialize_class_resources(rpg.CharacterClass.Cleric, 3)  # no War domain
    assert "War Priest" not in s2.resources, "only War-domain Clerics get War Priest"
    print("✅ test_war_priest_resource passed")


def test_avatar_of_battle_resistance():
    # applyArmorMultipliers builds from the current multipliers (it doesn't reset to 1.0), so it's
    # run once from a clean state — use separate fresh agents for the L17 and L16 cases.
    bm = setup_battle_map(); engine = setup_combat_engine()
    war17 = _add(engine, bm, "WarL17", 5, 5)
    war16 = _add(engine, bm, "WarL16", 7, 7)
    for idx, lvl in ((war17, 17), (war16, 16)):
        s = engine.get_agent_stats(bm, idx)
        s.character_class = rpg.CharacterClass.Cleric
        s.cleric_subclass = rpg.ClericSubclass.WarDomain
        s.char_level = lvl
        engine.set_agent_stats(bm, idx, s)
        engine.apply_armor_multipliers(bm, idx)

    m17 = list(engine.get_agent_stats(bm, war17).physical_damage_multipliers)
    m16 = list(engine.get_agent_stats(bm, war16).physical_damage_multipliers)
    assert m17[:3] == [0.5, 0.5, 0.5], f"L17 War Cleric should resist B/P/S, got {m17[:3]}"
    assert m16[:3] == [1.0, 1.0, 1.0], f"L16 has no Avatar of Battle, got {m16[:3]}"
    print("✅ test_avatar_of_battle_resistance passed")


def _war_mace():
    w = rpg.Weapon()
    w.name = "Mace"
    w.attack_bonus = 0          # +0 so misses are common against AC 11
    w.range_short_feet = 5
    w.range_long_feet = 5
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Bludgeoning
    pr.num_dice = 1
    pr.die_size = 6
    w.physical_damage_types = [pr]
    return w


def test_guided_strike_turns_miss_to_hit():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "WarCleric", 5, 5)
    target = _add(engine, bm, "Goblin", 6, 5, hp=200)

    cs = engine.get_agent_stats(bm, cleric)
    cs.character_class = rpg.CharacterClass.Cleric
    cs.cleric_subclass = rpg.ClericSubclass.WarDomain
    cs.char_level = 3
    cs.wis = 16
    cs.initialize_class_resources(rpg.CharacterClass.Cleric, 3)  # 2 Channel Divinity uses
    engine.set_agent_stats(bm, cleric, cs)
    engine.set_agent_weapons(bm, cleric, [_war_mace()] * 3)
    ts = engine.get_agent_stats(bm, target)
    ts.base_ac = 11; ts.hp_max = 200; ts.hp_cur = 200  # miss roll (2-10) + 10 always >= 11
    engine.set_agent_stats(bm, target, ts)

    attack = rpg.Attack(cleric, target, 0)
    r = None
    for _ in range(40):
        r = engine.execute_action(bm, attack)
        if not r.hit and engine.get_agent_conditions(bm, cleric).guided_strike_available:
            break
    assert r is not None and not r.hit, "needed a non-fumble miss to guide"
    assert engine.get_agent_conditions(bm, cleric).guided_strike_available

    cd_before = _cd(engine, bm, cleric)
    hp_before = engine.get_agent_stats(bm, target).hp_cur
    engine.apply_guided_strike_effect(bm, attack, cleric, r)
    assert r.hit, "Guided Strike (+10) should turn the miss into a hit at AC 11"
    assert engine.get_agent_stats(bm, target).hp_cur < hp_before, "the now-hit should deal weapon damage"
    assert _cd(engine, bm, cleric) == cd_before - 1, "Guided Strike spends one Channel Divinity"
    assert not engine.get_agent_conditions(bm, cleric).guided_strike_available, "availability cleared after use"
    print("✅ test_guided_strike_turns_miss_to_hit passed")


class _GuideDecider(rpg.CombatDecider):
    """At an OnMiss window, pick the Guided Strike option (else Skip). Counts OnMiss offers."""
    def __init__(self):
        super().__init__()
        self.onmiss_offers = 0
    def choose_reaction(self, ctx):
        resp = rpg.ReactionResponse(); resp.option = -1
        if ctx.window == rpg.ReactionWindow.OnMiss:
            self.onmiss_offers += 1
            for i, o in enumerate(ctx.options):
                if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "GuidedStrike":
                    resp.option = i
                    break
        return resp


def test_guided_strike_auto_via_decider():
    # The auto/RL path: a self-guiding War Cleric routes Guided Strike through the OnMiss window
    # (maybeGuidedStrikeInline → chooseReaction), so execute_action itself turns a miss into a hit.
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "WarCleric", 5, 5)
    target = _add(engine, bm, "Goblin", 6, 5, hp=200)

    cs = engine.get_agent_stats(bm, cleric)
    cs.character_class = rpg.CharacterClass.Cleric
    cs.cleric_subclass = rpg.ClericSubclass.WarDomain
    cs.char_level = 3
    cs.wis = 16
    cs.initialize_class_resources(rpg.CharacterClass.Cleric, 3)
    engine.set_agent_stats(bm, cleric, cs)
    engine.set_agent_weapons(bm, cleric, [_war_mace()] * 3)
    ts = engine.get_agent_stats(bm, target)
    ts.base_ac = 11; ts.hp_max = 200; ts.hp_cur = 200  # miss roll (2-10) + 10 always >= 11
    engine.set_agent_stats(bm, target, ts)

    dec = _GuideDecider(); engine.set_decider(dec)
    attack = rpg.Attack(cleric, target, 0)
    r = None
    for _ in range(40):
        cd_before = _cd(engine, bm, cleric)
        r = engine.execute_action(bm, attack)
        if dec.onmiss_offers >= 1:
            # The miss opened the window and the decider guided it → it is now a hit, CD spent.
            assert r.hit, "Guided Strike (+10) should have turned the miss into a hit"
            assert _cd(engine, bm, cleric) == cd_before - 1, "Guided Strike spends one Channel Divinity"
            print("✅ test_guided_strike_auto_via_decider passed")
            return
        if r.hit:
            continue  # a natural hit doesn't open the OnMiss window; retry for a miss
    raise AssertionError("never produced a guided miss in 40 attempts")


def test_war_gods_blessing_extends_guided_reach():
    """War God's Blessing (L6) widens an ally War Cleric's Guided Strike reach from 30 ft to 60 ft:
    an ally cleric 40 ft from the attacker is eligible at L6 but not at L3."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    attacker = _add(engine, bm, "Fighter", 1, 1)
    target   = _add(engine, bm, "Goblin", 2, 1, hp=200)
    cleric   = _add(engine, bm, "WarCleric", 9, 1)              # 8 cells = 40 ft from the attacker

    cs = engine.get_agent_stats(bm, cleric)
    cs.character_class = rpg.CharacterClass.Cleric
    cs.cleric_subclass = rpg.ClericSubclass.WarDomain
    cs.wis = 16; cs.char_level = 6
    cs.initialize_class_resources(rpg.CharacterClass.Cleric, 6)  # Channel Divinity uses
    engine.set_agent_stats(bm, cleric, cs)

    attack = rpg.Attack(attacker, target, 0)
    assert engine.can_guided_strike(bm, attack, cleric), \
        "an L6 ally War Cleric should reach 40 ft (War God's Blessing extends to 60 ft)"

    cs.char_level = 3                                            # below L6 → only 30 ft reach
    engine.set_agent_stats(bm, cleric, cs)
    assert not engine.can_guided_strike(bm, attack, cleric), \
        "an L3 ally War Cleric only reaches 30 ft, so 40 ft is out of range"
    print("✅ test_war_gods_blessing_extends_guided_reach passed")


# ── Corona of Light (Light Domain, L17) ───────────────────────────────────────
def _light_cleric(engine, bm, idx, level=17, wis=16):
    s = engine.get_agent_stats(bm, idx)
    s.character_class = rpg.CharacterClass.Cleric
    s.cleric_subclass = rpg.ClericSubclass.LightDomain
    s.char_level = level
    s.wis = wis; s.prof_bonus = 6
    s.hp_max = 60; s.hp_cur = 60
    s.can_cast_spell = True
    s.initialize_class_resources(rpg.CharacterClass.Cleric, level)
    engine.set_agent_stats(bm, idx, s)


def _save_spell(name, dmg_type, num_dice=1, die_size=8):
    s = rpg.Spell()
    s.name = name
    s.type = rpg.SpellType.Harm
    s.geometry = rpg.SpellGeometry.Single
    s.attack_type = rpg.SpellAttack.Save
    s.save_ability = rpg.SaveAbility.Dexterity
    s.range = 60
    s.level = 0
    roll = rpg.MagicDamageRoll(); roll.type = dmg_type; roll.num_dice = num_dice; roll.die_size = die_size
    s.magic_damage_rolls = [roll]
    return s


def test_corona_activation_and_duration():
    """activate_corona_of_light gates on L17 Light Domain Cleric and sets a 10-round duration that
    ticks down at each turn start."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 5, 5)

    # Wrong level → rejected.
    _light_cleric(engine, bm, cleric, level=16)
    assert not engine.activate_corona_of_light(bm, cleric), "L16 Light cleric cannot use Corona"

    # Wrong subclass → rejected.
    _light_cleric(engine, bm, cleric, level=17)
    s = engine.get_agent_stats(bm, cleric); s.cleric_subclass = rpg.ClericSubclass.LifeDomain
    engine.set_agent_stats(bm, cleric, s)
    assert not engine.activate_corona_of_light(bm, cleric), "non-Light Domain cleric cannot use Corona"

    # Eligible → activates, sets 10 rounds.
    _light_cleric(engine, bm, cleric, level=17)
    assert engine.activate_corona_of_light(bm, cleric), "L17 Light cleric activates Corona"
    assert engine.get_agent_stats(bm, cleric).corona_of_light_turns == 10, "Corona lasts 10 rounds"

    engine.begin_turn(bm, cleric)
    assert engine.get_agent_stats(bm, cleric).corona_of_light_turns == 9, "first turn start ticks to 9"
    for _ in range(9):
        engine.begin_turn(bm, cleric)
    assert engine.get_agent_stats(bm, cleric).corona_of_light_turns == 0, "duration expires after 10 turns"
    print("✅ test_corona_activation_and_duration passed")


def _save_rate(engine, bm, cleric, target, spell, trials=300):
    """Cast a single-target Save spell `trials` times; return the fraction of successful saves."""
    engine.set_agent_spells(bm, cleric, [spell])
    saves = 0
    for _ in range(trials):
        t = engine.get_agent_stats(bm, target); t.hp_cur = t.hp_max  # keep it alive so the save is rolled
        engine.set_agent_stats(bm, target, t)
        action = rpg.SpellAction()
        action.caster_idx = cleric; action.spell_idx = 0; action.target_indices = [target]
        res = engine.execute_spell(bm, action)
        for tr in res.target_results:
            if tr.target_idx == target and tr.saved:
                saves += 1
    return saves / trials


def test_corona_disadvantage_on_fire_radiant_saves():
    """While Corona is active, an enemy within 60 ft saves LESS often vs the caster's Fire/Radiant
    spells (Disadvantage), but is unaffected for non-Fire/Radiant spells or when out of range / allied."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 1, 1)
    enemy  = _add(engine, bm, "Enemy", 1, 3, hp=100000)   # 10 ft, in range
    _light_cleric(engine, bm, cleric)
    e = engine.get_agent_stats(bm, enemy); e.dex = 18; e.hp_max = 100000; e.hp_cur = 100000
    engine.set_agent_stats(bm, enemy, e)

    radiant = _save_spell("Test Radiance", rpg.MagicDamage.Radiant)

    off = _save_rate(engine, bm, cleric, enemy, radiant)         # Corona inactive
    assert engine.activate_corona_of_light(bm, cleric)
    on = _save_rate(engine, bm, cleric, enemy, radiant)          # Corona active → Disadvantage
    assert on < off - 0.10, f"Corona should drop the save rate (off={off:.2f}, on={on:.2f})"

    # A non-Fire/Radiant spell is unaffected by Corona (save rate ~ unchanged).
    force = _save_spell("Test Force", rpg.MagicDamage.Force)
    force_on = _save_rate(engine, bm, cleric, enemy, force)
    assert force_on > off - 0.10, \
        f"Corona must not touch non-Fire/Radiant saves (off={off:.2f}, force_on={force_on:.2f})"
    print("✅ test_corona_disadvantage_on_fire_radiant_saves passed")


def test_corona_spares_allies():
    """Corona's Disadvantage is gated to ENEMIES: a same-faction ally in range is spared.
    (The >60-ft range gate can't be exercised on the 12x12 test map, which tops out at ~55 ft.)"""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 1, 1)
    ally   = _add(engine, bm, "Ally", 1, 3, hp=100000)
    _light_cleric(engine, bm, cleric)
    bm.set_agent_faction(cleric, 1)
    bm.set_agent_faction(ally, 1)                                 # same team → not an enemy
    a = engine.get_agent_stats(bm, ally); a.dex = 18; a.hp_max = 100000; a.hp_cur = 100000
    engine.set_agent_stats(bm, ally, a)

    radiant = _save_spell("Test Radiance", rpg.MagicDamage.Radiant)
    off = _save_rate(engine, bm, cleric, ally, radiant)
    assert engine.activate_corona_of_light(bm, cleric)
    on = _save_rate(engine, bm, cleric, ally, radiant)
    assert abs(on - off) < 0.12, f"an allied target must not get Disadvantage (off={off:.2f}, on={on:.2f})"
    print("✅ test_corona_spares_allies passed")


# ── Life Domain ───────────────────────────────────────────────────────────────
def _life_cleric(engine, bm, idx, level=3, wis=10):
    s = engine.get_agent_stats(bm, idx)
    s.character_class = rpg.CharacterClass.Cleric
    s.cleric_subclass = rpg.ClericSubclass.LifeDomain
    s.char_level = level
    s.wis = wis
    s.spellcasting_ability = 4          # WIS
    s.can_cast_spell = True
    s.initialize_class_resources(rpg.CharacterClass.Cleric, level)
    engine.set_agent_stats(bm, idx, s)
    return s


def _heal_spell(name="Cure Wounds", num_dice=1, die_size=8, bonus=0, level=1,
                geometry=rpg.SpellGeometry.Single):
    sp = rpg.Spell()
    sp.name = name
    sp.type = rpg.SpellType.Heal
    sp.geometry = geometry
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range = 30
    sp.level = level
    h = rpg.HealingRoll(); h.num_dice = num_dice; h.die_size = die_size; h.bonus = bonus
    sp.healing_type = h
    return sp


def _cast_heal(engine, bm, caster, target, sp, slot_level=1):
    engine.set_agent_spells(bm, caster, [sp])
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.target_indices = [target]
    action.slot_level = slot_level
    return engine.execute_spell(bm, action)


def _heal_amount(engine, bm, caster, target, sp, slot_level=1, wound=30):
    """Cast a heal on a wounded target; return the HP actually restored (capped by hp_max)."""
    t = engine.get_agent_stats(bm, target)
    t.hp_max = 200; t.hp_cur = 200 - wound
    engine.set_agent_stats(bm, target, t)
    before = engine.get_agent_stats(bm, target).hp_cur
    _cast_heal(engine, bm, caster, target, sp, slot_level)
    return engine.get_agent_stats(bm, target).hp_cur - before


def test_disciple_of_life_adds_to_each_heal():
    """Disciple of Life (L3): a slot-1+ heal restores an extra 2 + slot level HP to each creature.
    A fixed-bonus heal (0 dice) isolates the rider from die variance."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 1, 1)
    ally   = _add(engine, bm, "Ally", 1, 2)
    _life_cleric(engine, bm, cleric, level=3, wis=10)   # WIS mod 0

    sp = _heal_spell(num_dice=0, die_size=8, bonus=5)   # deterministic 5 HP base
    healed = _heal_amount(engine, bm, cleric, ally, sp, slot_level=1)
    assert healed == 5 + (2 + 1), f"L1 slot: 5 base + Disciple (2+1) = 8, got {healed}"

    healed3 = _heal_amount(engine, bm, cleric, ally, sp, slot_level=3)
    assert healed3 == 5 + (2 + 3), f"L3 slot: 5 base + Disciple (2+3) = 10, got {healed3}"

    # A non-Life cleric gets no Disciple bonus.
    plain = _add(engine, bm, "Plain", 3, 1)
    ps = engine.get_agent_stats(bm, plain)
    ps.character_class = rpg.CharacterClass.Cleric; ps.char_level = 3
    ps.spellcasting_ability = 4; ps.wis = 10; ps.can_cast_spell = True
    engine.set_agent_stats(bm, plain, ps)
    base = _heal_amount(engine, bm, plain, ally, sp, slot_level=1)
    assert base == 5, f"non-Life cleric heals the base 5 only, got {base}"
    print("✅ test_disciple_of_life_adds_to_each_heal passed")


def test_blessed_healer_heals_caster():
    """Blessed Healer (L6): healing another creature with a slot-1+ heal restores 2 + slot level HP
    to the cleric too — but only when the target is someone else."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 1, 1)
    ally   = _add(engine, bm, "Ally", 1, 2)
    _life_cleric(engine, bm, cleric, level=6, wis=10)

    cs = engine.get_agent_stats(bm, cleric); cs.hp_max = 100; cs.hp_cur = 50
    engine.set_agent_stats(bm, cleric, cs)

    sp = _heal_spell(num_dice=0, die_size=8, bonus=5)
    _heal_amount(engine, bm, cleric, ally, sp, slot_level=2)
    assert engine.get_agent_stats(bm, cleric).hp_cur == 50 + (2 + 2), \
        "Blessed Healer restores 2+slot (4) to the caster when healing another"

    # Healing only YOURSELF does not trigger Blessed Healer.
    cs = engine.get_agent_stats(bm, cleric); cs.hp_cur = 50
    engine.set_agent_stats(bm, cleric, cs)
    _cast_heal(engine, bm, cleric, cleric, _heal_spell(num_dice=0, bonus=5), slot_level=2)
    # self-heal 5 (+ Disciple 2+2 = 4) = 9, but NO extra Blessed Healer self-heal on top.
    assert engine.get_agent_stats(bm, cleric).hp_cur == 50 + 5 + (2 + 2), \
        "self-only heal should not add a Blessed Healer bonus"
    print("✅ test_blessed_healer_heals_caster passed")


def test_supreme_healing_maximizes_dice():
    """Supreme Healing (L17): every healing die is its maximum. 4d8 → always 32 (before mods)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 1, 1)
    ally   = _add(engine, bm, "Ally", 1, 2)
    _life_cleric(engine, bm, cleric, level=17, wis=10)   # WIS mod 0

    sp = _heal_spell(num_dice=4, die_size=8, bonus=0)
    # Disciple (L17 includes L3) adds 2+slot; isolate dice by subtracting it.
    for _ in range(20):
        healed = _heal_amount(engine, bm, cleric, ally, sp, slot_level=1, wound=80)
        assert healed == 32 + (2 + 1), f"Supreme Healing must max 4d8=32 (+Disciple 3), got {healed}"
    print("✅ test_supreme_healing_maximizes_dice passed")


def test_preserve_life_distributes_pool():
    """Preserve Life (CD, L3+): 5 x level HP among chosen allies within 30 ft, each capped at half
    HP max; undead excluded; spends a Channel Divinity use; gated to Life Domain L3+."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 1, 1)
    a1     = _add(engine, bm, "A1", 1, 2)
    a2     = _add(engine, bm, "A2", 1, 3)
    undead = _add(engine, bm, "Zombie", 2, 1)
    _life_cleric(engine, bm, cleric, level=5, wis=10)    # pool = 25
    for i in (cleric, a1, a2, undead):
        bm.set_agent_faction(i, 1)

    for idx, hp in ((a1, 4), (a2, 4)):
        s = engine.get_agent_stats(bm, idx); s.hp_max = 40; s.hp_cur = hp
        engine.set_agent_stats(bm, idx, s)
    zs = engine.get_agent_stats(bm, undead); zs.is_undead = True; zs.hp_max = 40; zs.hp_cur = 4
    engine.set_agent_stats(bm, undead, zs)

    cd_before = _cd(engine, bm, cleric)
    res = engine.use_preserve_life(bm, cleric, [a1, a2, undead])
    assert res.valid and res.pool == 25
    # a1 first: 4 -> cap 20 needs 16; a2: 4 -> cap 20 needs 16 but only 9 pool left -> 13.
    assert engine.get_agent_stats(bm, a1).hp_cur == 20, "a1 restored up to half HP max (20)"
    assert engine.get_agent_stats(bm, a2).hp_cur == 4 + 9, "a2 gets the remaining 9 of the pool"
    assert engine.get_agent_stats(bm, undead).hp_cur == 4, "undead cannot be healed"
    assert res.spent == 25, f"the full 25 HP pool was spent, got {res.spent}"
    assert _cd(engine, bm, cleric) == cd_before - 1, "one Channel Divinity use spent"

    # Gating: a non-Life cleric is rejected.
    plain = _add(engine, bm, "Plain", 5, 5)
    ps = engine.get_agent_stats(bm, plain)
    ps.character_class = rpg.CharacterClass.Cleric; ps.char_level = 5
    ps.initialize_class_resources(rpg.CharacterClass.Cleric, 5)
    engine.set_agent_stats(bm, plain, ps)
    assert not engine.use_preserve_life(bm, plain, [a1]).valid, "non-Life cleric cannot Preserve Life"
    print("✅ test_preserve_life_distributes_pool passed")


def test_preserve_life_revives_downed_ally():
    """Preserve Life can bring a downed (0 HP) ally back up and restore consciousness."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 1, 1)
    downed = _add(engine, bm, "Downed", 1, 2)
    _life_cleric(engine, bm, cleric, level=4, wis=10)    # pool = 20
    bm.set_agent_faction(cleric, 1); bm.set_agent_faction(downed, 1)

    s = engine.get_agent_stats(bm, downed); s.hp_max = 30; s.hp_cur = 0
    engine.set_agent_stats(bm, downed, s)
    c = engine.get_agent_conditions(bm, downed); c.unconscious = True
    engine.set_agent_conditions(bm, downed, c)

    res = engine.use_preserve_life(bm, cleric, [downed])
    assert res.valid
    assert engine.get_agent_stats(bm, downed).hp_cur == 15, "restored up to half (15) of 30 HP max"
    assert not engine.get_agent_conditions(bm, downed).unconscious, "revived → no longer unconscious"
    print("✅ test_preserve_life_revives_downed_ally passed")


# ── Trickery Domain: Invoke Duplicity ────────────────────────────────────────
def _reach_weapon(reach_ft=5):
    w = rpg.Weapon()
    w.name = "Mace"
    w.attack_bonus = 30          # always hits; we only read r.advantage
    w.reach_ft = reach_ft        # melee reach (canAttack uses this for Melee)
    w.range_short_feet = reach_ft
    w.range_long_feet = reach_ft
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Bludgeoning
    pr.num_dice = 1; pr.die_size = 4
    w.physical_damage_types = [pr]
    return w


def _trickery_cleric(engine, bm, idx, level=3, wis=16):
    s = engine.get_agent_stats(bm, idx)
    s.character_class = rpg.CharacterClass.Cleric
    s.cleric_subclass = rpg.ClericSubclass.TrickeryDomain
    s.char_level = level
    s.wis = wis
    s.initialize_class_resources(rpg.CharacterClass.Cleric, level)
    engine.set_agent_stats(bm, idx, s)


def _spawn_dup(bm, col, row, cleric_idx, spell="Invoke Duplicity"):
    cfg = rpg.AgentConfig()
    cfg.name = "Duplicate"; cfg.size = 1; cfg.sprite_path = "dup.png"
    cfg.start_col = col; cfg.start_row = row
    idx = bm.spawn_agent(cfg)
    assert idx >= 0, "duplicate spawn should succeed on an open cell"
    bm.set_agent_summoner_idx(idx, cleric_idx)
    bm.set_agent_summon_spell(idx, spell)
    return idx


def _attack_has_advantage(engine, bm, attacker, target, weapon):
    engine.set_agent_weapons(bm, attacker, [weapon] * 3)
    return engine.execute_action(bm, rpg.Attack(attacker, target, 0)).advantage


def _dup_cell(bm, idx):
    o = bm.placed_agents[idx].origin
    return (o.col, o.row)


def test_invoke_duplicity_grants_advantage_when_both_adjacent():
    """Both the cleric AND a duplicate within 5 ft of the target → Advantage (strict RAW)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "TrickCleric", 5, 5)
    target = _add(engine, bm, "Goblin", 6, 5, hp=200)
    _trickery_cleric(engine, bm, cleric, level=3)
    _spawn_dup(bm, 6, 6, cleric)            # adjacent to target; cleric (5,5) is also adjacent
    assert _attack_has_advantage(engine, bm, cleric, target, _reach_weapon(5)), \
        "cleric + duplicate both within 5 ft → Advantage"
    print("✅ test_invoke_duplicity_grants_advantage_when_both_adjacent passed")


def test_invoke_duplicity_no_advantage_when_duplicate_far():
    """The duplicate must be within 5 ft of the target — far away → no Advantage."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "TrickCleric", 5, 5)
    target = _add(engine, bm, "Goblin", 6, 5, hp=200)
    _trickery_cleric(engine, bm, cleric, level=3)
    _spawn_dup(bm, 12, 12, cleric)
    assert not _attack_has_advantage(engine, bm, cleric, target, _reach_weapon(5)), \
        "duplicate not within 5 ft of target → no Advantage"
    print("✅ test_invoke_duplicity_no_advantage_when_duplicate_far passed")


def test_invoke_duplicity_no_advantage_when_cleric_far():
    """RAW requires BOTH within 5 ft: an adjacent duplicate but a distant cleric → no Advantage."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "TrickCleric", 5, 5)
    target = _add(engine, bm, "Goblin", 8, 5, hp=200)   # 15 ft from the cleric
    _trickery_cleric(engine, bm, cleric, level=3)
    _spawn_dup(bm, 9, 5, cleric)                          # adjacent to the target
    assert not _attack_has_advantage(engine, bm, cleric, target, _reach_weapon(15)), \
        "cleric is 15 ft from the target → no Advantage even with an adjacent duplicate"
    print("✅ test_invoke_duplicity_no_advantage_when_cleric_far passed")


def test_invoke_duplicity_advantage_requires_trickery_domain():
    """A non-Trickery cleric gets no Invoke Duplicity Advantage from an adjacent duplicate."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "WarCleric", 5, 5)
    target = _add(engine, bm, "Goblin", 6, 5, hp=200)
    s = engine.get_agent_stats(bm, cleric)
    s.character_class = rpg.CharacterClass.Cleric
    s.cleric_subclass = rpg.ClericSubclass.WarDomain
    s.char_level = 3
    engine.set_agent_stats(bm, cleric, s)
    _spawn_dup(bm, 6, 6, cleric)
    assert not _attack_has_advantage(engine, bm, cleric, target, _reach_weapon(5)), \
        "Invoke Duplicity Advantage is Trickery-only"
    print("✅ test_invoke_duplicity_advantage_requires_trickery_domain passed")


def test_move_duplicate_respects_30ft_range():
    """move_duplicate teleports the illusion up to 30 ft; a longer hop is rejected (illusion stays)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "TrickCleric", 5, 5)
    _trickery_cleric(engine, bm, cleric, level=3)
    dup = _spawn_dup(bm, 6, 5, cleric)
    assert engine.move_duplicate(bm, cleric, dup, 8, 5), "10 ft move is within 30 ft"
    assert _dup_cell(bm, dup) == (8, 5)
    assert not engine.move_duplicate(bm, cleric, dup, 20, 5), "60 ft move exceeds 30 ft"
    assert _dup_cell(bm, dup) == (8, 5), "rejected move leaves the duplicate in place"
    print("✅ test_move_duplicate_respects_30ft_range passed")


def test_swap_with_duplicate_trades_positions_at_l6():
    """Trickster's Transposition (L6) swaps the cleric and duplicate cells."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "TrickCleric", 5, 5)
    _trickery_cleric(engine, bm, cleric, level=6)
    dup = _spawn_dup(bm, 9, 9, cleric)
    assert engine.swap_with_duplicate(bm, cleric, dup)
    assert _dup_cell(bm, cleric) == (9, 9), "cleric took the duplicate's spot"
    assert _dup_cell(bm, dup) == (5, 5), "duplicate took the cleric's spot"
    print("✅ test_swap_with_duplicate_trades_positions_at_l6 passed")


def test_swap_with_duplicate_requires_level_6():
    """Trickster's Transposition is gated at L6 — an L3 Trickery cleric cannot swap."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "TrickCleric", 5, 5)
    _trickery_cleric(engine, bm, cleric, level=3)
    dup = _spawn_dup(bm, 9, 9, cleric)
    assert not engine.swap_with_duplicate(bm, cleric, dup)
    assert _dup_cell(bm, cleric) == (5, 5), "no swap below L6"
    assert _dup_cell(bm, dup) == (9, 9)
    print("✅ test_swap_with_duplicate_requires_level_6 passed")


def test_invoke_duplicity_survives_concentration_loss():
    """Invoke Duplicity is Channel Divinity (not concentration), so dropping concentration spares it
    while a true concentration summon is dismissed."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "TrickCleric", 5, 5)
    _trickery_cleric(engine, bm, cleric, level=6)
    summon = _spawn_dup(bm, 7, 7, cleric, spell="Summon Dragon")   # real concentration summon
    dup    = _spawn_dup(bm, 6, 6, cleric, spell="Invoke Duplicity")
    cond = engine.get_agent_conditions(bm, cleric)
    cond.concentrating = True; cond.concentrating_on = "Summon Dragon"
    engine.set_agent_conditions(bm, cleric, cond)

    engine.drop_concentration(bm, cleric)
    assert bm.is_agent_removed_from_play(summon), "the concentration summon is dismissed"
    assert not bm.is_agent_removed_from_play(dup), "Invoke Duplicity persists through concentration loss"
    print("✅ test_invoke_duplicity_survives_concentration_loss passed")


if __name__ == "__main__":
    test_channel_divinity_uses_by_level()
    test_divine_strike_adds_damage_once_per_turn()
    test_divine_strike_scales_at_14()
    test_potent_spellcasting_adds_wis_to_cantrip()
    test_turn_undead_frightens_sears_and_filters()
    test_turn_undead_ends_on_damage()
    test_radiance_of_the_dawn()
    test_war_priest_resource()
    test_avatar_of_battle_resistance()
    test_guided_strike_turns_miss_to_hit()
    test_guided_strike_auto_via_decider()
    test_war_gods_blessing_extends_guided_reach()
    test_corona_activation_and_duration()
    test_corona_disadvantage_on_fire_radiant_saves()
    test_corona_spares_allies()
    test_disciple_of_life_adds_to_each_heal()
    test_blessed_healer_heals_caster()
    test_supreme_healing_maximizes_dice()
    test_preserve_life_distributes_pool()
    test_preserve_life_revives_downed_ally()
    test_invoke_duplicity_grants_advantage_when_both_adjacent()
    test_invoke_duplicity_no_advantage_when_duplicate_far()
    test_invoke_duplicity_no_advantage_when_cleric_far()
    test_invoke_duplicity_advantage_requires_trickery_domain()
    test_move_duplicate_respects_30ft_range()
    test_swap_with_duplicate_trades_positions_at_l6()
    test_swap_with_duplicate_requires_level_6()
    test_invoke_duplicity_survives_concentration_loss()
    print("\n✅ All Cleric tests passed!")
