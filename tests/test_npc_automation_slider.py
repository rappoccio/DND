#!/usr/bin/env python3
"""Agents… → Automate NPCs… (live play 2026-11-04): one slider, 0–5, sets every red
creature's NPC automation at once.

  · level n automates every red creature at n, and only the reds   (test_level_sets_only_the_reds)
  · 0 puts every red back to manual, difficulty reset             (test_zero_is_off)
  · dead and tombstoned reds are left alone                       (test_dead_and_removed_are_skipped)
  · applied on a red's turn, the driver is armed at once          (test_arms_the_driver_on_a_red_turn)
  · the dialog: arrows move the slider, Enter applies, Esc cancels (test_the_dialog)
  · the default is the last value, else the reds' usual level, else 1 (test_default_level)

The scene is a headless `App` on `test_combat_panel.py`'s map.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame

from menus import dm
from test_combat_panel import (App, MAP_PATH, SEED, FOE_TEAM, PC_TEAM, _goto, _idx, _place,
                               _set_conditions, _preserve_cwd_logs, _restore_cwd_logs)

NEUTRAL = 0
SCENE = (("Aria", 2, 2, PC_TEAM), ("Brannor", 3, 2, PC_TEAM),
         ("Skarn", 8, 8, FOE_TEAM), ("Grik", 9, 8, FOE_TEAM), ("Zug", 9, 9, FOE_TEAM),
         ("Bystander", 5, 5, NEUTRAL))


def _app(combat=False):
    app = App(MAP_PATH, seed=SEED)
    for name, col, row, _fac in SCENE:
        _place(app, name, col, row)
    app.combat.apply_agent_configs(app.bm)
    for name, _c, _r, fac in SCENE:
        app.bm.set_agent_faction(_idx(app, name), fac)
    if combat:
        app._start_combat()
        app.combat.stop_recording()
        app._npc_drive_idx = -1
    return app


def _state(app, name):
    i = _idx(app, name)
    return (app.bm.is_agent_npc_automated(i), app.bm.get_agent_npc_automation_difficulty(i))


def _reds():
    return [n for n, *_r, fac in SCENE if fac == FOE_TEAM]


def _others():
    return [n for n, *_r, fac in SCENE if fac != FOE_TEAM]


def test_level_sets_only_the_reds():
    app = _app()
    assert dm.apply_npc_automation(app, 3) == 3
    for name in _reds():
        assert _state(app, name) == (True, 3), (name, _state(app, name))
    for name in _others():
        assert _state(app, name) == (False, 0), (name, _state(app, name))
    assert any("3 red creatures at difficulty 3" in line for line in app.combat_log), \
        app.combat_log[-3:]
    print("✅ test_level_sets_only_the_reds")


def test_zero_is_off():
    app = _app()
    dm.apply_npc_automation(app, 4)
    dm.apply_npc_automation(app, 0)
    for name in _reds() + _others():
        assert _state(app, name) == (False, 0), (name, _state(app, name))
    print("✅ test_zero_is_off")


def test_dead_and_removed_are_skipped():
    app = _app(combat=True)
    _set_conditions(app, _idx(app, "Grik"), dead=True)
    app.bm.set_agent_removed_from_play(_idx(app, "Zug"), True)
    assert dm.apply_npc_automation(app, 2) == 1
    assert _state(app, "Skarn") == (True, 2)
    assert _state(app, "Grik") == (False, 0)
    assert _state(app, "Zug") == (False, 0)
    print("✅ test_dead_and_removed_are_skipped")


def test_arms_the_driver_on_a_red_turn():
    app = _app(combat=True)
    skarn = _goto(app, "Skarn")
    assert app._current_agent_idx() == skarn
    dm.apply_npc_automation(app, 3)
    assert app._npc_drive_idx == skarn, app._npc_drive_idx
    dm.apply_npc_automation(app, 0)          # Off on its own turn takes it back
    assert app._npc_drive_idx == -1, app._npc_drive_idx
    # On a blue turn nothing is armed: the reds wait for their own turn-start.
    _goto(app, "Aria")
    dm.apply_npc_automation(app, 3)
    assert app._npc_drive_idx == -1, app._npc_drive_idx
    print("✅ test_arms_the_driver_on_a_red_turn")


def _key(k):
    return pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="")


def test_the_dialog():
    app = _app()
    dm.show_npc_automation_dialog(app)
    dlg = app._npc_auto_dialog
    assert dlg.visible and dlg.level == 1 and dlg.red_count == 3
    assert app._modal_active()
    for _ in range(3):
        dlg.handle(_key(pygame.K_RIGHT))
    assert dlg.level == 4
    dlg.draw(app.screen)                     # renders without error
    dlg.handle(_key(pygame.K_RETURN))
    assert not dlg.visible
    assert _state(app, "Skarn") == (True, 4)
    # Esc leaves everything as it was.
    dm.show_npc_automation_dialog(app)
    assert dlg.level == 4                     # remembered for the session
    dlg.handle(_key(pygame.K_LEFT))
    dlg.handle(_key(pygame.K_ESCAPE))
    assert not dlg.visible and _state(app, "Skarn") == (True, 4)
    # A click on the slider's first stop is Off.
    dm.show_npc_automation_dialog(app)
    dlg.draw(app.screen)                      # first frame: the opening click is swallowed
    x0, y = dlg.slider.stop_x(0), dlg.slider.rect.centery
    dlg.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(x0, y)))
    dlg.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(x0, y)))
    assert dlg.level == 0, dlg.level
    dlg.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=dlg._ok_rect.center))
    assert _state(app, "Skarn") == (False, 0)
    print("✅ test_the_dialog")


def test_default_level():
    app = _app()
    assert dm._default_npc_level(app) == 1
    for name, lv in (("Skarn", 2), ("Grik", 2), ("Zug", 5)):
        i = _idx(app, name)
        app.bm.set_agent_npc_automated(i, True)
        app.bm.set_agent_npc_automation_difficulty(i, lv)
    assert dm._default_npc_level(app) == 2
    dm.apply_npc_automation(app, 5)
    assert dm._default_npc_level(app) == 5
    print("✅ test_default_level")


if __name__ == "__main__":
    _saved = _preserve_cwd_logs()
    try:
        test_level_sets_only_the_reds()
        test_zero_is_off()
        test_dead_and_removed_are_skipped()
        test_arms_the_driver_on_a_red_turn()
        test_the_dialog()
        test_default_level()
    finally:
        _restore_cwd_logs(_saved)
    print("\n✅ All NPC automation slider tests passed!")
    sys.exit(0)
