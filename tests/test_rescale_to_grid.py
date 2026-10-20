#!/usr/bin/env python3
"""tools/rescale_to_grid.py: re-render page images so drawn squares are whole pixels.

  · it measures the drawn square per axis (31.5 × 32.4 here, nominal 32);
  · with --apply the page's squares come out 32 × 32, rendered from the original image;
  · the anchor's cell index is kept, so edge edits still name the same squares;
  · everything it replaces is copied to pre_rescale/ first;
  · without --apply nothing is written; a page that already fits is left alone;
  · an original image (foo.png beside foo_32px.png) is never rescaled itself;
  · in the game, Terrain… → Rescale Image to Grid… does the same and reloads the map.
"""

import json
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "tools"))

from PIL import Image, ImageDraw

import rescale_to_grid as rg

CELL = 16
SQUARE_FT = 10                       # 2 × 2 cells per drawn square, nominal 32 px
PAPER, INK = (205, 200, 190), (60, 60, 60)


def _grid_png(path, w, h, px, py, x0, y0):
    """Paper with 1-px dark lines every ``px`` / ``py`` from (x0, y0), plus a dark room."""
    img = Image.new("RGB", (w, h), PAPER)
    d = ImageDraw.Draw(img)
    x = x0
    while x < w:
        d.line([(round(x), 0), (round(x), h - 1)], fill=INK)
        x += px
    y = y0
    while y < h:
        d.line([(0, round(y)), (w - 1, round(y))], fill=INK)
        y += py
    d.rectangle([w // 3, h // 3, w // 2, h // 2], outline=INK, width=4)
    img.save(path)


def _dungeon(tmp, fit=False):
    """A one-page dungeon: original foo.png (2/3 size) and foo_32px.png = its resize."""
    px, py = (32.0, 32.0) if fit else (31.5, 32.4)
    x0, y0 = 10.0, 7.0
    _grid_png(os.path.join(tmp, "foo_32px.png"), 900, 700, px, py, x0, y0)
    big = Image.open(os.path.join(tmp, "foo_32px.png"))
    # The "original": the same drawing at another size; the page image is its resize.
    big.resize((1350, 1050), Image.LANCZOS).save(os.path.join(tmp, "foo.png"))
    Image.open(os.path.join(tmp, "foo.png")).resize((900, 700), Image.LANCZOS) \
        .save(os.path.join(tmp, "foo_32px.png"))
    anchor = [int(round(x0 + 10 * px)), int(round(y0 + 6 * py))]     # a drawn line
    terrain = {"regions": [], "walls_enabled": True,
               "manual_grid": {"cell_px": CELL, "anchor": anchor, "square_ft": SQUARE_FT},
               "edge_overrides": {"add": [[20, 12, "E"]], "remove": []}}
    with open(os.path.join(tmp, "foo_terrain.json"), "w") as f:
        json.dump(terrain, f)
    manifest = os.path.join(tmp, "foo.dungeon.json")
    with open(manifest, "w") as f:
        json.dump({"version": 1, "entry_page_id": "foo", "pages": [
            {"id": "foo", "png": "foo_32px.png", "encounter_base": "foo_agents.json",
             "origin": [0, 0, 0], "cols": 55, "rows": 43}]}, f)
    return manifest, anchor


def _page(manifest):
    with open(manifest) as f:
        return json.load(f)["pages"][0]


def test_measures_each_axis():
    with tempfile.TemporaryDirectory() as tmp:
        manifest, _ = _dungeon(tmp)
        plan = rg.plan_page(tmp, _page(manifest))
        px, py = plan["period"]
        assert abs(px - 31.5) < 0.1 and abs(py - 32.4) < 0.1, (px, py)
    print("✅ test_measures_each_axis passed")


def test_apply_makes_whole_squares_and_keeps_indices():
    with tempfile.TemporaryDirectory() as tmp:
        manifest, anchor = _dungeon(tmp)
        rg.main([manifest, "--apply"])
        with open(os.path.join(tmp, "foo_terrain.json")) as f:
            doc = json.load(f)
        new_anchor = doc["manual_grid"]["anchor"]
        assert [a // CELL for a in new_anchor] == [a // CELL for a in anchor], \
            (anchor, new_anchor)
        assert doc["edge_overrides"]["add"] == [[20, 12, "E"]], "edits untouched"
        plan = rg.plan_page(tmp, _page(manifest))
        px, py = plan["period"]
        assert abs(px - 32) < 0.1 and abs(py - 32) < 0.1, (px, py)
        for fn in ("foo_32px.png", "foo_terrain.json", "foo.dungeon.json"):
            assert os.path.exists(os.path.join(tmp, "pre_rescale", fn)), fn
        page = _page(manifest)
        w, h = Image.open(os.path.join(tmp, "foo_32px.png")).size
        assert page["cols"] == (w - new_anchor[0] % CELL) // CELL
        assert page["rows"] == (h - new_anchor[1] % CELL) // CELL
    print("✅ test_apply_makes_whole_squares_and_keeps_indices passed")


def test_report_only_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        manifest, _ = _dungeon(tmp)
        before = open(os.path.join(tmp, "foo_32px.png"), "rb").read()
        rg.main([manifest])
        assert open(os.path.join(tmp, "foo_32px.png"), "rb").read() == before
        assert not os.path.exists(os.path.join(tmp, "pre_rescale"))
    print("✅ test_report_only_writes_nothing passed")


def test_a_page_that_fits_is_left_alone():
    with tempfile.TemporaryDirectory() as tmp:
        manifest, _ = _dungeon(tmp, fit=True)
        before = open(os.path.join(tmp, "foo_32px.png"), "rb").read()
        rg.main([manifest, "--apply"])
        assert open(os.path.join(tmp, "foo_32px.png"), "rb").read() == before
    print("✅ test_a_page_that_fits_is_left_alone passed")


def test_an_original_is_not_rescaled():
    with tempfile.TemporaryDirectory() as tmp:
        _dungeon(tmp)
        p = rg.grid_rescale.plan(os.path.join(tmp, "foo.png"),
                                 os.path.join(tmp, "foo_terrain.json"))
        assert "original of foo_32px.png" in p.get("skip", ""), p
    print("✅ test_an_original_is_not_rescaled passed")


def test_from_the_terrain_menu():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    sys.path.insert(0, os.path.join(_ROOT, "gui"))
    from main import App
    from menus import dm
    with tempfile.TemporaryDirectory() as tmp:
        manifest, anchor = _dungeon(tmp)
        os.remove(manifest)                     # a plain map: no dungeon around it
        png = os.path.join(tmp, "foo_32px.png")
        os.replace(os.path.join(tmp, "foo_terrain.json"),
                   os.path.join(tmp, "foo_32px_terrain.json"))
        app = App(png, seed=1)
        app._load_terrain()
        assert app._manual_grid
        seen = {}
        app._ask_dm = lambda kind, title, items, **kw: seen.setdefault(title, items)
        dm.show_terrain_menu(app)
        labels = [label for label, _fn in seen.pop("Terrain")]
        assert "Rescale Image to Grid…" in labels
        app._rescale_image_to_grid()
        (title, items), = seen.items()
        assert title.startswith("Squares 31.") and items[-1][0] == "Cancel", title
        items[0][1]()                             # "Rescale image ×…"
        new_anchor = app._manual_grid["anchor"]
        assert [a // CELL for a in new_anchor] == [a // CELL for a in anchor]
        assert Image.open(png).size != (900, 700), "the image was re-rendered"
        assert os.path.exists(os.path.join(tmp, "pre_rescale", "foo_32px.png"))
        assert app._edge_overrides["add"] == [[20, 12, "E"]], "edits reloaded intact"
    print("✅ test_from_the_terrain_menu passed")


def main():
    tests = [test_measures_each_axis,
             test_apply_makes_whole_squares_and_keeps_indices,
             test_report_only_writes_nothing,
             test_a_page_that_fits_is_left_alone,
             test_an_original_is_not_rescaled,
             test_from_the_terrain_menu]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n❌ test_rescale_to_grid: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_rescale_to_grid: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
