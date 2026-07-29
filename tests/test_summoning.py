#!/usr/bin/env python3
"""
Summoning system — engine-level tests (Phases 1-3).

Covers the C++ pieces that the GUI summon flow relies on:
- bm.spawn_agent appends a single agent WITHOUT clearing existing agents/state.
- PlacedAgent summon fields (summoner_idx / summon_spell / removed_from_play) + accessors.
- drop_concentration tombstones the caster's summons and reports them in dismissed_summons,
  WITHOUT erasing them (indices stay valid).
- Losing concentration to damage also cascades the dismissal.

The GUI placement dialog / initiative insertion are pygame-driven and not unit-tested here.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import json

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle
from helpers import can_place_agent, summon_cell_placeable, compute_summon_loadout

# A synthetic spirit block so the scaling tests don't couple to summons.json's numbers.
_TEST_SPIRIT = {
    "form": "Test", "name": "Test Spirit", "size": "Medium",
    "str": 18, "dex": 12, "con": 14, "intel": 4, "wis": 10, "cha": 6,
    "speed_walk": 30, "ac_base": 11, "hp_base": 20, "hp_per_level": 5,
    "multiattack_at": 4, "darkvision": 60, "dmg_per_level": 2,
    "attack": {"name": "Slam", "num_dice": 2, "die_size": 6, "damage_type": "Bludgeoning"},
}


def _spawn_summon(bm, name, col, row, summoner_idx, spell="Summon Dragon"):
    cfg = rpg.AgentConfig()
    cfg.name = name
    cfg.start_col = col
    cfg.start_row = row
    cfg.size = 1
    cfg.sprite_path = "test.png"
    idx = bm.spawn_agent(cfg)
    assert idx >= 0, "spawn_agent should succeed on an open cell"
    bm.set_agent_summoner_idx(idx, summoner_idx)
    bm.set_agent_summon_spell(idx, spell)
    return idx


def _set_concentrating(engine, bm, idx, spell_name):
    cond = engine.get_agent_conditions(bm, idx)
    cond.concentrating = True
    cond.concentrating_on = spell_name
    engine.set_agent_conditions(bm, idx, cond)


def test_summon_bindings_present():
    """New summon bindings are exposed to Python."""
    bm = setup_battle_map()
    for m in ["spawn_agent", "get_agent_summoner_idx", "set_agent_summoner_idx",
              "get_agent_summon_spell", "set_agent_summon_spell",
              "is_agent_removed_from_play", "set_agent_removed_from_play"]:
        assert hasattr(bm, m), f"missing BattleMap binding: {m}"
    assert hasattr(rpg.DropConcentrationResult, "dismissed_summons"), \
        "DropConcentrationResult.dismissed_summons missing"
    print("✅ test_summon_bindings_present passed")


def test_spawn_agent_is_non_destructive():
    """spawn_agent appends one agent and preserves existing agents' runtime state."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5), hp=40)
    # Mutate the caster's runtime HP so we can prove it survives a spawn.
    st = engine.get_agent_stats(bm, caster)
    st.hp_cur = 17
    engine.set_agent_stats(bm, caster, st)

    summon = _spawn_summon(bm, "Spirit Dragon Wyrmling", 6, 6, caster)
    assert summon == len(bm.placed_agents) - 1, "summon should be the last placed agent"
    assert len(bm.placed_agents) == 2
    # Existing caster state is untouched (apply_agent_configs would have wiped it).
    assert engine.get_agent_stats(bm, caster).hp_cur == 17, "spawn clobbered caster HP"
    assert bm.get_agent_summoner_idx(summon) == caster
    assert bm.get_agent_summon_spell(summon) == "Summon Dragon"
    assert not bm.is_agent_removed_from_play(summon)
    print("✅ test_spawn_agent_is_non_destructive passed")


