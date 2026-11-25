#!/usr/bin/env python3
"""Species in the importer and in generated parties (SPECIES_PLAN.md SP7).

Importer: tools/import_character.map_species reads D&D Beyond's race into species, option
(Elven lineage, Fiendish legacy incl. DDB's "Cthonic", Giant and Draconic ancestry), size,
spell ability and the Human Skillful skill; a race the engine lacks gives nothing.
Generator: generate_party rolls a valid species and option for every PC from its own stream
(the seed's classes, roles and level don't depend on it) and covers all nine species; a PC of
each species and option loads with the species, Speed, HP and Darkvision the rules give.
"""

import os
from collections import Counter

import gui_driver   # noqa: F401 — sets the dummy SDL drivers and gui/ on sys.path first
import arena
import party_gen as G
import import_character as IC

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DDB = os.path.join(_ROOT, "tools", "ddb_sources")


def _ddb(stem: str) -> dict:
    return IC.fetch_character(os.path.join(_DDB, f"{stem}.ddb.json"), no_fetch=True)


# ── Importer ─────────────────────────────────────────────────────────────────
def test_importer_maps_ddb_races():
    cases = {
        "165616951_Astarion":            {"species": "Elf", "species_option": "High Elf",
                                          "species_size": "Medium", "species_spell_ability": 5},
        "165848631_Shadowheart":         {"species": "Elf", "species_option": "High Elf",
                                          "species_spell_ability": 4},
        "166596538_Seneval":             {"species": "Goliath", "species_option": "Stone"},
        "159231524_Hilaria":             {"species": "Tiefling", "species_option": "Chthonic",
                                          "species_size": "Small", "species_spell_ability": 5},
        "159143208_The_Menacing_Shadow": {"species": "Tiefling", "species_option": "Infernal",
                                          "species_size": "Medium", "species_spell_ability": 4},
        "138242594_Sprite":              {"species": "Halfling", "species_size": "Small"},
        "160014877_Aodh_n_of_Gleeum":    {"species": "Human", "species_size": "Medium"},
    }
    for stem, want in cases.items():
        got = IC.map_species(_ddb(stem))
        for k, v in want.items():
            assert got.get(k) == v, (stem, k, got)
    # Aodh's Skillful pick is Religion, which the engine doesn't model (D12): no skill.
    assert "species_skill" not in IC.map_species(_ddb("160014877_Aodh_n_of_Gleeum"))
    # A race the engine lacks (Kenku, Fairy) gives no species fields.
    assert IC.map_species(_ddb("156477696_Quoth_The_Raven")) == {}
    assert IC.map_species(_ddb("163238247_Nyxaria")) == {}
    print("✅ test_importer_maps_ddb_races passed")


def test_importer_synthetic_dragonborn_and_skill():
    drag = {"race": {"baseRaceName": "Dragonborn", "fullName": "Dragonborn", "sizeId": 4},
            "options": {"race": [{"definition": {"name": "Gold Dragon"}},
                                 {"definition": {"name": "Breath Weapon (Fire)"}},
                                 {"definition": {"name": "Draconic Resistance (Fire)"}}]}}
    got = IC.map_species(drag)
    assert got == {"species": "Dragonborn", "species_option": "Gold", "species_size": "Medium"}, got
    human = {"race": {"baseRaceName": "Human", "sizeId": 10},
             "choices": {"race": [{"label": "Choose a Skill", "optionValue": 1},
                                  {"label": "Choose a Character Size", "optionValue": 2}],
                         "choiceDefinitions": [{"options": [{"id": 1, "label": "Stealth"},
                                                            {"id": 2, "label": "Small"}]}]}}
    got = IC.map_species(human)
    assert got == {"species": "Human", "species_size": "Small", "species_skill": "Stealth"}, got
    # Old-style DDB race naming ("Wood Elf" as the full name) still finds the lineage.
    wood = {"race": {"baseRaceName": "Elf", "fullName": "Wood Elf", "sizeId": 4}}
    assert IC.map_species(wood)["species_option"] == "Wood Elf"
    print("✅ test_importer_synthetic_dragonborn_and_skill passed")


# ── Generator ────────────────────────────────────────────────────────────────
def test_generated_parties_roll_species():
    seen = Counter()
    for seed in range(400):
        party, meta = G.generate_party(seed)
        assert len(meta["species"]) == len(party)
        for p, (sp, opt) in zip(party, meta["species"]):
            assert p["stats"]["species"] == sp and sp in G.SPECIES, (seed, sp)
            assert (opt in G.SPECIES[sp]) if G.SPECIES[sp] else opt == "", (seed, sp, opt)
            seen[sp] += 1
    assert set(seen) == set(G.SPECIES), seen
    # The species stream is separate: the same seed draws the same builds with no species.
    party, meta = G.generate_party(11)
    import random
    rng = random.Random("party:11")
    lv = G.draw_level(rng)
    kind, roles = G.draw_roles(rng)
    assert (lv, kind, roles) == (meta["level"], meta["template"], meta["roles"])
    print(f"✅ test_generated_parties_roll_species passed ({dict(seen)})")


def test_species_pcs_load():
    ar = arena.arena()
    lv = 5
    recs = []
    for sp, opts in G.SPECIES.items():
        for opt in (opts or [""]):
            r = G.build_pc("Fighter.Champion", "ST", lv, name=f"{sp}/{opt}",
                           species=sp, species_option=opt)
            r["col"], r["row"] = len(recs) % 12, len(recs) // 12
            recs.append(r)
    plain = G.build_pc("Fighter.Champion", "ST", lv)
    bm, eng = ar.load_board("gui/TestGrid12x12.png", None, 1)
    ar.load_agents(recs)
    dv = {"Dwarf": 120, "Orc": 120, "Human": 0, "Halfling": 0, "Goliath": 0}
    for i, r in enumerate(recs):
        sp, opt = r["stats"]["species"], r["stats"]["species_option"]
        st = eng.get_agent_stats(bm, i)
        assert st.species == sp and st.species_option == opt, (r["name"], st.species)
        speed = 35 if sp == "Goliath" or opt == "Wood Elf" else 30
        assert st.speed_walk == speed, (r["name"], st.speed_walk)
        hp = plain["stats"]["hp_max"] + (lv if sp == "Dwarf" else 0)
        assert st.hp_max == hp, (r["name"], st.hp_max, hp)
        want_dv = 120 if opt == "Drow" else dv.get(sp, 60)
        assert st.darkvision_range == want_dv, (r["name"], st.darkvision_range)
    print(f"✅ test_species_pcs_load passed ({len(recs)} species/options)")


if __name__ == "__main__":
    try:
        test_importer_maps_ddb_races()
        test_importer_synthetic_dragonborn_and_skill()
        test_generated_parties_roll_species()
        test_species_pcs_load()
    finally:
        arena.arena().close()
    print("\nAll species import tests passed! 🎉")
