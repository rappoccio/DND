"use strict";
/*
 * Drag to move on the player board (QOL Q5), driven through `app.js` itself under node.
 * Run by `test_drag.py`; each check prints one line, and the first failure exits 1.
 *
 * The board box is 500 CSS px wide at dpr 1 over a 10 × 10 map of 50 px cells, so the fit
 * is 1:1 and cell (c, r)'s centre is at client (10 + 50c + 25, 20 + 50r + 25).
 */

const assert = require("assert");
const { load } = require("./app_harness");

const ARIA = { agent: 0, name: "Aria", col: 2, row: 2, size: 1, faction: 0, sprite: "",
               hp: { cur: 9, max: 14 }, conditions: [], yours: true };
const OGRE = { agent: 1, name: "Ogre", col: 6, row: 6, size: 1, faction: 1, sprite: "",
               hp: { band: "Healthy" }, conditions: [] };

function view(you, agents = [ARIA, OGRE], seq = 1) {
  return {
    t: "view", seq,
    map: { cell_px: 50, cols: 10, rows: 10, image: "" },
    fog: { active: false, explored_runs: [] },
    combat: { active: true, paused: false, round: 1, turn_idx: 0, turn_agent: 0,
              initiative: [{ agent: 0, total: 12 }, { agent: 1, total: 8 }] },
    you: Object.assign({ controls: [0] }, you),
    log: [],
    agents,
  };
}

const OFFER = { t: "prompt", id: "offer1", parent_id: null, actor: 0, kind: "action",
                expects: "choice", title: "Aria's turn", cancellable: false,
                options: [{ id: "move", label: "Move", enabled: true, group: "movement" },
                          { id: "dash", label: "Dash", enabled: true, group: "action" }] };
const REACH = [[1, 2], [3, 2], [3, 3], [4, 4]];
const MOVE = { t: "prompt", id: "move1", parent_id: "offer1", actor: 0, kind: "cell",
               expects: "cell", title: "Move: walking, 30 ft left", cancellable: true,
               options: [] };

function seated() {
  const h = load();
  h.ev("globalThis.innerHeight = 4000; globalThis.devicePixelRatio = 1;");
  const canvas = h.el("board");
  canvas.parentElement = { clientWidth: 500 };
  canvas.getBoundingClientRect = () => ({ left: 10, top: 20, width: 500, height: 500 });
  return h;
}

/* The offer is live: Aria's turn, nothing asked yet. */
function offerLive() {
  const h = seated();
  h.deliver(view({ prompt_id: "offer1" }));
  h.deliver(OFFER);
  return h;
}

/* The Move prompt this client opened is live, listing REACH. */
function moveLive() {
  const h = offerLive();
  h.ev("moveParent = 'offer1'");
  h.deliver(view({ prompt_id: "move1", reachable: REACH }, undefined, 2));
  h.deliver(MOVE);
  return h;
}

const at = (col, row) => [10 + 50 * col + 25, 20 + 50 * row + 25];
const ptr = (x, y, id = 1) => ({ pointerId: id, pointerType: "mouse", button: 0,
                                 clientX: x, clientY: y, type: "" });
const submits = (h) => h.socket.sent.filter((f) => f.t === "submit");

/* Press on `from`, move through a nudge to `to`, release there. */
function dragCells(h, from, to) {
  const c = h.el("board");
  const [x0, y0] = at(...from);
  const [x1, y1] = at(...to);
  c.fire("pointerdown", ptr(x0, y0));
  c.fire("pointermove", ptr(x0 + 10, y0 + 10));
  c.fire("pointermove", ptr(x1, y1));
  c.fire("pointerup", Object.assign(ptr(x1, y1), { type: "pointerup" }));
  c.fire("click", ptr(x1, y1));
}

const strokes = (h) => h.calls.filter((c) => c.fn === "strokeRect");

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check("the action offer draws no Move button", () => {
  const h = offerLive();
  const labels = h.el("prompt-options").children
    .filter((li) => li.className !== "section").map((li) => li.children[0].textContent);
  assert.deepStrictEqual(labels, ["Dash"]);
});

check("a drop on a reachable cell submits that cell, once", () => {
  const h = moveLive();
  dragCells(h, [2, 2], [3, 3]);
  assert.deepStrictEqual(submits(h).map((f) => [f.id, f.cell]), [["move1", [3, 3]]]);
});

check("a drop off the reachable set sends nothing", () => {
  const h = moveLive();
  dragCells(h, [2, 2], [8, 1]);
  assert.deepStrictEqual(submits(h), []);
  dragCells(h, [2, 2], [2, 2]);
  assert.deepStrictEqual(submits(h), [], "a drop back on its own square is not a move");
});

check("the ghost's outline is green on a listed cell, red off it", () => {
  const h = moveLive();
  const c = h.el("board");
  const [x0, y0] = at(2, 2);
  c.fire("pointerdown", ptr(x0, y0));
  c.fire("pointermove", ptr(...at(3, 3)));
  let last = strokes(h).pop();
  assert.strictEqual(last.stroke, "rgb(80, 220, 80)");
  assert.deepStrictEqual(last.args.slice(0, 2), [151.5, 151.5]);
  c.fire("pointermove", ptr(...at(8, 1)));
  last = strokes(h).pop();
  assert.strictEqual(last.stroke, "rgb(220, 60, 60)");
});

