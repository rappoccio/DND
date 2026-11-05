#!/usr/bin/env python3
"""Grave Domain Cleric (Ravenloft: The Horrors Within): Circle of Mortality, Path to the Grave,
Sentinel at Death's Door, Divine Reaper. See plans/GRAVE_DOMAIN_PLAN.md."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _add(engine, bm, name, col, row, hp=40, wis=10):
    return add_agent_to_battle(engine, bm, create_test_agent(name, col, row), wis=wis, hp=hp)


def _add_late(engine, bm, name, col, row, hp, faction):
    """Add an agent after factions were assigned: apply_agent_configs rebuilds the roster, so
    re-assign every faction afterwards."""
    factions = [bm.get_agent_faction(i) for i in range(len(bm.placed_agents))]
    idx = _add(engine, bm, name, col, row, hp=hp)
    for i, f in enumerate(factions):
        bm.set_agent_faction(i, f)
    bm.set_agent_faction(idx, faction)
    return idx


def _grave_cleric(engine, bm, idx, level=3, wis=10):
    s = engine.get_agent_stats(bm, idx)
    s.character_class = rpg.CharacterClass.Cleric
    s.cleric_subclass = rpg.ClericSubclass.GraveDomain
    s.char_level = level
    s.wis = wis
    s.spellcasting_ability = 4          # WIS
    s.can_cast_spell = True
    s.initialize_class_resources(rpg.CharacterClass.Cleric, level)
    engine.set_agent_stats(bm, idx, s)
    return s


def _heal_spell(num_dice=2, die_size=4, bonus=0, level=1):
    sp = rpg.Spell()
    sp.name = "Healing Word"
    sp.type = rpg.SpellType.Heal
    sp.geometry = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range = 60
    sp.level = level
    h = rpg.HealingRoll(); h.num_dice = num_dice; h.die_size = die_size; h.bonus = bonus
    sp.healing_type = h
    return sp


def _cast(engine, bm, caster, target, sp, slot_level=1):
    engine.set_agent_spells(bm, caster, [sp])
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.target_indices = [target]
    action.slot_level = slot_level
    return engine.execute_spell(bm, action)


def _down(engine, bm, idx):
    """Drop a PC to 0 HP, Unconscious and dying."""
    s = engine.get_agent_stats(bm, idx); s.hp_max = 100; s.hp_cur = 0; s.is_npc = False
    engine.set_agent_stats(bm, idx, s)
    c = engine.get_agent_conditions(bm, idx)
    c.unconscious = True; c.incapacitated = True; c.death_save_failures = 1
    engine.set_agent_conditions(bm, idx, c)


# ── G1: chassis ───────────────────────────────────────────────────────────────

def test_grave_resources_by_level():
    for level, sentinel, keeper in [(3, None, None), (6, 3, None), (17, 3, 1)]:
        s = rpg.Stats()
        s.wis = 16
        s.cleric_subclass = rpg.ClericSubclass.GraveDomain
        s.initialize_class_resources(rpg.CharacterClass.Cleric, level)
        sd = s.resources.get("Sentinel at Death's Door")
        ks = s.resources.get("Keeper of Souls")
        assert (sd.max if sd else None) == sentinel, f"L{level}: Sentinel uses {sd and sd.max} != {sentinel}"
        assert (ks.max if ks else None) == keeper, f"L{level}: Keeper of Souls {ks and ks.max} != {keeper}"
        if sd:
            assert sd.long_rest_regen == sentinel and sd.short_rest_regen == 0
        if ks:
            assert ks.short_rest_regen == 1 and ks.long_rest_regen == 1
    # WIS 8 still gets one Sentinel use (minimum of once).
    s = rpg.Stats(); s.wis = 8; s.cleric_subclass = rpg.ClericSubclass.GraveDomain
    s.initialize_class_resources(rpg.CharacterClass.Cleric, 6)
    assert s.resources["Sentinel at Death's Door"].max == 1
    print("✅ test_grave_resources_by_level passed")


def test_circle_of_mortality_maximizes_heal_at_zero_hp():
    """Healing dice aimed at a creature at 0 HP use their maximum: 2d4 → 8 every time."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 1, 1)
    ally   = _add(engine, bm, "Ally", 1, 2)
    _grave_cleric(engine, bm, cleric, level=3, wis=10)   # WIS mod 0
    for _ in range(15):
        _down(engine, bm, ally)
        _cast(engine, bm, cleric, ally, _heal_spell())
        assert engine.get_agent_stats(bm, ally).hp_cur == 8, "2d4 at 0 HP must heal exactly 8"
    print("✅ test_circle_of_mortality_maximizes_heal_at_zero_hp passed")


