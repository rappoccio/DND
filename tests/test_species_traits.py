"""SRD species passive traits (SPECIES_PLAN.md SP2).

Covered: each species' Speed, Darkvision, resistances and save bits, with the option's
traits (Drow Darkvision 120, Wood Elf Speed 35, Draconic and Fiendish resistance) merged
in; an option or species swap strips exactly what was applied; Dwarven Toughness folds
+1 HP per level into hp_max, follows a level change through sync_species_hp and strips
cleanly; Keen Senses turns perception_prof on (and off again only if it set it);
condition-save Advantage (D5) for Brave, Fey Ancestry and Dwarven Resilience, plus the
condition_save_adv list, reaches rollFixedDcSave and the weapon on-hit rider save;
Powerful Build gives Advantage on the grapple escape; the agent-JSON round trip keeps the
record and re-derives Darkvision and Keen Senses.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, create_test_agent, add_agent_to_battle

M = rpg.MagicDamage
INT, WIS, CHA = 3, 4, 5


def _stats(level=1, hp=10):
    s = rpg.Stats()
    s.speed_walk = 30
    s.char_level = level
    s.hp_max = s.hp_cur = hp
    return s


def _resists(s):
    return {t.name for t in (M.Acid, M.Cold, M.Fire, M.Force, M.Lightning, M.Necrotic,
                             M.Poison, M.Psychic, M.Radiant, M.Thunder)
            if s.magic_damage_multipliers[int(t)] == 0.5}


def test_species_and_option_traits():
    cases = [
        # (species, option, speed, darkvision, resistances, save bits)
        ("Dragonborn", "Black", 30, 60, {"Acid"}, 0),
        ("Dragonborn", "Bronze", 30, 60, {"Lightning"}, 0),
        ("Dragonborn", "Gold", 30, 60, {"Fire"}, 0),
        ("Dragonborn", "Green", 30, 60, {"Poison"}, 0),
        ("Dragonborn", "White", 30, 60, {"Cold"}, 0),
        ("Dwarf", "", 30, 120, {"Poison"}, 0),
        ("Elf", "Drow", 30, 120, set(), 0),
        ("Elf", "High Elf", 30, 60, set(), 0),
        ("Elf", "Wood Elf", 35, 60, set(), 0),
        ("Gnome", "Rock Gnome", 30, 60, set(), (1 << INT) | (1 << WIS) | (1 << CHA)),
        ("Goliath", "Hill", 35, 0, set(), 0),
        ("Halfling", "", 30, 0, set(), 0),
        ("Human", "", 30, 0, set(), 0),
        ("Orc", "", 30, 120, set(), 0),
        ("Tiefling", "Abyssal", 30, 60, {"Poison"}, 0),
        ("Tiefling", "Chthonic", 30, 60, {"Necrotic"}, 0),
        ("Tiefling", "Infernal", 30, 60, {"Fire"}, 0),
    ]
    for name, opt, speed, dv, res, bits in cases:
        s = _stats()
        s.set_species(name, opt)
        got = (s.speed_walk, s.darkvision_range, _resists(s), s.save_advantage_mask)
        assert got == (speed, dv, res, bits), (name, opt, got)
        for r in res:
            assert s.species_magic_mult(getattr(M, r)) == 0.5, (name, opt, r)
        s.set_species("")
        assert (s.speed_walk, s.darkvision_range, _resists(s), s.save_advantage_mask) == \
            (30, 0, set(), 0), (name, opt, "strip")
    print("✅ test_species_and_option_traits passed")


def test_option_swap_moves_the_option_traits():
    s = _stats()
    s.set_species("Dragonborn", "Red")
    assert _resists(s) == {"Fire"}
    s.set_species("Dragonborn", "Silver")
    assert _resists(s) == {"Cold"}, "Red's Fire Resistance stripped, Silver's Cold applied"
    s.set_species("Elf", "Wood Elf")
    assert (s.speed_walk, s.darkvision_range, _resists(s)) == (35, 60, set())
    s.set_species("Elf", "Drow")
    assert (s.speed_walk, s.darkvision_range) == (30, 120)
    # A Fire-immune creature keeps its immunity through an Infernal swap in and out.
    s = _stats()
    s.magic_damage_multipliers = [0.0 if i == int(M.Fire) else 1.0 for i in range(10)]
    s.set_species("Tiefling", "Infernal")
    assert s.magic_damage_multipliers[int(M.Fire)] == 0.0
    s.set_species("")
    assert s.magic_damage_multipliers[int(M.Fire)] == 0.0
    print("✅ test_option_swap_moves_the_option_traits passed")


def test_dwarven_toughness_hp():
    s = _stats(level=4, hp=30)
    s.set_species("Dwarf")
    assert (s.hp_max, s.hp_cur, s.species_applied.hp_bonus) == (34, 34, 4)
    s.sync_species_hp()                     # re-run: no-op
    assert s.hp_max == 34
    s.char_level = 6                        # levelled up in the Stats dialog
    s.sync_species_hp()
    assert (s.hp_max, s.hp_cur, s.species_applied.hp_bonus) == (36, 36, 6)
    s.set_species("Dwarf")                  # unchanged: no-op
    assert s.hp_max == 36
    s.set_species("Orc")                    # strip
    assert (s.hp_max, s.hp_cur, s.species_applied.hp_bonus) == (30, 30, 0)
    s.sync_species_hp()
    assert s.hp_max == 30, "only Dwarves sync"
    print("✅ test_dwarven_toughness_hp passed")


def test_keen_senses_perception():
    s = _stats()
    s.set_species("Elf")
    assert s.perception_prof and s.species_applied.perception_prof
    s.set_species("Human")
    assert not s.perception_prof
    s.perception_prof = True                # proficient already (class skill)
    s.set_species("Elf", "Wood Elf")
    assert s.perception_prof and not s.species_applied.perception_prof
    s.set_species("")
    assert s.perception_prof, "Keen Senses didn't set it, so it doesn't clear it"
    print("✅ test_keen_senses_perception passed")


def test_condition_save_adv_flags():
    expect = {"Halfling": {"Frightened"}, "Elf": {"Charmed"}, "Dwarf": {"Poisoned"}}
    for name in rpg.species_names():
        s = _stats()
        s.set_species(name)
        got = {c for c in ("Frightened", "Charmed", "Poisoned", "Paralyzed")
               if s.has_condition_save_adv(c)}
        assert got == expect.get(name, set()), (name, got)
    s = _stats()
    assert not s.has_condition_save_adv("Stunned") and not s.has_condition_save_adv("")
    s.condition_save_adv = ["Stunned"]
    assert s.has_condition_save_adv("Stunned")
    assert _stats().has_powerful_build() is False
    g = _stats()
    g.set_species("Goliath")
    assert g.has_powerful_build()
    print("✅ test_condition_save_adv_flags passed")


def _scene(species):
    bm = setup_battle_map()
    engine = rpg.CombatEngine(7)
    a = add_agent_to_battle(engine, bm, create_test_agent("Atk", 4, 5))
    t = add_agent_to_battle(engine, bm, create_test_agent("Tgt", 5, 5), hp=500)
    s = engine.get_agent_stats(bm, t)
    s.set_species(species)
    engine.set_agent_stats(bm, t, s)
    return bm, engine, a, t


def test_fixed_dc_save_gets_condition_advantage():
    """DC 11, +0: a flat d20 saves half the time, with Advantage three quarters."""
    rates = {}
    for species, cond in (("Human", "Poisoned"), ("Dwarf", "Poisoned"), ("Dwarf", "")):
        bm, engine, _, t = _scene(species)
        assert engine.condition_save_advantage(bm, t, cond) == (species == "Dwarf" and cond != "")
        n = 400
        ok = sum(engine.roll_fixed_dc_save(bm, t, rpg.SaveAbility.SaveCon, 11, "test", cond)
                 for _ in range(n))
        rates[(species, cond)] = ok / n
    assert 0.4 < rates[("Human", "Poisoned")] < 0.6, rates
    assert 0.4 < rates[("Dwarf", "")] < 0.6, rates
    assert rates[("Dwarf", "Poisoned")] > 0.67, rates
    print(f"✅ test_fixed_dc_save_gets_condition_advantage passed {rates}")


def _poison_blade():
    w = rpg.Weapon()
    w.name = "Venom Fang"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.bonus_hit = 50
    w.bonus_damage = 1
    c = rpg.AttackCondition()
    c.condition_name = "Poisoned"
    c.requires_save = True
    c.save_ability = rpg.SaveAbility.SaveCon
    c.save_dc_ability = rpg.SaveAbility.SaveCon
    c.condition_duration = 1
    w.conditions = [c]
    return [w, rpg.Weapon(), rpg.Weapon()]


def test_weapon_rider_save_gets_condition_advantage():
    """The weapon on-hit condition save (the monster Poisoned path) now asks the hook."""
    rates = {}
    for species in ("Human", "Dwarf"):
        bm, engine, a, t = _scene(species)
        engine.set_agent_weapons(bm, a, _poison_blade())
        fresh_a = engine.get_agent_conditions(bm, a)
        fresh_t = engine.get_agent_conditions(bm, t)
        hits, poisoned = 0, 0
        for _ in range(300):
            engine.set_agent_conditions(bm, a, fresh_a)
            engine.set_agent_conditions(bm, t, fresh_t)
            engine.begin_turn(bm, a)          # a fresh Attack action each time
            res = engine.execute_action(bm, rpg.Attack(a, t, 0))
            if not res.hit:                   # a natural 1
                continue
            hits += 1
            poisoned += bool(engine.get_agent_conditions(bm, t).poisoned)
        rates[species] = poisoned / hits
    # DC 8 + PB 2 + CON 0 = 10 vs +0: fail 45% flat, ~20% with Advantage.
    assert rates["Dwarf"] < rates["Human"] - 0.12, rates
    print(f"✅ test_weapon_rider_save_gets_condition_advantage passed {rates}")


def test_powerful_build_grapple_escape():
    """DC 15, STR/DEX +0, best of two checks: ~51% flat, ~76% when each has Advantage."""
    rates = {}
    for species in ("Human", "Goliath"):
        bm, engine, _, t = _scene(species)
        n, ok = 400, 0
        for _ in range(n):
            c = engine.get_agent_conditions(bm, t)
            c.grappled = True
            c.grapple_escape_dc = 15
            engine.set_agent_conditions(bm, t, c)
            ok += engine.execute_grapple_escape(bm, t).success
        rates[species] = ok / n
    assert 0.4 < rates["Human"] < 0.62, rates
    assert rates["Goliath"] > 0.68, rates
    print(f"✅ test_powerful_build_grapple_escape passed {rates}")


def test_loader_round_trip():
    from agent_loader import dict_to_stats
    s = _stats(level=5, hp=40)
    s.set_species("Elf", "Drow")
    assert (s.darkvision_range, s.perception_prof) == (120, True)
    d = {"species": s.species, "species_option": s.species_option,
         "hp_max": s.hp_max, "hp_cur": s.hp_cur, "speed_walk": s.speed_walk,
         "species_applied": {k: getattr(s.species_applied, k) for k in
                             ("speed_from", "speed_to", "darkvision_from", "darkvision_to",
                              "magic_resist_mask", "save_advantage_bits", "hp_bonus",
                              "perception_prof")},
         "condition_save_adv": ["Stunned"]}
    r = dict_to_stats(d)
    assert (r.darkvision_range, r.perception_prof) == (120, True), "re-derived with the option"
    assert r.species_applied == s.species_applied
    assert list(r.condition_save_adv) == ["Stunned"]
    r.set_species("")
    assert (r.darkvision_range, r.perception_prof) == (0, False)

    dw = _stats(level=3, hp=20)
    dw.set_species("Dwarf")
    r = dict_to_stats({"species": "Dwarf", "hp_max": dw.hp_max, "hp_cur": dw.hp_cur,
                       "char_level": 3, "magic_damage_multipliers": list(dw.magic_damage_multipliers),
                       "species_applied": {"hp_bonus": 3, "magic_resist_mask": 1 << int(M.Poison),
                                           "darkvision_from": 0, "darkvision_to": 120}})
    assert (r.hp_max, r.species_applied.hp_bonus) == (23, 3)
    r.set_species("")
    assert r.hp_max == 20 and _resists(r) == set()
    print("✅ test_loader_round_trip passed")


def main():
    test_species_and_option_traits()
    test_option_swap_moves_the_option_traits()
    test_dwarven_toughness_hp()
    test_keen_senses_perception()
    test_condition_save_adv_flags()
    test_fixed_dc_save_gets_condition_advantage()
    test_weapon_rider_save_gets_condition_advantage()
    test_powerful_build_grapple_escape()
    test_loader_round_trip()
    print("All species trait tests passed.")


if __name__ == "__main__":
    main()
