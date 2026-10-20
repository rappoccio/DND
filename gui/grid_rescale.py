"""Re-render a map image so its drawn squares are a whole number of pixels.

A manual grid is whole pixels (``manual_grid.cell_px``), and pathing, reach and sizing
all lean on that nominal cell size. A page whose drawn squares are a fraction off
(31.69 × 32.03 px where the grid assumes 32 × 32) drifts across the map. Rather than
make the grid fractional, the image is re-rendered so the squares ARE the nominal size.

``plan(png, terrain_path)`` measures; ``apply(plan, backup_dir)`` rewrites the image and
the terrain file. Used by Terrain… → Rescale Image to Grid… and by
``tools/rescale_to_grid.py`` (a whole dungeon from the command line).

How it works:

  1. the drawn square is measured separately for width and height, by fitting evenly
     spaced lines to the image's darkness profile, pinned to the grid line at the saved
     anchor (the corner the DM sampled with Set Grid);
  2. the image is re-rendered at the corrected size, from the original image when there
     is one (``foo.png`` beside ``foo_32px.png``), so it is resampled only once;
  3. the saved anchor moves onto the same drawn line in the new image, so every cell
     keeps its index: edge edits, outside seeds, doors and ladders still name the same
     squares (if the margin before the anchor would gain or lose a whole cell, the image
     is padded or cropped there to keep the count);
  4. everything replaced is first copied to ``backup_dir`` (the first copy is kept if it
     is run twice).
"""

import json
import os
import re
import shutil

from PIL import Image

SEARCH = 0.03          # look for the true square within ±3 % of the nominal size
PERIOD_STEP = 0.005    # px
PHASE_SLACK = 3.0      # the sampled anchor is trusted to ±3 px
PHASE_STEP = 0.25      # px
SMOOTH = 9             # moving-average width for the darkness high-pass
MIN_DRIFT_CELLS = 0.15 # total drift below this fraction of a cell: leave the image alone


# ── Measuring ────────────────────────────────────────────────────────────────
def darkness_profiles(img):
    """(columns, rows): how much darker each column / row is than its neighbourhood.
    Grid lines are thin dark lines, so they stand out as peaks."""
    g = img.convert("L")
    w, h = g.size
    cols = list(g.resize((w, 1), Image.BOX).getdata())
    rows = list(g.resize((1, h), Image.BOX).getdata())
    return _highpass(cols), _highpass(rows)


def _highpass(prof):
    n, half = len(prof), SMOOTH // 2
    pre = [0.0]
    for v in prof:
        pre.append(pre[-1] + v)
    out = []
    for i in range(n):
        a, b = max(0, i - half), min(n, i + half + 1)
        out.append((pre[b] - pre[a]) / (b - a) - prof[i])
    return out


def _score(hp, period, t):
    """Mean darkness at the lines t + k·period that fall inside the profile."""
    n = len(hp)
    x = t - int(t // period) * period
    total, count = 0.0, 0
    while x < n:
        i = int(round(x))
        if 0 <= i < n:
            total += hp[i]
            count += 1
        x += period
    return total / count if count else float("-inf")


def fit_axis(hp, nominal, anchor):
    """(period, t): the drawn-square period near ``nominal`` and the position ``t``
    (within PHASE_SLACK of ``anchor``) of the line the grid was anchored to."""
    best = None
    steps = int(round(2 * SEARCH * nominal / PERIOD_STEP))
    for i in range(steps + 1):
        period = nominal * (1 - SEARCH) + i * PERIOD_STEP
        k = 0
        while True:
            t = anchor - PHASE_SLACK + k * PHASE_STEP
            if t > anchor + PHASE_SLACK + 1e-9:
                break
            s = _score(hp, period, t)
            if best is None or s > best[2]:
                best = (period, t, s)
            k += 1
    return best[0], best[1]


# ── Files ────────────────────────────────────────────────────────────────────
def original_for(png):
    """``foo.png`` for ``foo_32px.png`` when it exists, else None."""
    d, fn = os.path.split(png)
    m = re.match(r"^(.*)_\d+px(\.\w+)$", fn)
    if m:
        cand = os.path.join(d, m.group(1) + m.group(2))
        if os.path.exists(cand):
            return cand
    return None


def derived_from(png):
    """The ``foo_32px.png``-style images beside ``png`` that were rendered from it."""
    d, fn = os.path.split(os.path.abspath(png))
    stem, ext = os.path.splitext(fn)
    pat = re.compile(r"^" + re.escape(stem) + r"_\d+px" + re.escape(ext) + r"$")
    try:
        return sorted(f for f in os.listdir(d) if pat.match(f))
    except OSError:
        return []


def _backup(path, folder):
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, os.path.basename(path))
    if not os.path.exists(dst):
        shutil.copy2(path, dst)