def test_circle_of_mortality_rolls_normally_above_zero():
    """A wounded creature above 0 HP gets ordinary rolled healing (2d4 varies, and isn't always 8)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 1, 1)
    ally   = _add(engine, bm, "Ally", 1, 2)
    _grave_cleric(engine, bm, cleric, level=3, wis=10)
    seen = set()
    for _ in range(40):
        s = engine.get_agent_stats(bm, ally); s.hp_max = 100; s.hp_cur = 50
        engine.set_agent_stats(bm, ally, s)
        _cast(engine, bm, cleric, ally, _heal_spell())
        seen.add(engine.get_agent_stats(bm, ally).hp_cur - 50)
    assert all(2 <= h <= 8 for h in seen) and len(seen) > 1, f"rolled heals expected, saw {seen}"
    print("✅ test_circle_of_mortality_rolls_normally_above_zero passed")


def test_circle_of_mortality_needs_grave_domain():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 1, 1)
    ally   = _add(engine, bm, "Ally", 1, 2)
    s = _grave_cleric(engine, bm, cleric, level=3, wis=10)
    s.cleric_subclass = rpg.ClericSubclass.WarDomain
    engine.set_agent_stats(bm, cleric, s)
    seen = set()
    for _ in range(40):
        _down(engine, bm, ally)
        _cast(engine, bm, cleric, ally, _heal_spell())
        seen.add(engine.get_agent_stats(bm, ally).hp_cur)
    assert len(seen) > 1, "a non-Grave cleric rolls its healing dice"
    print("✅ test_circle_of_mortality_needs_grave_domain passed")


def _spare_the_dying():
    sp = rpg.Spell()
    sp.name = "Spare the Dying"
    sp.type = rpg.SpellType.Harm
    sp.geometry = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range = 15
    sp.level = 0
    return sp


def test_spare_the_dying_stabilizes():
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 1, 1)
    ally   = _add(engine, bm, "Ally", 1, 2)
    _grave_cleric(engine, bm, cleric, level=3)
    _down(engine, bm, ally)
    _cast(engine, bm, cleric, ally, _spare_the_dying(), slot_level=0)
    c = engine.get_agent_conditions(bm, ally)
    assert c.stabilized and not c.dead, "Spare the Dying makes a dying creature Stable"
    assert c.death_save_failures == 0
    assert engine.get_agent_stats(bm, ally).hp_cur == 0, "Stable is still 0 HP"

    # A standing creature is unaffected.
    other = _add(engine, bm, "Other", 2, 1)
    _cast(engine, bm, cleric, other, _spare_the_dying(), slot_level=0)
    assert not engine.get_agent_conditions(bm, other).stabilized
    print("✅ test_spare_the_dying_stabilizes passed")


# ── G2: Pull of Death ─────────────────────────────────────────────────────────

def _mace():
    w = rpg.Weapon()
    w.name = "Mace"
    w.range_short_feet = 5
    w.range_long_feet = 5
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Bludgeoning
    pr.num_dice = 1
    pr.die_size = 4
    w.physical_damage_types = [pr]
    return w


def _melee_setup(level=3, target_hp=200, wounded=True):
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric = _add(engine, bm, "Cleric", 5, 5)
    target = _add(engine, bm, "Ghoul", 6, 5, hp=target_hp)
    _grave_cleric(engine, bm, cleric, level=level)
    engine.set_agent_weapons(bm, cleric, [_mace()])
    t = engine.get_agent_stats(bm, target); t.base_ac = 1; t.is_npc = True
    if wounded:
        t.hp_cur = target_hp - 10
    engine.set_agent_stats(bm, target, t)
    return bm, engine, cleric, target


def _hit(engine, bm, attacker, target):
    for _ in range(30):
        r = engine.execute_action(bm, rpg.Attack(attacker, target, 0))
        if r.hit:
            return r
    raise AssertionError("attack never hit")


def _pod(r):
    return dict(r.damage_breakdown).get("pull of death", 0)


def test_pull_of_death_on_wounded_weapon_target():
    seen = set()
    bm, engine, cleric, target = _melee_setup()
    for _ in range(20):
        engine.begin_turn(bm, cleric)
        t = engine.get_agent_stats(bm, target); t.hp_cur = 190; engine.set_agent_stats(bm, target, t)
        before = engine.get_agent_stats(bm, target).hp_cur
        r = _hit(engine, bm, cleric, target)
        pod = _pod(r)
        assert 1 <= pod <= 4, f"Pull of Death must add 1d4, got {pod} ({list(r.damage_breakdown)})"
        assert before - engine.get_agent_stats(bm, target).hp_cur == r.total_damage
        seen.add(pod)
    assert len(seen) > 1
    print("✅ test_pull_of_death_on_wounded_weapon_target passed")


def test_pull_of_death_skips_full_hp_target():
    bm, engine, cleric, target = _melee_setup(wounded=False)
    r = _hit(engine, bm, cleric, target)
    assert _pod(r) == 0, "a target at full HP before the hit isn't missing any HP"
    # ...but the next hit (the target is now wounded) qualifies.
    r2 = _hit(engine, bm, cleric, target)
    assert 1 <= _pod(r2) <= 4
    print("✅ test_pull_of_death_skips_full_hp_target passed")


def test_pull_of_death_once_per_turn():
    bm, engine, cleric, target = _melee_setup()
    engine.begin_turn(bm, cleric)
    assert _pod(_hit(engine, bm, cleric, target)) > 0
    assert _pod(_hit(engine, bm, cleric, target)) == 0, "once per turn"
    engine.begin_turn(bm, target)          # a new turn (anyone's) re-arms it
    assert _pod(_hit(engine, bm, cleric, target)) > 0
    print("✅ test_pull_of_death_once_per_turn passed")


def test_pull_of_death_scales_to_d6_at_11():
    seen = set()
    bm, engine, cleric, target = _melee_setup(level=11)
    for _ in range(60):
        engine.begin_turn(bm, cleric)
        t = engine.get_agent_stats(bm, target); t.hp_cur = 190; engine.set_agent_stats(bm, target, t)
        seen.add(_pod(_hit(engine, bm, cleric, target)))
    assert max(seen) <= 6 and max(seen) >= 5 and min(seen) >= 1, f"L11 die is a d6, saw {seen}"
    print("✅ test_pull_of_death_scales_to_d6_at_11 passed")


def test_pull_of_death_needs_grave_domain():
    bm, engine, cleric, target = _melee_setup()
    s = engine.get_agent_stats(bm, cleric); s.cleric_subclass = rpg.ClericSubclass.LifeDomain
    engine.set_agent_stats(bm, cleric, s)
    assert _pod(_hit(engine, bm, cleric, target)) == 0
    print("✅ test_pull_of_death_needs_grave_domain passed")


def _flat_spell(dmg=5):
    sp = rpg.Spell()
    sp.name = "Test Bolt"
    sp.type = rpg.SpellType.Harm
    sp.geometry = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range = 60
    sp.level = 0
    roll = rpg.MagicDamageRoll()
    roll.type = rpg.MagicDamage.Force
    roll.num_dice = 0
    roll.die_size = 4
    roll.bonus = dmg
    sp.magic_damage_rolls = [roll]
    return sp


def test_pull_of_death_on_spell_damage():
    bm, engine, cleric, target = _melee_setup()
    before = engine.get_agent_stats(bm, target).hp_cur
    res = _cast(engine, bm, cleric, target, _flat_spell(5), slot_level=0)
    lost = before - engine.get_agent_stats(bm, target).hp_cur
    assert 6 <= lost <= 9, f"5 flat + 1d4 Pull of Death, lost {lost}"
    # Once per turn across spells and attacks alike.
    before = engine.get_agent_stats(bm, target).hp_cur
    _cast(engine, bm, cleric, target, _flat_spell(5), slot_level=0)
    assert before - engine.get_agent_stats(bm, target).hp_cur == 5
    print("✅ test_pull_of_death_on_spell_damage passed")


# ── G3: Path to the Grave ─────────────────────────────────────────────────────

def _cd(engine, bm, idx):
    return engine.get_agent_stats(bm, idx).resources["Channel Divinity"].current


def _party(level=5):
    """Grave cleric + fighter ally (faction 1) vs a ghoul (faction 2), all adjacent."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    cleric  = _add(engine, bm, "Cleric", 5, 5)
    fighter = _add(engine, bm, "Fighter", 5, 6)
    ghoul   = _add(engine, bm, "Ghoul", 6, 5, hp=200)
    _grave_cleric(engine, bm, cleric, level=level)
    for i in (cleric, fighter):
        engine.set_agent_weapons(bm, i, [_mace()])
        bm.set_agent_faction(i, 1)
    bm.set_agent_faction(ghoul, 2)
    engine.set_agent_weapons(bm, ghoul, [_mace()])
    g = engine.get_agent_stats(bm, ghoul); g.base_ac = 1; g.is_npc = True
    engine.set_agent_stats(bm, ghoul, g)
    engine.begin_turn(bm, cleric)
    return bm, engine, cleric, fighter, ghoul


