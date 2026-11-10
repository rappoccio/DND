#!/usr/bin/env python3
"""Spell scrolls SS2 — making a scroll (plans/SPELL_SCROLLS_PLAN.md).

Picking the blank catalog "Spell Scroll" from the item picker (the one the Items dialog, chest
contents and Place item all share) asks for its spell (only spells a scroll can hold), then
its save DC and attack, prefilled from the DMG table (S2); the caller gets the made scroll.
Esc at either step adds nothing; any other item passes straight through. The DM's answer
parses as "15" (attack = DC − 8), "15 +6", "15/6" or "DC 15 +6".
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import tempfile

import pygame
from helpers import parse_scroll_dc, _dict_to_item


def _app(tmp):
    from main import App
    from test_restore_oracle import MAP_PATH, SEED, _place
    app = App(MAP_PATH, seed=SEED)
    app.autosave_enabled = False
    app._set_encounter_base(os.path.join(tmp, "ss2_agents.json"))
    _place(app, "Aria", 2, 3)
    app.combat.apply_agent_configs(app.bm)
    return app


def _key(dialog, key):
    return dialog.handle(pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0))


def _pick_item(app, name, got):
    """Open the shared item picker and choose ``name`` (filter to it, then Return)."""
    dlg = app.item_selection_dialog
    dlg.show(got.append)
    dlg.search_text = name
    dlg._update_filtered_items()
    dlg.filtered_items = [i for i in dlg.filtered_items if i["name"] == name]
    _key(dlg, pygame.K_RETURN)
    assert not dlg.visible


def _spell(app, name):
    return next(d for d in app.all_spells if d["name"] == name)


def test_parse_scroll_dc():
    assert parse_scroll_dc("15") == (15, 7)
    assert parse_scroll_dc("15 +6") == (15, 6)
    assert parse_scroll_dc("15/6") == (15, 6)
    assert parse_scroll_dc("dc 17 +9") == (17, 9)
    assert parse_scroll_dc("fifteen") is None
    assert parse_scroll_dc("15 6 2") is None
    print("✅ test_parse_scroll_dc")


def test_blank_scroll_asks_spell_then_dc(app):
    got = []
    _pick_item(app, "Spell Scroll", got)
    assert not got, "nothing delivered until the spell and DC are chosen"
    sd = app.spell_selection_dialog
    assert sd.visible and "Fear" in sd.allow_names
    assert not any(n.startswith("Breath") for n in sd.allow_names)

    sd._commit(_spell(app, "Fear"))
    np_ = app.name_prompt
    assert np_.visible and np_._text == "15 +7", f"prefilled from the table (got {np_._text!r})"
    _key(np_, pygame.K_RETURN)
    assert len(got) == 1
    rec = got[0]
    assert rec["name"] == "Spell Scroll (Fear)" and rec["type"] == "Scroll"
    assert (rec["spell_dc"], rec["spell_attack"]) == (15, 7)
    it = _dict_to_item(rec)
    assert it.item_spells.uses_remaining == {"Fear": 1}
    print("✅ test_blank_scroll_asks_spell_then_dc")


def test_dm_sets_the_dc(app):
    got = []
    _pick_item(app, "Spell Scroll", got)
    app.spell_selection_dialog._commit(_spell(app, "Fireball"))
    app.name_prompt._text = "17"
    _key(app.name_prompt, pygame.K_RETURN)
    assert (got[0]["spell_dc"], got[0]["spell_attack"]) == (17, 9)

    got.clear()
    _pick_item(app, "Spell Scroll", got)
    app.spell_selection_dialog._commit(_spell(app, "Fireball"))
    app.name_prompt._text = "not a dc"
    _key(app.name_prompt, pygame.K_RETURN)
    assert not got, "a bad answer makes nothing"
    print("✅ test_dm_sets_the_dc")


def test_escape_adds_nothing(app):
    got = []
    _pick_item(app, "Spell Scroll", got)
    _key(app.spell_selection_dialog, pygame.K_ESCAPE)
    assert not app.spell_selection_dialog.visible and not got

    _pick_item(app, "Spell Scroll", got)
    app.spell_selection_dialog._commit(_spell(app, "Fear"))
    _key(app.name_prompt, pygame.K_ESCAPE)
    assert not app.name_prompt.visible and not got
    print("✅ test_escape_adds_nothing")


def test_other_items_pass_through(app):
    got = []
    _pick_item(app, "Potion of Healing", got)
    assert [r["name"] for r in got] == ["Potion of Healing"]
    assert not app.spell_selection_dialog.visible
    print("✅ test_other_items_pass_through")


if __name__ == "__main__":
    test_parse_scroll_dc()
    with tempfile.TemporaryDirectory() as tmp:
        app = _app(tmp)
        test_blank_scroll_asks_spell_then_dc(app)
        test_dm_sets_the_dc(app)
        test_escape_adds_nothing(app)
        test_other_items_pass_through(app)
    print("\nAll spell scroll SS2 tests passed.")
