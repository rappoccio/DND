"use strict";
/*
 * The action offer laid out as the DM's panel is (QOL Q4), driven through `app.js` itself
 * under node. Run by `test_offer.py`; each check prints one line, and the first failure
 * exits 1.
 */

const assert = require("assert");
const { load } = require("./app_harness");

function view() {
  return {
    t: "view", seq: 1,
    map: { cell_px: 50, cols: 4, rows: 4, image: "" },
    fog: { active: false, explored_runs: [] },
    combat: { active: true, paused: false, round: 1, turn_idx: 0, turn_agent: 0,
              initiative: [{ agent: 0, total: 12 }] },
    you: { prompt_id: "p1" },
    log: [],
    agents: [{ agent: 0, name: "Aria", col: 0, row: 0, size: 1, faction: 0, sprite: "",
               hp: { cur: 9, max: 14 }, conditions: [], yours: true }],
  };
}

/* The offer as `net/offer.offered` sends it: Move first, then the menu in the DM's draw
   order (turn, action, bonus, utility). */
const OFFER = [
  { id: "move", label: "Move", enabled: true, group: "movement" },
  { id: "end_turn", label: "End Turn", enabled: true, group: "turn", color: "#465a82" },
  { id: "atk_action", label: "⚔ Attack", enabled: true, group: "action", color: "#378c3c" },
  { id: "dash", label: "Dash", enabled: true, group: "action", color: "#325fa0" },
  { id: "second_wind", label: "Second Wind", enabled: true, group: "bonus", color: "#8c5a5a" },
  { id: "bend_luck", label: "Bend Luck", enabled: false, group: "bonus", color: "#5a5a8c",
    disabled_reason: "Not playable remotely yet — ask the DM" },
  { id: "drop_weapon_main", label: "Drop Sword", enabled: true, group: "utility",
    color: "#505050" },
  { id: "new_thing", label: "New", enabled: true, group: "someday" },
];

function offered(h, options = OFFER, kind = "action") {
  h.deliver(view());
  h.deliver({ t: "prompt", id: "p1", kind, expects: "choice", title: "Aria's turn",
              cancellable: false, options });
  return h.el("prompt-options").children;
}

/* Each item as a heading ["§", text] or a button's label. */
const layout = (items) => items.map((li) => (li.className === "section"
  ? ["§", li.textContent] : li.children[0].textContent));

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check("sections in the DM's order, each with its own rows, End Turn last", () => {
  const h = load();
  assert.deepStrictEqual(layout(offered(h)), [
    ["§", "Action"], "⚔ Attack", "Dash",
    ["§", "Bonus Action"], "Second Wind", "Bend Luck",
    ["§", "Movement"], "Move",
    ["§", "Other"], "Drop Sword", "New",
    ["§", ""], "End Turn",
  ]);
});

check("a row is drawn in the DM's colour; a disabled one is greyed and keeps its reason", () => {
  const h = load();
  const items = offered(h);
  const button = (label) => items.find((li) => li.className !== "section"
                                       && li.children[0].textContent === label);
  const atk = button("⚔ Attack").children[0];
  assert.strictEqual(atk.style.background, "#378c3c");
  assert.strictEqual(atk.className, "dm");
  const bend = button("Bend Luck");
  assert.strictEqual(bend.children[0].disabled, true);
  assert.strictEqual(bend.children[0].className, "dm off");
  assert.strictEqual(bend.children[0].style.background, undefined);
  assert.match(bend.children[1].textContent, /ask the DM/);
  const move = button("Move").children[0];
  assert.strictEqual(move.className, "");          // no colour → the client's default
});

check("a click still submits the option id", () => {
  const h = load();
  const items = offered(h);
  const dash = items.find((li) => li.className !== "section"
                          && li.children[0].textContent === "Dash");
  dash.children[0].fire("click");
  const sent = h.socket.sent.filter((f) => f.t === "submit");
  assert.deepStrictEqual(sent.map((f) => [f.id, f.option]), [["p1", "dash"]]);
});

check("any other prompt kind is a flat list, as before", () => {
  const h = load();
  const items = offered(h, [{ id: "yes", label: "Yes", enabled: true },
                            { id: "no", label: "No", enabled: true }], "reaction");
  assert.deepStrictEqual(layout(items), ["Yes", "No"]);
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