def test_path_to_the_grave_curses_and_spends():
    bm, engine, cleric, fighter, ghoul = _party()
    cd = _cd(engine, bm, cleric)
    assert engine.can_path_to_the_grave(bm, cleric, ghoul)
    assert engine.use_path_to_the_grave(bm, cleric, ghoul)
    assert engine.get_agent_conditions(bm, ghoul).grave_cursed_by == cleric
    assert _cd(engine, bm, cleric) == cd - 1, "spends one Channel Divinity use"
    assert not engine.has_bonus_action(bm, cleric), "spends the Bonus Action"
    assert not engine.use_path_to_the_grave(bm, cleric, ghoul), "no second use without a Bonus Action"
    print("✅ test_path_to_the_grave_curses_and_spends passed")


def test_path_to_the_grave_range_and_gates():
    bm, engine, cleric, fighter, ghoul = _party()
    far = _add_late(engine, bm, "FarGhoul", 13, 5, 40, 2)        # 40 ft away
    engine.begin_turn(bm, cleric)
    assert not engine.can_path_to_the_grave(bm, cleric, far), "beyond 30 ft"
    assert not engine.can_path_to_the_grave(bm, cleric, cleric), "not yourself"
    s = engine.get_agent_stats(bm, cleric); s.resources["Channel Divinity"].current = 0
    engine.set_agent_stats(bm, cleric, s)
    assert not engine.can_path_to_the_grave(bm, cleric, ghoul), "needs a Channel Divinity use"
    # A Life cleric doesn't have it.
    s = engine.get_agent_stats(bm, cleric); s.resources["Channel Divinity"].current = 2
    s.cleric_subclass = rpg.ClericSubclass.LifeDomain; engine.set_agent_stats(bm, cleric, s)
    assert not engine.can_path_to_the_grave(bm, cleric, ghoul)
    print("✅ test_path_to_the_grave_range_and_gates passed")