def test_spawn_agent_blocked_cell_returns_negative():
    """spawn_agent onto an occupied/blocked cell returns -1 (no agent added)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    _spawn_summon(bm, "First", 6, 6, caster)
    before = len(bm.placed_agents)
    # Same cell as the first summon → blocked.
    cfg = rpg.AgentConfig()
    cfg.name = "Second"
    cfg.start_col = 6
    cfg.start_row = 6
    cfg.size = 1
    cfg.sprite_path = "test.png"
    assert bm.spawn_agent(cfg) == -1, "expected -1 on a blocked cell"
    assert len(bm.placed_agents) == before, "no agent should have been added"
    print("✅ test_spawn_agent_blocked_cell_returns_negative passed")


def test_drop_concentration_dismisses_summon():
    """Losing concentration tombstones the caster's summons and reports them."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    summon = _spawn_summon(bm, "Spirit Dragon Wyrmling", 6, 6, caster)
    _set_concentrating(engine, bm, caster, "Summon Dragon")

    res = engine.drop_concentration(bm, caster)
    assert res.dropped
    assert summon in list(res.dismissed_summons), "summon not reported as dismissed"
    assert bm.is_agent_removed_from_play(summon), "summon should be tombstoned"
    # Tombstone, NOT erase: the agent is still in the vector so indices stay valid.
    assert len(bm.placed_agents) == 2, "summon must not be erased"
    print("✅ test_drop_concentration_dismisses_summon passed")


def test_dismissed_summon_moved_off_map():
    """A dismissed summon is banished to (-1,-1) so its old cell no longer collides
    with movement/placement on the real grid (while its index stays valid)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    summon = _spawn_summon(bm, "Spirit Dragon Wyrmling", 6, 6, caster)
    assert bm.placed_agents[summon].origin.col == 6
    _set_concentrating(engine, bm, caster, "Summon Dragon")

    engine.drop_concentration(bm, caster)
    off = bm.placed_agents[summon].origin
    assert (off.col, off.row) == (-1, -1), f"summon should be off-map, got ({off.col},{off.row})"
    assert len(bm.placed_agents) == 2, "summon must not be erased"
    assert can_place_agent(bm, rpg.Cell(6, 6), 1), "the freed cell should be placeable again"
    print("✅ test_dismissed_summon_moved_off_map passed")


def test_unrelated_summon_not_dismissed():
    """Dropping caster A's concentration leaves caster B's summon alone."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    a = add_agent_to_battle(engine, bm, create_test_agent("A", 2, 2))
    b = add_agent_to_battle(engine, bm, create_test_agent("B", 8, 8))
    sa = _spawn_summon(bm, "A-Summon", 3, 3, a)
    sb = _spawn_summon(bm, "B-Summon", 9, 9, b)
    _set_concentrating(engine, bm, a, "Summon Dragon")
    _set_concentrating(engine, bm, b, "Summon Dragon")

    res = engine.drop_concentration(bm, a)
    assert sa in list(res.dismissed_summons)
    assert sb not in list(res.dismissed_summons)
    assert bm.is_agent_removed_from_play(sa)
    assert not bm.is_agent_removed_from_play(sb), "B's summon wrongly dismissed"
    print("✅ test_unrelated_summon_not_dismissed passed")


def test_damage_breaking_concentration_dismisses_summon():
    """A failed concentration save from damage also cascades the summon dismissal."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5, con=10), hp=40)
    summon = _spawn_summon(bm, "Spirit Dragon Wyrmling", 6, 6, caster)
    _set_concentrating(engine, bm, caster, "Summon Dragon")

    # concentration_save rolls a CON save (DC = max(10, damage/2)); a high damage value makes
    # a failure very likely. On a failed save the engine routes through dropConcentration, which
    # must tombstone the summon via the same cascade.
    res = engine.concentration_save(bm, caster, 60)
    assert res.checked, "a concentrating agent should have to save"

    if res.concentration_lost:
        assert bm.is_agent_removed_from_play(summon), \
            "concentration broke but summon was not dismissed"
        print("✅ test_damage_breaking_concentration_dismisses_summon passed (broke + dismissed)")
    else:
        # Save succeeded (RNG): concentration held, so the summon must remain in play.
        assert not bm.is_agent_removed_from_play(summon)
        print("✅ test_damage_breaking_concentration_dismisses_summon passed (held)")


def test_placement_in_range_and_empty_is_valid():
    """A nearby empty cell with line of sight is a legal summon spot."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    origin = bm.placed_agents[caster].origin
    assert summon_cell_placeable(bm, origin, 1, rpg.Cell(6, 5), 1, 60), \
        "adjacent empty cell within range should be valid"
    print("✅ test_placement_in_range_and_empty_is_valid passed")


