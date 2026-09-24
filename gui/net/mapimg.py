"""The masked page image behind ``GET /map.png`` (MULTIPLAYER_PLAN.md D-M4-1, frozen
2026-09-23).

``_draw_fog_overlay`` (``main.py:15303``) paints unexplored cells dark on the DM's own
screen, and D-M3-5 already omits unexplored terrain, doors and lighting from the wire.
Serving the page PNG verbatim hands a player the floor plan of the wing the party has not
entered, as a picture — the same leak arriving by a quieter route. So the image is masked
**before** it is served, and never composited on the client: a player who reads their own
traffic would otherwise have the level.

The four rules this module exists to keep, all frozen:

  · **The mask is opaque — alpha 255.** It is deliberately *not* ``main.py``'s
    ``FOG_COL = (24, 24, 28, 245)``. Ten of 255 is ≈4% of the art passing through, which is
    invisible at a glance on a DM screen and recoverable by a contrast stretch on a
    high-contrast floor plan. Reusing the constant is the obvious implementation and it is
    the wrong one; ``MASK_RGB`` shares only its colour, for a fog that looks the same.
  · **Cell geometry is raw image px.** ``v_lines`` / ``h_lines`` are ``BattleMap``'s line
    positions *unscaled*: ``map_scale`` is a screen-space concern with no meaning on the
    wire, and multiplying by it here is how the mask ends up a few pixels off the cells it
    is hiding.
  · **Two cache entries, not one per viewer.** Fog is party-scoped (Step 0.1), so one
    masked render serves every player; the DM gets the page's own pixels, unmasked.
  · **Staleness is safe in exactly one direction.** The explored mask only grows within a
    page, so a render that lags it shows *more* fog than the party has earned, never less.
    That sentence is now load-bearing rather than hypothetical: D-M4-1 was amended
    2026-09-23 to lag the published snapshot on purpose (``IMAGE_LAG_S``), because the
    player's key is the mask hash and a re-key costs a fetch of the whole page.
    ``_lag_is_only_fog()`` is the invariant as code, checked on every publish.

**What is masked is everything not explicitly earned.** The render starts from a fully
opaque sheet and punches out the explored cells, rather than painting rectangles over the
unexplored ones. The two differ on the margins — image area outside the outermost grid
lines, and any cell the line lists are too short to describe — and the punch-out is the
one whose failure mode is extra fog instead of a leaked strip of floor plan.

**Every viewer is served the grid, not the page** (owed item 11, 2026-09-24). The image is
cropped to the outermost grid lines, ``v_lines[0]..v_lines[-1]`` by
``h_lines[0]..h_lines[-1]``, because the client stretches whatever it is sent onto its
nominal ``cols * cell_px`` lattice. Sent the whole page, a margin is stretched along with
the art: ``TestDNDMap.png`` is 1298x1003 with its 20x16 grid at x 58-1057, y 89-887, and the
phone put the right-hand column 3.7 cells from its art. Cropped, the stretch maps the
grid's outer lines onto the lattice's, and what remains is the spacing jitter between lines
— a few px, not cells. The margin was masked for a player anyway; now nobody is sent it.
A page whose grid already fills it is still served as the file's own bytes.

Like ``roster.py`` and unlike ``view.py``, nothing here imports pygame or the extension:
it takes a plain snapshot of cells and line positions, so the net thread can hold it and
do the encode off the frame thread.
"""

from __future__ import annotations

import hashlib
import io
import os
import threading
import time
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

# The DM's fog colour, at the alpha the wire requires. See the module docstring: sharing
# the RGB keeps a player's fog looking like the DM's; sharing the alpha would leak.
MASK_RGB = (24, 24, 28)

# Measured in the container on the largest page in the tree — `wachterhaus.png`,
# 1084x1504, a 98x91 grid, 8918 cells (see the M4 write-up for the table). The encode *is*
# the route's cost: the mask build and the composite together are under 5 ms at every
# exploration level, and Pillow's default level 6 spends 330-430 ms on the same image that
# level 1 encodes in 60-72 ms for 6% more bytes. This route re-encodes on an exploration
# delta, so it buys the time and pays the bytes.
_COMPRESS_LEVEL = 1

_KEY_CHARS = 16

# What ``render`` does to a page, as a name folded into every key. Both keys hash their
# *inputs* — the file, the lines, the mask — so a change to what the render makes of those
# inputs would otherwise keep the key, and a client holding the old picture revalidates it
# (`If-None-Match` -> 304) and keeps it indefinitely. Found by owed item 11's own phone
# check: the crop shipped, and the phone went on showing the stretched page. Change this
# whenever the bytes for the same inputs change.
_RENDER_REV = "grid-crop"

# How long a published mask may lag the live one (D-M4-1, amended 2026-09-23). The player's
# `?v=` is the mask hash, so without this every newly-explored cell costs that player a
# fresh fetch of the whole page — 0.8-2.5 MB on the largest one in this tree. At 3 s the
# worst case is one page per viewer per 3 s while the party is actively exploring, and the
# cost of the lag is that a just-earned cell reads as dark art until the next re-key. A turn
# boundary always re-keys, so the picture is current whenever anyone is about to act.
IMAGE_LAG_S = 3.0