def test_path_to_the_grave_disadvantage():
    bm, engine, cleric, fighter, ghoul = _party()
    engine.use_path_to_the_grave(bm, cleric, ghoul)
    r = engine.execute_action(bm, rpg.Attack(ghoul, fighter, 0))
    assert r.disadvantage, "a cursed creature attacks at Disadvantage"
    for ab in (rpg.SaveAbility.Strength, rpg.SaveAbility.Dexterity, rpg.SaveAbility.Wisdom):
        assert engine.curse_save_disadvantage(bm, ghoul, ab), f"Disadvantage on {ab} saves"
    assert not engine.curse_save_disadvantage(bm, fighter, rpg.SaveAbility.Wisdom)
    print("✅ test_path_to_the_grave_disadvantage passed")


def test_path_to_the_grave_expires_at_clerics_turn():
    bm, engine, cleric, fighter, ghoul = _party()
    engine.use_path_to_the_grave(bm, cleric, ghoul)
    engine.begin_turn(bm, ghoul)
    engine.begin_turn(bm, fighter)
    assert engine.get_agent_conditions(bm, ghoul).grave_cursed_by == cleric, "lasts through other turns"
    engine.begin_turn(bm, cleric)
    assert engine.get_agent_conditions(bm, ghoul).grave_cursed_by == -1, "ends at the cleric's next turn"
    print("✅ test_path_to_the_grave_expires_at_clerics_turn passed")


def test_path_to_the_grave_detonation_by_ally():
    bm, engine, cleric, fighter, ghoul = _party(level=5)
    engine.use_path_to_the_grave(bm, cleric, ghoul)
    assert engine.path_to_the_grave_cleric(bm, fighter, ghoul) == cleric, "an ally's hit qualifies"
    assert engine.path_to_the_grave_cleric(bm, ghoul, fighter) == -1, "only the cursed creature"
    r = _hit(engine, bm, fighter, ghoul)
    before_total = r.total_damage
    hp = engine.get_agent_stats(bm, ghoul).hp_cur
    dmg = engine.detonate_path_to_the_grave(bm, cleric, fighter, ghoul, True, r)
    assert dmg == 5, f"extra damage = cleric level (5), got {dmg}"
    assert r.total_damage == before_total + 5
    assert engine.get_agent_stats(bm, ghoul).hp_cur == hp - 5
    assert engine.get_agent_conditions(bm, ghoul).grave_cursed_by == -1, "the curse ends"
    assert engine.detonate_path_to_the_grave(bm, cleric, fighter, ghoul, True, r) == -1, "only once"
    print("✅ test_path_to_the_grave_detonation_by_ally passed")


