"use strict";
/*
 * The player board's zoom and pan (QOL Q1), driven through `app.js` itself under node.
 * Run by `test_viewport.py`; each check prints one line, and the first failure exits 1.
 *
 * The harness has no layout, so a check that needs one gives the canvas a box to measure
 * (`parentElement.clientWidth`) and a CSS-sized bounding rect, which is what a browser
 * would report.
 */

const assert = require("assert");
const { load } = require("./app_harness");

function view(extra = {}) {
  return Object.assign({
    t: "view", seq: 1,
    map: { cell_px: 50, cols: 20, rows: 20, image: "" },     // 1000 × 1000 world px
    fog: { active: false, explored_runs: [] },
    combat: { active: true, paused: false, round: 1, turn_idx: 0, turn_agent: null,
              initiative: [] },
    you: { prompt_id: null },
    log: [],
    agents: [],
  }, extra);
}

/* A seated client whose board box is `cssW` CSS px wide, at `dpr`. */
function laidOut(cssW = 500, dpr = 2) {
  const h = load();
  h.ev(`globalThis.innerHeight = 4000; globalThis.devicePixelRatio = ${dpr};`);
  const canvas = h.el("board");
  canvas.parentElement = { clientWidth: cssW };
  canvas.getBoundingClientRect = () => ({ left: 10, top: 20, width: cssW,
                                          height: parseInt(canvas.style.height, 10) });
  h.deliver(view());
  return h;
}

/* A live Move-style cell prompt accepting `cells`. */
function cellPrompt(h, cells) {
  h.ev("prompt = { id: 'p1', expects: 'cell', options: [] }");
  h.ev(`view.you = { prompt_id: 'p1', reachable: ${JSON.stringify(cells)} }`);
}

/* The client coordinates of the centre of cell (col, row), through the live lens. */
function clientOf(h, col, row) {
  const L = h.ev("lens");
  return [10 + L.ox + (col + 0.5) * 50 * L.scale, 20 + L.oy + (row + 0.5) * 50 * L.scale];
}

const pointer = (id, x, y) => ({ pointerId: id, pointerType: "touch", button: 0,
                                 clientX: x, clientY: y });
const submits = (h) => h.socket.sent.filter((f) => f.t === "submit");

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check("with no box to measure, the board is nominal and the transform the identity", () => {
  const h = load();
  h.deliver(view());
  const canvas = h.el("board");
  assert.strictEqual(canvas.width, 1000);
  assert.strictEqual(canvas.height, 1000);
  const sets = h.calls.filter((c) => c.fn === "setTransform");
  assert.deepStrictEqual(sets[sets.length - 1].args, [1, 0, 0, 1, 0, 0]);
  assert.strictEqual(h.el("zoom-level").textContent, "100%");
});

check("the canvas fills its box at devicePixelRatio, and the map fits it", () => {
  const h = laidOut(500, 2);
  const canvas = h.el("board");
  assert.strictEqual(canvas.style.height, "500px");
  assert.strictEqual(canvas.width, 1000);
  assert.strictEqual(canvas.height, 1000);
  assert.strictEqual(h.ev("lens.scale"), 0.5);
  const sets = h.calls.filter((c) => c.fn === "setTransform");
  assert.deepStrictEqual(sets[sets.length - 1].args, [1, 0, 0, 1, 0, 0],
                         "dpr 2 × fit 0.5 is the identity on the backing store");
});

check("a tall map is capped at the window's height and centred", () => {
  const h = load();
  h.ev("globalThis.innerHeight = 500; globalThis.devicePixelRatio = 1;");
  h.el("board").parentElement = { clientWidth: 800 };
  h.deliver(view({ map: { cell_px: 50, cols: 10, rows: 40, image: "" } }));   // 500 × 2000
  assert.strictEqual(h.el("board").style.height, "400px");                    // 0.8 × 500
  assert.strictEqual(h.ev("lens.scale"), 0.2);
  assert.strictEqual(h.ev("lens.ox"), 350, "the map is not centred across the box");
});

check("zooming keeps the point under the cursor where it is", () => {
  const h = laidOut();
  const before = h.ev("toWorld(120, 80)");
  h.ev("zoomAt(2, 120, 80)");
  const after = h.ev("toWorld(120, 80)");
  assert.ok(Math.abs(before[0] - after[0]) < 1e-9 && Math.abs(before[1] - after[1]) < 1e-9,
            `${before} moved to ${after}`);
  assert.strictEqual(h.el("zoom-level").textContent, "200%");
});