def test_placement_out_of_range_is_invalid():
    """Beyond the spell's range the cell is rejected, but a closer one is allowed."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    origin = bm.placed_agents[caster].origin
    # range 5 ft = one cell: three cells away is out of range, adjacent is in range.
    assert not summon_cell_placeable(bm, origin, 1, rpg.Cell(8, 5), 1, 5), "should be out of range"
    assert summon_cell_placeable(bm, origin, 1, rpg.Cell(6, 5), 1, 5), "adjacent should be in range"
    print("✅ test_placement_out_of_range_is_invalid passed")


def test_placement_on_occupied_cell_is_invalid():
    """A cell occupied by another live agent is not a legal summon spot."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    add_agent_to_battle(engine, bm, create_test_agent("Ally", 6, 5))
    origin = bm.placed_agents[caster].origin
    assert not summon_cell_placeable(bm, origin, 1, rpg.Cell(6, 5), 1, 60), \
        "occupied cell should be rejected"
    print("✅ test_placement_on_occupied_cell_is_invalid passed")


def test_can_place_ignores_tombstoned_summon():
    """A dismissed (tombstoned) summon frees its cell for placement again."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    summon = _spawn_summon(bm, "Spirit Dragon Wyrmling", 6, 6, caster)
    assert not can_place_agent(bm, rpg.Cell(6, 6), 1), "live summon should block its cell"
    bm.set_agent_removed_from_play(summon, True)
    assert can_place_agent(bm, rpg.Cell(6, 6), 1), "tombstoned summon should free its cell"
    print("✅ test_can_place_ignores_tombstoned_summon passed")


def test_can_place_out_of_bounds_is_invalid():
    """Cells off the grid (negative or past the edge) are rejected."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    assert not can_place_agent(bm, rpg.Cell(-1, 5), 1), "negative cell should be rejected"
    assert not can_place_agent(bm, rpg.Cell(bm.grid_cols, 5), 1), "past-edge cell should be rejected"
    print("✅ test_can_place_out_of_bounds_is_invalid passed")


def test_summon_loadout_scales_with_slot():
    """AC = ac_base + slot_level; HP = hp_base + hp_per_level x slot_level."""
    stats_l3, _ = compute_summon_loadout(_TEST_SPIRIT, slot_level=3, pb=2, spell_ability_mod=3)
    stats_l6, _ = compute_summon_loadout(_TEST_SPIRIT, slot_level=6, pb=4, spell_ability_mod=5)
    assert stats_l3["base_ac"] == 11 + 3, stats_l3["base_ac"]
    assert stats_l3["hp_max"] == 20 + 5 * 3, stats_l3["hp_max"]
    assert stats_l6["base_ac"] == 11 + 6, stats_l6["base_ac"]
    assert stats_l6["hp_max"] == 20 + 5 * 6, stats_l6["hp_max"]
    assert stats_l6["hp_cur"] == stats_l6["hp_max"]
    print("✅ test_summon_loadout_scales_with_slot passed")


def test_summon_loadout_to_hit_and_damage_from_caster():
    """bonus_hit cancels the spirit's own ability mod so total to-hit = pb + spell mod;
    bonus_damage leaves only the per-level rider (dmg_per_level x slot_level)."""
    pb, spell_mod, slot = 4, 5, 5
    stats, weapon = compute_summon_loadout(_TEST_SPIRIT, slot, pb, spell_mod)
    str_mod = (_TEST_SPIRIT["str"] - 10) // 2  # 18 -> +4, the attacking ability (not finesse)
    # engine: to-hit = ability_mod + pb + bonus_hit  (proficient) == pb + spell_mod
    assert weapon["bonus_hit"] + str_mod + pb == pb + spell_mod, weapon["bonus_hit"]
    # engine: damage bonus = ability_mod + bonus_damage == dmg_per_level * slot
    assert weapon["bonus_damage"] + str_mod == _TEST_SPIRIT["dmg_per_level"] * slot
    print("✅ test_summon_loadout_to_hit_and_damage_from_caster passed")


