#!/usr/bin/env python3
"""The masked page image (MULTIPLAYER_PLAN.md D-M4-1, frozen 2026-09-23).

``GET /map.png`` is the one place in the protocol where the map arrives as *art* rather
than as fields, so it is the one place D-M3-5's filtering can be undone by accident: a
verbatim page PNG hands a player the floor plan of the wing the party has not entered.
These checks read **pixels**, for the same reason ``test_gameview.py`` reads bytes — a
client that cheats does not look at the screen, it looks at what it was sent.

The scene every check shares — a 200×150 page whose grid lines are deliberately uneven
and inset, so a render that quietly assumed square cells or a full-bleed grid fails here:

    v_lines = (10, 40, 90, 160, 195)      4 columns, margins at both ends
    h_lines = (5, 30, 100, 140)           3 rows, margins at both ends
    explored = {(0, 0), (1, 0)}           the top-left strip, and nothing else

The art is a high-contrast floor plan — near-black walls on near-white floor — because
that is the picture a 4%-transparent fog gives back under a contrast stretch.

Covered here:
  · an unexplored cell is one opaque colour, with no art in it   (test_unexplored_is_one_flat_colour)
  · ...and FOG_COL's alpha 245 would have leaked the plan        (test_fog_col_alpha_would_have_leaked)
  · an explored cell is the source art, pixel for pixel          (test_explored_cells_are_verbatim)
  · cell edges land on the raw line px, unscaled                 (test_geometry_is_raw_image_px)
  · every viewer is served the grid, with no margin              (test_the_served_image_is_the_grid)
  · ...so the client's stretch lands each outer line on its own  (test_the_stretch_lands_on_the_lattice)
  · a cell the line lists cannot describe stays masked           (test_undescribable_cell_stays_masked)
  · an all-opaque alpha channel is dropped from the wire         (test_opaque_alpha_is_dropped)
  · ...but art that really is translucent keeps it              (test_real_transparency_survives)
  · the DM gets the page's own pixels, cropped to the grid       (test_dm_gets_the_page_unmasked)
  · ...and a page whose grid fills it is the file's own bytes    (test_a_full_bleed_grid_is_served_verbatim)
  · fog down serves everyone the DM's image                      (test_fog_down_serves_the_unmasked_page)
  · the key is party-scoped and moves with the mask              (test_key_is_party_scoped_and_moves_with_the_mask)
  · ...and with the render itself, or a 304 keeps the old one    (test_a_new_render_is_a_new_key)
  · two cache entries, not one per viewer                        (test_cache_holds_two_entries_not_one_per_viewer)
  · the cache follows the newest published mask                  (test_cache_follows_the_newest_published_mask)
  · the image key lags on purpose, and a boundary re-keys        (test_the_image_key_lags_on_purpose)
  · ...and the lag is only ever extra fog, never a leak          (test_the_lag_is_only_ever_extra_fog)
"""

import io
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

from PIL import Image, ImageDraw, ImageOps

from net import mapimg
from net.mapimg import IMAGE_LAG_S, MapImageCache, PageImage

W, H = 200, 150
V_LINES = (10, 40, 90, 160, 195)
H_LINES = (5, 30, 100, 140)
EXPLORED = frozenset({(0, 0), (1, 0)})

FLOOR = (246, 244, 238)
WALL  = (12, 10, 9)


def _page_png(path, mode="RGB", translucent=None):
    """A floor plan with structure in every cell, explored or not."""
    im = Image.new(mode, (W, H), FLOOR if mode == "RGB" else (*FLOOR, 255))
    d = ImageDraw.Draw(im)
    for x in range(0, W, 7):
        d.line([(x, 0), (x, H)], fill=WALL, width=2)
    for y in range(0, H, 11):
        d.line([(0, y), (W, y)], fill=WALL, width=2)
    if translucent is not None:
        im.putpixel(translucent, (*FLOOR, 60))
    im.save(path, format="PNG")
    return im


def _scene(tmpdir, explored=EXPLORED, fog_on=True, v=V_LINES, h=H_LINES,
           mode="RGB", translucent=None):
    path = os.path.join(tmpdir, "page.png")
    art = _page_png(path, mode=mode, translucent=translucent)
    page = PageImage(path=path, cols=len(v) - 1, rows=len(h) - 1,
                     v_lines=v, h_lines=h,
                     explored=frozenset(explored), fog_on=fog_on)
    return art, page