# ── The snapshot ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PageImage:
    """Everything the render needs, frozen at one instant on the pygame thread.

    This is the whole handoff between the two threads. It is immutable and carries no
    reference to ``App`` or ``BattleMap``, so the net thread can render from it while the
    game advances underneath — and the result is stale in the safe direction.
    """

    path: str
    cols: int
    rows: int
    v_lines: tuple[int, ...]
    h_lines: tuple[int, ...]
    explored: frozenset[tuple[int, int]]
    fog_on: bool

    # Memo, not state: `compare=False` keeps it out of equality and out of the generated
    # `__hash__`, so two snapshots of the same mask stay equal. Hashing 8918 explored cells
    # takes ~1.8 ms on the largest page, and both callers — `_map` once per view build and
    # the route once per request — would otherwise pay it every time.
    _keys: dict = field(default_factory=dict, compare=False, repr=False)

    def masked_for(self, is_dm: bool) -> bool:
        """Whether *this* viewer's image hides anything.

        The same rule ``build_view`` calls ``hide_map``: with fog down the DM's own screen
        is drawing the whole map, so nothing here may hide more than it does.
        """
        return bool(self.fog_on) and not is_dm

    def key(self, is_dm: bool) -> str:
        """The ``?v=`` cache key: the mask hash for a player, the content-and-crop hash for
        the DM."""
        masked = self.masked_for(is_dm)
        memo = self._keys.get(masked)
        if memo is None:
            memo = mask_key(self) if masked else raw_key(self)
            self._keys[masked] = memo
        return memo


def _lines_digest(h, page: PageImage) -> None:
    h.update(f"{_RENDER_REV}|".encode())
    h.update(",".join(str(x) for x in page.v_lines).encode())
    h.update(b"|")
    h.update(",".join(str(y) for y in page.h_lines).encode())
    h.update(b"|")


def raw_key(page: PageImage) -> str:
    """Hash the unmasked image: the file *and* the crop, since both decide the bytes."""
    h = hashlib.sha256()
    h.update(content_key(page.path).encode())
    h.update(b"|")
    _lines_digest(h, page)
    return h.hexdigest()[:_KEY_CHARS]


def mask_key(page: PageImage) -> str:
    """Hash the mask, not the image.

    A content hash alone would never change as the party explores, so the masked render
    would cache forever at the first mask it saw. The page's content hash is folded in
    anyway — it is memoized, so it costs nothing — because swapping the art under a page
    of the same name must also change the key.
    """
    h = hashlib.sha256()
    h.update(content_key(page.path).encode())
    h.update(f"|{page.cols}x{page.rows}|".encode())
    _lines_digest(h, page)
    for col, row in sorted(page.explored):
        h.update(f"{col}.{row};".encode())
    return h.hexdigest()[:_KEY_CHARS]


_content_cache: dict[str, tuple[tuple[float, int], str]] = {}


def content_key(path: str) -> str:
    """Hash the page file, memoized on ``(mtime, size)``.

    Called once per view build for a DM viewer and once per mask key, so it may not read a
    3 MB page every time. ``mtime``/``size`` is the ordinary stat-cache bargain: a rewrite
    that preserves both inside one filesystem timestamp tick goes unnoticed, which for a
    map file an author is editing is not a failure anyone can produce on purpose.
    """
    try:
        st = os.stat(path)
    except OSError:
        return ""
    stamp = (st.st_mtime, st.st_size)
    hit = _content_cache.get(path)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    key = h.hexdigest()[:_KEY_CHARS]
    _content_cache[path] = (stamp, key)
    return key


# ── The render ──────────────────────────────────────────────────────────────

def _flat(mode: str, size: tuple[int, int]) -> Image.Image:
    if mode == "L":
        return Image.new(mode, size, int(sum(MASK_RGB) / 3))
    if mode == "RGBA":
        return Image.new(mode, size, (*MASK_RGB, 255))
    return Image.new(mode, size, MASK_RGB)


