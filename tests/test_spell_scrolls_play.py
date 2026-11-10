#!/usr/bin/env python3
"""Spell scrolls SS3 — play + NPCs (plans/SPELL_SCROLLS_PLAN.md).

The spell menu labels a scroll 'Fear (scroll, DC 15)'; the Items dialog rows, side panel and
player sheet show one 'DC 15 · +7' line, the sheet saying whether its holder can read it (S5).
The DM's creature menu offers *Reads any scroll* once the creature carries a scroll, and the
tick grants the spell at once. A GUI cast from a scroll drops the scroll straight away
(_finish_cast), out of combat too. An automated caster carrying a scroll casts from it at the
scroll's DC with no slot, and the spent scroll goes at the next sync.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import json
import tempfile

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from helpers import (_dict_to_item, item_dict_summary, item_spell_label, is_item_spell,
                     make_spell_scroll, sync_item_spells)

_GUI = os.path.join(_ROOT, "gui")
with open(os.path.join(_GUI, "spells.json")) as f:
    CATALOG = {d["name"]: d for d in json.load(f)}
with open(os.path.join(_GUI, "items.json")) as f:
    TEMPLATE = next(r for r in json.load(f) if r["name"] == "Spell Scroll")


def _scroll(spell, dc=None):
    return make_spell_scroll(TEMPLATE, CATALOG[spell], dc)


def _item_spell_rows(engine, bm, idx):
    return [(j, sp) for j, sp in enumerate(engine.get_agent_spells(bm, idx)) if is_item_spell(sp)]


def _app(tmp):
    from main import App
    from test_restore_oracle import MAP_PATH, SEED, _place
    app = App(MAP_PATH, seed=SEED)
    app.autosave_enabled = False
    app._set_encounter_base(os.path.join(tmp, "ss3_agents.json"))
    _place(app, "Aria", 2, 3)
    app.combat.apply_agent_configs(app.bm)
    return app


def _give(app, idx, *records):
    items = list(app.combat.get_agent_items(app.bm, idx)) + [_dict_to_item(r) for r in records]
    app.combat.set_agent_items(app.bm, idx, items)
    app._sync_item_spells(idx)


def _set_class(app, idx, cls):
    s = app.combat.get_agent_stats(app.bm, idx)
    s.set_class_level(cls, 5)
    s.reads_any_scroll = False
    app.combat.set_agent_stats(app.bm, idx, s)


# ── Labels ──────────────────────────────────────────────────────────────────────
def test_dialog_row_summary():
    assert item_dict_summary(_scroll("Fear")) == ["DC 15 · +7"]
    assert item_dict_summary(_scroll("Fear", dc=17)) == ["DC 17 · +9"]
    assert item_dict_summary(TEMPLATE) == [], "a blank scroll has nothing to show"
    print("✅ test_dialog_row_summary")


def test_menu_label_and_sheet(app):
    from net.view import _item_spells
    _set_class(app, 0, rpg.CharacterClass.Wizard)
    app.combat.set_agent_items(app.bm, 0, [])
    _give(app, 0, _scroll("Fear"), _scroll("Cure Wounds"))
    (_, sp), = _item_spell_rows(app.combat, app.bm, 0)
    assert item_spell_label(app.combat, app.bm, 0, sp) == "Fear (scroll, DC 15)"
    sheet = {r["item"]: r for r in _item_spells(app, 0)}
    assert sheet["Spell Scroll (Fear)"]["spells"] == ["DC 15 · +7"]
    assert sheet["Spell Scroll (Fear)"]["readable"] is True
    assert sheet["Spell Scroll (Cure Wounds)"]["readable"] is False, "not a Wizard spell"
    print("✅ test_menu_label_and_sheet")


# ── DM override in the creature menu ────────────────────────────────────────────
def _dm_menu_rows(app, idx):
    from menus import board
    seen = {}
    real = app._ask_dm
    app._ask_dm = lambda slot, title, opts, **kw: seen.setdefault("rows", opts)
    try:
        board.show_agent_menu(app, idx, (100, 100))
    finally:
        app._ask_dm = real
    return dict(seen["rows"])


def test_reads_any_scroll_toggle(app):
    _set_class(app, 0, rpg.CharacterClass.Fighter)
    app.combat.set_agent_items(app.bm, 0, [])
    app._sync_item_spells(0)
    assert "Reads any scroll" not in _dm_menu_rows(app, 0), "no scroll: no row"
    _give(app, 0, _scroll("Fear"))
    assert not _item_spell_rows(app.combat, app.bm, 0), "a Fighter can't read Fear"
    _dm_menu_rows(app, 0)["Reads any scroll"]()
    assert app.combat.get_agent_stats(app.bm, 0).reads_any_scroll
    assert [sp.name for _, sp in _item_spell_rows(app.combat, app.bm, 0)] == ["Fear"]
    rows = _dm_menu_rows(app, 0)
    assert "✓ Reads any scroll" in rows
    rows["✓ Reads any scroll"]()
    assert not _item_spell_rows(app.combat, app.bm, 0), "untick: the grant goes again"
    print("✅ test_reads_any_scroll_toggle")


# ── A GUI cast drops the scroll at once ─────────────────────────────────────────
def test_gui_cast_discards_spent_scroll(app):
    """Through the real cast path (_resolve_spell_cast → begin_cast → _finish_cast), out of combat."""
    _set_class(app, 0, rpg.CharacterClass.Cleric)
    s = app.combat.get_agent_stats(app.bm, 0)
    s.spell_slots_max = [0] * 9
    s.spell_slots_remaining = [0] * 9
    s.hp_cur = 1
    app.combat.set_agent_stats(app.bm, 0, s)
    app.combat.set_agent_items(app.bm, 0, [])
    _give(app, 0, _scroll("Cure Wounds"))
    (j, sp), = _item_spell_rows(app.combat, app.bm, 0)
    real_cur = app._current_agent_idx
    app._current_agent_idx = lambda: 0
    try:
        app.pending_spell_slot, app.pending_spell_idx, app.pending_spell_slot_level = "action", j, 0
        app.pending_spell_targets = []
        app._resolve_spell_cast(0)
    finally:
        app._current_agent_idx = real_cur
    st = app.combat.get_agent_stats(app.bm, 0)
    assert st.hp_cur > 1, "Cure Wounds healed"
    assert list(st.spell_slots_remaining) == [0] * 9, "no slot"
    assert not app.combat.get_agent_items(app.bm, 0), "the scroll is gone straight after the cast"
    assert not _item_spell_rows(app.combat, app.bm, 0)
    print("✅ test_gui_cast_discards_spent_scroll")


# ── NPC automation ──────────────────────────────────────────────────────────────
def test_automated_caster_uses_scroll():
    bm, engine = setup_battle_map(), setup_combat_engine()
    me = add_agent_to_battle(engine, bm, create_test_agent("Acolyte", 5, 5), hp=40)
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 6, 5), wis=1, hp=200)
    bm.set_agent_faction(me, 1)
    bm.set_agent_faction(foe, 2)
    s = engine.get_agent_stats(bm, me)
    s.is_npc = True
    s.reads_any_scroll = True              # a classless monster, with the DM's tick
    s.spell_slots_max = [0] * 9
    s.spell_slots_remaining = [0] * 9
    engine.set_agent_stats(bm, me, s)
    engine.set_agent_items(bm, me, [_dict_to_item(_scroll("Fear", dc=17))])
    sync_item_spells(engine, bm, me, CATALOG)
    bm.set_agent_npc_automated(me, True)
    bm.set_agent_npc_automation_strategy(me, rpg.NpcAutomationStrategy.PreferControl)

    engine.begin_turn(bm, me)
    assert engine.run_npc_turn(bm, me) == rpg.FlowStatus.Completed
    fr = [c for c in engine.active_agent_conditions
          if c.agent_idx == foe and c.condition_name == "Frightened"]
    assert fr and fr[0].save_dc == 17, "Fear from the scroll at its DC 17"
    assert list(engine.get_agent_stats(bm, me).spell_slots_remaining) == [0] * 9
    assert engine.get_agent_items(bm, me)[0].item_spells.uses_remaining == {"Fear": 0}

    sync_item_spells(engine, bm, me, CATALOG)
    assert len(engine.get_agent_items(bm, me)) == 1, "concentrating on Fear: kept"
    engine.drop_concentration(bm, me)
    sync_item_spells(engine, bm, me, CATALOG)
    assert not engine.get_agent_items(bm, me), "then gone"
    print("✅ test_automated_caster_uses_scroll")


if __name__ == "__main__":
    test_dialog_row_summary()
    test_automated_caster_uses_scroll()
    with tempfile.TemporaryDirectory() as tmp:
        app = _app(tmp)
        test_menu_label_and_sheet(app)
        test_reads_any_scroll_toggle(app)
        test_gui_cast_discards_spent_scroll(app)
    print("\nAll spell scroll SS3 tests passed.")
