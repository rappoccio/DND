"use strict";
/*
 * The player's combined initiative/health table and the turn highlight (QOL Q3), driven
 * through `app.js` itself under node. Run by `test_roster.py`; each check prints one line,
 * and the first failure exits 1.
 */

const assert = require("assert");
const { load } = require("./app_harness");

const agent = (idx, name, extra = {}) => Object.assign({
  agent: idx, name, col: idx, row: 0, size: 1, faction: 0, sprite: "",
  hp: { band: "Healthy" }, conditions: [], yours: false,
}, extra);

function view(combat = {}, agents = null) {
  return {
    t: "view", seq: 1,
    map: { cell_px: 50, cols: 10, rows: 4, image: "" },
    fog: { active: false, explored_runs: [] },
    combat: Object.assign({ active: true, paused: false, round: 2, turn_idx: 1,
                            turn_agent: 3,
                            initiative: [{ agent: 1, total: 18 }, { agent: 3, total: 12 },
                                         { agent: 0, total: 7 }] }, combat),
    you: { prompt_id: null },
    log: [],
    agents: agents || [
      agent(0, "Zombie", { conditions: ["prone"] }),
      agent(1, "Ireena", { yours: true, hp: { cur: 9, max: 14 } }),
      agent(2, "Barrel"),
      agent(3, "Strahd", { hp: { band: "Bloodied" } }),
      agent(4, "Apple Cart"),
    ],
  };
}

/* Each row as [mark, name, init, hp, conds] — the text the player reads. */
function rows(h) {
  return h.el("roster").children.map((li) => {
    if (li.className === "divider" || li.className === "empty") return [li.className, li.textContent];
    const c = li.children.map((s) => s.textContent);
    return [c[0], c[1], c[2], c[3], c[4] || ""];
  });
}

const outlines = (h) => h.calls.filter((c) => c.fn === "strokeRect" && c.stroke === "rgb(255, 215, 0)");

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check("in combat: initiative order, then the rest of the board alphabetically", () => {
  const h = load();
  h.deliver(view());
  assert.deepStrictEqual(rows(h), [
    ["", "Ireena", "18", "9/14", ""],
    ["▶", "Strahd", "12", "Bloodied", ""],
    ["", "Zombie", "7", "Healthy", "prone"],
    ["divider", "Not in initiative"],
    ["", "Apple Cart", "", "Healthy", ""],
    ["", "Barrel", "", "Healthy", ""],
  ]);
  assert.strictEqual(h.el("round").textContent, 2);
});

check("only the creature on turn is marked, and its row carries the turn class", () => {
  const h = load();
  h.deliver(view());
  const marked = h.el("roster").children.filter((li) => li.className === "turn");
  assert.strictEqual(marked.length, 1);
  assert.strictEqual(marked[0].children[1].textContent, "Strahd");
});

check("the name keeps the viewer's colour class", () => {
  const h = load();
  h.deliver(view());
  const names = h.el("roster").children.filter((li) => li.children.length)
    .map((li) => li.children[1].className);
  assert.deepStrictEqual(names.slice(0, 3), ["name mine", "name other", "name other"]);
});

check("a hidden creature on turn (turn_agent null) marks nothing, on the table or the board", () => {
  const h = load();
  h.deliver(view({ turn_agent: null }));
  assert.ok(rows(h).every((r) => r[0] !== "▶"));
  assert.strictEqual(outlines(h).length, 0);
});

check("an initiative entry this view does not carry shows as #idx with no HP", () => {
  const h = load();
  h.deliver(view({ initiative: [{ agent: 9, total: 20 }, { agent: 1, total: 18 }], turn_agent: 1 },
                 [agent(1, "Ireena", { yours: true, hp: { cur: 9, max: 14 } })]));
  assert.deepStrictEqual(rows(h), [["", "#9", "20", "", ""], ["▶", "Ireena", "18", "9/14", ""]]);
});

check("out of combat: the board alphabetically, no marker, no init, no divider", () => {
  const h = load();
  h.deliver(view({ active: false, turn_agent: 3 }));
  assert.deepStrictEqual(rows(h).map((r) => r[1]),
                         ["Apple Cart", "Barrel", "Ireena", "Strahd", "Zombie"]);
  assert.ok(rows(h).every((r) => r[0] === "" && r[2] === ""));
  assert.strictEqual(outlines(h).length, 0);
});

check("an empty board says so", () => {
  const h = load();
  h.deliver(view({ initiative: [], turn_agent: null }, []));
  assert.deepStrictEqual(rows(h), [["empty", "nothing on the board"]]);
});

check("the token on turn gets the DM's yellow outline, and only that one", () => {
  const h = load();
  h.deliver(view());
  const rects = outlines(h);
  assert.strictEqual(rects.length, 1);
  assert.deepStrictEqual(rects[0].args, [3 * 50 + 1.5, 1.5, 47, 47]);
});

check("the outline follows the turn on the next view", () => {
  const h = load();
  h.deliver(view());
  h.calls.length = 0;
  h.el("roster").children = [];      // the stub's textContent = "" keeps them; a DOM does not
  h.deliver(Object.assign(view({ turn_agent: 0, turn_idx: 2 }), { seq: 2 }));
  const rects = outlines(h);
  assert.strictEqual(rects.length, 1);
  assert.strictEqual(rects[0].args[0], 0 * 50 + 1.5);
  assert.strictEqual(rows(h)[2][0], "▶");
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