def grid_box(page: PageImage, size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    """The outermost grid lines as a crop box, or ``None`` when there is nothing to crop.

    Right and bottom are exclusive, the same convention as the cell rectangles in
    ``render``: cell *c* is ``v[c] .. v[c+1] - 1``, so the last line's own px is not the
    grid's. ``None`` covers both a page whose grid fills it and line lists too short to
    describe a box — the second serves the whole page, which is what shipped before.
    """
    v, h = page.v_lines, page.h_lines
    if len(v) < 2 or len(h) < 2:
        return None
    box = (max(0, v[0]), max(0, h[0]), min(size[0], v[-1]), min(size[1], h[-1]))
    if box[0] >= box[2] or box[1] >= box[3] or box == (0, 0, *size):
        return None
    return box


def _encode(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG", compress_level=_COMPRESS_LEVEL)
    return buf.getvalue()


def render(page: PageImage, is_dm: bool) -> bytes:
    """The bytes this viewer gets.

    A DM gets the page unmasked and cropped to its grid — the file's own bytes when there
    is no margin to crop, and otherwise a lossless PNG of the same pixels in their own
    mode. Everyone else gets the composite, cropped the same way.
    """
    raw = Image.open(page.path)
    if not page.masked_for(is_dm):
        box = grid_box(page, raw.size)
        if box is None:
            raw.close()
            with open(page.path, "rb") as fh:
                return fh.read()
        raw.load()
        return _encode(raw.crop(box))

    raw.load()
    if raw.mode not in ("RGB", "RGBA", "L"):
        # Paletted, LA, 1-bit: composite requires one mode for all three images, and RGBA
        # is the only one that can hold any of them without discarding a channel.
        raw = raw.convert("RGBA")
    if raw.mode == "RGBA" and raw.getchannel("A").getextrema() == (255, 255):
        # Every page in this tree is RGBA with a channel that is 255 everywhere — a quarter
        # of the bytes on the wire and a sixth of the encode, carrying no information. The
        # mask is opaque either way; this only declines to say so 1.6M times.
        raw = raw.convert("RGB")
    size = raw.size

    holes = Image.new("L", size, 0)
    draw = ImageDraw.Draw(holes)
    v, h = page.v_lines, page.h_lines
    for col, row in page.explored:
        if not (0 <= col < len(v) - 1 and 0 <= row < len(h) - 1):
            continue   # mirrors _draw_fog_overlay's break: no line pair, no cell
        draw.rectangle([v[col], h[row], v[col + 1] - 1, h[row + 1] - 1], fill=255)

    out = Image.composite(raw, _flat(raw.mode, size), holes)
    box = grid_box(page, size)
    return _encode(out.crop(box) if box is not None else out)


# ── The cache ───────────────────────────────────────────────────────────────

def _lag_is_only_fog(held: PageImage, live: PageImage) -> bool:
    """Is continuing to serve ``held`` nothing worse than showing too much fog?

    The machine-checkable form of D-M4-1's staleness invariant. Same page, same fog state,
    and a mask that has only grown: then every cell ``held`` hides is either still hidden or
    merely not yet revealed, which is the safe direction. Anything else — including a mask
    that shrank — is not staleness, it is the wrong picture.
    """
    return (held.path == live.path
            and held.fog_on == live.fog_on
            and held.explored <= live.explored)

class MapImageCache:
    """Two entries — the DM's raw page and the party's masked one — and a published
    snapshot to render them from.

    ``publish`` is the pygame thread's half and is O(1): it swaps in a snapshot and drops
    nothing, because a render is only ever discarded by its key going stale. ``png`` is
    the net thread's half and does the work lazily, on request, holding no lock across the
    encode — a 30 ms render must never stall the frame that published it.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._page: PageImage | None = None
        self._published_at = 0.0
        self._entries: dict[bool, tuple[str, bytes]] = {}
        self.renders = 0          # tests assert on this; the route never reads it

    def publish(self, page: PageImage | None, *,
                boundary: bool = False, now: float | None = None) -> PageImage | None:
        """Offer the live snapshot; return the one that is now published.

        Called once per push cycle on the pygame thread — not once per viewer, because what
        is published is party-scoped and the decision to hold it is a cadence decision.

        **The lag is only ever extra fog.** Holding the previous snapshot is safe exactly
        while its mask is a *subset* of the live one, and that is checked rather than
        inferred from the cases we thought of: a page switch, fog toggled back on, and a
        mask that shrank because a save was loaded all fail the subset test and publish
        immediately. In the fog-on case holding would not be foggier, it would be a leak.
        """
        if page is None:
            with self._lock:
                self._page = None
            return None
        now = time.monotonic() if now is None else now
        with self._lock:
            held = self._page
            if (held is not None
                    and not boundary
                    and _lag_is_only_fog(held, page)
                    and (now - self._published_at) < IMAGE_LAG_S):
                return held
            self._page = page
            self._published_at = now
            return page

    @property
    def page(self) -> PageImage | None:
        with self._lock:
            return self._page

    def png(self, is_dm: bool) -> tuple[str, bytes] | None:
        """``(key, bytes)`` for this viewer, or ``None`` if no page has been published.

        Always renders from the *latest* published snapshot rather than from whatever
        ``?v=`` the client asked for. Serving the newest mask can only ever reveal cells
        the party has already earned, and refusing to would mean keeping every mask a
        client might still be holding.
        """
        with self._lock:
            page = self._page
            entry = self._entries.get(is_dm)
        if page is None:
            return None

        key = page.key(is_dm)
        if entry is not None and entry[0] == key:
            return entry

        data = render(page, is_dm)
        fresh = (key, data)
        with self._lock:
            self.renders += 1
            # Last writer wins: two threads racing the same key produce the same bytes,
            # and a racing *newer* key is the one that should survive.
            held = self._entries.get(is_dm)
            if held is None or held[0] != key:
                self._entries[is_dm] = fresh
        return fresh