def _run(check, **kw):
    with tempfile.TemporaryDirectory() as tmp:
        check(*_scene(tmp, **kw), tmp)


def _open(data):
    im = Image.open(io.BytesIO(data))
    im.load()
    return im


def _wider(page, cell=(2, 0)):
    """The same page with one more cell earned."""
    return PageImage(path=page.path, cols=page.cols, rows=page.rows,
                     v_lines=page.v_lines, h_lines=page.h_lines,
                     explored=page.explored | {cell}, fog_on=page.fog_on)


def _cell_box(page, col, row):
    """A cell in the *source* page's px."""
    return (page.v_lines[col], page.h_lines[row],
            page.v_lines[col + 1], page.h_lines[row + 1])


def _served_box(page, col, row):
    """The same cell in the *served* image's px, which starts at the first grid lines."""
    x0, y0, x1, y1 = _cell_box(page, col, row)
    ox, oy = page.v_lines[0], page.h_lines[0]
    return (x0 - ox, y0 - oy, x1 - ox, y1 - oy)


# ─────────────────────────────────────────────────────────────────────────────
#  What the fog has to hide
# ─────────────────────────────────────────────────────────────────────────────

def test_unexplored_is_one_flat_colour():
    """An unexplored cell carries no information at all — not faint information.

    ``getcolors`` over the cell must find exactly one colour. A render that painted a
    translucent fog passes a "looks dark" eyeball check and fails this one.
    """
    def check(_art, page, _tmp):
        out = _open(mapimg.render(page, is_dm=False))
        assert out.mode in ("RGB", "RGBA"), out.mode
        for col, row in ((2, 0), (0, 1), (3, 2)):
            cell = out.crop(_served_box(page, col, row))
            colours = cell.getcolors(maxcolors=1 << 16)
            assert len(colours) == 1, f"cell {(col, row)} carries {len(colours)} colours"
            assert colours[0][1][:3] == mapimg.MASK_RGB, colours[0]
            if out.mode == "RGBA":
                assert colours[0][1][3] == 255, "the mask must be opaque (alpha 255)"
    _run(check)
    print("✅ test_unexplored_is_one_flat_colour")


def test_fog_col_alpha_would_have_leaked():
    """The trap D-M4-1 exists to name, made into a failing counter-example.

    ``main.py``'s ``FOG_COL`` is ``(24, 24, 28, 245)``. This composites the same fog at
    that alpha, stretches the contrast the way anyone looking at their own traffic would,
    and shows the floor plan coming back. The frozen mask, given the identical treatment,
    stays a single flat value — which is the assertion that would fail the day someone
    "reuses the existing constant".
    """
    def check(art, page, _tmp):
        box = _cell_box(page, 2, 0)          # never explored, structure underneath
        served = _served_box(page, 2, 0)

        leaky = Image.blend(art.convert("RGB"),
                            Image.new("RGB", art.size, mapimg.MASK_RGB),
                            245 / 255).crop(box)
        # `tobytes()` rather than `getdata()`: one byte per px in "L", and the container's
        # Pillow deprecates the latter.
        recovered = ImageOps.autocontrast(leaky.convert("L")).tobytes()
        assert len(set(recovered)) > 1, \
            "the counter-example did not leak; the test no longer proves anything"
        assert max(recovered) - min(recovered) > 200, \
            "a contrast stretch should bring the plan most of the way back"

        honest = ImageOps.autocontrast(
            _open(mapimg.render(page, is_dm=False)).convert("L").crop(served)).tobytes()
        assert len(set(honest)) == 1, "the masked render gave art back"
    _run(check)
    print("✅ test_fog_col_alpha_would_have_leaked")


def test_explored_cells_are_verbatim():
    """What the party has earned arrives untouched — the mask is not a filter over the
    whole page, and a re-encode may not resample the art it keeps."""
    def check(art, page, _tmp):
        out = _open(mapimg.render(page, is_dm=False)).convert("RGB")
        for col, row in sorted(EXPLORED):
            box = _cell_box(page, col, row)
            assert out.crop(_served_box(page, col, row)).tobytes() \
                == art.convert("RGB").crop(box).tobytes(), \
                f"explored cell {(col, row)} was altered"
    _run(check)
    print("✅ test_explored_cells_are_verbatim")


