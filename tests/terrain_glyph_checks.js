"use strict";
/*
 * The player board's doors, ladders and staircases, driven through `app.js` itself under
 * node. Run by `test_terrain_glyphs.py`; each check prints one line, and the first failure
 * exits 1.
 *
 * The board is 50 px a cell with no box to measure, so the transform is the identity and a
 * recorded canvas call's arguments are world pixels.
 */

const assert = require("assert");
const { load } = require("./app_harness");

function view(terrain, extra = {}) {
  return Object.assign({
    t: "view", seq: 1,
    map: { cell_px: 50, cols: 20, rows: 20, image: "" },
    fog: { active: false, explored_runs: [] },
    combat: { active: false, paused: false, round: 0, turn_idx: 0, turn_agent: null,
              initiative: [] },
    you: { prompt_id: null },
    log: [],
    agents: [],
    terrain,
  }, extra);
}

function drawn(terrain, extra) {
  const h = load();
  h.deliver(view(terrain, extra));
  return h;
}

const WOOD = "rgb(110, 70, 35)";
const OPEN = "rgb(120, 200, 120)";
const LOCK = "rgb(230, 200, 60)";
const BROKEN = "rgb(150, 70, 45)";

const find = (h, fn, colour, args) => h.calls.findIndex(
  (c) => c.fn === fn && (fn === "fillRect" ? c.fill : c.stroke) === colour
         && (!args || JSON.stringify(c.args) === JSON.stringify(args)));

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check("a view with no terrain draws no door and does not throw", () => {
  const h = drawn(undefined);
  assert.strictEqual(find(h, "fillRect", WOOD), -1);
});

check("a closed two-cell door is one slab over both cells", () => {
  const h = drawn({ doors: [{ id: 1, cells: [[3, 4], [4, 4]], open: false, locked: false,
                              broken: false }] });
  // pad = 50 // 8 = 6, over the 100 × 50 bounding box of (3,4)–(4,4).
  assert.notStrictEqual(find(h, "fillRect", WOOD, [156, 206, 88, 38]), -1,
                        "no wooden slab at the door's bounding box");
  assert.strictEqual(find(h, "fillRect", LOCK), -1, "an unlocked door shows no padlock");
});

check("an open door is a frame, not a slab", () => {
  const h = drawn({ doors: [{ id: 1, cells: [[3, 4]], open: true, locked: false,
                              broken: false }] });
  assert.strictEqual(find(h, "fillRect", WOOD), -1, "an open door drew the closed slab");
  assert.notStrictEqual(find(h, "strokeRect", OPEN, [156, 206, 38, 38]), -1);
});

check("a locked door shows the padlock", () => {
  const h = drawn({ doors: [{ id: 1, cells: [[3, 4]], open: false, locked: true,
                              broken: false }] });
  assert.notStrictEqual(find(h, "fillRect", WOOD), -1);
  // The body: max(6, 50 // 4) = 12 wide, max(5, 50 // 5) = 10 high, under the centre.
  assert.notStrictEqual(find(h, "fillRect", LOCK, [169, 225, 12, 10]), -1);
});

check("a broken door is the splintered frame", () => {
  const h = drawn({ doors: [{ id: 1, cells: [[3, 4]], open: true, locked: false,
                              broken: true }] });
  assert.notStrictEqual(find(h, "strokeRect", BROKEN, [156, 206, 38, 38]), -1);
  assert.strictEqual(find(h, "strokeRect", OPEN), -1);
});

check("an east edge door is a bar on the cell's east grid line", () => {
  const h = drawn({ doors: [{ id: 2, cells: [], edges: [[5, 5, "E"]], open: false,
                              locked: false, broken: false }] });
  // t = 50 // 3 = 16, centred on x = 300; pad = max(2, 16 // 8) = 2.
  assert.notStrictEqual(find(h, "fillRect", WOOD, [294, 252, 12, 46]), -1);
});

check("a south edge door two edges long is a bar on the south grid line", () => {
  const h = drawn({ doors: [{ id: 3, cells: [], edges: [[2, 1, "S"], [3, 1, "S"]],
                              open: false, locked: false, broken: false }] });
  // Centred on y = 100, from x = 100, 100 long.
  assert.notStrictEqual(find(h, "fillRect", WOOD, [102, 94, 96, 12]), -1);
});

check("doors draw over the fog, not under it", () => {
  const h = drawn({ doors: [{ id: 1, cells: [[3, 4]], open: false, locked: false,
                              broken: false }] },
                  { fog: { active: true, explored_runs: [[4, 0, 3]] } });
  const slab = find(h, "fillRect", WOOD);
  const lastFog = h.calls.map((c) => c.fn === "fillRect" && c.fill === "rgb(0, 0, 0)")
                         .lastIndexOf(true);
  assert.ok(slab > lastFog, "the fog was painted over the door");
});

check("a ladder draws its backing over its cells", () => {
  const h = drawn({ ladders: [{ cells: [[6, 7]] }] });
  // pad = 50 // 6 = 8.
  assert.notStrictEqual(find(h, "fillRect", "rgba(90, 60, 30, 0.35)", [308, 358, 34, 34]), -1);
});

check("staircase ends sharing a cell draw once, with both ids", () => {
  const h = drawn({ staircases: [
    { id: 7, name: "A", cell: [2, 2], direction: "up" },
    { id: 9, name: "B", cell: [2, 2], direction: "down" },
  ] });
  const backs = h.calls.filter((c) => c.fn === "fillRect" && c.fill === "rgba(40, 50, 90, 0.43)");
  assert.strictEqual(backs.length, 1);
  assert.ok(h.texts.some((t) => t.text === "7/9"), "no id label");
  const arrows = h.calls.filter((c) => c.fn === "fill" && c.fill === "rgb(120, 220, 255)");
  assert.strictEqual(arrows.length, 2, "an up and a down arrow");
});

check("an unfinished staircase draws greyed, with no arrow", () => {
  const h = drawn({ staircases: [{ id: 4, name: "C", cell: [1, 1], direction: null }] });
  assert.notStrictEqual(find(h, "fillRect", "rgba(60, 60, 60, 0.35)"), -1);
  assert.ok(!h.calls.some((c) => c.fn === "fill" && c.fill === "rgb(120, 220, 255)"));
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
