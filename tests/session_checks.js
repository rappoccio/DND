"use strict";
/*
 * The Table panel and M7's close codes, driven through `app.js` itself under node
 * (MULTIPLAYER_PLAN.md D-M7-3, D-M7-4, D-M7-5). Run by `test_hardening.py`; each check
 * prints one line, and the first failure exits 1.
 */

const assert = require("assert");
const { load } = require("./app_harness");

function view(session) {
  const v = {
    t: "view", seq: 1,
    map: { cell_px: 50, cols: 4, rows: 4, image: "" },
    fog: { active: false, explored_runs: [] },
    combat: { active: false, paused: false, round: 0, turn_idx: 0, turn_agent: null,
              initiative: [] },
    you: { prompt_id: null },
    log: [],
    agents: [],
  };
  if (session !== undefined) v.session = session;
  return v;
}

/* Each line as [class, time, text]. */
const lines = (h) => h.el("table-log").children.map(
  (li) => [li.className, li.children[0].textContent, li.children[1].textContent]);

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check("the Table panel draws each line with its time", () => {
  const h = load();
  h.deliver(view([{ n: 1, at: "20:14", text: "Kira joined the table." },
                  { n: 2, at: "20:15", text: "The DM paused the game." }]));
  assert.deepStrictEqual(lines(h), [["", "20:14", "Kira joined the table."],
                                    ["", "20:15", "The DM paused the game."]]);
});

check("a DM-only line is marked, so the DM's own browser can tell it apart", () => {
  const h = load();
  h.deliver(view([{ n: 1, at: "20:14", text: "Refused a join from 10.0.0.9.", dm: true }]));
  assert.deepStrictEqual(lines(h), [["dm", "20:14", "Refused a join from 10.0.0.9."]]);
});

check("a server older than M7 sends no session block, and nothing is drawn", () => {
  const h = load();
  h.deliver(view());
  assert.deepStrictEqual(h.el("table-log").children, []);
});

check("the panel's text is text: a name cannot inject markup", () => {
  const h = load();
  h.deliver(view([{ n: 1, at: "20:14", text: "<img src=x onerror=alert(1)> joined the table." }]));
  const li = h.el("table-log").children[0];
  assert.strictEqual(li.children[1].textContent, "<img src=x onerror=alert(1)> joined the table.");
  assert.strictEqual(li.innerHTML, undefined, "the client wrote innerHTML");
});

check("4403: the DM removed the seat — credential forgotten, join card says so", () => {
  const h = load();
  h.deliver(view([]));
  h.close(4403);
  assert.strictEqual(h.stores.session.has("dnd.credential"), false);
  assert.strictEqual(h.el("join").hidden, false);
  assert.strictEqual(h.el("join-error").textContent, "The DM removed you from the table.");
});

check("4408: another screen took the slot — no reconnect, and the status says why", () => {
  const h = load();
  h.deliver(view([]));
  const before = h.timeouts.length;
  h.close(4408);
  assert.strictEqual(h.timeouts.length, before, "a replaced screen scheduled a reconnect");
  assert.match(h.el("status").textContent, /another screen/);
  assert.strictEqual(h.stores.session.has("dnd.credential"), true, "the credential is still good");
});

check("an ordinary drop still reconnects", () => {
  const h = load();
  h.deliver(view([]));
  const before = h.timeouts.length;
  h.close(1006);
  assert.strictEqual(h.timeouts.length, before + 1);
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