def test_path_to_the_grave_enemy_hit_does_not_detonate():
    bm, engine, cleric, fighter, ghoul = _party()
    other = _add_late(engine, bm, "Other", 7, 5, 40, 2)
    engine.use_path_to_the_grave(bm, cleric, ghoul)
    assert engine.path_to_the_grave_cleric(bm, other, ghoul) == -1, "an enemy of the cleric can't"
    print("✅ test_path_to_the_grave_enemy_hit_does_not_detonate passed")


def test_path_to_the_grave_auto_type():
    s = rpg.Stats()
    assert engine_auto_radiant(s) is True, "tie -> Radiant"
    m = list(s.magic_damage_multipliers); m[int(rpg.MagicDamage.Radiant)] = 0.5
    s.magic_damage_multipliers = m
    assert engine_auto_radiant(s) is False, "resists Radiant -> Necrotic"
    print("✅ test_path_to_the_grave_auto_type passed")


def engine_auto_radiant(stats):
    return setup_combat_engine().path_to_the_grave_auto_radiant(stats)


class _SkipDecider(rpg.CombatDecider):
    def choose_reaction(self, ctx):
        resp = rpg.ReactionResponse(); resp.option = -1
        return resp


def test_path_to_the_grave_auto_detonates_with_decider():
    bm, engine, cleric, fighter, ghoul = _party(level=5)
    engine.use_path_to_the_grave(bm, cleric, ghoul)
    engine.set_decider(_SkipDecider())
    r = _hit(engine, bm, fighter, ghoul)
    assert dict(r.damage_breakdown).get("path to the grave") == 5, list(r.damage_breakdown)
    assert engine.get_agent_conditions(bm, ghoul).grave_cursed_by == -1
    print("✅ test_path_to_the_grave_auto_detonates_with_decider passed")


# ── G4: Sentinel at Death's Door ──────────────────────────────────────────────

class _SentinelDecider(rpg.CombatDecider):
    def __init__(self):
        super().__init__()
        self.offers = []
    def choose_reaction(self, ctx):
        resp = rpg.ReactionResponse(); resp.option = -1
        for i, o in enumerate(ctx.options):
            if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "SentinelAtDeathsDoor":
                self.offers.append(ctx.reactor_idx)
                resp.option = i
        return resp


def _sentinel_party(level=6, fighter_hp=20, fighter_max=40):
    bm, engine, cleric, fighter, ghoul = _party(level=level)
    s = _grave_cleric(engine, bm, cleric, level=level, wis=16)   # 3 uses
    f = engine.get_agent_stats(bm, fighter); f.hp_max = fighter_max; f.hp_cur = fighter_hp; f.base_ac = 1
    engine.set_agent_stats(bm, fighter, f)
    return bm, engine, cleric, fighter, ghoul


def _uses(engine, bm, cleric):
    return engine.get_agent_stats(bm, cleric).resources["Sentinel at Death's Door"].current


def test_sentinel_gates():
    bm, engine, cleric, fighter, ghoul = _sentinel_party()
    assert engine.can_sentinel_at_deaths_door(bm, cleric, fighter), "Bloodied ally (20/40)"
    assert engine.can_sentinel_at_deaths_door(bm, cleric, cleric), "the cleric itself, Bloodied or not"
    assert not engine.can_sentinel_at_deaths_door(bm, cleric, ghoul), "not an enemy"
    f = engine.get_agent_stats(bm, fighter); f.hp_cur = 21; engine.set_agent_stats(bm, fighter, f)
    assert not engine.can_sentinel_at_deaths_door(bm, cleric, fighter), "21/40 isn't Bloodied"
    f.hp_cur = 20; engine.set_agent_stats(bm, fighter, f)
    far = _add_late(engine, bm, "FarAlly", 5, 19, 40, 1)          # 70 ft away
    fs = engine.get_agent_stats(bm, far); fs.hp_max = 40; fs.hp_cur = 10; engine.set_agent_stats(bm, far, fs)
    assert not engine.can_sentinel_at_deaths_door(bm, cleric, far), "beyond 60 ft"
    # Level 5 doesn't have it.
    bm5, engine5, c5, f5, g5 = _sentinel_party(level=5)
    assert not engine5.can_sentinel_at_deaths_door(bm5, c5, c5)
    print("✅ test_sentinel_gates passed")