check("zoom is clamped to the DM screen's 50%–600%", () => {
  const h = laidOut();
  h.ev("zoomAt(100, 250, 250)");
  assert.strictEqual(h.ev("vp.zoom"), 6);
  h.ev("zoomAt(0.0001, 250, 250)");
  assert.strictEqual(h.ev("vp.zoom"), 0.5);
});

check("a tap maps to the right cell at any zoom and pan", () => {
  const h = laidOut();
  for (const [factor, dx, dy] of [[1, 0, 0], [2.5, 0, 0], [3, -140, 60], [0.6, 30, -10]]) {
    h.ev(`zoomAt(${factor}, 200, 170)`);
    h.ev(`panBy(${dx}, ${dy})`);
    for (const [col, row] of [[0, 0], [7, 3], [12, 15], [19, 19]]) {
      const [x, y] = clientOf(h, col, row);
      assert.deepStrictEqual(Array.from(h.ev(`cellAt({ clientX: ${x}, clientY: ${y} })`)),
                             [col, row], `zoom ${h.ev("vp.zoom")} lost cell ${col},${row}`);
    }
  }
});

check("the map cannot be panned out of sight", () => {
  const h = laidOut();
  h.ev("zoomAt(3, 250, 250)");
  h.ev("panBy(100000, -100000)");
  assert.strictEqual(h.ev("vp.cx"), 0);
  assert.strictEqual(h.ev("vp.cy"), 1000);
});

check("a tap submits its cell; a drag pans and submits nothing", () => {
  const h = laidOut();
  cellPrompt(h, [[4, 4], [5, 4]]);
  const canvas = h.el("board");
  const [x, y] = clientOf(h, 4, 4);
  canvas.fire("pointerdown", pointer(1, x, y));
  canvas.fire("pointermove", pointer(1, x + 3, y));            // inside the tap slop
  canvas.fire("pointerup", pointer(1, x + 3, y));
  canvas.fire("click", { clientX: x + 3, clientY: y });
  assert.deepStrictEqual(submits(h).map((f) => f.cell), [[4, 4]]);

  h.ev("awaiting = ''");
  const cx = h.ev("vp.cx");
  canvas.fire("pointerdown", pointer(2, x, y));
  canvas.fire("pointermove", pointer(2, x + 40, y));
  canvas.fire("pointerup", pointer(2, x + 40, y));
  canvas.fire("click", { clientX: x + 40, clientY: y });
  assert.strictEqual(submits(h).length, 1, "the end of a pan was taken for a tap");
  assert.strictEqual(h.ev("vp.cx"), cx - 40 / h.ev("lens.scale"), "the drag did not pan");
});

check("a touch pan that fires no click does not eat the next tap", () => {
  const h = laidOut();
  cellPrompt(h, [[4, 4]]);
  const canvas = h.el("board");
  const [x, y] = clientOf(h, 4, 4);
  canvas.fire("pointerdown", pointer(1, x, y));
  canvas.fire("pointermove", pointer(1, x + 40, y));
  canvas.fire("pointerup", pointer(1, x + 40, y));             // a touch: no click follows
  const [x2, y2] = clientOf(h, 4, 4);
  canvas.fire("pointerdown", pointer(2, x2, y2));
  canvas.fire("pointerup", pointer(2, x2, y2));
  canvas.fire("click", { clientX: x2, clientY: y2 });
  assert.deepStrictEqual(submits(h).map((f) => f.cell), [[4, 4]]);
});

check("a pinch zooms, and is never a tap", () => {
  const h = laidOut();
  cellPrompt(h, [[4, 4]]);
  const canvas = h.el("board");
  canvas.fire("pointerdown", pointer(1, 200, 200));
  canvas.fire("pointerdown", pointer(2, 300, 200));
  canvas.fire("pointermove", pointer(2, 400, 200));            // fingers 100 → 200 apart
  canvas.fire("pointerup", pointer(2, 400, 200));
  canvas.fire("pointerup", pointer(1, 200, 200));
  canvas.fire("click", { clientX: 200, clientY: 200 });
  assert.ok(Math.abs(h.ev("vp.zoom") - 2) < 1e-9, `zoom is ${h.ev("vp.zoom")}`);
  assert.strictEqual(submits(h).length, 0);
});

