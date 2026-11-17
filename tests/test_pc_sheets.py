#!/usr/bin/env python3
"""PCs from the campaign's sheets, play state in the run (plans/NEW_DUNGEON_PLAN.md D3,
step 3).

Pure ``pc_sheets``: a record splits into sheet + play state and builds back; HP and slots
are clamped to a changed sheet; an old run's full PC record reads as play state over its
sheet; a PC under an effect is held whole; the party list's override order; arrivals on
staging cells, else on deck; ``new_dungeon`` keeps only the PCs' play state in the run.

A headless App on a two-dungeon campaign: the party arrives on the staging cells when a
dungeon first opens, the run stores play state only, a change to max HP reaches the other
dungeon while each keeps its own current HP, a Hasted PC is held whole, and a dungeon's
``party`` limits who joins.
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

import campaign_import as ci
import main as app_main
import pc_sheets as ps
import run_state as rs
import save_layout as sl
from dungeon import Dungeon
from main import App

CELL = 30
COLS, ROWS = 10, 8
GRID = {"cell_px": CELL, "anchor": [0, 0], "square_ft": 5}


def _pc(name, hp=20, col=5, row=5):
    return {"name": name, "faction": 2, "size": 1, "col": col, "row": row,
            "controller": "dm", "on_deck": False, "sprite_path": "",
            "stats": {"str": 10, "dex": 14, "con": 12, "intel": 10, "wis": 10, "cha": 10,
                      "hp_max": hp, "hp_cur": hp, "ac": 14, "speed_walk": 30},
            "weapons": [], "items": [{"name": "Potion of Healing", "quantity": 1}],
            "spell_slots_max": [2, 0, 0, 0, 0, 0, 0, 0, 0],
            "spell_slots_cur": [2, 0, 0, 0, 0, 0, 0, 0, 0]}


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(doc, f)


def _read(path):
    with open(path) as f:
        return json.load(f)


def _camp(tmp):
    camp = sl.Campaign.create(os.path.join(tmp, "Camp"))
    for n in ("Sabalath", "Java of the Indies"):
        _write(camp.pc_path(n), _pc(n))
    return camp


# ── Pure ─────────────────────────────────────────────────────────────────────
def test_split_and_build():
    tmp = tempfile.mkdtemp()
    try:
        camp = _camp(tmp)
        sheets = ps.Sheets(camp)
        rec = _pc("Sabalath", col=3, row=4)
        rec["stats"]["hp_cur"] = 6
        rec["spell_slots_cur"] = [0, 0, 0, 0, 0, 0, 0, 0, 0]
        rec["stats"]["ac"] = 16                               # new armor: a sheet change
        play = ps.play_state(rec, "sabalath")
        assert play[ps.SHEET_TAG] == "sabalath" and "weapons" not in play
        assert play["stats"] == {"hp_cur": 6} and (play["col"], play["row"]) == (3, 4)
        sheet = ps.sheet_from(rec, sheets.get("sabalath"))
        assert sheet["stats"]["ac"] == 16 and sheet["stats"]["hp_cur"] == 20
        assert (sheet["col"], sheet["row"]) == (5, 5)         # the sheet's own cell kept
        assert ps.build(sheet, play) == rec
        # A smaller sheet clamps what the run had left.
        small = _pc("Sabalath", hp=4)
        small["spell_slots_max"] = [1, 0, 0, 0, 0, 0, 0, 0, 0]
        back = ps.build(small, ps.play_state(_pc("Sabalath"), "sabalath"))
        assert back["stats"]["hp_cur"] == 4 and back["spell_slots_cur"][0] == 1
    finally:
        shutil.rmtree(tmp)
    print("  ✅ record → sheet + play state → record; HP and slots clamp to the sheet")


def test_expand_collapse():
    tmp = tempfile.mkdtemp()
    try:
        camp = _camp(tmp)
        sheets = ps.Sheets(camp)
        old = _pc("Sabalath", col=1, row=1)
        old["stats"].update(hp_cur=3, ac=99)                  # an old run's full record
        doc = {"agents": [old, {"name": "Goblin", "faction": 1, "stats": {}},
                          _pc("Nobody")],
               "map_items": [], "active_conditions": []}
        built = ps.expand(doc, sheets)
        sab = built["agents"][0]
        assert sab["stats"]["ac"] == 14 and sab["stats"]["hp_cur"] == 3   # sheet wins
        assert built["agents"][1:] == doc["agents"][1:]       # no sheet ⇒ as it is
        assert doc["agents"][0]["stats"]["ac"] == 99          # input untouched

        section, wrote = ps.collapse(built, sheets)
        assert wrote == [] and section["agents"][0][ps.SHEET_TAG] == "sabalath"
        assert "weapons" not in section["agents"][0] and "weapons" in section["agents"][2]
        built["agents"][0]["stats"]["hp_max"] = 30
        section, wrote = ps.collapse(built, sheets)
        assert wrote == ["sabalath"] and _read(camp.pc_path("Sabalath"))["stats"]["hp_max"] == 30
        assert ps.expand(section, sheets)["agents"][0] == built["agents"][0]

        # Under a condition, or Hasted: held whole, sheet untouched.
        cond = {**built, "active_conditions": [{"agent_idx": 0, "name": "Aided"}]}
        cond["agents"][0]["stats"]["hp_max"] = 35
        section, wrote = ps.collapse(cond, sheets)
        assert wrote == [] and section["agents"][0][ps.WHOLE_TAG] is True
        assert ps.expand(section, sheets)["agents"][0] == cond["agents"][0]
        hasted = json.loads(json.dumps(built))
        hasted["agents"][0]["stats"]["hasted"] = True
        assert ps.collapse(hasted, sheets)[0]["agents"][0][ps.WHOLE_TAG] is True
        assert _read(camp.pc_path("Sabalath"))["stats"]["hp_max"] == 30
        # write=False (D4: the sheet wins) stores play state and leaves the sheet alone.
        section, wrote = ps.collapse({"agents": [_pc("Sabalath", hp=50)]}, sheets, write=False)
        assert wrote == [] and ps.SHEET_TAG in section["agents"][0]
        assert _read(camp.pc_path("Sabalath"))["stats"]["hp_max"] == 30
    finally:
        shutil.rmtree(tmp)
    print("  ✅ runs hold play state; sheets written on change; unsettled PCs held whole")


def test_party_and_arrivals():
    tmp = tempfile.mkdtemp()
    try:
        camp = _camp(tmp)
        sheets = ps.Sheets(camp)
        assert ps.party_slugs(sheets, None, None, None) == ["java-of-the-indies", "sabalath"]
        assert ps.party_slugs(sheets, None, ["Sabalath", "Ghost"], []) == ["sabalath"]
        assert ps.party_slugs(sheets, [], ["Sabalath"]) == []
        run = rs.new_run("hall")
        rs.set_creatures(run, "hall", {"agents": [ps.play_state(_pc("Sabalath"), "sabalath")]})
        assert ps.present_slugs(run) == {"sabalath"}
        recs = ps.arrivals(sheets, ["sabalath", "java-of-the-indies"], [[1, 1], [2, 1]],
                           occupied=[(1, 1)])
        assert [(r["col"], r["row"], r["on_deck"]) for r in recs] == [(2, 1, False),
                                                                     (5, 5, True)]
        assert all(r["land_near"] for r in recs)
    finally:
        shutil.rmtree(tmp)
    print("  ✅ party: run > dungeon > campaign > every sheet; arrivals staged, else on deck")


def test_new_dungeon_run_holds_play_state():
    tmp = tempfile.mkdtemp()
    try:
        art = os.path.join(tmp, "hall.png")
        with open(art, "wb") as f:
            f.write(b"art")
        roster = {"agents": [_pc("Sabalath", col=2, row=2),
                             {"name": "Goblin", "faction": 1, "col": 4, "row": 4}]}
        root = os.path.join(tmp, "C")
        out = ci.new_dungeon(root, "Hall", ci.Scene(art, {"manual_grid": GRID}, roster))
        sec = rs.load_run(out.layout.run_path())["maps"][out.map_name]
        assert sec["agents"][0][ps.SHEET_TAG] == "sabalath"
        assert "weapons" not in sec["agents"][0] and sec["agents"][1]["name"] == "Goblin"
        # A second dungeon whose map has a stronger Sabalath: the sheet wins (D4), the
        # map's cell and HP are this run's play state.
        roster["agents"][0]["stats"].update(hp_max=99, hp_cur=99)
        out = ci.new_dungeon(root, "Hall", ci.Scene(art, {"manual_grid": GRID}, roster))
        assert out.pcs_kept == ["Sabalath"]
        sheet = _read(sl.Campaign(root).pc_path("Sabalath"))
        assert sheet["stats"]["hp_max"] == 20
        sec = rs.load_run(out.layout.run_path())["maps"][out.map_name]
        built = ps.expand(sec, ps.Sheets(sl.Campaign(root)))["agents"][0]
        assert built["stats"]["hp_cur"] == 20 and (built["col"], built["row"]) == (2, 2)
    finally:
        shutil.rmtree(tmp)
    print("  ✅ new_dungeon: the run keeps PCs' play state, the sheet wins")


# ── Headless App ─────────────────────────────────────────────────────────────
def _png(path):
    surf = pygame.Surface((COLS * CELL, ROWS * CELL))
    surf.fill((200, 195, 185))
    pygame.image.save(surf, path)


def _dungeon(camp, name, staging=None, party=None):
    dl = camp.dungeon(name)
    os.makedirs(dl.root)
    dung = Dungeon.single_map("hall", COLS, ROWS)
    dung.pages[0].staging_cells = staging
    dung.party = party
    dung.save(dl.manifest_path)
    return dl


def _open(path):
    png, manifest = app_main.resolve_start_path(path)
    app = App(png, seed=1)
    app._on_open_dungeon_chosen(manifest)
    return app


def _by_name(app):
    out = {}
    for i, pt in enumerate(app.bm.placed_agents):
        out[pt.name] = (i, pt)
    return out


def test_app_party_follows():
    tmp = tempfile.mkdtemp(prefix="pc_sheets_")
    try:
        camp = _camp(tmp)
        lib = camp.library_map_dir("hall")
        os.makedirs(lib)
        _png(os.path.join(lib, "hall.png"))
        _write(os.path.join(lib, sl.MAP_FILE), {"regions": [], "walls_enabled": False,
                                                "manual_grid": GRID, "doors": []})
        a = _dungeon(camp, "a", staging=[[1, 1], [2, 1]])
        b = _dungeon(camp, "b")
        c = _dungeon(camp, "c", party=["Sabalath"])

        app = _open(a.manifest_path)
        pcs = _by_name(app)
        assert sorted(pcs) == ["Java of the Indies", "Sabalath"]
        cells = {(pt.origin.col, pt.origin.row) for _, pt in pcs.values()}
        assert cells == {(1, 1), (2, 1)}
        assert not any(app.bm.is_agent_on_deck(i) for i, _ in pcs.values())
        sec = rs.load_run(a.run_path())["maps"]["hall"]
        assert all(r[ps.SHEET_TAG] and "weapons" not in r for r in sec["agents"])

        i = pcs["Sabalath"][0]
        s = app.combat.get_agent_stats(app.bm, i)
        s.hp_max, s.hp_cur = 25, 7
        app.combat.set_agent_stats(app.bm, i, s)
        app._save_agents()
        assert _read(camp.pc_path("Sabalath"))["stats"]["hp_max"] == 25
        assert _read(camp.pc_path("Sabalath"))["stats"]["hp_cur"] == 20

        other = _open(b.manifest_path)                     # no staging: on deck
        pcs = _by_name(other)
        assert sorted(pcs) == ["Java of the Indies", "Sabalath"]
        assert all(other.bm.is_agent_on_deck(i) for i, _ in pcs.values())
        s = other.combat.get_agent_stats(other.bm, pcs["Sabalath"][0])
        assert (s.hp_max, s.hp_cur) == (25, 20)

        again = _open(a.manifest_path)
        i = _by_name(again)["Sabalath"][0]
        s = again.combat.get_agent_stats(again.bm, i)
        assert (s.hp_max, s.hp_cur) == (25, 7)
        s.hasted = True
        again.combat.set_agent_stats(again.bm, i, s)
        again._save_agents()
        rec = next(r for r in rs.load_run(a.run_path())["maps"]["hall"]["agents"]
                   if r["name"] == "Sabalath")
        assert rec[ps.WHOLE_TAG] is True and "weapons" in rec

        only = _open(c.manifest_path)
        assert sorted(_by_name(only)) == ["Sabalath"]
    finally:
        shutil.rmtree(tmp)
    print("  ✅ App: party arrives, run keeps play state, max HP follows to another dungeon")


def main():
    pygame.init()
    tests = [test_split_and_build, test_expand_collapse, test_party_and_arrivals,
             test_new_dungeon_run_holds_play_state, test_app_party_follows]
    print("Running PC sheet tests…")
    for t in tests:
        t()
    print(f"\n✅ All {len(tests)} PC sheet tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