def test_sentinel_halves_hit_on_bloodied_ally():
    bm, engine, cleric, fighter, ghoul = _sentinel_party(fighter_hp=20)
    dec = _SentinelDecider(); engine.set_decider(dec)
    hp = engine.get_agent_stats(bm, fighter).hp_cur
    r = _hit(engine, bm, ghoul, fighter)
    assert dec.offers == [cleric]
    bd = dict(r.damage_breakdown)
    weapon = bd["weapon"]
    assert r.total_damage == weapon // 2, f"halved (round down): {list(r.damage_breakdown)}"
    assert engine.get_agent_stats(bm, fighter).hp_cur == hp - r.total_damage
    assert _uses(engine, bm, cleric) == 2, "spends a use"
    assert engine.get_agent_conditions(bm, cleric).reaction_used, "spends the Reaction"
    # Reaction spent → no second offer this round.
    dec.offers.clear()
    _hit(engine, bm, ghoul, fighter)
    assert dec.offers == []
    print("✅ test_sentinel_halves_hit_on_bloodied_ally passed")


def test_sentinel_cancels_crit():
    bm, engine, cleric, fighter, ghoul = _sentinel_party(fighter_hp=40, fighter_max=40)
    g = engine.get_agent_stats(bm, ghoul); g.crit_threshold = 2; engine.set_agent_stats(bm, ghoul, g)
    dec = _SentinelDecider(); engine.set_decider(dec)
    for _ in range(30):
        r = engine.execute_action(bm, rpg.Attack(ghoul, cleric, 0))   # the cleric protects itself
        if r.hit:
            break
    assert r.hit and dec.offers == [cleric]
    assert not r.critical and r.crit_canceled, "the Critical Hit is canceled"
    weapon = dict(r.damage_breakdown)["weapon"]
    assert 1 <= weapon <= 4, f"re-rolled as a normal 1d4 hit, got weapon {weapon}"
    assert r.total_damage == weapon // 2
    print("✅ test_sentinel_cancels_crit passed")


def test_sentinel_blocks_auto_crit_on_unconscious():
    bm, engine, cleric, fighter, ghoul = _sentinel_party()
    _down(engine, bm, fighter)
    dec = _SentinelDecider(); engine.set_decider(dec)
    r = _hit(engine, bm, ghoul, fighter)
    assert dec.offers == [cleric], "a dying ally (0 HP) is Bloodied"
    assert not r.critical and r.crit_canceled, "no melee auto-crit after Sentinel"
    print("✅ test_sentinel_blocks_auto_crit_on_unconscious passed")


def test_sentinel_gui_window():
    bm, engine, cleric, fighter, ghoul = _sentinel_party(fighter_hp=20)
    for _ in range(30):
        st = engine.begin_attack(bm, rpg.Attack(ghoul, fighter, 0))
        if st == rpg.FlowStatus.AwaitingDecision:
            break
        assert not engine.last_attack_result().hit, "a hit on a Bloodied ally must open the window"
    pd = engine.pending_decision()
    assert pd.active and pd.ctx.reactor_idx == cleric
    feats = [o.feature for o in pd.ctx.options]
    assert feats[0] == "SentinelAtDeathsDoor", feats
    resp = rpg.ReactionResponse(); resp.option = 0
    st = engine.submit_decision(bm, resp)
    assert st == rpg.FlowStatus.Completed
    r = engine.last_attack_result()
    assert r.total_damage == dict(r.damage_breakdown)["weapon"] // 2
    assert _uses(engine, bm, cleric) == 2
    print("✅ test_sentinel_gui_window passed")


# ── G5: Divine Reaper ─────────────────────────────────────────────────────────

def _reaper_party(level=17):
    bm, engine, cleric, fighter, ghoul = _party(level=level)
    _grave_cleric(engine, bm, cleric, level=level, wis=16)
    s = engine.get_agent_stats(bm, cleric); s.spell_slots_remaining = [4, 3, 3, 3, 3, 2, 1, 1, 1]
    s.hp_max = 100; s.hp_cur = 90
    engine.set_agent_stats(bm, cleric, s)
    f = engine.get_agent_stats(bm, fighter); f.hp_max = 100; f.hp_cur = 30
    engine.set_agent_stats(bm, fighter, f)
    g = engine.get_agent_stats(bm, ghoul); g.hp_max = 10; g.hp_cur = 10
    engine.set_agent_stats(bm, ghoul, g)
    return bm, engine, cleric, fighter, ghoul