check("the wheel zooms, and keeps the page from scrolling", () => {
  const h = laidOut();
  let prevented = false;
  h.el("board").fire("wheel", { clientX: 260, clientY: 270, deltaY: -200, deltaMode: 0,
                                ctrlKey: false, preventDefault: () => { prevented = true; } });
  assert.ok(prevented);
  assert.ok(h.ev("vp.zoom") > 1, "a wheel up did not zoom in");
});

check("+, − and Fit", () => {
  const h = laidOut();
  h.el("zoom-in").fire("click", {});
  assert.strictEqual(h.ev("vp.zoom"), 1.25);
  h.el("zoom-out").fire("click", {});
  h.el("zoom-out").fire("click", {});
  assert.strictEqual(h.ev("vp.zoom"), 0.8);
  h.ev("panBy(50, 50)");
  h.el("zoom-fit").fire("click", {});
  assert.deepStrictEqual([h.ev("vp.zoom"), h.ev("vp.cx"), h.ev("vp.cy")], [1, 500, 500]);
});

check("a map of a different size starts at Fit again", () => {
  const h = laidOut();
  h.ev("zoomAt(3, 100, 100)");
  h.deliver(view({ map: { cell_px: 50, cols: 30, rows: 20, image: "" } }));
  assert.deepStrictEqual([h.ev("vp.zoom"), h.ev("vp.cx"), h.ev("vp.cy")], [1, 750, 500]);
});

/* The wide layout (QOL Q2): the board box is the whole area left of the 340 px column. */
function wide(h, matches = true) {
  h.ev(`globalThis.matchMedia = (q) => ({ matches: ${matches} && q === WIDE_QUERY });`);
}

check("in the wide layout the canvas fills its box both ways, and the map fits it", () => {
  const h = load();
  wide(h);
  h.ev("globalThis.innerHeight = 700; globalThis.devicePixelRatio = 2;");
  const canvas = h.el("board");
  canvas.parentElement = { clientWidth: 1100, clientHeight: 700 };
  h.deliver(view());                                         // 1000 × 1000
  assert.strictEqual(canvas.style.height, "", "the CSS sizes the canvas, not app.js");
  assert.deepStrictEqual([canvas.width, canvas.height], [2200, 1400]);
  assert.strictEqual(h.ev("lens.scale"), 0.7, "fit is min(box ÷ map) both ways");
  assert.strictEqual(h.ev("lens.ox"), 200, "the map is centred across the box");
  assert.strictEqual(h.ev("lens.oy"), 0);
});

check("a wide map in the wide layout fits the width, not the 80% cap", () => {
  const h = load();
  wide(h);
  h.ev("globalThis.innerHeight = 800; globalThis.devicePixelRatio = 1;");
  h.el("board").parentElement = { clientWidth: 1000, clientHeight: 800 };
  h.deliver(view({ map: { cell_px: 50, cols: 40, rows: 10, image: "" } }));  // 2000 × 500
  assert.strictEqual(h.ev("lens.scale"), 0.5);
  assert.strictEqual(h.ev("lens.oy"), 275, "the map is not centred down the box");
});

check("below the breakpoint the narrow stack's sizing still holds", () => {
  const h = load();
  wide(h, false);
  h.ev("globalThis.innerHeight = 500; globalThis.devicePixelRatio = 1;");
  h.el("board").parentElement = { clientWidth: 800, clientHeight: 9999 };
  h.deliver(view({ map: { cell_px: 50, cols: 10, rows: 40, image: "" } }));
  assert.strictEqual(h.el("board").style.height, "400px");
});

check("a resize across the breakpoint re-lays the board", () => {
  const h = load();
  wide(h, false);
  h.ev("globalThis.innerHeight = 600; globalThis.devicePixelRatio = 1;");
  const canvas = h.el("board");
  canvas.parentElement = { clientWidth: 600, clientHeight: 600 };
  h.deliver(view({ map: { cell_px: 50, cols: 40, rows: 10, image: "" } }));  // 2000 × 500
  assert.strictEqual(canvas.style.height, "150px");
  wide(h);
  canvas.parentElement = { clientWidth: 1000, clientHeight: 600 };
  h.ev("drawBoard()");
  assert.strictEqual(canvas.style.height, "");
  assert.deepStrictEqual([canvas.width, canvas.height], [1000, 600]);
});

(async () => {
  for (const [name, fn] of checks) {
    try {
      await fn();
      console.log(`✅ ${name}`);
    } catch (e) {
      console.log(`❌ ${name}\n   ${e.message}`);
      process.exit(1);
    }
  }
})();
