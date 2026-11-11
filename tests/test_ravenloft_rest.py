#!/usr/bin/env python3
"""Ravenloft items RI6 — M6 luck, M10 Rod slot regain, M11 Potion of Heroism
(plans/RAVENLOFT_ITEMS_PLAN.md; M7, Wish on the Luck Blade, is dropped).

The Luck Blade carries one Luck Point a day (`luck_points`), spent like the Lucky feat's for
Advantage on the next D20 Test, only while attuned, refilled by a long rest and saved with the
blade. A Rod of the Pact Keeper regains one expended spell slot (`regain_slot`), once per long
rest. The Potion of Heroism, drunk, gives 10 Temporary Hit Points and the Blessed condition for
600 rounds without Concentration. The action menu offers Luck and the Rod's slot when they can
be used.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import json

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from helpers import (_dict_to_item, _dict_to_weapon, _item_to_dict, _weapon_to_dict,
                     item_slot_regain_ready, item_spells_summary)

_GUI = os.path.join(_ROOT, "gui")


def _load(fname):
    with open(os.path.join(_GUI, fname)) as f:
        return {r["name"]: r for r in json.load(f)}


WEAPONS, ITEMS = _load("weapons.json"), _load("items.json")


def _board():
    bm, engine = setup_battle_map(), setup_combat_engine()
    h = add_agent_to_battle(engine, bm, create_test_agent("Holder", 5, 5), hp=30)
    o = add_agent_to_battle(engine, bm, create_test_agent("Other", 6, 5), hp=30)
    return bm, engine, h, o


def _blade(engine, bm, idx, attuned=True):
    w = _dict_to_weapon(WEAPONS["Luck Blade (Longsword)"])
    w.item_spells.attuned = attuned
    weapons = engine.get_agent_weapons(bm, idx)
    weapons[0] = w
    engine.set_agent_weapons(bm, idx, weapons)


# ── M6: Luck Blade ────────────────────────────────────────────────────────────
def test_luck_blade_point():
    bm, engine, h, _ = _board()
    assert engine.luck_available(bm, h) == 0
    _blade(engine, bm, h, attuned=False)
    assert engine.luck_available(bm, h) == 0, "only while attuned"
    assert not engine.spend_luck_for_advantage(bm, h)

    _blade(engine, bm, h)
    assert engine.luck_available(bm, h) == 1
    assert engine.spend_luck_for_advantage(bm, h)
    assert engine.get_agent_weapons(bm, h)[0].item_spells.luck == 0
    assert engine.luck_available(bm, h) == 0 and not engine.spend_luck_for_advantage(bm, h)

    saved = _weapon_to_dict(engine.get_agent_weapons(bm, h)[0])
    assert (saved["luck_points"], saved["luck_remaining"]) == (1, 0), "spent luck is saved"
    assert _dict_to_weapon(saved).item_spells.luck == 0

    engine.apply_long_rest(bm)
    assert engine.get_agent_weapons(bm, h)[0].item_spells.luck == 1, "back at dawn"
    print("✅ test_luck_blade_point")


def test_feat_points_go_first():
    bm, engine, h, _ = _board()
    s = engine.get_agent_stats(bm, h)
    s.feats = list(s.feats) + ["Lucky"]
    s.luck_points = s.luck_points_max = 1
    engine.set_agent_stats(bm, h, s)
    _blade(engine, bm, h)
    assert engine.luck_available(bm, h) == 2
    assert engine.spend_luck_for_advantage(bm, h)
    assert engine.get_agent_stats(bm, h).luck_points == 0
    assert engine.get_agent_weapons(bm, h)[0].item_spells.luck == 1
    print("✅ test_feat_points_go_first")


# ── M10: Rod of the Pact Keeper ───────────────────────────────────────────────
def test_rod_regains_a_pact_slot_once():
    bm, engine, h, _ = _board()
    s = engine.get_agent_stats(bm, h)
    s.set_class_level(rpg.CharacterClass.Warlock, 5)
    s.initialize_class_resources(rpg.CharacterClass.Warlock, 5)
    s.spell_slots_remaining = [0] * 9          # both level-3 pact slots spent
    engine.set_agent_stats(bm, h, s)
    rod = _dict_to_item(ITEMS["Rod of the Pact Keeper +1"])
    rod.item_spells.attuned = True
    engine.set_agent_items(bm, h, [rod])

    assert item_slot_regain_ready(engine, bm, h)
    assert engine.regain_slot_from_item(bm, h) == 3
    assert list(engine.get_agent_stats(bm, h).spell_slots_remaining)[2] == 1
    assert not item_slot_regain_ready(engine, bm, h)
    assert engine.regain_slot_from_item(bm, h) == 0, "once per long rest"
    assert _item_to_dict(engine.get_agent_items(bm, h)[0])["slot_regain_used"] is True
    assert "slot regain used" in item_spells_summary(engine.get_agent_items(bm, h)[0].item_spells)

    engine.apply_long_rest(bm)
    assert not engine.get_agent_items(bm, h)[0].item_spells.slot_regain_used
    assert not item_slot_regain_ready(engine, bm, h), "a long rest also refilled the slots"
    print("✅ test_rod_regains_a_pact_slot_once")


def test_rod_needs_a_missing_slot_and_attunement():
    bm, engine, h, _ = _board()
    s = engine.get_agent_stats(bm, h)
    s.spell_slots_max = [2] + [0] * 8
    s.spell_slots_remaining = [1] + [0] * 8
    engine.set_agent_stats(bm, h, s)
    rod = _dict_to_item(ITEMS["Rod of the Pact Keeper +2"])
    engine.set_agent_items(bm, h, [rod])
    assert engine.regain_slot_from_item(bm, h) == 0, "not attuned"
    rod.item_spells.attuned = True
    engine.set_agent_items(bm, h, [rod])
    assert engine.regain_slot_from_item(bm, h) == 1
    assert list(engine.get_agent_stats(bm, h).spell_slots_remaining)[0] == 2
    print("✅ test_rod_needs_a_missing_slot_and_attunement")


# ── M11: Potion of Heroism ────────────────────────────────────────────────────
def test_potion_of_heroism():
    bm, engine, h, o = _board()
    pot = _dict_to_item(ITEMS["Potion of Heroism"])
    assert (pot.temp_hp, pot.applies_condition, pot.applies_condition_turns) == (10, "Blessed", 600)
    assert _dict_to_item(_item_to_dict(pot)).applies_condition_turns == 600
    engine.set_agent_items(bm, h, [pot])
    engine.begin_turn(bm, h)
    res = engine.use_item(bm, h, 0, h)
    assert res.valid and res.consumed
    st = engine.get_agent_stats(bm, h)
    assert st.temp_hp == 10 and st.blessed
    assert not engine.get_agent_conditions(bm, h).concentrating, "no Concentration"
    blessed = [c for c in engine.active_agent_conditions
               if c.agent_idx == h and c.condition_name == "Blessed"]
    assert blessed and blessed[0].turns_remaining >= 590
    for _ in range(5):
        engine.begin_turn(bm, h)
        engine.end_turn(bm, h)
    assert engine.get_agent_stats(bm, h).blessed, "still Blessed a few rounds later"
    print("✅ test_potion_of_heroism")


# ── Action menu ───────────────────────────────────────────────────────────────
def test_action_menu_offers_luck_and_rod():
    from actions import ActionMenu
    from test_combat_panel import App, MAP_PATH, SEED, _build_scene
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()
    idx = app._current_agent_idx()
    ids = [a.id for a in ActionMenu.build(app, idx)]
    assert "use_luck" not in ids and "regain_slot" not in ids

    _blade(app.combat, app.bm, idx)
    s = app.combat.get_agent_stats(app.bm, idx)
    s.spell_slots_max = [1] + [0] * 8
    s.spell_slots_remaining = [0] * 9
    app.combat.set_agent_stats(app.bm, idx, s)
    rod = _dict_to_item(ITEMS["Rod of the Pact Keeper +1"])
    rod.item_spells.attuned = True
    app.combat.set_agent_items(app.bm, idx, list(app.combat.get_agent_items(app.bm, idx)) + [rod])
    by = {a.id: a for a in ActionMenu.build(app, idx)}
    assert by["use_luck"].label == "Luck (1)"
    assert "regain_slot" in by

    print("✅ test_action_menu_offers_luck_and_rod")


def test_panel_draws_luck_and_potion_works_at_full_hp():
    """Found in the RI7 live check: the panel needs a button for every action it lays out (it
    crashed drawing Luck), and the full-HP guard refused a Potion of Heroism."""
    import tempfile
    from gui_driver import screenshot
    from test_combat_panel import App, MAP_PATH, SEED, _build_scene
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()
    idx = app._current_agent_idx()
    _blade(app.combat, app.bm, idx)
    s = app.combat.get_agent_stats(app.bm, idx)
    s.spell_slots_max = [1] + [0] * 8
    s.spell_slots_remaining = [0] * 9
    app.combat.set_agent_stats(app.bm, idx, s)
    rod = _dict_to_item(ITEMS["Rod of the Pact Keeper +1"])
    rod.item_spells.attuned = True
    pot = _dict_to_item(ITEMS["Potion of Heroism"])
    app.combat.set_agent_items(app.bm, idx, list(app.combat.get_agent_items(app.bm, idx)) + [rod, pot])
    with tempfile.TemporaryDirectory() as d:
        screenshot(app, os.path.join(d, "panel.png"))        # draws Luck and Regain Slot
    assert app.btn_cbt_use_luck.text == "Luck (1)"

    app._perform_action("regain_slot", None)
    assert list(app.combat.get_agent_stats(app.bm, idx).spell_slots_remaining)[0] == 1
    assert app.action_used, "the Rod's slot is a Magic action"

    st = app.combat.get_agent_stats(app.bm, idx)
    assert st.hp_cur == st.hp_max
    app.bonus_used = False
    inv = app.combat.get_agent_items(app.bm, idx)
    app.pending_use_item = next(i for i, it in enumerate(inv) if it.name == "Potion of Heroism")
    app._resolve_use_item(idx)
    st = app.combat.get_agent_stats(app.bm, idx)
    assert st.temp_hp == 10 and st.blessed, "drunk at full HP for its temp HP and Bless"
    print("✅ test_panel_draws_luck_and_potion_works_at_full_hp")


if __name__ == "__main__":
    test_luck_blade_point()
    test_feat_points_go_first()
    test_rod_regains_a_pact_slot_once()
    test_rod_needs_a_missing_slot_and_attunement()
    test_potion_of_heroism()
    test_action_menu_offers_luck_and_rod()
    test_panel_draws_luck_and_potion_works_at_full_hp()
    print("\nAll Ravenloft items RI6 tests passed!")