def test_geometry_is_raw_image_px():
    """Cell edges land exactly on ``v_lines`` / ``h_lines``.

    ``map_scale`` is screen space and has no meaning on the wire (D-M4-1). The lines here
    are uneven on purpose: a render that multiplied by any scale, or that recomputed cells
    from ``cell_pixel_size``, puts these four probes on the wrong side of a boundary.
    """
    def check(_art, page, _tmp):
        out = _open(mapimg.render(page, is_dm=False)).convert("RGB")
        x0, y0, x1, y1 = _served_box(page, 1, 0)    # explored
        assert out.getpixel((x0, y0)) != mapimg.MASK_RGB, "first px of a seen cell is fog"
        assert out.getpixel((x1 - 1, y1 - 1)) != mapimg.MASK_RGB, "last px of a seen cell is fog"
        assert out.getpixel((x1, y0)) == mapimg.MASK_RGB, "the fog starts a px late"
        assert out.getpixel((x0, y1)) == mapimg.MASK_RGB, "the fog starts a row late"
    _run(check)
    print("✅ test_geometry_is_raw_image_px")


def test_the_served_image_is_the_grid():
    """Nobody is sent the margins (owed item 11).

    The client stretches the image onto its ``cols * cell_px`` lattice, so a margin in the
    image is a margin in the stretch and every cell lands off its art. The served image is
    exactly the rectangle between the outermost lines, and its corners are the grid's
    corners in the source — for the masked render and the DM's alike.
    """
    def check(art, page, _tmp):
        want = (V_LINES[-1] - V_LINES[0], H_LINES[-1] - H_LINES[0])
        dm = _open(mapimg.render(page, is_dm=True)).convert("RGB")
        player = _open(mapimg.render(page, is_dm=False)).convert("RGB")
        assert dm.size == want, f"the DM was sent {dm.size}, the grid is {want}"
        assert player.size == want, f"a player was sent {player.size}, the grid is {want}"
        grid = art.convert("RGB").crop((V_LINES[0], H_LINES[0], V_LINES[-1], H_LINES[-1]))
        assert dm.tobytes() == grid.tobytes(), "the DM's crop is not the grid's pixels"
    _run(check)
    print("✅ test_the_served_image_is_the_grid")


def test_the_stretch_lands_on_the_lattice():
    """What the client does with the image, done here with the numbers from the page
    that found this: ``TestDNDMap.png``, 1298x1003, a 20x16 grid at nominal 50 px.

    ``app.js`` draws the image into ``cols * cell_px`` by ``rows * cell_px`` and places
    cell *n* at ``n * cell_px``. Stretching the whole page put the right-hand column 3.7
    cells from its art; stretching the served image may put no line further off than the
    grid's own spacing jitter. The line lists are the ones ``analyze_grid`` reports.
    """
    v = (58, 108, 159, 209, 259, 308, 358, 408, 458, 508, 558, 608, 658, 708, 758, 808,
         858, 910, 958, 1008, 1057)
    h = (89, 138, 188, 237, 288, 338, 388, 438, 487, 537, 588, 637, 688, 738, 788, 837, 887)
    size, cell = (1298, 1003), 50
    page = PageImage(path="", cols=len(v) - 1, rows=len(h) - 1, v_lines=v, h_lines=h,
                     explored=frozenset(), fog_on=True)
    left, top, right, bottom = mapimg.grid_box(page, size)

    def worst(lines, lo, hi, n):
        """Furthest any line lands from ``i * cell`` when ``lo..hi`` is stretched to
        ``n * cell``."""
        k = n * cell / (hi - lo)
        return max(abs((x - lo) * k - i * cell) for i, x in enumerate(lines))

    for lines, lo, hi, span, n in ((v, left, right, size[0], page.cols),
                                   (h, top, bottom, size[1], page.rows)):
        whole = worst(lines, 0, span, n)
        assert whole > cell, f"the counter-example no longer shows the bug ({whole:.0f} px)"
        cropped = worst(lines, lo, hi, n)
        assert cropped < 3, f"a line lands {cropped:.1f} px from its lattice position"
    print("✅ test_the_stretch_lands_on_the_lattice")