def _kill(engine, bm, caster, victim):
    """Drop an NPC from a non-cleric caster with a big flat spell (no Grave riders in play)."""
    s = engine.get_agent_stats(bm, victim); s.is_npc = True; engine.set_agent_stats(bm, victim, s)
    _cast(engine, bm, caster, victim, _flat_spell(500), slot_level=0)
    assert engine.get_agent_conditions(bm, victim).dead


def _keeper(engine, bm, cleric):
    return engine.get_agent_stats(bm, cleric).resources["Keeper of Souls"].current


def test_keeper_of_souls_auto_heals_most_hurt_ally():
    bm, engine, cleric, fighter, ghoul = _reaper_party()
    engine.set_decider(_SkipDecider())
    _kill(engine, bm, fighter, ghoul)
    assert engine.get_agent_stats(bm, fighter).hp_cur == 30 + 34, "2 x L17 = 34 to the most-hurt ally"
    assert engine.get_agent_stats(bm, cleric).hp_cur == 90
    assert _keeper(engine, bm, cleric) == 0, "once per rest"
    # A second death: no use left, and auto never spends a slot.
    ghoul2 = _add_late(engine, bm, "Ghoul2", 6, 6, 10, 2)
    _kill(engine, bm, fighter, ghoul2)
    assert engine.get_agent_stats(bm, fighter).hp_cur == 64
    assert engine.get_agent_stats(bm, cleric).spell_slots_remaining[5] == 2, "no slot spent"
    print("✅ test_keeper_of_souls_auto_heals_most_hurt_ally passed")


def test_keeper_of_souls_gui_pending_and_slot_restore():
    bm, engine, cleric, fighter, ghoul = _reaper_party()
    _kill(engine, bm, fighter, ghoul)                       # no decider → GUI flag
    assert engine.get_agent_conditions(bm, cleric).keeper_of_souls_pending
    assert engine.get_agent_stats(bm, fighter).hp_cur == 30, "nothing healed until the prompt is answered"
    assert sorted(engine.keeper_of_souls_targets(bm, cleric)) == sorted([cleric, fighter])
    assert engine.use_keeper_of_souls(bm, cleric, fighter, 0) == 34
    assert not engine.get_agent_conditions(bm, cleric).keeper_of_souls_pending
    assert _keeper(engine, bm, cleric) == 0
    # Spent: a level 6+ slot restores it.
    assert engine.can_keeper_of_souls(bm, cleric)
    assert engine.keeper_of_souls_slot(engine.get_agent_stats(bm, cleric)) == 6
    assert engine.use_keeper_of_souls(bm, cleric, cleric, 0) == -1, "no use left without a slot"
    assert engine.use_keeper_of_souls(bm, cleric, cleric, 6) == 10, "90 -> 100 (capped)"
    assert engine.get_agent_stats(bm, cleric).spell_slots_remaining[5] == 1
    print("✅ test_keeper_of_souls_gui_pending_and_slot_restore passed")


def test_keeper_of_souls_needs_enemy_within_60():
    bm, engine, cleric, fighter, ghoul = _reaper_party()
    # An ally dying doesn't count.
    ally = _add_late(engine, bm, "Ally", 4, 5, 10, 1)
    _kill(engine, bm, fighter, ally)
    assert not engine.get_agent_conditions(bm, cleric).keeper_of_souls_pending
    # An enemy dying 70 ft away doesn't either.
    far = _add_late(engine, bm, "FarGhoul", 5, 19, 10, 2)
    _kill(engine, bm, fighter, far)
    assert not engine.get_agent_conditions(bm, cleric).keeper_of_souls_pending
    # Below L17: nothing.
    bm2, engine2, c2, f2, g2 = _reaper_party(level=16)
    _kill(engine2, bm2, f2, g2)
    assert not engine2.get_agent_conditions(bm2, c2).keeper_of_souls_pending
    print("✅ test_keeper_of_souls_needs_enemy_within_60 passed")


def _necro_spell(level=1, name="Test Necro", school=None):
    sp = _flat_spell(5)
    sp.name = name
    sp.level = level
    sp.school = rpg.SpellSchool.Necromancy if school is None else school
    return sp


