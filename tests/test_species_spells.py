"""SRD species granted spells (SPECIES_PLAN.md SP3, D3).

Covered: set_species fills Stats.granted_spells from the species/option table (unlock
level, uses, the species' spell ability) and a swap rebuilds it, keeping free casts spent
on a spell that stays and any other source's entries; unlock levels gate is_granted_spell;
the spell-list sync (helpers.sync_item_spells) adds tagged entries as they unlock, skips a
name the creature already knows and drops them on a swap; a leveled granted spell is
castable with no slot, its free cast spends no slot and is not the turn's slot spell, a
second is refused, a slotless plain cast falls back to the free cast, a slot cast leaves
the free cast alone, and a Long Rest refills it; Forest Gnome's Speak with Animals gets PB
free casts; the cast uses the species' ability and the caster's own comes back after; the
agent-JSON round trip keeps the free casts spent and the ability.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
import helpers
from test_helpers import setup_battle_map, create_test_agent, add_agent_to_battle

INT, WIS, CHA = 3, 4, 5
CATALOG = {d["name"]: d for d in json.load(
    open(os.path.join(os.path.dirname(rpg.__file__), "spells.json")))}


def _stats(level=1):
    s = rpg.Stats()
    s.char_level = level
    s.prof_bonus = 2 if level < 5 else 3
    return s


def _grants(s):
    return [(g.name, g.unlock_level, g.uses, g.ability) for g in s.granted_spells]


def test_table_fills_granted_spells():
    s = _stats()
    s.set_species("Elf", "High Elf")
    assert _grants(s) == [("Prestidigitation", 1, 0, INT), ("Detect Magic", 3, 1, INT),
                          ("Misty Step", 5, 1, INT)], _grants(s)
    assert all(g.source == "species" for g in s.granted_spells)
    assert s.set_species_spell_ability(CHA)
    assert {g.ability for g in s.granted_spells} == {CHA}
    s.set_species("Tiefling", "Infernal")
    assert [g[0] for g in _grants(s)] == ["Thaumaturgy", "Fire Bolt", "Hellish Rebuke", "Darkness"]
    s.set_species("Gnome", "Forest Gnome")
    assert _grants(s)[1][:3] == ("Speak with Animals", 1, -1)
    s.set_species("Dwarf")                  # no spells, no spell ability
    assert _grants(s) == []
    print("✅ test_table_fills_granted_spells passed")


def test_swap_keeps_spent_and_other_sources():
    s = _stats(level=5)
    s.set_species("Elf", "Drow")
    assert s.spend_granted_free("Darkness")
    other = rpg.GrantedSpell()
    other.name, other.source, other.uses = "Bless", "feat", 1
    s.granted_spells = list(s.granted_spells) + [other]
    s.set_species("Tiefling", "Infernal")   # Darkness stays: its free cast stays spent
    assert s.granted_free_left("Darkness") == 0
    assert s.granted_free_left("Hellish Rebuke") == 1
    assert "Bless" in [g.name for g in s.granted_spells], "another source's entry is kept"
    s.set_species("")
    assert [g.name for g in s.granted_spells] == ["Bless"]
    print("✅ test_swap_keeps_spent_and_other_sources passed")


def test_unlock_levels():
    s = _stats(level=1)
    s.set_species("Elf", "Wood Elf")
    assert list(s.unlocked_granted_spell_names()) == ["Druidcraft"]
    assert not s.is_granted_spell("Longstrider") and s.granted_free_left("Longstrider") == 0
    s.char_level = 3
    assert list(s.unlocked_granted_spell_names()) == ["Druidcraft", "Longstrider"]
    assert s.granted_free_left("Longstrider") == 1
    s.char_level = 5
    assert "Pass without Trace" in s.unlocked_granted_spell_names()
    assert s.granted_free_left("Druidcraft") == 0, "a cantrip has no free casts to count"
    print("✅ test_unlock_levels passed")


def _scene(species, option, level=5, slots=None, ability=CHA, **scores):
    bm = setup_battle_map()
    engine = rpg.CombatEngine(11)
    c = add_agent_to_battle(engine, bm, create_test_agent("Caster", 4, 5), hp=40, **scores)
    t = add_agent_to_battle(engine, bm, create_test_agent("Tgt", 6, 5), hp=500)
    bm.set_agent_faction(t, 1)
    s = engine.get_agent_stats(bm, c)
    s.char_level = level
    s.prof_bonus = 3 if level >= 5 else 2
    s.is_npc = False
    s.spellcasting_ability = INT
    s.spell_slots_max = list(slots or [0] * 9)
    s.spell_slots_remaining = list(slots or [0] * 9)
    s.set_species(species, option)
    s.set_species_spell_ability(ability)
    engine.set_agent_stats(bm, c, s)
    engine.set_agent_spells(bm, c, [])
    assert helpers.sync_item_spells(engine, bm, c, CATALOG) is not None
    return bm, engine, c, t


def _idx(engine, bm, c, name):
    return next(i for i, sp in enumerate(engine.get_agent_spells(bm, c)) if sp.name == name)


def _cast(engine, bm, c, t, si, slot_level=0, use_grant=False):
    a = rpg.SpellAction()
    a.caster_idx, a.spell_idx, a.slot_level = c, si, slot_level
    a.target_indices = [t]
    a.use_grant = use_grant
    engine.begin_turn(bm, c)
    return engine.execute_spell(bm, a)


def test_sync_adds_tagged_entries():
    bm, engine, c, _ = _scene("Tiefling", "Abyssal", level=3)
    spells = engine.get_agent_spells(bm, c)
    assert [sp.name for sp in spells] == ["Thaumaturgy", "Poison Spray", "Ray of Sickness"]
    assert all(sp.granted for sp in spells)
    s = engine.get_agent_stats(bm, c)
    s.char_level = 5
    engine.set_agent_stats(bm, c, s)
    helpers.sync_item_spells(engine, bm, c, CATALOG)
    assert [sp.name for sp in engine.get_agent_spells(bm, c)][-1] == "Hold Person"
    # A spell the creature already knows is not added twice.
    own = helpers._dict_to_spell(CATALOG["Fire Bolt"])
    engine.set_agent_spells(bm, c, [own])
    s = engine.get_agent_stats(bm, c)
    s.set_species("Tiefling", "Infernal")
    engine.set_agent_stats(bm, c, s)
    helpers.sync_item_spells(engine, bm, c, CATALOG)
    names = [sp.name for sp in engine.get_agent_spells(bm, c)]
    assert names.count("Fire Bolt") == 1 and not engine.get_agent_spells(bm, c)[0].granted, names
    # A swap to a species without spells drops the tagged entries, keeps the own one.
    s = engine.get_agent_stats(bm, c)
    s.set_species("Orc")
    engine.set_agent_stats(bm, c, s)
    helpers.sync_item_spells(engine, bm, c, CATALOG)
    assert [sp.name for sp in engine.get_agent_spells(bm, c)] == ["Fire Bolt"]
    print("✅ test_sync_adds_tagged_entries passed")


def test_free_cast_without_slots():
    bm, engine, c, t = _scene("Tiefling", "Abyssal", level=3)
    si = _idx(engine, bm, c, "Ray of Sickness")
    assert si in engine.available_castable_spells(bm, c), "a free cast makes it castable"
    r = _cast(engine, bm, c, t, si, slot_level=1, use_grant=True)
    assert r.valid
    s = engine.get_agent_stats(bm, c)
    assert s.granted_free_left("Ray of Sickness") == 0
    assert not s.leveled_spell_cast_this_turn, "no slot, so not the turn's slot spell"
    assert si not in engine.available_castable_spells(bm, c)
    assert not _cast(engine, bm, c, t, si, use_grant=True).valid, "none left: refused"
    engine.apply_long_rest(bm)
    assert engine.get_agent_stats(bm, c).granted_free_left("Ray of Sickness") == 1
    # A plain cast with no slot to pay (the automation passes slot 0) uses the free cast.
    assert _cast(engine, bm, c, t, si).valid
    assert engine.get_agent_stats(bm, c).granted_free_left("Ray of Sickness") == 0
    print("✅ test_free_cast_without_slots passed")


def test_slot_cast_keeps_the_free_cast():
    bm, engine, c, t = _scene("Tiefling", "Abyssal", level=3, slots=[2, 0, 0, 0, 0, 0, 0, 0, 0])
    si = _idx(engine, bm, c, "Ray of Sickness")
    assert _cast(engine, bm, c, t, si, slot_level=1).valid
    s = engine.get_agent_stats(bm, c)
    assert (s.spell_slots_remaining[0], s.granted_free_left("Ray of Sickness")) == (1, 1)
    assert s.leveled_spell_cast_this_turn
    assert _cast(engine, bm, c, t, si, slot_level=1, use_grant=True).valid
    s = engine.get_agent_stats(bm, c)
    assert (s.spell_slots_remaining[0], s.granted_free_left("Ray of Sickness")) == (1, 0)
    print("✅ test_slot_cast_keeps_the_free_cast passed")


def test_speak_with_animals_pb_uses():
    s = _stats(level=5)
    s.set_species("Gnome", "Forest Gnome")
    assert s.granted_free_left("Speak with Animals") == 3
    for _ in range(3):
        assert s.spend_granted_free("Speak with Animals")
    assert not s.spend_granted_free("Speak with Animals")
    s.refill_granted_spells()
    assert s.granted_free_left("Speak with Animals") == 3
    print("✅ test_speak_with_animals_pb_uses passed")


def test_cast_uses_the_species_ability():
    # INT 8 (−1), CHA 18 (+4), PB 3: Fire Bolt's attack modifier is 7 with CHA, 2 with INT.
    mods = {}
    for ability in (CHA, INT):
        bm, engine, c, t = _scene("Tiefling", "Infernal", ability=ability, intel=8, cha=18)
        r = _cast(engine, bm, c, t, _idx(engine, bm, c, "Fire Bolt"))
        assert r.valid and r.target_results
        mods[ability] = r.target_results[0].attack_mod
        assert engine.get_agent_stats(bm, c).spellcasting_ability == INT, "own ability restored"
    assert mods[CHA] - mods[INT] == 5, mods
    print(f"✅ test_cast_uses_the_species_ability passed {mods}")


def test_loader_round_trip():
    from agent_loader import dict_to_stats
    s = _stats(level=5)
    s.set_species("Tiefling", "Chthonic")
    s.set_species_spell_ability(WIS)
    s.spend_granted_free("False Life")
    d = {"species": s.species, "species_option": s.species_option, "char_level": 5,
         "species_spell_ability": s.species_spell_ability,
         "granted_spells": [{k: getattr(g, k) for k in ("name", "source", "unlock_level", "uses",
                                                        "free_used", "ability")}
                            for g in s.granted_spells]
                           + [{"name": "Bless", "source": "feat", "uses": 1, "free_used": 1}]}
    r = dict_to_stats(d)
    r.char_level = 5            # the loader derives the level from class_levels, absent here
    assert _grants(r)[:4] == _grants(s), (_grants(r), _grants(s))
    assert {g.ability for g in r.granted_spells if g.source == "species"} == {WIS}
    assert r.granted_free_left("False Life") == 0 and r.granted_free_left("Ray of Enfeeblement") == 1
    assert [(g.name, g.free_used) for g in r.granted_spells][-1] == ("Bless", 1)
    # A save from before SP3 gets the species' spells with nothing spent.
    old = dict_to_stats({"species": "Elf", "species_option": "Drow"})
    old.char_level = 3
    assert [g.name for g in old.granted_spells] == ["Dancing Lights", "Faerie Fire", "Darkness"]
    assert old.granted_free_left("Faerie Fire") == 1
    print("✅ test_loader_round_trip passed")


def main():
    test_table_fills_granted_spells()
    test_swap_keeps_spent_and_other_sources()
    test_unlock_levels()
    test_sync_adds_tagged_entries()
    test_free_cast_without_slots()
    test_slot_cast_keeps_the_free_cast()
    test_speak_with_animals_pb_uses()
    test_cast_uses_the_species_ability()
    test_loader_round_trip()
    print("All species spell tests passed.")


if __name__ == "__main__":
    main()
