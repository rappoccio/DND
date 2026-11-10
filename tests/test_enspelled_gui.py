#!/usr/bin/env python3
"""Enspelled items E4 — the GUI (plans/ENSPELLED_ITEMS_PLAN.md).

Spell-menu labels ('Fear (Mace of Terror) 2/2', '… at will', pool rows with their cost and
'charges 5/7'), offered even with no slots left; the per-item summary that item info, the
side panel and the player sheet share; the Attuned toggle in the Items / Weapons / Armor
dialogs and the > 3 warning (D5); the Armor dialog round-tripping a worn piece whole.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import json
import shutil
import tempfile

import pygame
import rpg_battle_map as rpg
from helpers import (_dict_to_armor, _dict_to_item, _dict_to_weapon, attuned_count,
                     attunement_warning, item_dict_summary, item_spell_label,
                     item_spells_summary, is_item_spell)

_GUI = os.path.join(_ROOT, "gui")
_records = {}

# A charge-pool item, so the pool labels are covered without one in the catalog yet.
WAND = {"name": "Test Wand", "type": "Wondrous", "action_type": "NoAction",
        "consumable": False, "requires_attunement": False,
        "charges": {"max": 7, "regain": "long_rest"},
        "charge_spells": {"1": ["Burning Hands"], "3": ["Fireball"]}}


def _record(fname, name):
    if fname not in _records:
        with open(os.path.join(_GUI, fname)) as f:
            _records[fname] = json.load(f)
    return next(r for r in _records[fname] if r["name"] == name)


def _app(tmp):
    from main import App
    from test_restore_oracle import MAP_PATH, SEED, _place
    app = App(MAP_PATH, seed=SEED)
    app.autosave_enabled = False
    app._set_encounter_base(os.path.join(tmp, "e4_agents.json"))
    _place(app, "Aria", 2, 3)
    app.combat.apply_agent_configs(app.bm)
    return app


def _click(dialog, rect, screen=None):
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center)
    return dialog.handle(ev, screen) if screen is not None else dialog.handle(ev)


def test_summary_and_status_text():
    mace = _dict_to_weapon(_record("weapons.json", "Mace of Terror"))
    assert item_spells_summary(mace.item_spells) == ["Fear 2/2"]
    mace.item_spells.spend("Fear", 0)
    assert item_spells_summary(mace.item_spells) == ["Fear 1/2"]

    icon = _record("items.json", "Icon of Ravenloft")
    assert item_dict_summary(icon) == ["Protection from Evil and Good at will", "Cure Wounds 1/1"]

    wand = _dict_to_item(WAND)
    wand.item_spells.spend("Fireball", 3)
    assert item_spells_summary(wand.item_spells) == \
        ["charges 4/7: Burning Hands (1), Fireball (3)"]

    assert item_dict_summary(_record("items.json", "Net")) == []
    print("✅ test_summary_and_status_text")


def test_attunement_count_and_warning():
    assert attunement_warning(3) == ""
    assert "4" in attunement_warning(4) and "3" in attunement_warning(4)
    print("✅ test_attunement_count_and_warning")


def test_spell_menu_labels_without_slots():
    tmp = tempfile.mkdtemp()
    try:
        app = _app(tmp)
        aria = 0
        stats = app.combat.get_agent_stats(app.bm, aria)
        stats.spell_slots_max = [0] * 9
        stats.spell_slots_remaining = [0] * 9
        app.combat.set_agent_stats(app.bm, aria, stats)

        mace = _dict_to_weapon(_record("weapons.json", "Mace of Terror"))
        mace.item_spells.attuned = True
        weapons = list(app.combat.get_agent_weapons(app.bm, aria))
        weapons[0] = mace
        app.combat.set_agent_weapons(app.bm, aria, weapons)
        icon = _dict_to_item(_record("items.json", "Icon of Ravenloft"))
        icon.item_spells.attuned = True
        app.combat.set_agent_items(app.bm, aria, [icon, _dict_to_item(WAND)])
        app._sync_item_spells(aria)

        offered = []
        app._current_agent_idx = lambda: aria
        app._ask_actor = lambda idx, kind, title, pairs, **kw: offered.extend(l for l, _ in pairs)
        app._start_cast_spell("action")
        assert "Fear (Mace of Terror) 2/2" in offered, offered
        assert "Protection from Evil and Good (Icon of Ravenloft) at will" in offered, offered
        assert "Cure Wounds (Icon of Ravenloft) 1/1" in offered, offered
        assert "Fireball (Test Wand) 3 ch · charges 7/7" in offered, offered

        # Drain the wand below Fireball's cost: the engine stops offering it, Burning Hands stays.
        items = list(app.combat.get_agent_items(app.bm, aria))
        items[1].item_spells.charges = 2
        app.combat.set_agent_items(app.bm, aria, items)
        offered.clear()
        app._start_cast_spell("action")
        assert not any(l.startswith("Fireball") for l in offered), offered
        assert "Burning Hands (Test Wand) 1 ch · charges 2/7" in offered, offered

        fear = next(sp for sp in app.combat.get_agent_spells(app.bm, aria)
                    if is_item_spell(sp) and sp.name == "Fear")
        assert item_spell_label(app.combat, app.bm, aria, fear) == "Fear (Mace of Terror) 2/2"
        assert attuned_count(app.combat, app.bm, aria) == 2   # mace + icon; the wand needs none

        # Player sheet: the same lines, with attunement state.
        from net.view import _item_spells
        sheet = {r["item"]: r for r in _item_spells(app, aria)}
        assert sheet["Mace of Terror"] == {"item": "Mace of Terror", "attuned": True,
                                           "spells": ["Fear 2/2"]}
        assert sheet["Test Wand"]["attuned"] is None
        assert sheet["Test Wand"]["spells"] == ["charges 2/7: Burning Hands (1), Fireball (3)"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_spell_menu_labels_without_slots")


def test_dialog_attune_toggles_and_armor_round_trip():
    tmp = tempfile.mkdtemp()
    try:
        app = _app(tmp)
        screen = app.screen

        # Items dialog: the toggle flips "attuned"; the row carries through _dict_to_item.
        icon = _dict_to_item(_record("items.json", "Icon of Ravenloft"))
        dlg = app.items_dialog
        dlg.open(screen, 0, "Aria", [icon, _dict_to_item(_record("items.json", "Net"))],
                 app.item_selection_dialog, None, other_attuned=3)
        from dialogs import _attune_rect, _attune_warning
        dlg.draw(screen)
        assert _attune_warning(dlg.current_items, dlg.other_attuned) == ""
        assert _click(dlg, _attune_rect(dlg._slot_rect(0)), screen)
        assert dlg.current_items[0]["attuned"] is True
        assert _dict_to_item(dlg.current_items[0]).item_spells.attuned
        assert _attune_warning(dlg.current_items, dlg.other_attuned) == attunement_warning(4)
        dlg.draw(screen)
        assert _click(dlg, _attune_rect(dlg._slot_rect(0)), screen)
        assert dlg.current_items[0]["attuned"] is False

        # Weapons dialog: the mace's toggle, not the picker.
        mace = _dict_to_weapon(_record("weapons.json", "Mace of Terror"))
        wd = app.weapons_dialog
        wd.open(screen, 0, "Aria", [mace], app.weapon_selection_dialog, None)
        wd.draw(screen)
        assert _click(wd, wd._attune_rect(0), screen)
        assert wd.current_weapons[0]["attuned"] is True
        assert not app.weapon_selection_dialog.visible
        assert _dict_to_weapon(wd.current_weapons[0]).item_spells.attuned

        # Armor dialog: a worn piece comes back whole (it used to lose its AC bonus).
        shield = _dict_to_armor({"name": "Ward Shield", "ac_bonus": 2, "requires_attunement": True,
                                 "item_spell_groups": {"1": ["Shield"]}})
        ad = app.armor_dialog
        ad.open(screen, 0, "Aria", [shield] + [rpg.Armor() for _ in range(5)],
                app.armor_selection_dialog, None)
        ad.draw(screen)
        assert _click(ad, _attune_rect(ad._slot_rect(0)), screen)
        back = _dict_to_armor(ad.current_armor[0])
        assert back.ac_bonus == 2, back.ac_bonus
        assert back.item_spells.attuned
        assert not app.armor_selection_dialog.visible

        # A second Icon from the catalog is a new row, not a stack (D0).
        dlg.open(screen, 0, "Aria", [icon], app.item_selection_dialog, None)
        _click(dlg, dlg._add_rect(), screen)
        app.item_selection_dialog.selected_callback(_record("items.json", "Icon of Ravenloft"))
        assert [d["name"] for d in dlg.current_items] == ["Icon of Ravenloft"] * 2
        assert [d["quantity"] for d in dlg.current_items] == [1, 1]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_dialog_attune_toggles_and_armor_round_trip")


if __name__ == "__main__":
    test_summary_and_status_text()
    test_attunement_count_and_warning()
    test_spell_menu_labels_without_slots()
    test_dialog_attune_toggles_and_armor_round_trip()
