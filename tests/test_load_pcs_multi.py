#!/usr/bin/env python3
"""Load PCs with a multi-select file browser.

  · FileBrowser(multi_select=True): clicking files toggles them, the selection survives
    a folder change, and Load hands the callback every ticked path in pick order;
  · Load PCs opens on the campaign's pcs/ folder and takes any mix of single-PC files
    (pcs/<name>.json, one bare agent) and party files ({"agents": [...]}), adding them
    all to the scene on the blue team.
"""

import os
import sys
import json
import shutil
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame
import rpg_battle_map as rpg

import main as app_main
from main import App, PC_FACTION
from dialogs import FileBrowser
from test_helpers import make_fixture_campaign


def _click(fb, screen, idx):
    lrect = fb._list_rect(fb._dlg(screen))
    y = lrect.y + (idx - fb.scroll) * fb.ITEM_H + fb.ITEM_H // 2
    fb.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                 pos=(lrect.x + 20, y)), screen)


def _row(fb, name):
    return next(i for i, (n, _) in enumerate(fb._raw) if n == name)


def test_browser_multi_select():
    pygame.init()
    screen = pygame.display.set_mode((1200, 800))
    font = pygame.font.SysFont(None, 18)
    tmp = tempfile.mkdtemp(prefix="load_pcs_fb_")
    try:
        sub = os.path.join(tmp, "more")
        os.makedirs(sub)
        for p in ("a.json", "b.json", os.path.join("more", "c.json")):
            open(os.path.join(tmp, p), "w").write("{}")
        got = []
        fb = FileBrowser(font, font, font)
        fb.open(tmp, got.append, extensions={".json"}, multi_select=True)

        _click(fb, screen, _row(fb, "b.json"))
        _click(fb, screen, _row(fb, "a.json"))
        _click(fb, screen, _row(fb, "b.json"))           # untick
        _click(fb, screen, _row(fb, "b.json"))           # tick again, now last
        assert fb.active and not got                     # file clicks never close
        _click(fb, screen, _row(fb, "more"))
        assert fb.cwd == sub
        _click(fb, screen, _row(fb, "c.json"))
        fb.draw(screen)                                  # check marks + Load (3) render

        fb.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                     pos=fb._save_rect(fb._dlg(screen)).center), screen)
        assert not fb.active
        assert got == [[os.path.join(tmp, "a.json"), os.path.join(tmp, "b.json"),
                        os.path.join(sub, "c.json")]], got

        got.clear()
        fb.open(tmp, got.append, extensions={".json"}, multi_select=True)
        fb.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN), screen)
        assert fb.active and not got                     # nothing ticked: Load is inert
    finally:
        shutil.rmtree(tmp)
    print("  ✅ multi-select toggles, keeps picks across folders, returns them in order")


def _place(app, name, col, row):
    cfg = rpg.AgentConfig()
    cfg.name, cfg.start_col, cfg.start_row, cfg.size, cfg.sprite_path = name, col, row, 1, ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)
    app.combat.apply_agent_configs(app.bm)


def test_load_pcs_from_campaign_folder():
    tmp = tempfile.mkdtemp(prefix="load_pcs_")
    try:
        camp = make_fixture_campaign(os.path.join(tmp, "Test Campaign"))
        png, manifest = app_main.resolve_start_path(camp.root)
        app = App(png, seed=1)
        app._on_open_dungeon_chosen(manifest)

        # Real agent dicts, as the app writes them, for the PC files.
        for i, n in enumerate(("Aodhan", "Hilaria", "Seungho")):
            _place(app, n, 1 + i, 1)
        app._save_agents()
        dicts = {a["name"]: a for a in app.store.creatures()["agents"]}
        os.makedirs(camp.pcs_dir, exist_ok=True)
        for n in ("Aodhan", "Hilaria"):
            with open(camp.pc_path(n), "w") as f:
                json.dump(dicts[n], f)
        party = os.path.join(tmp, "party_pc_agents.json")
        with open(party, "w") as f:
            json.dump({"agents": [dicts["Seungho"]]}, f)
        notes = os.path.join(camp.pcs_dir, "notes.json")
        with open(notes, "w") as f:
            json.dump({"hello": 1}, f)                   # not a PC: skipped

        app._clear_agents()
        app._save_agents()

        app._open_load_pcs_browser()
        fb = app.file_browser
        assert fb.active and fb.multi_select and fb.cwd == os.path.abspath(camp.pcs_dir)
        assert {"aodhan.json", "hilaria.json"} <= {n for n, _ in fb._raw}
        fb.active = False

        app._on_load_pcs_chosen([camp.pc_path("Aodhan"), camp.pc_path("Hilaria"),
                                 party, notes])
        assert sorted(pt.name for pt in app.bm.placed_agents) == [
            "Aodhan", "Hilaria", "Seungho"]
        app._save_agents()
        saved = app.store.creatures()["agents"]
        assert len({(a["col"], a["row"]) for a in saved}) == 3
        assert all(a["faction"] == PC_FACTION for a in saved)

        app._on_load_pcs_chosen([notes])                 # nothing usable: no change
        assert len(app.bm.placed_agents) == 3
    finally:
        shutil.rmtree(tmp)
    print("  ✅ Load PCs opens on pcs/ and loads single-PC and party files together")


def main():
    tests = [
        test_browser_multi_select,
        test_load_pcs_from_campaign_folder,
    ]
    print("Running Load PCs multi-select tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} Load PCs multi-select tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
