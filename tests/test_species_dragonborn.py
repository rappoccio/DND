"""Dragonborn Breath Weapon and Draconic Flight (SPECIES_PLAN.md SP5, D7 + D8).

Covered: set_species grants the two Breath Weapon shapes with CON as their ability and the
sync adds them as tagged entries; the save DC is 8 + CON mod + PB whatever the caster's own
spellcasting ability; the damage type is the ancestry's (and follows a changed ancestry);
the dice are 1d10/2d10/3d10/4d10 at character levels 1/5/11/17; a save halves the damage
(not the zero of a save cantrip); the Cone and Line share PB uses per Long Rest, an empty
pool makes both uncastable and refuses a cast, a Long Rest refills it; non-Dragonborn have no
pool. Draconic Flight: level 5 only, sets fly = walk and puts the old fly Speed back, once
per Long Rest, free dismissal, 100 rounds counted at turn start, ends on Incapacitated
(Unconscious, or found at turn start); the agent-JSON round trip keeps the pools.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
import helpers
from test_helpers import setup_battle_map, create_test_agent, add_agent_to_battle

CON, INT = 2, 3
CONE, LINE = "Breath Weapon (Cone)", "Breath Weapon (Line)"
CATALOG = {d["name"]: d for d in json.load(
    open(os.path.join(os.path.dirname(rpg.__file__), "spells.json")))}
PB = {1: 2, 5: 3, 11: 4, 17: 6}


def _scene(level=1, ancestry="Red", con=16, tgt_dex=10, tgt_hp=500):
    """A Dragonborn Fighter at (4,5) facing a foe at (5,5)."""
    bm = setup_battle_map()
    engine = rpg.CombatEngine(7)
    c = add_agent_to_battle(engine, bm, create_test_agent("Drake", 4, 5), hp=60, con=con)
    t = add_agent_to_battle(engine, bm, create_test_agent("Tgt", 5, 5), hp=tgt_hp, dex=tgt_dex)
    bm.set_agent_faction(t, 1)
    s = engine.get_agent_stats(bm, c)
    s.add_class_level(rpg.CharacterClass.Fighter, level)
    s.char_level = level
    s.prof_bonus = PB[level]
    s.is_npc = False
    s.spellcasting_ability = INT
    s.speed_walk = 30
    s.speed_fly = 0
    s.set_species("Dragonborn", ancestry)
    engine.set_agent_stats(bm, c, s)
    engine.set_agent_spells(bm, c, [])
    assert helpers.sync_item_spells(engine, bm, c, CATALOG) is not None
    return bm, engine, c, t


def _idx(engine, bm, c, name):
    return next(i for i, sp in enumerate(engine.get_agent_spells(bm, c)) if sp.name == name)


def _breathe(engine, bm, c, t, name=CONE):
    a = rpg.SpellAction()
    a.caster_idx, a.spell_idx, a.slot_level = c, _idx(engine, bm, c, name), 0
    a.target_indices = []
    tc = bm.placed_agents[t].origin
    a.aoe_col, a.aoe_row = tc.col, tc.row
    return engine.execute_spell(bm, a)


def _foe_result(res, t):
    trs = [tr for tr in res.target_results if tr.target_idx == t]
    assert trs, "the foe should be in the breath"
    return trs[0]


def test_grants_and_sync():
    s = rpg.Stats()
    s.char_level = 1
    s.set_species("Dragonborn", "Blue")
    got = [(g.name, g.uses, g.ability) for g in s.granted_spells]
    assert got == [(CONE, 0, CON), (LINE, 0, CON)], got
    bm, engine, c, _ = _scene()
    spells = engine.get_agent_spells(bm, c)
    assert [sp.name for sp in spells] == [CONE, LINE]
    assert all(sp.granted and sp.resource_name == "Breath Weapon" for sp in spells)
    s = rpg.Stats()
    s.prof_bonus = 3
    s.set_species("Elf", "Drow")
    assert s.breath_weapon_remaining() == 0, "no pool without Breath Weapon"
    print("✅ test_grants_and_sync passed")


def test_dc_uses_con():
    # CON 16 (+3), PB 2: DC 13. The caster's own INT (10) would give DC 10.
    bm, engine, c, t = _scene(con=16)
    tr = _foe_result(_breathe(engine, bm, c, t), t)
    assert tr.save_dc == 13, tr.save_dc
    assert engine.get_agent_stats(bm, c).spellcasting_ability == INT, "own ability restored"
    print("✅ test_dc_uses_con passed")


def test_damage_type_follows_ancestry():
    for ancestry, resist in (("Red", "Fire"), ("White", "Cold"), ("Black", "Acid")):
        bm, engine, c, t = _scene(ancestry=ancestry)
        ts = engine.get_agent_stats(bm, t)
        mults = list(ts.magic_damage_multipliers)
        mults[int(getattr(rpg.MagicDamage, resist))] = 0.0   # immune to its own type only
        ts.magic_damage_multipliers = mults
        engine.set_agent_stats(bm, t, ts)
        tr = _foe_result(_breathe(engine, bm, c, t), t)
        assert tr.total_damage == 0, f"{ancestry}: {resist} immunity should stop it"
    print("✅ test_damage_type_follows_ancestry passed")


def test_dice_scale_by_level():
    for level, dice in ((1, 1), (5, 2), (11, 3), (17, 4)):
        bm, engine, c, t = _scene(level=level, con=30, tgt_dex=1)   # the save fails
        tr = _foe_result(_breathe(engine, bm, c, t), t)
        assert len(tr.dice_results) == dice, (level, list(tr.dice_results))
        assert all(1 <= d <= 10 for d in tr.dice_results)
    print("✅ test_dice_scale_by_level passed")


def test_half_on_save():
    # CON 1 (-5), PB 2: DC 5; DEX 30 (+10) saves on any roll. Half, not zero.
    seen = False
    for _ in range(10):
        bm, engine, c, t = _scene(level=17, con=1, tgt_dex=30)
        tr = _foe_result(_breathe(engine, bm, c, t), t)
        assert tr.saved
        assert tr.total_damage == sum(tr.dice_results) // 2, (tr.total_damage, list(tr.dice_results))
        seen |= tr.total_damage > 0
    assert seen, "a saved breath should still deal half damage"
    print("✅ test_half_on_save passed")


def test_shared_pb_uses():
    bm, engine, c, t = _scene(level=1)            # PB 2
    cone, line = _idx(engine, bm, c, CONE), _idx(engine, bm, c, LINE)
    assert {cone, line} <= set(engine.available_castable_spells(bm, c))
    assert _breathe(engine, bm, c, t, CONE).valid
    assert engine.get_agent_stats(bm, c).breath_weapon_remaining() == 1
    assert _breathe(engine, bm, c, t, LINE).valid
    s = engine.get_agent_stats(bm, c)
    assert (s.breath_weapon_used, s.breath_weapon_remaining()) == (2, 0)
    avail = set(engine.available_castable_spells(bm, c))
    assert cone not in avail and line not in avail, "the shared pool is empty"
    assert not _breathe(engine, bm, c, t, CONE).valid, "an empty pool refuses the cast"
    assert engine.get_agent_stats(bm, c).breath_weapon_used == 2
    engine.apply_long_rest(bm)
    assert engine.get_agent_stats(bm, c).breath_weapon_remaining() == 2
    print("✅ test_shared_pb_uses passed")


def test_flight_level_gate_and_toggle():
    bm, engine, c, _ = _scene(level=1)
    assert not engine.can_draconic_flight(bm, c), "level 5 feature"
    assert not engine.toggle_draconic_flight(bm, c)
    bm, engine, c, _ = _scene(level=5)
    s = engine.get_agent_stats(bm, c)
    s.speed_fly = 10                               # some other, slower fly Speed
    engine.set_agent_stats(bm, c, s)
    assert engine.can_draconic_flight(bm, c)
    assert engine.toggle_draconic_flight(bm, c)
    s = engine.get_agent_stats(bm, c)
    assert (s.speed_fly, s.draconic_flight_rounds, s.draconic_flight_used) == (30, 100, True)
    assert not engine.can_draconic_flight(bm, c), "already flying"
    assert engine.toggle_draconic_flight(bm, c), "dismissal"
    s = engine.get_agent_stats(bm, c)
    assert (s.speed_fly, s.draconic_flight_rounds) == (10, 0), "the old fly Speed comes back"
    assert not engine.can_draconic_flight(bm, c), "once per Long Rest"
    engine.apply_long_rest(bm)
    assert engine.can_draconic_flight(bm, c)
    print("✅ test_flight_level_gate_and_toggle passed")


def test_flight_lasts_100_rounds():
    bm, engine, c, _ = _scene(level=5)
    assert engine.toggle_draconic_flight(bm, c)
    for _ in range(99):
        engine.begin_turn(bm, c)
    s = engine.get_agent_stats(bm, c)
    assert (s.draconic_flight_rounds, s.speed_fly) == (1, 30)
    engine.begin_turn(bm, c)
    s = engine.get_agent_stats(bm, c)
    assert (s.draconic_flight_rounds, s.speed_fly) == (0, 0)
    print("✅ test_flight_lasts_100_rounds passed")


def test_flight_ends_on_incapacitated():
    bm, engine, c, _ = _scene(level=5)
    assert engine.toggle_draconic_flight(bm, c)
    engine.apply_unconscious(bm, c)              # Sleep: Unconscious with HP left
    s = engine.get_agent_stats(bm, c)
    assert (s.draconic_flight_rounds, s.speed_fly) == (0, 0), "Unconscious ends it"
    # Incapacitated set some other way: it lapses at the next turn start.
    bm, engine, c, _ = _scene(level=5)
    assert engine.toggle_draconic_flight(bm, c)
    cond = engine.get_agent_conditions(bm, c)
    cond.incapacitated = True
    engine.set_agent_conditions(bm, c, cond)
    assert not engine.can_draconic_flight(bm, c)
    engine.begin_turn(bm, c)
    assert engine.get_agent_stats(bm, c).draconic_flight_rounds == 0
    print("✅ test_flight_ends_on_incapacitated passed")


def test_loader_round_trip():
    from agent_loader import dict_to_stats
    r = dict_to_stats({"species": "Dragonborn", "species_option": "Gold", "breath_weapon_used": 1,
                       "draconic_flight_used": True, "draconic_flight_rounds": 40,
                       "draconic_flight_fly_from": 0})
    assert (r.breath_weapon_used, r.draconic_flight_used, r.draconic_flight_rounds) == (1, True, 40)
    old = dict_to_stats({"species": "Dragonborn", "species_option": "Gold"})
    assert (old.breath_weapon_used, old.draconic_flight_used) == (0, False)
    print("✅ test_loader_round_trip passed")


def main():
    test_grants_and_sync()
    test_dc_uses_con()
    test_damage_type_follows_ancestry()
    test_dice_scale_by_level()
    test_half_on_save()
    test_shared_pb_uses()
    test_flight_level_gate_and_toggle()
    test_flight_lasts_100_rounds()
    test_flight_ends_on_incapacitated()
    test_loader_round_trip()
    print("\n✅ All Dragonborn tests passed")


if __name__ == "__main__":
    main()