def test_undescribable_cell_stays_masked():
    """An explored cell with no line pair to place it is dropped, not guessed at.

    ``_draw_fog_overlay`` breaks out of the loop in the same case. Here the mask is the
    default, so the failure mode is extra fog rather than a rectangle drawn at coordinates
    nobody verified.
    """
    def check(_art, page, _tmp):
        out = _open(mapimg.render(page, is_dm=False)).convert("RGB")
        assert out.getpixel((1, 1)) != mapimg.MASK_RGB
        colours = out.getcolors(maxcolors=1 << 16)
        assert any(c[1] == mapimg.MASK_RGB for c in colours), "nothing was masked at all"
    _run(check, explored=frozenset({(0, 0), (9, 9), (-1, 0)}))
    print("✅ test_undescribable_cell_stays_masked")


def test_opaque_alpha_is_dropped():
    """A page whose alpha channel is 255 everywhere — which is every page in this tree —
    is served without it.

    A quarter of the bytes and a sixth of the encode, carrying nothing. The art must come
    back unchanged, which is the half of this that could go wrong.
    """
    def check(art, page, _tmp):
        out = _open(mapimg.render(page, is_dm=False))
        assert out.mode == "RGB", out.mode
        assert out.crop(_served_box(page, 0, 0)).tobytes() \
            == art.convert("RGB").crop(_cell_box(page, 0, 0)).tobytes()
    _run(check, mode="RGBA")
    print("✅ test_opaque_alpha_is_dropped")


def test_real_transparency_survives():
    """A page that actually uses its alpha keeps it, and the fog stays opaque regardless.

    The drop above is an optimization on a channel that says nothing; it may not become a
    flatten that discards art. The masked cells are alpha 255 in the same image — a client
    compositing this over anything must not see through the fog.
    """
    def check(_art, page, _tmp):
        seen = _served_box(page, 0, 0)
        out = _open(mapimg.render(page, is_dm=False))
        assert out.mode == "RGBA", out.mode
        assert out.getpixel((seen[0] + 1, seen[1] + 1))[3] == 60, "the art's alpha was lost"
        hidden = _served_box(page, 2, 0)
        assert out.getpixel((hidden[0] + 1, hidden[1] + 1)) == (*mapimg.MASK_RGB, 255)
    _run(check, mode="RGBA", translucent=(V_LINES[0] + 1, H_LINES[0] + 1))
    print("✅ test_real_transparency_survives")


# ─────────────────────────────────────────────────────────────────────────────
#  Who gets what
# ─────────────────────────────────────────────────────────────────────────────

def test_dm_gets_the_page_unmasked():
    """The DM's entitlement is the whole grid: every px of it, in the page's own mode, and
    no fog. Cropping is the only thing done to it, and PNG is lossless, so this compares
    pixels with the source rather than bytes with the file."""
    def check(art, page, _tmp):
        out = _open(mapimg.render(page, is_dm=True))
        assert out.mode == art.mode, f"the DM's image changed mode: {art.mode} -> {out.mode}"
        box = (V_LINES[0], H_LINES[0], V_LINES[-1], H_LINES[-1])
        assert out.tobytes() == art.crop(box).tobytes(), "the DM's image is not the page's"
    _run(check)
    _run(check, mode="RGBA")
    print("✅ test_dm_gets_the_page_unmasked")


def test_a_full_bleed_grid_is_served_verbatim():
    """When the outer lines are the image's edges there is nothing to crop, and the DM
    gets the file's own bytes — no decode, no re-encode — exactly as before item 11."""
    def check(_art, page, _tmp):
        assert mapimg.grid_box(page, (W, H)) is None
        assert mapimg.render(page, is_dm=True) == open(page.path, "rb").read()
    _run(check, v=(0, 50, 120, W), h=(0, 70, H))
    print("✅ test_a_full_bleed_grid_is_served_verbatim")