def test_enhanced_necromancy_eligibility():
    bm, engine, cleric, fighter, ghoul = _reaper_party()
    cs = engine.get_agent_stats(bm, cleric)
    assert engine.can_enhanced_necromancy(cs, _necro_spell(level=3))
    assert not engine.can_enhanced_necromancy(cs, _necro_spell(level=6)), "level 5 or lower"
    assert not engine.can_enhanced_necromancy(cs, _necro_spell(level=3), 6), "upcast past 5"
    evo = _necro_spell(level=1, school=rpg.SpellSchool.Evocation)
    assert not engine.can_enhanced_necromancy(cs, evo), "not Necromancy"
    evo.name = "Revivify"
    assert engine.can_enhanced_necromancy(cs, evo), "a Grave Domain spell qualifies by name"
    cs16 = _grave_cleric(engine, bm, cleric, level=16, wis=16)
    assert not engine.can_enhanced_necromancy(cs16, _necro_spell(level=3)), "L17 feature"
    print("✅ test_enhanced_necromancy_eligibility passed")


def _cast2(engine, bm, caster, targets, sp, enhanced):
    engine.set_agent_spells(bm, caster, [sp])
    action = rpg.SpellAction()
    action.caster_idx = caster
    action.spell_idx = 0
    action.target_indices = targets
    action.slot_level = sp.level
    action.enhanced_necromancy = enhanced
    return engine.execute_spell(bm, action)


def test_enhanced_necromancy_second_target():
    bm, engine, cleric, fighter, ghoul = _reaper_party()
    ghoul2 = _add_late(engine, bm, "Ghoul2", 6, 6, 100, 2)
    for g in (ghoul, ghoul2):
        s = engine.get_agent_stats(bm, g); s.hp_max = 100; s.hp_cur = 100; engine.set_agent_stats(bm, g, s)
    cd = _cd(engine, bm, cleric)
    # Without the request only the first target is hit and nothing is spent.
    _cast2(engine, bm, cleric, [ghoul, ghoul2], _necro_spell(level=1), False)
    assert engine.get_agent_stats(bm, ghoul2).hp_cur == 100
    assert _cd(engine, bm, cleric) == cd
    # With it, both are hit and one Channel Divinity use is spent.
    _cast2(engine, bm, cleric, [ghoul, ghoul2], _necro_spell(level=1), True)
    assert engine.get_agent_stats(bm, ghoul2).hp_cur < 100
    assert _cd(engine, bm, cleric) == cd - 1
    # A one-target cast with the request armed costs nothing.
    _cast2(engine, bm, cleric, [ghoul], _necro_spell(level=1), True)
    assert _cd(engine, bm, cleric) == cd - 1
    print("✅ test_enhanced_necromancy_second_target passed")


if __name__ == "__main__":
    test_grave_resources_by_level()
    test_circle_of_mortality_maximizes_heal_at_zero_hp()
    test_circle_of_mortality_rolls_normally_above_zero()
    test_circle_of_mortality_needs_grave_domain()
    test_spare_the_dying_stabilizes()
    test_pull_of_death_on_wounded_weapon_target()
    test_pull_of_death_skips_full_hp_target()
    test_pull_of_death_once_per_turn()
    test_pull_of_death_scales_to_d6_at_11()
    test_pull_of_death_needs_grave_domain()
    test_pull_of_death_on_spell_damage()
    test_path_to_the_grave_curses_and_spends()
    test_path_to_the_grave_range_and_gates()
    test_path_to_the_grave_disadvantage()
    test_path_to_the_grave_expires_at_clerics_turn()
    test_path_to_the_grave_detonation_by_ally()
    test_path_to_the_grave_enemy_hit_does_not_detonate()
    test_path_to_the_grave_auto_type()
    test_path_to_the_grave_auto_detonates_with_decider()
    test_sentinel_gates()
    test_sentinel_halves_hit_on_bloodied_ally()
    test_sentinel_cancels_crit()
    test_sentinel_blocks_auto_crit_on_unconscious()
    test_sentinel_gui_window()
    test_keeper_of_souls_auto_heals_most_hurt_ally()
    test_keeper_of_souls_gui_pending_and_slot_restore()
    test_keeper_of_souls_needs_enemy_within_60()
    test_enhanced_necromancy_eligibility()
    test_enhanced_necromancy_second_target()
    print("\n✅ All Grave Domain tests passed!")
