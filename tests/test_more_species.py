"""More species, MS1: table rows and passives (plans/MORE_SPECIES_PLAN.md).

Covered: the six new rows (Aasimar, Hexblood, Lupin, Reborn, Bugbear, Fairy) with their
sizes, options, skill picks and spell-ability flag; each one's Speed, Darkvision and
resistances, applied and stripped on a swap; the Fey creature type (D1) sets is_fey and
clears it only when it set it; Reborn's Strange Endurance option swaps the resistance;
Lupin's skill pick (Perception / Stealth / Survival) and Reborn's (the four modelled
skills); Bugbear Stealth proficiency and Fey Ancestry with no Powerful Build; Reborn
Advantage on death saves through the engine; Fairy Flight follows walk Speed and is
grounded by Medium or Heavy armor (D11); the agent-JSON round trip keeps the new record
fields, and an older save without them re-derives them.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

M = rpg.MagicDamage
INT, WIS, CHA = 3, 4, 5
NEW = ["Aasimar", "Hexblood", "Lupin", "Reborn", "Bugbear", "Fairy"]


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


def test_table_rows():
    names = list(rpg.species_names())
    assert names[-6:] == NEW, names
    sizes = {"Bugbear": ["Medium"], "Fairy": ["Small"]}
    for n in NEW:
        assert list(rpg.species_sizes(n)) == sizes.get(n, ["Small", "Medium"]), n
    assert {n for n in NEW if rpg.species_has_spell_ability(n)} == {"Hexblood", "Fairy"}
    assert {n for n in NEW if rpg.species_has_skillful(n)} == {"Lupin", "Reborn"}
    assert rpg.species_option_label("Reborn") == "Endurance"
    assert list(rpg.species_options("Reborn")) == ["Cold", "Necrotic", "Poison"]
    assert {n for n in NEW if rpg.species_creature_type(n) == "Fey"} == {"Hexblood", "Fairy"}
    assert rpg.species_creature_type("Elf") == "Humanoid"
    assert list(rpg.species_skill_options("Lupin")) == ["Perception", "Stealth", "Survival"]
    assert list(rpg.species_skill_options("Reborn")) == list(rpg.species_skills())
    assert list(rpg.species_skill_options("Human")) == list(rpg.species_skills())
    assert list(rpg.species_skill_options("Bugbear")) == []
    print("✅ test_table_rows passed")


def test_passives_apply_and_strip():
    expect = {  # darkvision, resistances
        "Aasimar":  (60, {"Necrotic", "Radiant"}),
        "Hexblood": (60, set()),
        "Lupin":    (60, set()),
        "Reborn":   (0,  {"Cold"}),
        "Bugbear":  (60, set()),
        "Fairy":    (0,  set()),
    }
    for n, (dv, res) in expect.items():
        s = _stats()
        s.set_species(n)
        assert s.speed_walk == 30, n
        assert s.darkvision_range == dv, (n, s.darkvision_range)
        assert _resists(s) == res, (n, _resists(s))
        s.set_species("")
        assert (s.darkvision_range, _resists(s), s.is_fey, s.speed_fly) == (0, set(), False, 0), n
        assert s.species_applied == rpg.SpeciesApplied(), n
    # Swaps between the new species strip the old one's traits.
    s = _stats()
    s.set_species("Aasimar")
    s.set_species("Fairy")
    assert (_resists(s), s.darkvision_range, s.is_fey, s.speed_fly) == (set(), 0, True, 30)
    s.set_species("Hexblood")
    assert (s.speed_fly, s.is_fey, s.darkvision_range) == (0, True, 60)
    s.set_species("Bugbear")
    assert (s.speed_fly, s.is_fey) == (0, False)
    print("✅ test_passives_apply_and_strip passed")


def test_fey_type_only_cleared_when_set():
    s = _stats()
    s.is_fey = True                          # already Fey (a DM edit): the species didn't set it
    s.set_species("Hexblood")
    assert s.is_fey and not s.species_applied.fey
    s.set_species("")
    assert s.is_fey, "the species didn't set it, so it doesn't clear it"
    h = _stats()
    h.set_species("Fairy")
    assert h.is_fey and h.species_applied.fey
    h.set_species("Human")
    assert not h.is_fey
    print("✅ test_fey_type_only_cleared_when_set passed")


def test_reborn_strange_endurance_option():
    s = _stats()
    s.set_species("Reborn", "Necrotic")
    assert _resists(s) == {"Necrotic"}
    s.set_species("Reborn", "Poison")
    assert _resists(s) == {"Poison"}
    s.set_species("Reborn", "Bogus")
    assert s.species_option == "Cold" and _resists(s) == {"Cold"}
    s.set_species("Lupin")
    assert _resists(s) == set()
    print("✅ test_reborn_strange_endurance_option passed")


def test_skill_picks():
    s = _stats()
    s.prof_bonus = 2
    s.dex = 14
    s.set_species("Lupin")
    assert s.set_species_skill("Stealth") and s.stealth_bonus() == 4
    assert s.set_species_skill("Survival") and s.species_skill == "Survival"
    assert s.stealth_bonus() == 2, "Survival is flavor"
    assert not s.set_species_skill("Athletics"), "Lupin doesn't offer Athletics"
    r = _stats()
    r.set_species("Reborn")
    assert r.set_species_skill("Athletics")
    assert not r.set_species_skill("Survival")
    r.wis = 12
    assert r.set_species_skill("Perception") and r.passive_perception() == 10 + 1 + r.prof_bonus
    print("✅ test_skill_picks passed")


def test_bugbear_stealth_and_fey_ancestry():
    s = _stats()
    s.prof_bonus = 3
    s.dex = 12
    base = s.stealth_bonus()
    s.set_species("Bugbear")
    assert s.stealth_bonus() == base + 3
    assert s.has_condition_save_adv("Charmed") and not s.has_condition_save_adv("Frightened")
    assert not s.has_powerful_build(), "MotM Powerful Build is carrying capacity only"
    assert s.species_size == "Medium"
    s.set_species("")
    assert s.stealth_bonus() == base and not s.has_condition_save_adv("Charmed")
    print("✅ test_bugbear_stealth_and_fey_ancestry passed")


def _death_save_success_rate(engine, bm, idx, species, n=500):
    s = engine.get_agent_stats(bm, idx)
    s.con = 10
    s.hp_cur = 0; s.hp_max = 50
    s.set_species(species)
    engine.set_agent_stats(bm, idx, s)
    successes = 0
    for _ in range(n):
        c = engine.get_agent_conditions(bm, idx)
        c.unconscious = True; c.dead = False; c.stabilized = False
        c.death_save_successes = 0; c.death_save_failures = 0
        engine.set_agent_conditions(bm, idx, c)
        engine.begin_turn(bm, idx)
        after = engine.get_agent_conditions(bm, idx)
        if after.death_save_successes > 0 or after.stabilized:
            successes += 1
    return successes / n


def test_reborn_death_save_advantage():
    assert _stats().has_death_save_advantage() is False
    r = _stats()
    r.set_species("Reborn")
    assert r.has_death_save_advantage()
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = add_agent_to_battle(engine, bm, create_test_agent("Dying", 5, 5))
    without = _death_save_success_rate(engine, bm, a, "Lupin")
    with_adv = _death_save_success_rate(engine, bm, a, "Reborn")
    assert with_adv > without + 0.1, (without, with_adv)
    print(f"✅ test_reborn_death_save_advantage passed ({without:.2f} → {with_adv:.2f})")


def _armor(cap):
    a = rpg.Armor()
    a.name = f"Cap {cap}"
    a.ac_base = 14
    a.dex_mod_cap = cap
    return a


def test_fairy_flight_and_armor_gate():
    s = _stats()
    s.set_species("Fairy")
    assert s.speed_fly == 30 and s.species_size == "Small"
    s.speed_walk = 35
    s.sync_species_flight()
    assert s.speed_fly == 35, "follows walk Speed"
    s.speed_fly = 60                         # something else changed it: leave it alone
    s.sync_species_flight()
    assert s.speed_fly == 60
    s.set_species("")
    assert s.speed_fly == 60, "not Fairy Flight's value any more, so the strip keeps it"

    bm = setup_battle_map(); engine = setup_combat_engine()
    i = add_agent_to_battle(engine, bm, create_test_agent("Fae", 5, 5))
    st = engine.get_agent_stats(bm, i)
    st.speed_walk = 30
    st.set_species("Fairy")
    engine.set_agent_stats(bm, i, st)
    assert engine.get_agent_stats(bm, i).speed_fly == 30
    for cap, grounded in ((30, False), (2, True), (30, False), (0, True)):
        armor = list(engine.get_agent_armor(bm, i))
        armor[0] = _armor(cap)
        engine.set_agent_armor(bm, i, armor)
        got = engine.get_agent_stats(bm, i)
        assert got.armor_medium_heavy == grounded, cap
        assert got.speed_fly == (0 if grounded else 30), (cap, got.speed_fly)
    engine.set_agent_armor(bm, i, [rpg.Armor() for _ in range(6)])
    assert engine.get_agent_stats(bm, i).speed_fly == 30, "armor off: flying again"
    # Setting the species while already in Heavy armor starts grounded.
    armor = list(engine.get_agent_armor(bm, i))
    armor[0] = _armor(0)
    engine.set_agent_armor(bm, i, armor)
    st = engine.get_agent_stats(bm, i)
    st.set_species("")
    st.set_species("Fairy")
    assert st.speed_fly == 0 and st.is_fey
    print("✅ test_fairy_flight_and_armor_gate passed")


def test_loader_round_trip():
    from agent_loader import dict_to_stats
    keys = ("speed_from", "speed_to", "darkvision_from", "darkvision_to", "magic_resist_mask",
            "save_advantage_bits", "hp_bonus", "perception_prof", "fey", "fly_from", "fly_to")
    s = _stats()
    s.set_species("Fairy")
    d = {"species": "Fairy", "speed_walk": 30, "speed_fly": s.speed_fly, "is_fey": True,
         "hp_max": 10, "hp_cur": 10,
         "species_applied": {k: getattr(s.species_applied, k) for k in keys}}
    r = dict_to_stats(d)
    assert r.species_applied == s.species_applied and r.speed_fly == 30 and r.is_fey
    r.set_species("")
    assert (r.speed_fly, r.is_fey) == (0, False)
    # A save from before MS1's keys: restore_species derives fey and the fly record.
    old = dict(d, species_applied={k: getattr(s.species_applied, k) for k in keys[:8]})
    r = dict_to_stats(old)
    assert (r.species_applied.fey, r.species_applied.fly_from, r.species_applied.fly_to) == (True, 0, 30)
    r.set_species("Human")
    assert (r.speed_fly, r.is_fey) == (0, False)
    # Reborn's option resistance re-derives from the saved option.
    rb = dict_to_stats({"species": "Reborn", "species_option": "Poison", "hp_max": 10, "hp_cur": 10})
    assert _resists(rb) == {"Poison"}
    print("✅ test_loader_round_trip passed")


if __name__ == "__main__":
    test_table_rows()
    test_passives_apply_and_strip()
    test_fey_type_only_cleared_when_set()
    test_reborn_strange_endurance_option()
    test_skill_picks()
    test_bugbear_stealth_and_fey_ancestry()
    test_reborn_death_save_advantage()
    test_fairy_flight_and_armor_gate()
    test_loader_round_trip()
    print("All MS1 more-species tests passed.")