check("picking the token up during the offer opens Move, and its squares paint while held", () => {
  const h = offerLive();
  const c = h.el("board");
  const [x0, y0] = at(2, 2);
  c.fire("pointerdown", ptr(x0, y0));
  assert.deepStrictEqual(submits(h).map((f) => [f.id, f.option]), [["offer1", "move"]],
                         "the press did not ask for the Move prompt");
  h.deliver({ t: "submit_ack", id: "offer1", ok: true });
  h.deliver(view({ prompt_id: "move1", reachable: REACH }, undefined, 2));
  const mark = h.calls.length;
  h.deliver(MOVE);
  const green = h.calls.slice(mark).filter((k) => k.fn === "fillRect" && k.fill === "rgba(90, 200, 120, 0.28)");
  assert.strictEqual(green.length, REACH.length, "the reachable squares are not painted");
  // still held: now the outline knows the set, and a drop answers directly
  c.fire("pointermove", ptr(x0 + 10, y0 + 10));
  c.fire("pointermove", ptr(...at(3, 2)));
  assert.strictEqual(strokes(h).pop().stroke, "rgb(80, 220, 80)");
  c.fire("pointerup", Object.assign(ptr(...at(3, 2)), { type: "pointerup" }));
  assert.deepStrictEqual(submits(h).map((f) => [f.id, f.option || f.cell]),
                         [["offer1", "move"], ["move1", [3, 2]]]);
});

check("a tap on the token during the offer leaves the Move prompt up, and sends no cell", () => {
  const h = offerLive();
  const c = h.el("board");
  const [x0, y0] = at(2, 2);
  c.fire("pointerdown", ptr(x0, y0));
  c.fire("pointerup", Object.assign(ptr(x0, y0), { type: "pointerup" }));
  c.fire("click", ptr(x0, y0));
  h.deliver({ t: "submit_ack", id: "offer1", ok: true });
  h.deliver(view({ prompt_id: "move1", reachable: REACH }, undefined, 2));
  h.deliver(MOVE);
  assert.strictEqual(submits(h).length, 1);
  assert.strictEqual(h.el("prompt").hidden, false);
  dragCells(h, [2, 2], [4, 4]);                     // …and it can be dragged from there
  assert.deepStrictEqual(submits(h).pop().cell, [4, 4]);
});

check("the chain: a drop before the Move prompt arrives is sent when it does — two submits", () => {
  const h = offerLive();
  dragCells(h, [2, 2], [4, 4]);
  assert.deepStrictEqual(submits(h).map((f) => [f.id, f.option]), [["offer1", "move"]]);
  h.deliver({ t: "submit_ack", id: "offer1", ok: true });
  h.deliver(view({ prompt_id: "move1", reachable: REACH }, undefined, 2));
  assert.strictEqual(submits(h).length, 1, "the cell went before its prompt arrived");
  h.deliver(MOVE);
  assert.deepStrictEqual(submits(h).map((f) => [f.id, f.option || f.cell]),
                         [["offer1", "move"], ["move1", [4, 4]]]);
  h.deliver(MOVE);                                  // the prompt re-sent: nothing more
  assert.strictEqual(submits(h).length, 2);
});

check("the chain to an unreachable cell leaves the Move prompt up and says so", () => {
  const h = offerLive();
  dragCells(h, [2, 2], [9, 9]);
  h.deliver({ t: "submit_ack", id: "offer1", ok: true });
  h.deliver(view({ prompt_id: "move1", reachable: REACH }, undefined, 2));
  h.deliver(MOVE);
  assert.strictEqual(submits(h).length, 1);
  assert.match(h.el("prompt-note").textContent, /out of reach/);
});

check("a jump's cell pick under the same offer is not taken for a Move prompt", () => {
  const h = offerLive();
  h.deliver(view({ prompt_id: "jump1", reachable: REACH }, undefined, 2));
  h.deliver(Object.assign({}, MOVE, { id: "jump1", title: "Long jump: choose a landing" }));
  dragCells(h, [2, 2], [3, 3]);
  assert.deepStrictEqual(submits(h), [], "a drag during a jump pick moved the token");
});

check("someone else's token, or yours off its turn, pans instead", () => {
  const h = moveLive();
  dragCells(h, [6, 6], [3, 3]);
  assert.deepStrictEqual(submits(h), []);
  assert.strictEqual(h.ev("drag"), null);
  const g = seated();
  g.deliver(view({ prompt_id: null }));
  dragCells(g, [2, 2], [3, 3]);
  assert.deepStrictEqual(submits(g), []);
});

check("your own drop shows at once and its move event does not replay", () => {
  const h = moveLive();
  dragCells(h, [2, 2], [4, 4]);
  assert.deepStrictEqual(h.board()[0].slice(0, 2), [4, 4], "the token snapped back to wait");
  h.deliver({ t: "events", since: 2, seq: 3,
              events: [{ seq: 3, kind: "move", agent: 0, path: [[2, 2], [3, 3], [4, 4]] }] });
  h.frame(16);
  assert.deepStrictEqual(h.board()[0].slice(0, 2), [4, 4], "the own move replayed");
  assert.strictEqual(h.ev("play"), null);
});

check("someone else's move still animates", () => {
  const h = moveLive();
  h.deliver({ t: "events", since: 2, seq: 3,
              events: [{ seq: 3, kind: "move", agent: 1, path: [[6, 6], [5, 6], [4, 6]] }] });
  h.frame(16);
  assert.notStrictEqual(h.ev("play"), null);
  const [col] = h.board()[1];
  assert.ok(col > 4 && col <= 6, `the ogre jumped to ${col}`);
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
