"""Halfling, Orc and Human features (SPECIES_PLAN.md SP4).

Covered: Halfling Luck rerolls a natural 1 on a save and on an attack roll (D10); Orc
Adrenaline Rush (Dash + PB temp HP, PB uses, back on a Short Rest) and Relentless Endurance
(0 HP → 1 HP once per Long Rest); Heroic Inspiration (D11): a Human starts with it and
regains it on a Long Rest, a miss with it held offers the reroll, which spends it, and a
failed spell save offers it in the OnSaveFail window; Skillful (D12) adds a proficiency read
live; Versatile (D13) holds a second origin feat through set_origin_feat; the agent-JSON
round trip keeps the new fields.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _stats(level=1, hp=10, pb=2):
    s = rpg.Stats()
    s.speed_walk = 30
    s.char_level = level
    s.prof_bonus = pb
    s.hp_max = s.hp_cur = hp
    return s


def _scene(species_a="", species_t="", seed=7):
    bm = setup_battle_map()
    engine = rpg.CombatEngine(seed)
    a = add_agent_to_battle(engine, bm, create_test_agent("Atk", 4, 5), hp=50)
    t = add_agent_to_battle(engine, bm, create_test_agent("Tgt", 5, 5), hp=500)
    for idx, sp in ((a, species_a), (t, species_t)):
        s = engine.get_agent_stats(bm, idx)
        s.set_species(sp)
        engine.set_agent_stats(bm, idx, s)
    return bm, engine, a, t


def test_luck_on_saves():
    """DC 2 at +0 fails only on a natural 1: ~5% flat, ~0.25% with Luck."""
    fails = {}
    for species in ("Human", "Halfling"):
        bm, engine, _, t = _scene(species_t=species)
        n = 3000
        fails[species] = sum(not engine.roll_fixed_dc_save(bm, t, rpg.SaveAbility.SaveCon, 2, "test")
                             for _ in range(n)) / n
    assert 0.03 < fails["Human"] < 0.075, fails
    assert fails["Halfling"] < 0.012, fails
    print(f"✅ test_luck_on_saves passed {fails}")


def _sure_blade():
    w = rpg.Weapon()
    w.name = "Sure Blade"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.bonus_hit = 60          # only a natural 1 misses
    w.bonus_damage = 1
    return [w, rpg.Weapon(), rpg.Weapon()]


def test_luck_on_attacks():
    misses = {}
    for species in ("Human", "Halfling"):
        bm, engine, a, t = _scene(species_a=species)
        engine.set_agent_weapons(bm, a, _sure_blade())
        fresh = engine.get_agent_conditions(bm, a)
        n, miss = 1500, 0
        for _ in range(n):
            engine.set_agent_conditions(bm, a, fresh)
            engine.begin_turn(bm, a)
            miss += not engine.execute_action(bm, rpg.Attack(a, t, 0)).hit
        misses[species] = miss / n
    # The scene gives Advantage on some swings, so a flat natural 1 is under 5%.
    assert misses["Human"] > 0.01, misses
    assert misses["Halfling"] < min(0.006, misses["Human"] / 3), misses
    print(f"✅ test_luck_on_attacks passed {misses}")


def test_adrenaline_rush():
    bm, engine, a, _ = _scene(species_a="Orc")
    s = engine.get_agent_stats(bm, a)
    s.prof_bonus = 3
    s.temp_hp = 0
    engine.set_agent_stats(bm, a, s)
    assert engine.can_adrenaline_rush(bm, a)
    for left in (2, 1, 0):
        assert engine.use_adrenaline_rush(bm, a)
        s = engine.get_agent_stats(bm, a)
        assert s.temp_hp == 3 and s.adrenaline_rush_remaining() == left
    assert not engine.can_adrenaline_rush(bm, a) and not engine.use_adrenaline_rush(bm, a)
    s.restore_resources_short_rest()
    assert s.adrenaline_rush_remaining() == 3
    human = _stats()
    human.set_species("Human")
    assert human.adrenaline_rush_remaining() == 0
    bm2, engine2, h, _ = _scene(species_a="Human")
    assert not engine2.can_adrenaline_rush(bm2, h)
    print("✅ test_adrenaline_rush passed")


def test_relentless_endurance():
    bm, engine, a, t = _scene(species_a="Orc", species_t="Human")
    assert engine.damage_agent(bm, a, 80) == 1, "drops to 1 HP instead"
    s = engine.get_agent_stats(bm, a)
    assert s.relentless_endurance_used and s.hp_cur == 1
    assert engine.damage_agent(bm, a, 5) == 0, "once per Long Rest"
    s = engine.get_agent_stats(bm, a)
    s.restore_resources_long_rest()
    assert not s.relentless_endurance_used
    assert engine.damage_agent(bm, t, 600) == 0, "a Human has no Relentless Endurance"
    print("✅ test_relentless_endurance passed")


def test_heroic_inspiration_grant_and_rest():
    s = _stats()
    assert not s.heroic_inspiration
    s.set_species("Human")
    assert s.heroic_inspiration, "a new Human starts with it"
    s.heroic_inspiration = False
    s.restore_resources_long_rest()
    assert s.heroic_inspiration, "Resourceful: back on a Long Rest"
    o = _stats()
    o.set_species("Orc")
    o.restore_resources_long_rest()
    assert not o.heroic_inspiration
    print("✅ test_heroic_inspiration_grant_and_rest passed")


def _blunt_blade():
    w = rpg.Weapon()
    w.name = "Blunt"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.bonus_hit = -60         # only a natural 20 hits
    return [w, rpg.Weapon(), rpg.Weapon()]


def test_heroic_attack_reroll():
    bm, engine, a, t = _scene(species_a="Human")
    engine.set_agent_weapons(bm, a, _blunt_blade())
    engine.begin_turn(bm, a)
    for _ in range(50):
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if not r.hit:
            break
    assert not r.hit
    assert engine.get_agent_conditions(bm, a).heroic_reroll_available
    r2 = engine.apply_heroic_reroll(bm, a, t, 0)
    assert r2.valid
    assert not engine.get_agent_stats(bm, a).heroic_inspiration
    assert not engine.get_agent_conditions(bm, a).heroic_reroll_available
    assert not engine.apply_heroic_reroll(bm, a, t, 0).valid, "the offer is spent"
    # Without the ★ a miss offers nothing.
    for _ in range(50):
        if not engine.execute_action(bm, rpg.Attack(a, t, 0)).hit:
            break
    assert not engine.get_agent_conditions(bm, a).heroic_reroll_available
    print("✅ test_heroic_attack_reroll passed")


def _cause_fear():
    sp = rpg.Spell(); sp.name = "Cause Fear"; sp.level = 1
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = rpg.SaveAbility.SaveWis
    sp.geometry = rpg.SpellGeometry.Single
    c = rpg.AttackCondition()
    c.condition_name = "Frightened"; c.requires_save = True
    c.save_ability = rpg.SaveAbility.SaveWis; c.condition_duration = 10
    sp.conditions = [c]
    return sp


def test_heroic_save_reroll():
    """A failed spell save parks OnSaveFail with Heroic Inspiration; taking it spends the ★."""
    bm = setup_battle_map()
    bm.set_uniform_grid(bm.cell_pixel_size // 3, 0, 0)
    bm.detect_walls()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    hero = add_agent_to_battle(engine, bm, create_test_agent("Hero", 6, 5), hp=30)
    s = engine.get_agent_stats(bm, caster)
    s.cha = 18; s.prof_bonus = 3; s.spellcasting_ability = 5
    s.hp_max = s.hp_cur = 40
    engine.set_agent_stats(bm, caster, s)
    engine.set_agent_spells(bm, caster, [_cause_fear()])
    for _ in range(400):
        s = engine.get_agent_stats(bm, caster); s.spell_slots_remaining = [9, 0, 0, 0, 0, 0, 0, 0, 0]
        engine.set_agent_stats(bm, caster, s)
        h = engine.get_agent_stats(bm, hero); h.heroic_inspiration = True
        engine.set_agent_stats(bm, hero, h)
        c = engine.get_agent_conditions(bm, hero); c.frightened = False
        engine.set_agent_conditions(bm, hero, c)
        a = rpg.SpellAction(); a.caster_idx = caster; a.spell_idx = 0; a.target_indices = [hero]
        if engine.begin_cast(bm, a) != rpg.FlowStatus.AwaitingDecision:
            continue
        ctx = engine.pending_decision().ctx
        assert ctx.window == rpg.ReactionWindow.OnSaveFail and ctx.reactor_idx == hero
        resp = rpg.ReactionResponse()
        resp.option = next(i for i, o in enumerate(ctx.options) if o.feature == "HeroicInspiration")
        engine.submit_decision(bm, resp)
        assert not engine.get_agent_stats(bm, hero).heroic_inspiration
        break
    else:
        raise AssertionError("the hero never failed the save")
    print("✅ test_heroic_save_reroll passed")


def test_skillful():
    assert list(rpg.species_skills()) == ["Athletics", "Perception", "Sleight of Hand", "Stealth"]
    assert rpg.species_has_skillful("Human") and not rpg.species_has_skillful("Elf")
    s = _stats(pb=3)
    s.dex = 14
    s.set_species("Human")
    base = s.stealth_bonus()
    assert s.set_species_skill("Stealth") and s.stealth_bonus() == base + 3
    assert not s.set_species_skill("Arcana") and s.species_skill == "Stealth"
    assert s.set_species_skill("Perception")
    assert s.stealth_bonus() == base and s.passive_perception() == 10 + 3
    s.set_species("Orc")
    assert s.passive_perception() == 10, "Skillful is the Human's"
    print("✅ test_skillful passed")


def test_versatile_second_origin_feat():
    from app_char_setup import set_origin_feat
    assert rpg.species_has_versatile("Human") and not rpg.species_has_versatile("Orc")
    s = _stats(level=4, hp=30, pb=2)
    s.set_species("Human")
    set_origin_feat(s, "Tough", 4, "Lucky")
    assert [f for f in s.feats] == ["Tough", "Lucky"]
    assert s.hp_max == 38 and s.luck_points_max == 2
    set_origin_feat(s, "Tough", 4, "Lucky")            # re-confirm: no double count
    assert s.hp_max == 38
    set_origin_feat(s, "Tough", 4, "Alert")            # swap the second slot
    assert list(s.feats) == ["Tough", "Alert"] and s.luck_points_max == 0 and s.initiative_prof
    set_origin_feat(s, "Alert", 4, "Alert")            # a duplicate is dropped
    assert list(s.feats) == ["Alert"] and s.hp_max == 30
    print("✅ test_versatile_second_origin_feat passed")


def test_loader_round_trip():
    from agent_loader import dict_to_stats
    r = dict_to_stats({"species": "Human", "species_skill": "Athletics",
                       "adrenaline_rush_used": 1, "relentless_endurance_used": True,
                       "heroic_inspiration": True})
    assert r.species_skill == "Athletics"
    assert (r.adrenaline_rush_used, r.relentless_endurance_used, r.heroic_inspiration) == (1, True, True)
    old = dict_to_stats({"species": "Human"})
    assert old.species_skill == "" and not old.heroic_inspiration
    print("✅ test_loader_round_trip passed")


def main():
    test_luck_on_saves()
    test_luck_on_attacks()
    test_adrenaline_rush()
    test_relentless_endurance()
    test_heroic_inspiration_grant_and_rest()
    test_heroic_attack_reroll()
    test_heroic_save_reroll()
    test_skillful()
    test_versatile_second_origin_feat()
    test_loader_round_trip()
    print("All species SP4 tests passed.")


if __name__ == "__main__":
    main()