def test_summon_loadout_multiattack_threshold():
    """num_attacks flips to 2 once slot_level >= multiattack_at, else 1."""
    below, _ = compute_summon_loadout(_TEST_SPIRIT, slot_level=3, pb=2, spell_ability_mod=3)
    at,    _ = compute_summon_loadout(_TEST_SPIRIT, slot_level=4, pb=2, spell_ability_mod=3)
    assert below["num_attacks"] == 1, below["num_attacks"]
    assert at["num_attacks"] == 2, at["num_attacks"]
    print("✅ test_summon_loadout_multiattack_threshold passed")


def test_summon_loadout_magic_damage_routing():
    """A magical damage type routes to magic_damage_types (bypasses non-magical resistance);
    a physical type stays in physical_damage_types."""
    phys = dict(_TEST_SPIRIT)  # Bludgeoning (physical)
    _, w_phys = compute_summon_loadout(phys, 3, 2, 3)
    assert w_phys["physical_damage_types"] and not w_phys["magic_damage_types"]

    magic = dict(_TEST_SPIRIT,
                 attack={"name": "Sear", "num_dice": 2, "die_size": 6,
                         "damage_type": "Radiant", "magic": True})
    _, w_magic = compute_summon_loadout(magic, 3, 2, 3)
    assert w_magic["magic_damage_types"] and not w_magic["physical_damage_types"]
    assert w_magic["magic_damage_types"][0]["type"] == "Radiant"
    print("✅ test_summon_loadout_magic_damage_routing passed")


def test_summon_loadout_hp_above_base_level():
    """HP scales only ABOVE the spell's base level: hp_base + hp_per_level x (slot - base_level)."""
    blk = dict(_TEST_SPIRIT, base_level=5, hp_base=50, hp_per_level=10)
    assert compute_summon_loadout(blk, 5, 4, 5)[0]["hp_max"] == 50   # at base level
    assert compute_summon_loadout(blk, 7, 4, 5)[0]["hp_max"] == 70   # +10/level above
    assert compute_summon_loadout(blk, 4, 2, 3)[0]["hp_max"] == 50   # below base: clamped, not negative
    print("✅ test_summon_loadout_hp_above_base_level passed")


def test_summon_loadout_half_level_multiattack():
    """multiattack_half_level: num_attacks = max(1, slot // 2) (the 2024 'Rend = half level' rule)."""
    blk = dict(_TEST_SPIRIT, multiattack_half_level=True)
    assert compute_summon_loadout(blk, 3, 2, 3)[0]["num_attacks"] == 1
    assert compute_summon_loadout(blk, 5, 2, 3)[0]["num_attacks"] == 2
    assert compute_summon_loadout(blk, 9, 4, 5)[0]["num_attacks"] == 4
    print("✅ test_summon_loadout_half_level_multiattack passed")


def test_verified_draconic_spirit_matches_card():
    """The real Draconic Spirit block reproduces the PHB card exactly at a L5 cast:
    AC 19, HP 50, 2 Rend attacks, Rend = 1d6 + 4 + 5 Piercing, to-hit = caster's spell-atk mod."""
    path = os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"), "summons.json")
    drac = next(r for r in json.load(open(path)) if r.get("name") == "Draconic Spirit")
    pb, spell_mod = 4, 5
    stats, weapon = compute_summon_loadout(drac, slot_level=5, pb=pb, spell_ability_mod=spell_mod)
    assert stats["base_ac"] == 19, stats["base_ac"]          # 14 + 5
    assert stats["hp_max"] == 50, stats["hp_max"]            # 50 + 10*(5-5)
    assert stats["num_attacks"] == 2, stats["num_attacks"]   # 5 // 2
    assert weapon["physical_damage_types"][0] == {"type": "Piercing", "num_dice": 1, "die_size": 6}
    assert weapon["reach_ft"] == 10
    str_mod = (drac["str"] - 10) // 2  # 19 -> +4
    # printed Rend damage = 1d6 + 4 + spell level: engine adds str_mod, bonus_damage supplies the rest.
    assert weapon["bonus_damage"] + str_mod == drac["dmg_flat"] + 5   # == 9
    assert weapon["bonus_hit"] + str_mod + pb == pb + spell_mod       # to-hit == spell attack mod
    print("✅ test_verified_draconic_spirit_matches_card passed")