def test_fog_down_serves_the_unmasked_page():
    """With fog down the DM's own screen is drawing the whole map, so nothing here may
    hide more than it does — the same rule ``build_view`` calls ``hide_map``."""
    def check(_art, page, _tmp):
        assert not page.masked_for(is_dm=False)
        assert mapimg.render(page, is_dm=False) == mapimg.render(page, is_dm=True)
        assert page.key(is_dm=False) == page.key(is_dm=True)
    _run(check, fog_on=False)
    print("✅ test_fog_down_serves_the_unmasked_page")


def test_key_is_party_scoped_and_moves_with_the_mask():
    """One key for every player, a different one for the DM, and a new one the moment the
    party earns a cell.

    The last clause is why the key is the mask hash and not the content hash: the file on
    disk never changes as the party explores, so a content-keyed URL would pin every
    player to the first mask their browser cached.
    """
    def check(_art, page, tmp):
        player_key = page.key(is_dm=False)
        assert player_key != page.key(is_dm=True), "the DM and a player share a key"
        assert player_key == page.key(is_dm=False), "the key is not stable"

        wider = _wider(page)
        assert wider.key(is_dm=False) != player_key, "a newly explored cell kept the key"
        assert wider.key(is_dm=True) == page.key(is_dm=True), \
            "the DM's key moved for a mask the DM does not have"
    _run(check)
    print("✅ test_key_is_party_scoped_and_moves_with_the_mask")


def test_a_new_render_is_a_new_key():
    """Both keys hash the render's inputs, so a change to the render itself must still move
    them — or a client holding the old picture asks `If-None-Match`, gets a 304 for the same
    key, and keeps it. That is how the crop first reached a phone and was not seen: same
    mask, same key, the stretched page kept. ``_RENDER_REV`` is the lever, and this checks
    it reaches both keys."""
    def check(_art, page, _tmp):
        before = (page.key(is_dm=False), page.key(is_dm=True))
        saved = mapimg._RENDER_REV
        try:
            mapimg._RENDER_REV = saved + "+next"
            fresh = PageImage(path=page.path, cols=page.cols, rows=page.rows,
                              v_lines=page.v_lines, h_lines=page.h_lines,
                              explored=page.explored, fog_on=page.fog_on)
            after = (fresh.key(is_dm=False), fresh.key(is_dm=True))
        finally:
            mapimg._RENDER_REV = saved
        assert after[0] != before[0], "a new render kept the player's key"
        assert after[1] != before[1], "a new render kept the DM's key"
    _run(check)
    print("✅ test_a_new_render_is_a_new_key")


# ─────────────────────────────────────────────────────────────────────────────
#  The cache
# ─────────────────────────────────────────────────────────────────────────────

def test_cache_holds_two_entries_not_one_per_viewer():
    """Fog is party-scoped (Step 0.1), so a table of six players costs one render."""
    def check(_art, page, _tmp):
        cache = MapImageCache()
        cache.publish(page)
        first = cache.png(is_dm=False)
        for _ in range(5):
            assert cache.png(is_dm=False) == first
        cache.png(is_dm=True)
        assert cache.renders == 2, f"{cache.renders} renders for six players and a DM"
    _run(check)
    print("✅ test_cache_holds_two_entries_not_one_per_viewer")


def test_cache_follows_the_newest_published_mask():
    """Once a snapshot is published, the renders the cache hands out are that mask's.

    Staleness is safe in exactly one direction (D-M4-1): the older render is the *foggier*
    one, and this check reads the disputed cell in both to say so rather than comparing
    keys and hoping.
    """
    def check(_art, page, _tmp):
        cache = MapImageCache()
        cache.publish(page, now=0.0)
        old_key, old_png = cache.png(is_dm=False)

        cache.publish(_wider(page), now=IMAGE_LAG_S + 1)
        new_key, new_png = cache.png(is_dm=False)
        assert new_key != old_key and new_png != old_png, "the cache served the old mask"
        assert cache.renders == 2

        box = _served_box(page, 2, 0)
        assert len(_open(old_png).crop(box).getcolors(1 << 16)) == 1, \
            "the older render was not the foggier one"
        assert len(_open(new_png).crop(box).getcolors(1 << 16)) > 1, \
            "the newly explored cell is still fogged"
    _run(check)
    print("✅ test_cache_follows_the_newest_published_mask")


