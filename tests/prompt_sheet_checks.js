"use strict";
/*
 * The phone prompt sheet (live play 2026-11-04): a prompt arrives collapsed to a handle
 * pinned over the board, opens on a tap, and closes without cancelling. Driven through
 * `app.js` itself under node; app.css acts on `data-mode` / `data-sheet` below 46rem.
 * Run by `test_prompt_sheet.py`; each check prints one line, and the first failure exits 1.
 */

const assert = require("assert");
const { load } = require("./app_harness");

function view(promptId = "p1") {
  return {
    t: "view", seq: 1,
    map: { cell_px: 50, cols: 4, rows: 4, image: "" },
    fog: { active: false, explored_runs: [] },
    combat: { active: true, paused: false, round: 1, turn_idx: 0, turn_agent: 0,
              initiative: [{ agent: 0, total: 12 }] },
    you: { prompt_id: promptId, reachable: [[1, 1]] },
    log: [],
    agents: [{ agent: 0, name: "Aria", col: 0, row: 0, size: 1, faction: 0, sprite: "",
               hp: { cur: 9, max: 14 }, conditions: [], yours: true }],
  };
}

const OPTIONS = [{ id: "yes", label: "Yes", enabled: true },
                 { id: "no", label: "No", enabled: true }];

function asked(h, id = "p1", extra = {}) {
  h.deliver(view(id));
  h.deliver(Object.assign({ t: "prompt", id, kind: "reaction", expects: "choice",
                            title: "Aria: use Shield?", cancellable: true,
                            options: OPTIONS }, extra));
}

const state = (h) => [h.el("prompt").dataset.mode, h.el("prompt").dataset.sheet];

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check("a prompt arrives collapsed to its handle, titled", () => {
  const h = load();
  asked(h);
  assert.deepStrictEqual(state(h), ["menu", "closed"]);
  assert.strictEqual(h.el("prompt-toggle-label").textContent, "▸ Aria: use Shield?");
  assert.strictEqual(h.el("prompt-toggle").attrs["aria-expanded"], "false");
  assert.strictEqual(h.el("prompt-options").children.length, 2);   // built, just hidden
});

check("the handle opens the sheet, and closes it without cancelling", () => {
  const h = load();
  asked(h);
  h.el("prompt-toggle").fire("click");
  assert.deepStrictEqual(state(h), ["menu", "open"]);
  assert.strictEqual(h.el("prompt-toggle-label").textContent, "▾ Aria: use Shield?");
  assert.strictEqual(h.el("prompt-toggle").attrs["aria-expanded"], "true");
  h.el("prompt-toggle").fire("click");
  assert.deepStrictEqual(state(h), ["menu", "closed"]);
  assert.deepStrictEqual(h.socket.sent.filter((f) => f.t === "submit"), []);
});

check("the sheet stays open across views of the same prompt", () => {
  const h = load();
  asked(h);
  h.el("prompt-toggle").fire("click");
  h.deliver(view("p1"));
  assert.deepStrictEqual(state(h), ["menu", "open"]);
});

check("picking an option submits it and closes the sheet", () => {
  const h = load();
  asked(h);
  h.el("prompt-toggle").fire("click");
  h.el("prompt-options").children[0].children[0].fire("click");
  const sent = h.socket.sent.filter((f) => f.t === "submit");
  assert.deepStrictEqual(sent.map((f) => [f.id, f.option]), [["p1", "yes"]]);
  assert.deepStrictEqual(state(h), ["menu", "closed"]);
});

check("a new prompt starts collapsed", () => {
  const h = load();
  asked(h, "p1");
  h.el("prompt-toggle").fire("click");
  asked(h, "p2");
  assert.deepStrictEqual(state(h), ["menu", "closed"]);
});

check("a cell pick is a strip that never opens over the board", () => {
  const h = load();
  asked(h, "p1", { kind: "cell", expects: "cell", title: "Aria: where to?", options: [] });
  assert.deepStrictEqual(state(h), ["strip", ""]);
  assert.strictEqual(h.el("prompt-hint").hidden, false);
  h.el("prompt-toggle").fire("click");        // not shown on a strip; a stray tap is harmless
  assert.deepStrictEqual(state(h), ["strip", ""]);
});

check("someone else's decision is a strip", () => {
  const h = load();
  h.deliver(view("p9"));
  assert.strictEqual(h.el("prompt").hidden, false);
  assert.deepStrictEqual(state(h), ["strip", ""]);
});

check("a timed prompt shows its countdown on the collapsed handle", () => {
  const h = load();
  asked(h, "p1", { deadline_ms: 12000 });
  assert.deepStrictEqual(state(h), ["menu", "closed"]);
  assert.strictEqual(h.el("prompt-toggle-timer").textContent, "12 s");
  h.clock.now += 5000;
  h.ev("drawTimer()");
  assert.strictEqual(h.el("prompt-toggle-timer").textContent, "7 s");
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