def test_summons_data_well_formed():
    """summons.json: every form record has the fields compute_summon_loadout reads,
    and all Tier-3 summon-framework spells (the ten 'Summon X' plus the conjure/named
    summons) are represented."""
    path = os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"), "summons.json")
    with open(path) as f:
        records = json.load(f)
    spells = {}
    for rec in records:
        spell = rec.get("spell", "")
        if not spell or spell.startswith("_"):
            continue
        spells.setdefault(spell, []).append(rec)
        for key in ("form", "name", "size", "ac_base", "hp_base", "hp_per_level", "attack"):
            assert key in rec, f"{spell}/{rec.get('form')} missing '{key}'"
        # Scaling must produce a sane creature at its own base level, and grow when cast with a
        # higher slot. A base-9 spell (e.g. Gate) can never be upcast, so its HP legitimately can't
        # grow — only assert growth when there is a higher slot to grow into.
        base_level = rec.get("base_level", 0)
        base, _ = compute_summon_loadout(rec, base_level, 4, 4)
        assert base["hp_max"] > 0, f"{spell}/{rec.get('form')} has non-positive HP"
        if base_level < 9:
            hi, _ = compute_summon_loadout(rec, 9, 4, 5)
            assert hi["hp_max"] > base["hp_max"], f"{spell}/{rec.get('form')} does not scale with slot"
    expected = {"Summon Beast", "Summon Fey", "Summon Undead", "Summon Aberration",
                "Summon Construct", "Summon Elemental", "Summon Celestial",
                "Summon Shadowspawn", "Summon Fiend", "Summon Dragon",
                # Conjure / named summons wired onto the same scaling-spirit framework (data-only).
                "Conjure Elemental", "Conjure Celestial", "Giant Insect",
                "Arcane Hand", "Create Undead", "Planar Ally", "Gate"}
    assert expected <= set(spells), expected - set(spells)
    print(f"✅ test_summons_data_well_formed passed ({len(spells)} spells)")


def test_conjure_summons_castable_and_named_in_spells_json():
    """Every conjure/named summon in summons.json must (a) exist in spells.json so it is a
    real, castable spell, and (b) key by the spell's EXACT name — the GUI auto-wires it via
    SUMMON_SPELL_TO_SPIRIT.get(sp.name), so a name mismatch would silently no-op the summon."""
    gui = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")
    summon_names = {r["spell"] for r in json.load(open(os.path.join(gui, "summons.json")))
                    if not r.get("spell", "_").startswith("_")}
    spell_names = {s["name"] for s in json.load(open(os.path.join(gui, "spells.json")))}
    missing = summon_names - spell_names
    assert not missing, f"summons.json references spells absent from spells.json: {missing}"
    for name in ("Conjure Elemental", "Conjure Celestial", "Giant Insect",
                 "Arcane Hand", "Create Undead", "Planar Ally", "Gate"):
        assert name in summon_names, f"{name} not wired in summons.json"
    print(f"✅ test_conjure_summons_castable_and_named_in_spells_json passed ({len(summon_names)} summons)")


if __name__ == "__main__":
    test_summon_bindings_present()
    test_spawn_agent_is_non_destructive()
    test_spawn_agent_blocked_cell_returns_negative()
    test_drop_concentration_dismisses_summon()
    test_dismissed_summon_moved_off_map()
    test_unrelated_summon_not_dismissed()
    test_damage_breaking_concentration_dismisses_summon()
    test_placement_in_range_and_empty_is_valid()
    test_placement_out_of_range_is_invalid()
    test_placement_on_occupied_cell_is_invalid()
    test_can_place_ignores_tombstoned_summon()
    test_can_place_out_of_bounds_is_invalid()
    test_summon_loadout_scales_with_slot()
    test_summon_loadout_to_hit_and_damage_from_caster()
    test_summon_loadout_multiattack_threshold()
    test_summon_loadout_magic_damage_routing()
    test_summon_loadout_hp_above_base_level()
    test_summon_loadout_half_level_multiattack()
    test_verified_draconic_spirit_matches_card()
    test_summons_data_well_formed()
    test_conjure_summons_castable_and_named_in_spells_json()
    print("\nAll summoning tests passed!")