def test_the_image_key_lags_on_purpose():
    """D-M4-1 as amended: at most one re-key per ``IMAGE_LAG_S``, and always one at a turn
    boundary.

    The lag is what keeps a corridor walk from costing each player a fresh fetch of the
    whole page per step. What it costs is that a just-earned cell reads as dark art until
    the next re-key — which the client can draw fog over, because the view's own fog block
    is live.
    """
    def check(_art, page, _tmp):
        cache = MapImageCache()
        assert cache.publish(page, now=0.0) is page, "the first snapshot must publish at once"
        wider = _wider(page)
        assert cache.publish(wider, now=IMAGE_LAG_S / 2) is page, "the key did not lag"
        assert cache.png(is_dm=False)[0] == page.key(is_dm=False), \
            "the route served a mask the view never named"
        assert cache.publish(wider, now=IMAGE_LAG_S / 2, boundary=True) is wider, \
            "a turn boundary must re-key"
    _run(check)
    print("✅ test_the_image_key_lags_on_purpose")


def test_the_lag_is_only_ever_extra_fog():
    """The three ways a held snapshot stops being *foggier* and becomes *wrong*.

    A page switch shows the party the wrong room. A mask that shrank — a save loaded mid
    session — is not a lag at all. And fog toggled back **on** is the one that matters: the
    held render was made with fog down, so serving it is serving the unmasked page. Each
    must publish immediately, mid-interval, without a boundary to ask for it.
    """
    def check(_art, page, tmp):
        other = os.path.join(tmp, "other.png")
        _page_png(other)
        cases = {
            "a page switch": PageImage(path=other, cols=page.cols, rows=page.rows,
                                       v_lines=page.v_lines, h_lines=page.h_lines,
                                       explored=page.explored, fog_on=True),
            "a mask that shrank": PageImage(path=page.path, cols=page.cols, rows=page.rows,
                                            v_lines=page.v_lines, h_lines=page.h_lines,
                                            explored=frozenset({(0, 0)}), fog_on=True),
        }
        for label, live in cases.items():
            cache = MapImageCache()
            cache.publish(page, now=0.0)
            assert cache.publish(live, now=IMAGE_LAG_S / 2) is live, f"{label} was lagged"

        # Fog down, then up: the held snapshot is the raw page.
        clear = PageImage(path=page.path, cols=page.cols, rows=page.rows,
                          v_lines=page.v_lines, h_lines=page.h_lines,
                          explored=page.explored, fog_on=False)
        cache = MapImageCache()
        cache.publish(clear, now=0.0)
        unmasked = mapimg.render(clear, is_dm=True)
        assert cache.png(is_dm=False)[1] == unmasked
        assert cache.publish(page, now=IMAGE_LAG_S / 2) is page, \
            "fog came back up and the unmasked page stayed published"
        assert cache.png(is_dm=False)[1] != unmasked
    _run(check)
    print("✅ test_the_lag_is_only_ever_extra_fog")


def test_cache_without_a_page_serves_nothing():
    """Before a page is published there is no image, and the route must be able to say so
    rather than serve a stale one from another session."""
    assert MapImageCache().png(is_dm=True) is None
    print("✅ test_cache_without_a_page_serves_nothing")


if __name__ == "__main__":
    test_unexplored_is_one_flat_colour()
    test_fog_col_alpha_would_have_leaked()
    test_explored_cells_are_verbatim()
    test_geometry_is_raw_image_px()
    test_the_served_image_is_the_grid()
    test_the_stretch_lands_on_the_lattice()
    test_undescribable_cell_stays_masked()
    test_opaque_alpha_is_dropped()
    test_real_transparency_survives()
    test_dm_gets_the_page_unmasked()
    test_a_full_bleed_grid_is_served_verbatim()
    test_fog_down_serves_the_unmasked_page()
    test_key_is_party_scoped_and_moves_with_the_mask()
    test_a_new_render_is_a_new_key()
    test_cache_holds_two_entries_not_one_per_viewer()
    test_cache_follows_the_newest_published_mask()
    test_the_image_key_lags_on_purpose()
    test_the_lag_is_only_ever_extra_fog()
    test_cache_without_a_page_serves_nothing()
    print("\nAll map image tests passed! 🎉")
