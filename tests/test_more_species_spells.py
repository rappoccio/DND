"""More species, MS2: granted spells and the Enlarge/Reduce mode (plans/MORE_SPECIES_PLAN.md D4).

Covered: the table rows for Aasimar (Light with CHA), Hexblood (Disguise Self and Hex, one
free cast each, the picked ability) and Fairy (Druidcraft; Faerie Fire at 3 and
Enlarge/Reduce at 5, one free cast each); the Fairy unlocks at levels 3 and 5; Hexblood's
free Hex spends no slot, a second free cast is refused, a slot cast leaves the free cast
alone and a Long Rest refills it; the cast uses the species' ability; Enlarge/Reduce in
Enlarge mode on the caster or an ally applies Enlarged with no save (+1 size die, Advantage
on STR saves, both cleared on teardown), on a foe it is still saved against, and Reduce
(the default) is unchanged; the SpellAction.enlarge field defaults to False.
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
SAVE_STR = 0
CATALOG = {d["name"]: d for d in json.load(
    open(os.path.join(os.path.dirname(rpg.__file__), "spells.json")))}


def _stats(level=1):
    s = rpg.Stats()
    s.char_level = level
    s.prof_bonus = 2 if level < 5 else 3
    return s


def _grants(s):
    return [(g.name, g.unlock_level, g.uses, g.ability) for g in s.granted_spells]


def test_table_rows():
    s = _stats()
    s.set_species("Aasimar")
    assert _grants(s) == [("Light", 1, 0, CHA)], _grants(s)
    s.set_species("Hexblood")
    s.set_species_spell_ability(WIS)
    assert _grants(s) == [("Disguise Self", 1, 1, WIS), ("Hex", 1, 1, WIS)], _grants(s)
    s.set_species("Fairy")
    s.set_species_spell_ability(INT)
    assert _grants(s) == [("Druidcraft", 1, 0, INT), ("Faerie Fire", 3, 1, INT),
                          ("Enlarge/Reduce", 5, 1, INT)], _grants(s)
    for sp in ("Light", "Disguise Self", "Hex", "Druidcraft", "Faerie Fire", "Enlarge/Reduce"):
        assert sp in CATALOG, sp
    for other in ("Lupin", "Reborn", "Bugbear"):
        s.set_species(other)
        assert _grants(s) == [], other
    print("✅ test_table_rows passed")


def test_fairy_unlocks():
    s = _stats(level=1)
    s.set_species("Fairy")
    assert list(s.unlocked_granted_spell_names()) == ["Druidcraft"]
    assert s.granted_free_left("Faerie Fire") == 0
    s.char_level = 3
    assert list(s.unlocked_granted_spell_names()) == ["Druidcraft", "Faerie Fire"]
    assert s.granted_free_left("Faerie Fire") == 1
    assert s.granted_free_left("Enlarge/Reduce") == 0
    s.char_level = 5
    assert list(s.unlocked_granted_spell_names()) == ["Druidcraft", "Faerie Fire", "Enlarge/Reduce"]
    assert s.granted_free_left("Enlarge/Reduce") == 1
    print("✅ test_fairy_unlocks passed")


def _scene(species, level=5, slots=None, ability=CHA, **scores):
    bm = setup_battle_map()
    engine = rpg.CombatEngine(11)
    c = add_agent_to_battle(engine, bm, create_test_agent("Caster", 4, 5), hp=40, **scores)
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 4, 6), hp=40)
    t = add_agent_to_battle(engine, bm, create_test_agent("Tgt", 6, 5), hp=500)
    bm.set_agent_faction(c, 1)
    bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(t, 2)
    s = engine.get_agent_stats(bm, c)
    s.char_level = level
    s.prof_bonus = 3 if level >= 5 else 2
    s.is_npc = False
    s.spellcasting_ability = INT
    s.spell_slots_max = list(slots or [0] * 9)
    s.spell_slots_remaining = list(slots or [0] * 9)
    s.set_species(species)
    s.set_species_spell_ability(ability)
    engine.set_agent_stats(bm, c, s)
    engine.set_agent_spells(bm, c, [])
    assert helpers.sync_item_spells(engine, bm, c, CATALOG) is not None
    return bm, engine, c, ally, t


def _idx(engine, bm, c, name):
    return next(i for i, sp in enumerate(engine.get_agent_spells(bm, c)) if sp.name == name)


def _cast(engine, bm, c, t, si, slot_level=0, use_grant=False, enlarge=False):
    a = rpg.SpellAction()
    a.caster_idx, a.spell_idx, a.slot_level = c, si, slot_level
    a.target_indices = [t]
    a.use_grant = use_grant
    a.enlarge = enlarge
    engine.begin_turn(bm, c)
    return engine.execute_spell(bm, a)


def test_hexblood_free_and_slot_casts():
    bm, engine, c, _, t = _scene("Hexblood", level=1, slots=[2, 0, 0, 0, 0, 0, 0, 0, 0])
    names = [sp.name for sp in engine.get_agent_spells(bm, c)]
    assert names == ["Disguise Self", "Hex"], names
    si = _idx(engine, bm, c, "Hex")
    assert _cast(engine, bm, c, t, si, slot_level=1, use_grant=True).valid
    s = engine.get_agent_stats(bm, c)
    assert (s.spell_slots_remaining[0], s.granted_free_left("Hex")) == (2, 0), "free: no slot"
    assert not _cast(engine, bm, c, t, si, slot_level=1, use_grant=True).valid, "none left"
    assert _cast(engine, bm, c, t, si, slot_level=1).valid, "a slot still casts it"
    s = engine.get_agent_stats(bm, c)
    assert (s.spell_slots_remaining[0], s.granted_free_left("Hex")) == (1, 0)
    engine.apply_long_rest(bm)
    s = engine.get_agent_stats(bm, c)
    assert s.granted_free_left("Hex") == 1 and s.granted_free_left("Disguise Self") == 1
    print("✅ test_hexblood_free_and_slot_casts passed")


def test_flavor_cantrips_cast():
    bm, engine, c, _, t = _scene("Aasimar", level=1)
    assert _cast(engine, bm, c, c, _idx(engine, bm, c, "Light")).valid
    bm, engine, c, _, t = _scene("Fairy", level=1)
    assert [sp.name for sp in engine.get_agent_spells(bm, c)] == ["Druidcraft"]
    assert _cast(engine, bm, c, c, _idx(engine, bm, c, "Druidcraft")).valid
    print("✅ test_flavor_cantrips_cast passed")


def test_fairy_faerie_fire_uses_species_ability():
    # INT 8 (−1), WIS 18 (+4), PB 2: the DC is 14 with WIS, 9 with INT.
    dcs = {}
    for ability in (WIS, INT):
        bm, engine, c, _, t = _scene("Fairy", level=3, ability=ability, intel=8, wis=18)
        si = _idx(engine, bm, c, "Faerie Fire")
        a = rpg.SpellAction()
        a.caster_idx, a.spell_idx, a.slot_level, a.use_grant = c, si, 1, True
        a.aoe_col, a.aoe_row = 6, 5
        engine.begin_turn(bm, c)
        r = engine.execute_spell(bm, a)
        assert r.valid, ability
        dcs[ability] = next(tr.save_dc for tr in r.target_results if tr.save_dc > 0)
        assert engine.get_agent_stats(bm, c).granted_free_left("Faerie Fire") == 0
    assert dcs == {WIS: 14, INT: 9}, dcs
    print("✅ test_fairy_faerie_fire_uses_species_ability passed")


def test_enlarge_self_and_ally_no_save():
    for who in ("self", "ally"):
        bm, engine, c, ally, t = _scene("Fairy", level=5)
        tgt = c if who == "self" else ally
        st = engine.get_agent_stats(bm, tgt)
        st.con = 1                                   # would fail any CON save
        st.save_advantage_mask = 0
        engine.set_agent_stats(bm, tgt, st)
        r = _cast(engine, bm, c, tgt, _idx(engine, bm, c, "Enlarge/Reduce"),
                  slot_level=2, use_grant=True, enlarge=True)
        assert r.valid, who
        assert all(tr.save_dc == 0 for tr in r.target_results), "a willing target rolls no save"
        st = engine.get_agent_stats(bm, tgt)
        assert st.size_damage_dice == 1, (who, st.size_damage_dice)
        assert st.save_advantage_mask & (1 << SAVE_STR), "Enlarge: Advantage on STR saves"
        engine.drop_concentration(bm, c)
        st = engine.get_agent_stats(bm, tgt)
        assert st.size_damage_dice == 0 and not (st.save_advantage_mask & (1 << SAVE_STR))
    print("✅ test_enlarge_self_and_ally_no_save passed")


def test_enlarge_foe_saves_and_reduce_default():
    # Enlarge on a foe: still a CON save. DC 11 (CHA 10, PB 3) vs CON 30 (+10) always saves.
    bm, engine, c, _, t = _scene("Fairy", level=5)
    st = engine.get_agent_stats(bm, t)
    st.con = 30
    engine.set_agent_stats(bm, t, st)
    r = _cast(engine, bm, c, t, _idx(engine, bm, c, "Enlarge/Reduce"),
              slot_level=2, use_grant=True, enlarge=True)
    assert r.valid and r.target_results[0].save_dc > 0, "an unwilling target saves"
    assert engine.get_agent_stats(bm, t).size_damage_dice == 0
    # Reduce (the default mode) on a foe with CON 1 that fails → Reduced.
    bm, engine, c, _, t = _scene("Fairy", level=5, cha=20)
    st = engine.get_agent_stats(bm, t)
    st.con = 1
    engine.set_agent_stats(bm, t, st)
    a = rpg.SpellAction()
    assert a.enlarge is False
    r = _cast(engine, bm, c, t, _idx(engine, bm, c, "Enlarge/Reduce"), slot_level=2, use_grant=True)
    assert r.valid and engine.get_agent_stats(bm, t).size_damage_dice == -1
    print("✅ test_enlarge_foe_saves_and_reduce_default passed")


if __name__ == "__main__":
    test_table_rows()
    test_fairy_unlocks()
    test_hexblood_free_and_slot_casts()
    test_flavor_cantrips_cast()
    test_fairy_faerie_fire_uses_species_ability()
    test_enlarge_self_and_ally_no_save()
    test_enlarge_foe_saves_and_reduce_default()
    print("All MS2 more-species spell tests passed.")