# ── Plan / apply ─────────────────────────────────────────────────────────────
def plan(png, terrain_path):
    """Measure one image against its terrain file's manual grid.

    Returns a dict. ``"skip"`` holds a reason when there is nothing to do or it can't be
    done; otherwise ``period`` (px per drawn square, x and y), ``drift`` (px the grid is
    off by across the map, x and y), ``scale`` and ``needed`` describe the change."""
    kids = derived_from(png)
    if kids:
        # Rescaling a source image would change what its derived pages render from.
        return {"skip": f"this is the original of {kids[0]}; rescale that one instead"}
    if not os.path.exists(terrain_path):
        return {"skip": "no terrain file"}
    with open(terrain_path) as f:
        terrain = json.load(f)
    mg = terrain.get("manual_grid")
    if not mg:
        return {"skip": "no manual grid (Set Grid first)"}
    cell = int(mg["cell_px"])
    per_side = max(1, int(mg.get("square_ft", 5)) // 5)
    nominal = cell * per_side
    img = Image.open(png)
    W, H = img.size
    anchor = (int(mg["anchor"][0]), int(mg["anchor"][1]))
    hx, hy = darkness_profiles(img)
    px, tx = fit_axis(hx, nominal, anchor[0])
    py, ty = fit_axis(hy, nominal, anchor[1])
    drift = (abs(px - nominal) * W / px, abs(py - nominal) * H / py)
    return {"png": png, "terrain": terrain_path, "terrain_doc": terrain, "cell": cell,
            "nominal": nominal, "size": (W, H), "anchor": anchor,
            "period": (px, py), "line": (tx, ty), "scale": (nominal / px, nominal / py),
            "drift": drift, "needed": max(drift) >= MIN_DRIFT_CELLS * cell}


def _axis_new(size, scale, line, anchor_old, cell):
    """New size, new anchor, and the pad (+) / crop (−) at the low edge, so the grid
    line at the anchor keeps its cell index."""
    new_size = int(round(size * scale))
    new_anchor = int(round(line * scale))
    shift = (anchor_old // cell - new_anchor // cell) * cell
    return new_size + shift, new_anchor + shift, shift


def apply(p, backup_dir):
    """Re-render ``p["png"]`` and rewrite its terrain file. Returns
    ``{"size", "anchor", "shift", "cols", "rows", "source"}`` for the new image."""
    W, H = p["size"]
    cell = p["cell"]
    nw, nax, shx = _axis_new(W, p["scale"][0], p["line"][0], p["anchor"][0], cell)
    nh, nay, shy = _axis_new(H, p["scale"][1], p["line"][1], p["anchor"][1], cell)
    src = original_for(p["png"]) or p["png"]
    _backup(p["png"], backup_dir)
    _backup(p["terrain"], backup_dir)
    base = Image.open(src)
    base.load()
    mode = "RGBA" if base.mode in ("RGBA", "LA", "P") else "RGB"
    out = base.convert(mode).resize((nw - shx, nh - shy), Image.LANCZOS)
    if shx or shy:
        canvas = Image.new(mode, (nw, nh), out.getpixel((0, 0)))
        canvas.paste(out, (shx, shy))
        out = canvas
    out.save(p["png"])

    doc = p["terrain_doc"]
    doc["manual_grid"]["anchor"] = [nax, nay]
    sx, sy = p["scale"]
    for r in doc.get("regions", []):         # pixel-space regions follow the image
        if all(k in r for k in ("x", "y", "width", "height")):
            r["x"] = int(round(r["x"] * sx + shx))
            r["y"] = int(round(r["y"] * sy + shy))
            r["width"] = int(round(r["width"] * sx))
            r["height"] = int(round(r["height"] * sy))
    with open(p["terrain"], "w") as f:
        json.dump(doc, f, indent=2)
    return {"size": (nw, nh), "anchor": (nax, nay), "shift": (shx, shy),
            "cols": (nw - nax % cell) // cell, "rows": (nh - nay % cell) // cell,
            "source": src}
